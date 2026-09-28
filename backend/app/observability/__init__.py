import logging
import sys
from typing import Any
import structlog
from pythonjsonlogger import jsonlogger
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.aws_lambda import AwsLambdaInstrumentor

from app.config import settings


# Prometheus metrics
registry = CollectorRegistry()

active_websocket_connections = Gauge(
    "active_websocket_connections",
    "Number of active WebSocket connections",
    registry=registry,
)

voice_sessions_started = Counter(
    "voice_sessions_started_total",
    "Total number of voice sessions started",
    registry=registry,
)

voice_sessions_completed = Counter(
    "voice_sessions_completed_total",
    "Total number of voice sessions completed successfully",
    registry=registry,
)

voice_sessions_failed = Counter(
    "voice_sessions_failed_total",
    "Total number of voice sessions failed",
    registry=registry,
)

nova_connection_errors = Counter(
    "nova_connection_errors_total",
    "Total number of Nova connection errors",
    registry=registry,
)

gemini_connection_errors = Counter(
    "gemini_connection_errors_total",
    "Total number of Gemini connection errors",
    registry=registry,
)

nova_session_renewals = Counter(
    "nova_session_renewals_total",
    "Total number of Nova session renewals",
    registry=registry,
)

time_to_first_audio_ms = Histogram(
    "time_to_first_audio_ms",
    "Time from session start to first audio response in milliseconds",
    buckets=[100, 250, 500, 1000, 2000, 5000, 10000],
    registry=registry,
)

conversation_duration_seconds = Histogram(
    "conversation_duration_seconds",
    "Duration of voice conversations in seconds",
    buckets=[10, 30, 60, 120, 300, 600, 1200],
    registry=registry,
)

mic_to_backend_latency_ms = Histogram(
    "mic_to_backend_latency_ms",
    "Latency from microphone to backend in milliseconds",
    buckets=[10, 25, 50, 100, 200, 500],
    registry=registry,
)

backend_to_bedrock_latency_ms = Histogram(
    "backend_to_bedrock_latency_ms",
    "Latency from backend to Bedrock in milliseconds",
    buckets=[50, 100, 200, 500, 1000, 2000],
    registry=registry,
)

nova_to_browser_latency_ms = Histogram(
    "nova_to_browser_latency_ms",
    "Latency from Nova response to browser playback in milliseconds",
    buckets=[50, 100, 200, 500, 1000, 2000],
    registry=registry,
)


def setup_logging() -> None:
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    add_log_level = structlog.processors.add_log_level
    format_exc_info = structlog.processors.format_exc_info

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        add_log_level,
        timestamper,
        format_exc_info,
    ]

    if settings.log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Configure stdlib logging to use structlog
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_format == "json":
        handler.setFormatter(jsonlogger.JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(message)s"))

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(log_level)

    # Reduce noise from libraries
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)


def setup_tracing(service_name: str = "nova-voice-agent") -> None:
    if settings.app_env == "dev":
        return

    provider = TracerProvider()
    trace.set_tracer_provider(provider)

    exporter = OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    FastAPIInstrumentor.instrument()
    AwsLambdaInstrumentor.instrument()


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)


class MetricsContext:
    def __init__(self, logger: structlog.BoundLogger):
        self.logger = logger
        self.start_time = None

    def __enter__(self):
        import time
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def record_latency(self, histogram: Histogram, labels: dict = None) -> None:
        import time
        elapsed_ms = (time.perf_counter() - self.start_time) * 1000
        histogram.observe(elapsed_ms)

    def log_event(self, event: str, **kwargs: Any) -> None:
        self.logger.info(event, **kwargs)