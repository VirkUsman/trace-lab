import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
DASHBOARD = ROOT / "grafana" / "dashboards" / "trace-lab.json"
RULES = ROOT / "rules" / "slo.rules.yml"
DATASOURCE = ROOT / "grafana" / "provisioning" / "datasources" / "prometheus.yml"


@pytest.fixture(scope="module")
def dash():
    return json.loads(DASHBOARD.read_text())


@pytest.fixture(scope="module")
def exprs(dash):
    return [t["expr"] for p in dash["panels"] for t in p["targets"]]


@pytest.fixture
def exposed(client):
    """Every sample name and label name the service exposes, after some traffic."""
    for path in ("/orders/3", "/orders/2", "/boom", "/slow?ms=1"):
        client.get(path)
    names, labels = set(), set()
    for family in client.app.state.metrics.registry.collect():
        for s in family.samples:
            names.add(s.name)
            labels.update(s.labels)
    return names, labels


def recorded_names():
    doc = yaml.safe_load(RULES.read_text())
    return {r["record"] for g in doc["groups"] for r in g["rules"] if "record" in r}


def metric_names(expr):
    return set(re.findall(r"\btrace_lab[:\w]*", expr))


def test_dashboard_has_a_stable_uid_and_title(dash):
    assert dash["uid"] == "trace-lab"
    assert dash["title"] == "trace-lab"


def test_panel_ids_are_unique(dash):
    ids = [p["id"] for p in dash["panels"]]
    assert len(ids) == len(set(ids))


def test_every_panel_has_a_query(dash):
    for p in dash["panels"]:
        assert p["targets"], p["title"]
        for t in p["targets"]:
            assert t["expr"].strip()


def test_every_panel_fits_the_24_column_grid(dash):
    for p in dash["panels"]:
        g = p["gridPos"]
        assert g["x"] + g["w"] <= 24, p["title"]


def test_panels_do_not_overlap(dash):
    boxes = [
        (p["gridPos"]["x"], p["gridPos"]["y"], p["gridPos"]["w"], p["gridPos"]["h"])
        for p in dash["panels"]
    ]
    for i, (x1, y1, w1, h1) in enumerate(boxes):
        for x2, y2, w2, h2 in boxes[i + 1 :]:
            apart = x1 + w1 <= x2 or x2 + w2 <= x1 or y1 + h1 <= y2 or y2 + h2 <= y1
            assert apart, ((x1, y1), (x2, y2))


def test_datasource_uid_matches_the_provisioned_one(dash):
    provisioned = yaml.safe_load(DATASOURCE.read_text())["datasources"][0]["uid"]
    for p in dash["panels"]:
        assert p["datasource"]["uid"] == provisioned
        for t in p["targets"]:
            assert t["datasource"]["uid"] == provisioned


def test_every_metric_in_a_query_exists(exprs, exposed):
    names, _ = exposed
    known = names | recorded_names()
    for expr in exprs:
        for m in metric_names(expr):
            assert m in known, (m, expr)


def test_every_label_used_in_a_query_exists(exprs, exposed):
    _, labels = exposed
    for expr in exprs:
        grouped = re.findall(r"by \(([^)]*)\)", expr)
        used = {x.strip() for g in grouped for x in g.split(",")}
        used |= set(re.findall(r"(\w+)=\"", expr))
        for label in used:
            assert label in labels, (label, expr)


def test_recorded_series_used_in_the_dashboard_are_defined_in_the_rules(exprs):
    for expr in exprs:
        for m in metric_names(expr):
            if ":" in m:
                assert m in recorded_names(), m


def test_dashboard_covers_requests_errors_latency_and_the_slo(exprs):
    joined = " ".join(exprs)
    assert "trace_lab_http_requests_total" in joined
    assert "histogram_quantile" in joined
    assert "trace_lab:http_error_ratio:rate1h" in joined
    assert "trace_lab:http_slow_ratio" in joined


def test_burn_rate_panel_divides_by_the_availability_budget(dash):
    stat = next(p for p in dash["panels"] if p["title"].startswith("Error budget burn rate, 1h"))
    assert stat["targets"][0]["expr"].endswith("/ 0.001")


def test_dashboard_json_is_stable_when_reserialised(dash):
    again = json.dumps(dash, indent=2) + "\n"
    assert again == DASHBOARD.read_text()
