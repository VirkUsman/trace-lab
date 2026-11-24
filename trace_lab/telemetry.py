"""Tracer provider construction.

The provider is passed around rather than installed globally, because the
global one can be set once per process and tests need a fresh exporter each.
"""

import os

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)

SERVICE_NAME = "trace-lab"


def build_provider(exporter: SpanExporter | None = None) -> TracerProvider:
    """A provider that sends spans to `exporter`.

    With no exporter, spans go over OTLP/HTTP when OTEL_EXPORTER_OTLP_ENDPOINT
    is set and are dropped otherwise. A given exporter is flushed on every
    span end (the tests read it straight after a request).
    """
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    elif os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    return provider
