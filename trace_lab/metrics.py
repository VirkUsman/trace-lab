"""Prometheus metrics for the service.

Every label here has a small, fixed set of values. The route label is the
route template ("/orders/{order_id}"), never the raw path, and the status
label is a class ("2xx"), never a code. Unmatched paths all collapse into one
"unmatched" route so a scanner cannot mint series.
"""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

# Bucket edges are chosen so 0.3 s, the latency SLO threshold, is an edge.
# The latency recording rule reads le="0.3" directly.
LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5, 5.0)

UNMATCHED = "unmatched"


def status_class(code: int) -> str:
    return f"{code // 100}xx"


class Metrics:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self.requests = Counter(
            "trace_lab_http_requests_total",
            "Requests served, by method, route template and status class.",
            ["method", "route", "status"],
            registry=self.registry,
        )
        self.duration = Histogram(
            "trace_lab_http_request_duration_seconds",
            "Request duration by route template.",
            ["method", "route"],
            buckets=LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.inflight = Gauge(
            "trace_lab_http_inflight_requests",
            "Requests currently being handled.",
            registry=self.registry,
        )
        self.inventory_calls = Counter(
            "trace_lab_inventory_calls_total",
            "Internal calls to the inventory service, by outcome.",
            ["outcome"],
            registry=self.registry,
        )
