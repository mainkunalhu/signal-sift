"""Phoenix tracing (Arize Cloud, OTLP/HTTP). Best-effort: never raises.

No Docker needed — spans export to `PHOENIX_ENDPOINT` with `PHOENIX_API_KEY`.
If anything is missing or unreachable, `setup_tracing()` returns False and
the `traced` decorator degrades to a transparent pass-through.
"""

import functools

_ready = False


def setup_tracing(*, project_name: str = "signalsift") -> bool:
    global _ready
    if _ready:
        return True
    try:
        from config import settings

        if not settings.phoenix_api_key:
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
