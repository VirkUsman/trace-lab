from prometheus_client.parser import text_string_to_metric_families

from trace_lab.metrics import LATENCY_BUCKETS

REQ = "trace_lab_http_requests_total"
BUCKET = "trace_lab_http_request_duration_seconds_bucket"
COUNT = "trace_lab_http_request_duration_seconds_count"


def sample(metrics, name, **labels):
    return metrics.registry.get_sample_value(name, labels)


def test_request_counter_uses_route_template_and_status_class(client, metrics):
    client.get("/orders/3")
    assert (
        sample(
            metrics,
            REQ,
            method="GET",
            route="/orders/{order_id}",
            status="2xx",
        )
        == 1
    )


def test_5xx_and_4xx_are_separate_classes(client, metrics):
    client.get("/boom")
    client.get("/orders/2")
    assert sample(metrics, REQ, method="GET", route="/boom", status="5xx") == 1
    assert (
        sample(
            metrics,
            REQ,
            method="GET",
            route="/orders/{order_id}",
            status="4xx",
        )
        == 1
    )


def test_many_order_ids_make_one_series(client, metrics):
    for i in range(40):
        client.get(f"/orders/{i}")
    routes = {
        s.labels["route"]
        for f in metrics.registry.collect()
        if f.name == "trace_lab_http_requests"
        for s in f.samples
        if s.name == REQ
    }
    assert routes == {"/orders/{order_id}"}


def test_scanner_paths_collapse_into_one_route(client, metrics):
    for i in range(30):
        client.get(f"/wp-admin/{i}.php")
    routes = {
        s.labels["route"] for f in metrics.registry.collect() for s in f.samples if s.name == REQ
    }
    assert routes == {"unmatched"}


def test_no_label_is_named_like_an_identifier(client, metrics):
    client.get("/orders/3")
    forbidden = {"path", "url", "user", "user_id", "order_id", "trace_id", "ip", "status_code"}
    for family in metrics.registry.collect():
        for s in family.samples:
            assert not forbidden & set(s.labels), (s.name, s.labels)


def test_label_value_sets_stay_small(client, metrics):
    for i in range(60):
        client.get(f"/orders/{i}")
    client.get("/boom")
    client.get("/nope")
    seen: dict[str, set[str]] = {}
    for family in metrics.registry.collect():
        for s in family.samples:
            for k, v in s.labels.items():
                seen.setdefault(k, set()).add(v)
    assert len(seen["route"]) <= 4
    assert len(seen["status"]) <= 3
    assert seen["method"] == {"GET"}


def test_histogram_has_the_slo_bucket_edge():
    assert 0.3 in LATENCY_BUCKETS


def test_slow_request_lands_above_the_300ms_bucket(client, metrics):
    client.get("/slow?ms=400")
    under = sample(
        metrics,
        BUCKET,
        method="GET",
        route="/slow",
        le="0.3",
    )
    total = sample(metrics, COUNT, method="GET", route="/slow")
    assert (under, total) == (0, 1)


def test_fast_request_lands_under_the_300ms_bucket(client, metrics):
    client.get("/slow?ms=0")
    assert (
        sample(
            metrics,
            BUCKET,
            method="GET",
            route="/slow",
            le="0.3",
        )
        == 1
    )


def test_inflight_returns_to_zero(client, metrics):
    client.get("/orders/3")
    client.get("/boom")
    assert sample(metrics, "trace_lab_http_inflight_requests") == 0


def test_inventory_outcomes_are_counted(client, metrics):
    client.get("/orders/3")  # sku-0 ok
    client.get("/orders/2")  # sku-2 not found
    assert sample(metrics, "trace_lab_inventory_calls_total", outcome="ok") == 1
    assert sample(metrics, "trace_lab_inventory_calls_total", outcome="not_found") == 1


def test_metrics_endpoint_serves_prometheus_text(client):
    client.get("/orders/3")
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    names = {f.name for f in text_string_to_metric_families(r.text)}
    assert "trace_lab_http_requests" in names
    assert "trace_lab_http_request_duration_seconds" in names


def test_scraping_metrics_does_not_count_itself(client, metrics):
    client.get("/metrics")
    client.get("/metrics")
    assert sample(metrics, REQ, method="GET", route="/metrics", status="2xx") is None


def test_odd_http_methods_do_not_mint_series(client, metrics):
    for verb in ("PURGE", "FOO", "BREW", "MKCOL"):
        client.request(verb, "/orders/3")
    client.get("/orders/3")
    methods = {
        s.labels["method"] for f in metrics.registry.collect() for s in f.samples if s.name == REQ
    }
    assert methods == {"GET", "OTHER"}
