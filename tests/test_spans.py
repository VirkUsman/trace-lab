from opentelemetry.trace import SpanKind, StatusCode

from tests.conftest import spans_named


def test_server_span_is_named_after_the_route_template(client, exporter):
    client.get("/orders/7")
    assert len(spans_named(exporter, "GET /orders/{order_id}")) == 1


def test_server_span_attributes(client, exporter):
    client.get("/orders/3")
    span = spans_named(exporter, "GET /orders/{order_id}")[0]
    assert span.kind == SpanKind.SERVER
    assert span.attributes["http.request.method"] == "GET"
    assert span.attributes["http.route"] == "/orders/{order_id}"
    assert span.attributes["url.path"] == "/orders/3"
    assert span.attributes["http.response.status_code"] == 200
    assert span.attributes["trace_lab.component"] == "api"


def test_handler_can_add_attributes_to_the_server_span(client, exporter):
    client.get("/orders/4")
    span = spans_named(exporter, "GET /orders/{order_id}")[0]
    assert span.attributes["order.sku"] == "sku-1"


def test_client_span_attributes(client, exporter):
    client.get("/orders/3")
    span = spans_named(exporter, "GET inventory")[0]
    assert span.kind == SpanKind.CLIENT
    assert span.attributes["peer.service"] == "inventory"
    assert span.attributes["http.response.status_code"] == 200


def test_a_5xx_marks_the_span_as_error(client, exporter):
    r = client.get("/boom")
    assert r.status_code == 500
    span = spans_named(exporter, "GET /boom")[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["http.response.status_code"] == 500


def test_exception_is_recorded_as_a_span_event(client, exporter):
    client.get("/boom")
    span = spans_named(exporter, "GET /boom")[0]
    assert [e.name for e in span.events] == ["exception"]
    assert span.events[0].attributes["exception.type"] == "RuntimeError"


def test_a_404_from_the_app_is_not_a_span_error(client, exporter):
    r = client.get("/orders/2")  # sku-2 is unknown to inventory
    assert r.status_code == 404
    span = spans_named(exporter, "GET /orders/{order_id}")[0]
    assert span.status.status_code == StatusCode.UNSET
    assert span.attributes["http.response.status_code"] == 404


def test_unmatched_path_uses_a_fixed_route_name(client, exporter):
    client.get("/nothing/here/123")
    span = spans_named(exporter, "GET unmatched")[0]
    assert span.attributes["http.route"] == "unmatched"
    assert span.attributes["url.path"] == "/nothing/here/123"


def test_metrics_and_health_are_not_traced(client, exporter):
    client.get("/metrics")
    client.get("/healthz")
    assert exporter.get_finished_spans() == ()


def test_all_spans_share_the_service_resource(client, exporter):
    client.get("/orders/3")
    names = {s.resource.attributes["service.name"] for s in exporter.get_finished_spans()}
    assert names == {"trace-lab"}
