import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from trace_lab.app import create_app
from trace_lab.metrics import Metrics
from trace_lab.telemetry import build_provider


@pytest.fixture
def exporter():
    return InMemorySpanExporter()


@pytest.fixture
def metrics():
    return Metrics()


@pytest.fixture
def client(exporter, metrics):
    app = create_app(build_provider(exporter), metrics)
    return TestClient(app, raise_server_exceptions=False)


def spans_named(exporter, name):
    return [s for s in exporter.get_finished_spans() if s.name == name]
