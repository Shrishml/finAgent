"""Phoenix tracing integration for FinAgent.

Usage:
    1. Set PHOENIX_ENABLED=1 to enable tracing
    2. Set PHOENIX_ENDPOINT to your Phoenix server (default: http://localhost:6006/v1/traces)
    3. Decorators automatically trace LLM calls when enabled
"""
import logging
import os

log = logging.getLogger("finagent.tracing")

_tracer = None
_initialized = False


def init_tracing(project_name: str = "finagent"):
    """Initialize Phoenix tracing. Called automatically on first get_tracer() call."""
    global _tracer, _initialized

    if _initialized:
        return _tracer

    # Only initialize if Phoenix is enabled
    if os.environ.get("PHOENIX_ENABLED", "").lower() not in ("1", "true"):
        log.debug("[tracing] Phoenix disabled (set PHOENIX_ENABLED=1 to enable)")
        _initialized = True
        return None

    endpoint = os.environ.get("PHOENIX_ENDPOINT", "http://localhost:6006/v1/traces")
    project = os.environ.get("PHOENIX_PROJECT_NAME", project_name)

    try:
        from phoenix.otel import register

        tracer_provider = register(
            project_name=project,
            endpoint=endpoint,
            auto_instrument=False,
        )
        _tracer = tracer_provider.get_tracer("finagent")
        _initialized = True
        log.info(f"[tracing] Phoenix initialized: project={project}, endpoint={endpoint}")
        return _tracer
    except ImportError:
        log.warning("[tracing] arize-phoenix-otel not installed, tracing disabled")
        _initialized = True
        return None
    except Exception as e:
        log.warning(f"[tracing] Failed to initialize Phoenix: {e}")
        _initialized = True
        return None


def get_tracer():
    """Get the global tracer instance. Returns None if tracing disabled."""
    if not _initialized:
        return init_tracing()
    return _tracer


def is_tracing_enabled() -> bool:
    """Check if tracing is enabled and initialized."""
    return get_tracer() is not None
