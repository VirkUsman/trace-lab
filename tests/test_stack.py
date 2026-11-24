"""The compose file and the configs it mounts, read as YAML. Nothing here starts a container."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent


def load(rel):
    return yaml.safe_load((ROOT / rel).read_text())


@pytest.fixture(scope="module")
def compose():
    return load("docker-compose.yml")


def test_compose_has_the_four_services(compose):
    assert set(compose["services"]) == {"service", "otel-collector", "prometheus", "grafana"}


def test_images_are_pinned_to_a_version(compose):
    for name in ("otel-collector", "prometheus", "grafana"):
        image = compose["services"][name]["image"]
        assert ":" in image and not image.endswith(":latest"), image


def test_service_exports_traces_to_the_collector_over_otlp_http(compose):
    env = compose["services"]["service"]["environment"]
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://otel-collector:4318"


def test_collector_listens_where_the_service_sends():
    cfg = load("otel/collector.yml")
    assert cfg["receivers"]["otlp"]["protocols"]["http"]["endpoint"].endswith(":4318")


def test_collector_pipeline_is_wired_end_to_end():
    cfg = load("otel/collector.yml")
    pipe = cfg["service"]["pipelines"]["traces"]
    for r in pipe["receivers"]:
        assert r in cfg["receivers"]
    for p in pipe["processors"]:
        assert p in cfg["processors"]
    for e in pipe["exporters"]:
        assert e in cfg["exporters"]


def test_prometheus_scrapes_the_service_port(compose):
    cfg = load("prometheus/prometheus.yml")
    target = cfg["scrape_configs"][0]["static_configs"][0]["targets"][0]
    assert target == "service:8000"
    assert "8000:8000" in compose["services"]["service"]["ports"]


def test_prometheus_loads_the_mounted_rules(compose):
    cfg = load("prometheus/prometheus.yml")
    mounts = compose["services"]["prometheus"]["volumes"]
    assert "./rules:/etc/prometheus/rules:ro" in mounts
    assert cfg["rule_files"] == ["/etc/prometheus/rules/*.yml"]


def test_rule_tests_are_not_inside_the_mounted_rules_folder():
    assert list((ROOT / "rules").glob("*.yml")) == [ROOT / "rules" / "slo.rules.yml"]


def test_grafana_mounts_dashboards_where_the_provider_looks(compose):
    provider = load("grafana/provisioning/dashboards/dashboards.yml")
    path = provider["providers"][0]["options"]["path"]
    mounts = compose["services"]["grafana"]["volumes"]
    assert f"./grafana/dashboards:{path}:ro" in mounts


def test_grafana_datasource_points_at_the_prometheus_service():
    ds = load("grafana/provisioning/datasources/prometheus.yml")["datasources"][0]
    assert ds["url"] == "http://prometheus:9090"


def test_dockerfile_serves_the_app_module():
    text = (ROOT / "Dockerfile").read_text()
    assert "trace_lab.main:app" in text
    assert "--frozen" in text
