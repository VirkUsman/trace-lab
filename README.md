# trace-lab

_Built with AI assistance._

A small FastAPI service with traces, metrics, a Grafana dashboard and SLO
burn-rate alerts, plus tests that check each of those pieces against the
others. The point is the checking: the dashboard queries are tested against the
metrics the service really exposes, and the alert windows are tested against
the table they are copied from.

```
trace_lab/app.py        API and an in-process inventory app, request middleware (spans + metrics)
trace_lab/metrics.py    prometheus_client metrics, label rules
trace_lab/telemetry.py  tracer provider: in-memory exporter in tests, OTLP/HTTP when configured
trace_lab/loadgen.py    mixed traffic for the dashboard
rules/slo.rules.yml     recording rules and 6 burn-rate alerts (availability and latency)
rules-tests/            promtool unit tests for those rules
grafana/                dashboard JSON and provisioning
otel/ prometheus/       collector and Prometheus config
docker-compose.yml      service, otel-collector, prometheus, grafana
tests/                  83 tests, about 1 s
```

Python 3.12.

    uv sync
    uv run pytest
    uv run uvicorn trace_lab.main:app

## What a request produces

`GET /orders/3` makes three spans in one trace:

| Span | Kind | Notes |
|---|---|---|
| `GET /orders/{order_id}` | server | route template in the name, `http.route`, `url.path`, status code, `order.sku` |
| `GET inventory` | client | `peer.service`, status code |
| `GET /stock/{sku}` | server | child of the client span, `trace_lab.component=inventory` |

The inventory app is a second FastAPI app called through httpx's ASGI transport,
so no socket is involved. The call is still an HTTP request: the API injects a
W3C `traceparent` header and the inventory app extracts it. A test also sends
its own `traceparent` and checks the trace id, parent id and sampled flag
survive both hops.

## Metrics

| Metric | Labels |
|---|---|
| `trace_lab_http_requests_total` | `method`, `route`, `status` |
| `trace_lab_http_request_duration_seconds` | `method`, `route` |
| `trace_lab_http_inflight_requests` | none |
| `trace_lab_inventory_calls_total` | `outcome` (ok, not_found, error) |

`route` is the template, `status` is a class (`2xx`), and anything unusual
collapses: unmatched paths become `unmatched`, odd HTTP verbs become `OTHER`.
Tests send 60 different order ids and 30 scanner paths and assert the series
count does not move. The histogram has a bucket edge at 0.3 s because the
latency SLO reads `le="0.3"` directly. `/metrics` and `/healthz` are not counted
or traced.

## SLO rules

Two objectives: 99.9 % of requests are not 5xx, and 99 % finish within 0.3 s.
Both are recorded over seven windows (5m, 30m, 1h, 2h, 6h, 1d, 3d). Alerts use
the multi-window, multi-burn-rate pairs from the Google SRE Workbook, chapter 5:

| Burn rate | Long window | Short window | Severity |
|---|---|---|---|
| 14.4 | 1h | 5m | page |
| 6 | 6h | 30m | page |
| 3 | 1d | 2h | ticket |
| 1 | 3d | 6h | ticket |

Latency has the first two rows only. An alert fires when both windows are over
the threshold. 14.4x for one hour spends 2 % of a 30 day budget, 6x for six
hours spends 5 %; both are asserted in the tests. The short window being a
twelfth of the long one is asserted for every alert.

## What ran

- `uv run pytest`: 83 tests. 80 run anywhere; 3 call promtool and skip when it
  is missing.
- promtool v0.316.0, built from source with `go install` on this machine (no
  prebuilt binary, no Docker): `promtool check rules` accepts 20 rules,
  `promtool check config` passes, and `promtool test rules` passes 4 scenarios:
  steady 2 % errors pages, exactly 0.1 % errors does not, the page clears
  within minutes after errors stop while the 1h ratio is still above threshold,
  and 20 % slow requests pages on latency.
- I changed the fast alert's short window from 5m to 1h by hand and the promtool
  test failed, so it does check windows. CI repeats that edit on every run.
- The service ran under uvicorn with the load generator (200 requests) and
  `/metrics` showed the expected series.

## What I did not run

- **`docker compose up` never ran.** The compose file, collector config, Dockerfile
  and Grafana provisioning are only parsed as YAML and cross-checked in tests
  (ports, mounts, datasource uid). The Dockerfile was never built.
- **OTLP export has not met a real collector.** Tests use the in-memory
  exporter. The OTLP path is a few lines in `telemetry.py` and is unexercised.
- **The dashboard was never loaded into Grafana.** Its JSON is checked for valid
  metric and label names, a stable uid and a non-overlapping grid, which does
  not prove the panels render the way I expect.
- **The collector keeps no traces.** It prints them to its log. Adding Tempo or
  Jaeger is the obvious next piece.

## Limits of this setup

- Both "services" run in one process with one tracer provider, so every span has
  `service.name=trace-lab`. A real split would show two services in a trace
  view; here the `trace_lab.component` attribute tells them apart.
- The promtool scenarios feed constant rates. They show the windows and `for`
  durations behave, not that 99.9 % is a sensible target for a real service.
- Burn-rate alerts need traffic. With a handful of requests an hour, one 5xx is
  a 14x burn. There is no minimum-traffic guard.
- Rates come from counters with `sum(...)` over every route and method, so one
  noisy route can hide inside the ratio. Per-route SLOs would need more rules.
- `/boom` and `/slow` exist to produce failures and slow requests. They would
  not ship.
- Dashboard burn-rate panels divide by 0.001 in the query. Change the SLO and
  you change the rules, the alert thresholds and that panel by hand.
- Pinned image versions (collector 0.114.0, Prometheus 2.55.1, Grafana 11.3.1)
  were chosen from memory of recent releases and not checked against a registry.
