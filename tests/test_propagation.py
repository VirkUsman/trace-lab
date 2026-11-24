from opentelemetry.trace import SpanKind

from tests.conftest import spans_named

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT_ID = "00f067aa0ba902b7"
TRACEPARENT = f"00-{TRACE_ID}-{PARENT_ID}-01"


def _chain(exporter):
    server = spans_named(exporter, "GET /orders/{order_id}")[0]
    client = spans_named(exporter, "GET inventory")[0]
    inv = spans_named(exporter, "GET /stock/{sku}")[0]
    return server, client, inv


def test_one_request_makes_one_trace_across_the_internal_call(client, exporter):
    client.get("/orders/3")
    server, client_span, inv = _chain(exporter)
    assert server.context.trace_id == client_span.context.trace_id == inv.context.trace_id


def test_parent_child_links(client, exporter):
    client.get("/orders/3")
    server, client_span, inv = _chain(exporter)
    assert server.parent is None
    assert client_span.parent.span_id == server.context.span_id
    assert inv.parent.span_id == client_span.context.span_id


def test_inventory_span_is_a_server_span_in_the_inventory_component(client, exporter):
    client.get("/orders/3")
    _, _, inv = _chain(exporter)
    assert inv.kind == SpanKind.SERVER
    assert inv.attributes["trace_lab.component"] == "inventory"


def test_incoming_traceparent_is_honoured(client, exporter):
    client.get("/orders/3", headers={"traceparent": TRACEPARENT})
    server, client_span, inv = _chain(exporter)
    assert format(server.context.trace_id, "032x") == TRACE_ID
    assert format(server.parent.span_id, "016x") == PARENT_ID
    assert inv.context.trace_id == server.context.trace_id


def test_sampled_flag_is_carried_through(client, exporter):
    client.get("/orders/3", headers={"traceparent": TRACEPARENT})
    _, _, inv = _chain(exporter)
    assert inv.context.trace_flags.sampled


def test_two_requests_get_two_traces(client, exporter):
    client.get("/orders/3")
    client.get("/orders/3")
    ids = {s.context.trace_id for s in exporter.get_finished_spans()}
    assert len(ids) == 2


def test_failed_inventory_lookup_is_still_the_same_trace(client, exporter):
    client.get("/orders/2")
    server, client_span, inv = _chain(exporter)
    assert inv.attributes["http.response.status_code"] == 404
    assert client_span.context.trace_id == inv.context.trace_id == server.context.trace_id
