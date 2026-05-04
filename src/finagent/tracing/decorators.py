"""Tracing decorators for LLM and orchestrator calls.

Decorators:
- @traced_llm: LLM complete() calls
- @traced_llm_stream: LLM complete_stream() calls
- @traced_chain: General chain/workflow operations
- @traced_orchestrator: Orchestrator with session context
"""
import functools
from typing import AsyncIterator, Callable, Any

from finagent.tracing import get_tracer


def traced_llm(func):
    """Decorator to trace LLM complete() calls.

    Captures inputs, outputs, and metadata for every LLM call.
    If tracing is disabled, runs the function normally with no overhead.
    """

    @functools.wraps(func)
    async def wrapper(self, prompt: str, system: str = "", json_mode: bool = False):
        tracer = get_tracer()

        # If tracing disabled, just run the function
        if tracer is None:
            return await func(self, prompt, system, json_mode)

        with tracer.start_as_current_span(
            f"llm.{self.name}",
            openinference_span_kind="llm",
        ) as span:
            # Capture inputs
            span.set_input({"system": system, "prompt": prompt})
            span.set_attributes(
                {
                    "llm.provider": self.name,
                    "llm.model_name": getattr(self, "_model", self.name),
                    "llm.invocation_parameters.json_mode": json_mode,
                }
            )

            # Execute LLM call
            result = await func(self, prompt, system, json_mode)

            # Capture output
            span.set_output(result)

            return result

    return wrapper


def traced_llm_stream(func):
    """Decorator to trace LLM complete_stream() calls.

    Captures input at start, accumulates output chunks, records complete output on finish.
    If tracing is disabled, yields from the function normally with no overhead.
    """

    @functools.wraps(func)
    async def wrapper(self, prompt: str, system: str = "") -> AsyncIterator[str]:
        tracer = get_tracer()

        # If tracing disabled, just yield from the function
        if tracer is None:
            async for chunk in func(self, prompt, system):
                yield chunk
            return

        with tracer.start_as_current_span(
            f"llm.{self.name}.stream",
            openinference_span_kind="llm",
        ) as span:
            # Capture inputs
            span.set_input({"system": system, "prompt": prompt})
            span.set_attributes(
                {
                    "llm.provider": self.name,
                    "llm.model_name": getattr(self, "_model", self.name),
                }
            )

            # Accumulate output for tracing while yielding chunks
            full_output = []
            async for chunk in func(self, prompt, system):
                full_output.append(chunk)
                yield chunk

            # Record complete output
            span.set_output("".join(full_output))

    return wrapper


def traced_chain(name: str = None):
    """Decorator to trace chain/workflow operations.

    Usage:
        @traced_chain("intent_classifier")
        async def classify_intent(query: str) -> dict:
            ...
    """

    def decorator(func: Callable) -> Callable:
        span_name = name or func.__name__

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            tracer = get_tracer()

            if tracer is None:
                return await func(*args, **kwargs)

            with tracer.start_as_current_span(
                f"chain.{span_name}",
                openinference_span_kind="chain",
            ) as span:
                # Capture first positional arg as input if it exists
                if args:
                    span.set_input(str(args[0])[:1000])

                result = await func(*args, **kwargs)

                # Capture output
                span.set_output(str(result)[:1000] if result else None)

                return result

        return wrapper

    return decorator


def traced_orchestrator(func: Callable) -> Callable:
    """Decorator to trace orchestrator handle_query with session context.

    Captures:
    - User query as input
    - Response as output
    - Session ID for grouping traces by user
    - Creates parent span for all nested LLM calls
    """

    @functools.wraps(func)
    async def wrapper(query: str, user_id: int | None = None, *args, **kwargs):
        tracer = get_tracer()

        if tracer is None:
            return await func(query, user_id, *args, **kwargs)

        # Import here to avoid circular dependency
        try:
            from phoenix.otel import using_attributes
        except ImportError:
            # Phoenix not installed, run without session context
            return await func(query, user_id, *args, **kwargs)

        session_id = str(user_id) if user_id else "anonymous"

        with using_attributes(
            session_id=session_id,
            user_id=session_id,
        ):
            with tracer.start_as_current_span(
                "orchestrator.handle_query",
                openinference_span_kind="chain",
            ) as span:
                span.set_input(query)
                span.set_attributes(
                    {
                        "user.id": session_id,
                        "session.id": session_id,
                    }
                )

                result = await func(query, user_id, *args, **kwargs)

                # For streaming, result might be a generator
                if isinstance(result, str):
                    span.set_output(result[:2000] if len(result) > 2000 else result)

                return result

    return wrapper


def traced_orchestrator_stream(func: Callable) -> Callable:
    """Decorator to trace orchestrator handle_query_stream with session context.

    Similar to traced_orchestrator but handles async generators.
    """

    @functools.wraps(func)
    async def wrapper(query: str, user_id: int | None = None, *args, **kwargs):
        tracer = get_tracer()

        if tracer is None:
            async for chunk in func(query, user_id, *args, **kwargs):
                yield chunk
            return

        try:
            from phoenix.otel import using_attributes
        except ImportError:
            async for chunk in func(query, user_id, *args, **kwargs):
                yield chunk
            return

        session_id = str(user_id) if user_id else "anonymous"

        with using_attributes(
            session_id=session_id,
            user_id=session_id,
        ):
            with tracer.start_as_current_span(
                "orchestrator.handle_query_stream",
                openinference_span_kind="chain",
            ) as span:
                span.set_input(query)
                span.set_attributes(
                    {
                        "user.id": session_id,
                        "session.id": session_id,
                    }
                )

                full_output = []
                async for chunk in func(query, user_id, *args, **kwargs):
                    # Don't accumulate status messages
                    if not chunk.startswith("["):
                        full_output.append(chunk)
                    yield chunk

                span.set_output("".join(full_output)[:2000])

    return wrapper
