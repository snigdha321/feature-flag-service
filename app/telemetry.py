"""OpenTelemetry tracing/metrics plus Prometheus metrics wiring.

Tracing is optional and only activated when ``OTEL_ENABLED`` is true, so the
service runs cleanly without a collector in local/dev. Prometheus metrics are
always available at ``/metrics``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import Counter, Histogram

from app.config import Settings
from app.logging_config import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI

log = get_logger(__name__)

# Domain metric: outcomes of flag evaluations.
EVALUATIONS_TOTAL = Counter(
    "feature_flag_evaluations_total",
    "Total number of flag evaluations",
    labelnames=("flag_key", "result", "reason"),
)

EVALUATION_LATENCY = Histogram(
    "feature_flag_evaluation_seconds",
    "Latency of a single flag evaluation",
    labelnames=("flag_key",),
)

CACHE_EVENTS = Counter(
    "feature_flag_cache_events_total",
    "Cache hit/miss/invalidation events",
    labelnames=("event",),
)

# Evaluations served in degraded mode because the database was unavailable.
# ``source`` is "stale_cache" (served an expired snapshot) or "default"
# (no snapshot available, fell back to the configured safe default).
EVALUATION_FALLBACKS_TOTAL = Counter(
    "feature_flag_evaluation_fallbacks_total",
    "Evaluations served from a degraded-mode fallback when the database was unavailable",
    labelnames=("source",),
)


def setup_tracing(app: FastAPI, settings: Settings) -> None:
    """Instrument the app with OpenTelemetry if enabled."""
    if not settings.otel_enabled:
        log.info("otel.disabled")
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    log.info("otel.enabled", endpoint=settings.otel_exporter_otlp_endpoint)
