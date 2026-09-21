"""Phoenix tracing (Arize Cloud, OTLP/HTTP). Best-effort: never raises.

No Docker needed — spans export to `PHOENIX_ENDPOINT` with `PHOENIX_API_KEY`.
If the key is missing or cloud ingestion is failing (persistent HTTP 500s on
free tier), tracing stays OFF with one clean log line instead of endless
retry spam, and the `traced` decorator degrades to a pass-through.
"""

import functools
import logging

_ready = False

_EXPORTER_LOGGERS = (
    "opentelemetry.exporter.otlp.proto.http.trace_exporter",
    "opentelemetry.sdk.trace.export",
)


def _silence_exporter_logs() -> None:
    """Exporter retry/failure logs are noise; app health never depends on them."""
    for name in _EXPORTER_LOGGERS:
        logging.getLogger(name).setLevel(logging.CRITICAL)


def _probe_ingestion(endpoint: str, api_key: str, timeout: float = 5.0) -> bool:
    """Send one real span with a bounded sync export. True if cloud accepts it."""
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        exporter = OTLPSpanExporter(
            endpoint=endpoint,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        with provider.get_tracer("signalsift-probe").start_as_current_span("probe"):
            pass
        ok = provider.force_flush(timeout_millis=int(timeout * 1000))
        provider.shutdown()
        return bool(ok)
    except Exception:
        return False


def setup_tracing(*, project_name: str = "signalsift") -> bool:
    global _ready
    if _ready:
        return True
    _silence_exporter_logs()
    try:
        from config import settings

        if not settings.phoenix_api_key:
            print("[tracing] off (no PHOENIX_API_KEY)")
            return False
        if not _probe_ingestion(settings.phoenix_endpoint, settings.phoenix_api_key):
            print(
                "[tracing] off (Phoenix Cloud ingestion failing — app unaffected, restart to retry)"
            )
            return False
        # register() handles Bearer auth + project resource + batch exporter.
        from phoenix.otel import register

        register(
            project_name=project_name,
            endpoint=settings.phoenix_endpoint,
            api_key=settings.phoenix_api_key,
            # Batch export runs in a background thread: span uploads never block
            # nodes. (Sync export added ~100s to a 4-way run against free-tier
            # cloud.) Export failures only pollute logs, never latency.
            batch=True,
            auto_instrument=False,  # we trace nodes explicitly via @traced
            set_global_tracer_provider=True,
        )
        try:  # future-proof: capture LangChain runnables when we adopt them
            from openinference.instrumentation.langchain import LangChainInstrumentor

            LangChainInstrumentor().instrument()
        except Exception:
            pass
        _ready = True
        print("[tracing] on (phoenix-cloud)")
        return True
    except Exception:
        return False


def traced(span_name: str):
    """Wrap an async node fn in an OTel span; no-op if tracing is unavailable."""

    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                from opentelemetry import trace

                tracer = trace.get_tracer("signalsift")
                with tracer.start_as_current_span(span_name):
                    return await fn(*args, **kwargs)
            except Exception:
                return await fn(*args, **kwargs)

        return wrapper

    return decorator
