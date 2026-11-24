"""The service: an API that calls an inventory service in the same process.

The inventory app is a second FastAPI app reached through httpx's ASGI
transport. No socket is involved, but the call is a real HTTP request: the
API injects a W3C `traceparent` header and the inventory app extracts it, so
the parent/child link in a trace comes from the wire format and not from
Python's contextvars.
"""

import asyncio
import time

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from opentelemetry import propagate, trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind, Status, StatusCode
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from trace_lab.metrics import UNMATCHED, Metrics, status_class

SKUS = ["sku-0", "sku-1", "sku-2"]
STOCK = {"sku-0": 12, "sku-1": 0}  # sku-2 is deliberately unknown
UNINSTRUMENTED = {"/metrics", "/healthz"}
MAX_SLOW_MS = 2000


def _instrument(
    app: FastAPI, provider: TracerProvider, component: str, metrics: Metrics | None
) -> None:
    tracer = provider.get_tracer("trace_lab." + component)

    @app.middleware("http")
    async def observe(request: Request, call_next):
        if request.url.path in UNINSTRUMENTED:
            return await call_next(request)

        parent = propagate.extract(dict(request.headers))
        started = time.perf_counter()
        if metrics:
            metrics.inflight.inc()
        with tracer.start_as_current_span(
            request.method, context=parent, kind=SpanKind.SERVER
        ) as span:
            try:
                response = await call_next(request)
                code = response.status_code
            except Exception as exc:
                span.record_exception(exc)
                response = Response("internal error", status_code=500)
                code = 500

            route_obj = request.scope.get("route")
            route = getattr(route_obj, "path", None) or UNMATCHED
            span.update_name(f"{request.method} {route}")
            span.set_attribute("http.request.method", request.method)
            span.set_attribute("http.route", route)
            span.set_attribute("url.path", request.url.path)
            span.set_attribute("http.response.status_code", code)
            span.set_attribute("trace_lab.component", component)
            if code >= 500:
                span.set_status(Status(StatusCode.ERROR))

        if metrics:
            elapsed = time.perf_counter() - started
            metrics.inflight.dec()
            metrics.requests.labels(request.method, route, status_class(code)).inc()
            metrics.duration.labels(request.method, route).observe(elapsed)
        return response


def create_inventory_app(provider: TracerProvider) -> FastAPI:
    app = FastAPI(title="inventory")
    _instrument(app, provider, "inventory", None)

    @app.get("/stock/{sku}")
    async def stock(sku: str):
        if sku not in STOCK:
            raise HTTPException(404, "unknown sku")
        return {"sku": sku, "on_hand": STOCK[sku]}

    return app


def create_app(provider: TracerProvider, metrics: Metrics | None = None) -> FastAPI:
    metrics = metrics or Metrics()
    app = FastAPI(title="trace-lab")
    app.state.metrics = metrics
    _instrument(app, provider, "api", metrics)

    tracer = provider.get_tracer("trace_lab.client")
    inventory = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_inventory_app(provider)),
        base_url="http://inventory",
    )

    async def stock_for(sku: str) -> int | None:
        with tracer.start_as_current_span("GET inventory", kind=SpanKind.CLIENT) as span:
            span.set_attribute("http.request.method", "GET")
            span.set_attribute("peer.service", "inventory")
            headers: dict[str, str] = {}
            propagate.inject(headers)
            resp = await inventory.get(f"/stock/{sku}", headers=headers)
            span.set_attribute("http.response.status_code", resp.status_code)
            if resp.status_code == 200:
                metrics.inventory_calls.labels("ok").inc()
                return resp.json()["on_hand"]
            if resp.status_code == 404:
                metrics.inventory_calls.labels("not_found").inc()
                return None
            metrics.inventory_calls.labels("error").inc()
            span.set_status(Status(StatusCode.ERROR))
            raise HTTPException(502, "inventory failed")

    @app.get("/orders/{order_id}")
    async def order(order_id: int):
        sku = SKUS[order_id % len(SKUS)]
        trace.get_current_span().set_attribute("order.sku", sku)
        on_hand = await stock_for(sku)
        if on_hand is None:
            raise HTTPException(404, "unknown sku")
        return {"order_id": order_id, "sku": sku, "on_hand": on_hand}

    @app.get("/slow")
    async def slow(ms: int = 0):
        await asyncio.sleep(min(max(ms, 0), MAX_SLOW_MS) / 1000)
        return {"slept_ms": min(max(ms, 0), MAX_SLOW_MS)}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("deliberate failure")

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/metrics")
    async def metrics_endpoint():
        return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

    return app
