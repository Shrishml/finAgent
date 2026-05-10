p# Arize Phoenix Integration Plan

## Problem Statement

We need to track all LLM interactions in FinAgent for evaluation purposes. Currently, LLM calls happen through custom providers (`GeminiAPIProvider`, `KiroCLIProvider`) without observability. We need:

1. **Tracing** - Record every LLM call with inputs, outputs, latency, and metadata
2. **Evaluation** - Run quality assessments (relevance, hallucination, etc.) on traces
3. **Debugging** - Ability to inspect and replay LLM interactions

## Why Arize Phoenix

- **Open-source** - Self-hosted, no vendor lock-in
- **OpenTelemetry-based** - Industry standard tracing
- **Manual instrumentation support** - Works with custom LLM providers (critical for us)
- **Built-in evaluators** - Relevance, QA correctness, hallucination detection
- **Lightweight packages** - Can install only what we need

## Options Considered

### Instrumentation Approach

| Option | Pros | Cons |
|--------|------|------|
| **A: Phoenix auto-instrumentation** | Zero code changes | Only works for SDK providers (OpenAI, Anthropic, etc). Won't work with CLI tools |
| **B: Manual span blocks** | Full control | Verbose, every LLM call wrapped in `with span:` blocks |
| **C: Custom decorator** | Clean, one-line change | We write the decorator ourselves |
| **D: Replace providers with SDK** | Auto-instrumentation works | CLI fallback still needs manual instrumentation |

### Provider Strategy

| Option | Pros | Cons |
|--------|------|------|
| **Keep current providers** | No refactoring | CLI tools can't be auto-instrumented |
| **Switch to Anthropic SDK** | Phoenix auto-instruments it | API costs, need ANTHROPIC_API_KEY |
| **Switch to Google GenAI SDK** | Phoenix auto-instruments it | Already using Gemini, just different client |
| **Hybrid: SDK + CLI fallback** | Best of both worlds | Two code paths to maintain |

## Chosen Approach: Custom Decorator (Option C)

**Decision:** Use a custom `@traced_llm` decorator on the `LLMProvider` base class.

**Why:**
1. **Minimal code change** - One decorator line on base class, all providers traced
2. **Works with CLI tools** - No SDK required, works with `kiro-cli` subprocess
3. **Graceful fallback** - If Phoenix not configured, runs normally without tracing
4. **Clean separation** - Tracing logic isolated in `tracing/` module
5. **Future-proof** - Can add SDK auto-instrumentation later without changing decorator

**Trade-off accepted:** We won't get token counts from CLI providers (they don't expose this). We accept latency-only metrics for CLI calls.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                            FinAgent App                                  │
│                                                                          │
│  ┌─────────────┐    ┌─────────────────────────────────────────────────┐ │
│  │ Orchestrator │───▶│                LLM Layer                        │ │
│  │   engine.py  │    │  ┌───────────────────────────────────────────┐ │ │
│  └─────────────┘    │  │  LLMProvider (base.py)                     │ │ │
│         │            │  │                                            │ │ │
│         ▼            │  │  @traced_llm  ◄── Decorator handles all   │ │ │
│  ┌─────────────┐    │  │  async def complete(...)                   │ │ │
│  │   Agents    │    │  │      return await self._complete(...)      │ │ │
│  │  mf.py etc  │───▶│  └───────────────────────────────────────────┘ │ │
│  └─────────────┘    │         │                                       │ │
│                      │         ▼                                       │ │
│                      │  ┌─────────────┐  ┌─────────────┐              │ │
│                      │  │ GeminiAPI   │  │ KiroCLI     │  (etc.)     │ │
│                      │  │ Provider    │  │ Provider    │              │ │
│                      │  └─────────────┘  └─────────────┘              │ │
│                      └─────────────────────────────────────────────────┘ │
│                                     │                                    │
│  ┌──────────────────────────────────┼──────────────────────────────────┐│
│  │           tracing/ module        │                                  ││
│  │  ┌────────────────┐    ┌─────────▼────────┐                        ││
│  │  │ __init__.py    │    │ decorators.py    │                        ││
│  │  │ - init_tracing │    │ - @traced_llm    │                        ││
│  │  │ - get_tracer   │    │ - @traced_chain  │                        ││
│  │  └────────────────┘    └──────────────────┘                        ││
│  └─────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────┘
                                     │
                                     │ OTLP/HTTP
                                     ▼
                      ┌──────────────────────────┐
                      │    Phoenix Server        │
                      │    (localhost:6006)      │
                      │                          │
                      │  - Trace Storage         │
                      │  - UI Dashboard          │
                      │  - Evaluation Engine     │
                      └──────────────────────────┘
```

## Key Design Decisions

1. **Decorator on base class** - Single point of instrumentation, all providers traced automatically
2. **Lazy tracer initialization** - Tracer created on first use, not at import time
3. **Graceful fallback** - If `get_tracer()` returns None, decorator runs function normally
4. **No provider changes** - Existing `GeminiAPIProvider`, `KiroCLIProvider` unchanged

## What We'll Track

### Phase 1: LLM Calls (via `@traced_llm` decorator)

| Attribute | Description | Captured By |
|-----------|-------------|-------------|
| `input.system` | System prompt | Decorator |
| `input.prompt` | User prompt | Decorator |
| `output` | Full LLM response | Decorator |
| `llm.provider` | gemini-api, kiro, etc | Decorator (`self.name`) |
| `llm.model_name` | gemini-2.0-flash, etc | Decorator (`self._model`) |
| `llm.invocation_parameters.json_mode` | JSON mode flag | Decorator |
| Latency | Auto-tracked | Span duration |

### Phase 2: Session Context (via `@traced_orchestrator` decorator)

| Attribute | Description | Captured By |
|-----------|-------------|-------------|
| `session.id` | User ID for grouping | Decorator |
| `user.id` | User identifier | Decorator |
| Orchestrator span | Parent span for all LLM calls | Decorator |

### Not Captured (CLI limitation)

| Attribute | Why |
|-----------|-----|
| Token counts | CLI tools don't expose this |
| Cost | Requires token counts |

## Phased Implementation

### Phase 1: Core Tracing Setup (Day 1)
**Goal:** Get basic LLM call tracing working with decorator approach

1. Add dependencies to `pyproject.toml`:
   ```toml
   dependencies = [
       # ... existing deps ...
       "arize-phoenix-otel>=0.16.0",
       "openinference-semantic-conventions",
   ]
   ```

2. Create `src/finagent/tracing/` module:
   - `__init__.py` - tracer initialization, `get_tracer()` function
   - `decorators.py` - `@traced_llm` and `@traced_llm_stream` decorators

3. Apply decorators to `LLMProvider` base class:
   - Add `@traced_llm` to `complete()` method
   - Add `@traced_llm_stream` to `complete_stream()` method
   - **No changes to provider implementations**

4. Test: Start Phoenix server, make LLM calls, verify traces appear

**Files Changed:**
- `pyproject.toml` - add dependencies
- `src/finagent/tracing/__init__.py` - new file, tracer setup
- `src/finagent/tracing/decorators.py` - new file, decorators
- `src/finagent/llm/base.py` - add 2 decorator lines only

### Phase 2: Rich Metadata (Day 2)
**Goal:** Add context to make traces useful for debugging

1. Add session tracking:
   - Pass `user_id` as `session.id` attribute
   - Group traces by user session

2. Add orchestrator context:
   - Track intent classification as a child span
   - Track action execution as child spans
   - Add `metadata.query` for the user's question

3. Add provider-specific metadata:
   - For `GeminiAPIProvider`: model version, temperature
   - For `KiroCLIProvider`: timeout, any flags used

**Files Changed:**
- `src/finagent/tracing/__init__.py` - add context managers
- `src/finagent/orchestrator/engine.py` - wrap orchestrator logic
- `src/finagent/orchestrator/router.py` - trace intent classification
- `src/finagent/llm/gemini_api.py` - add model metadata
- `src/finagent/llm/kiro.py` - add provider metadata

### Phase 3: Evaluation Setup (Day 3)
**Goal:** Run automated quality checks on traces

1. Add evaluation dependencies:
   ```toml
   "arize-phoenix-evals",
   "arize-phoenix-client",
   ```

2. Create `scripts/evaluate_traces.py`:
   - Fetch recent traces from Phoenix
   - Run built-in evaluators (relevance, QA correctness)
   - Log results back to Phoenix

3. Define evaluation criteria:
   - **Relevance**: Does response address the user's question?
   - **Groundedness**: Is financial advice based on user's data?
   - **Helpfulness**: Is the response actionable?

**Files Changed:**
- `pyproject.toml` - add eval dependencies
- `scripts/evaluate_traces.py` - new evaluation script
- `docs/EVALUATION_CRITERIA.md` - document eval rubrics

### Phase 4: Production Configuration (Day 4)
**Goal:** Make it deployable

1. Environment-based configuration:
   - `PHOENIX_ENDPOINT` - where to send traces
   - `PHOENIX_PROJECT_NAME` - project identifier
   - Local dev: `http://localhost:6006`
   - Production: Phoenix Cloud or self-hosted

2. Add startup/shutdown hooks:
   - Initialize tracer in `main.py`
   - Graceful shutdown to flush pending traces

3. Add to deployment:
   - Docker compose service for Phoenix server (local dev)
   - Document self-hosting options for production

**Files Changed:**
- `src/finagent/config.py` - add Phoenix config
- `src/finagent/main.py` - init tracing on startup
- `docker-compose.yml` - add Phoenix service (new file)
- `docs/DEPLOYMENT.md` - document Phoenix setup

## Code Examples

### Phase 1: Tracer Initialization

```python
# src/finagent/tracing/__init__.py
import logging
import os

log = logging.getLogger("finagent.tracing")

_tracer = None
_initialized = False

def init_tracing(project_name: str = "finagent"):
    """Initialize Phoenix tracing. Call once at app startup."""
    global _tracer, _initialized
    
    if _initialized:
        return _tracer
    
    endpoint = os.environ.get("PHOENIX_ENDPOINT", "http://localhost:6006/v1/traces")
    
    # Only initialize if Phoenix is configured
    if not os.environ.get("PHOENIX_ENABLED", "").lower() in ("1", "true"):
        log.info("[tracing] Phoenix disabled (set PHOENIX_ENABLED=1 to enable)")
        _initialized = True
        return None
    
    try:
        from phoenix.otel import register
        
        tracer_provider = register(
            project_name=project_name,
            endpoint=endpoint,
            auto_instrument=False,
        )
        _tracer = tracer_provider.get_tracer("finagent")
        _initialized = True
        log.info(f"[tracing] Phoenix initialized, sending to {endpoint}")
        return _tracer
    except Exception as e:
        log.warning(f"[tracing] Failed to initialize Phoenix: {e}")
        _initialized = True
        return None

def get_tracer():
    """Get the global tracer instance. Returns None if tracing disabled."""
    if not _initialized:
        return init_tracing()
    return _tracer
```

### Phase 1: Decorators

```python
# src/finagent/tracing/decorators.py
import functools
import time
from typing import AsyncIterator

from finagent.tracing import get_tracer

def traced_llm(func):
    """Decorator to trace LLM complete() calls.
    
    Captures:
    - Input: prompt + system message
    - Output: full LLM response
    - Latency: automatic from span duration
    - Provider metadata: model name, json_mode
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
            span.set_attributes({
                "llm.provider": self.name,
                "llm.model_name": getattr(self, "_model", self.name),
                "llm.invocation_parameters.json_mode": json_mode,
            })
            
            # Execute LLM call
            result = await func(self, prompt, system, json_mode)
            
            # Capture output
            span.set_output(result)
            
            return result
    
    return wrapper


def traced_llm_stream(func):
    """Decorator to trace LLM complete_stream() calls.
    
    Captures input at start, accumulates output chunks, records on completion.
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
            span.set_input({"system": system, "prompt": prompt})
            span.set_attributes({
                "llm.provider": self.name,
                "llm.model_name": getattr(self, "_model", self.name),
            })
            
            # Accumulate output for tracing
            full_output = []
            async for chunk in func(self, prompt, system):
                full_output.append(chunk)
                yield chunk
            
            # Record complete output
            span.set_output("".join(full_output))
    
    return wrapper
```

### Phase 1: Apply Decorators to Base Class

```python
# src/finagent/llm/base.py (only 2 lines added!)
from finagent.tracing.decorators import traced_llm, traced_llm_stream

class LLMProvider(ABC):
    
    @traced_llm  # <-- ADD THIS
    async def complete(self, prompt: str, system: str = "", json_mode: bool = False) -> str:
        """Send prompt, get response. json_mode forces JSON output."""
        log.debug(f"[llm:{self.name}] >>> CALL complete (json_mode={json_mode})")
        # ... existing code unchanged ...
        return result

    @traced_llm_stream  # <-- ADD THIS
    async def complete_stream(self, prompt: str, system: str = "") -> AsyncIterator[str]:
        """Streaming response for chat UI."""
        log.debug(f"[llm:{self.name}] >>> STREAM complete")
        # ... existing code unchanged ...
```

## What Gets Captured

| Field | Source | CLI Providers | SDK Providers |
|-------|--------|---------------|---------------|
| **Input (prompt)** | Decorator | ✅ Yes | ✅ Yes |
| **Input (system)** | Decorator | ✅ Yes | ✅ Yes |
| **Output (response)** | Decorator | ✅ Yes | ✅ Yes |
| **Latency** | Span duration | ✅ Yes | ✅ Yes |
| **Provider name** | `self.name` | ✅ Yes | ✅ Yes |
| **Model name** | `self._model` | ✅ Yes | ✅ Yes |
| **Token counts** | SDK response | ❌ No | ✅ Yes (if SDK) |
| **Cost** | Calculated | ❌ No | ✅ Yes (if SDK) |

### Phase 2: Session & Orchestrator Context

```python
# src/finagent/tracing/decorators.py (add this decorator)

def traced_orchestrator(func):
    """Decorator to trace orchestrator query handling with session context."""
    @functools.wraps(func)
    async def wrapper(query: str, user_id: int | None = None):
        tracer = get_tracer()
        
        if tracer is None:
            return await func(query, user_id)
        
        # Phoenix context manager for session grouping
        from phoenix.otel import using_attributes
        
        with using_attributes(
            session_id=str(user_id) if user_id else "anonymous",
            user_id=str(user_id) if user_id else None,
        ):
            with tracer.start_as_current_span("orchestrator.handle_query") as span:
                span.set_input(query)
                
                result = await func(query, user_id)
                
                span.set_output(result if isinstance(result, str) else "streaming")
                return result
    
    return wrapper

# Usage in orchestrator/engine.py:
@traced_orchestrator
async def handle_query(query: str, user_id: int | None = None) -> str:
    # ... existing code unchanged ...
```

### Phase 3: Evaluation Script

```python
# scripts/evaluate_traces.py
import phoenix as px
from phoenix.evals import llm_classify
from phoenix.evals.models import GeminiModel

# Connect to Phoenix
client = px.Client(endpoint="http://localhost:6006")

# Fetch recent traces
traces_df = client.get_spans_dataframe(project_name="finagent", limit=100)

# Define evaluator
relevance_eval = llm_classify(
    model=GeminiModel(model="gemini-1.5-flash"),
    template="""Given the user question and assistant response, 
    is the response relevant to the question?
    
    Question: {input}
    Response: {output}
    
    Answer: relevant or irrelevant""",
    labels=["relevant", "irrelevant"],
)

# Run evaluation
results = relevance_eval(traces_df)

# Log results back to Phoenix
client.log_evaluations(project_name="finagent", evaluations=results)
```

## Success Criteria

- [ ] All LLM calls appear in Phoenix UI with inputs/outputs
- [ ] Traces are grouped by user session
- [ ] Can see latency distribution across providers
- [ ] Evaluation script runs without errors
- [ ] Can identify problematic responses via eval scores

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Phoenix server adds latency | Traces sent async, non-blocking |
| Sensitive data in traces | Implement PII scrubbing before export |
| Phoenix server downtime | Graceful fallback - app continues without tracing |
| Token counts unavailable (Kiro CLI) | Mark as N/A, still track latency |

## Open Questions

1. **Where to run Phoenix server in production?**
   - Option A: Phoenix Cloud (managed, free tier available)
   - Option B: Self-host on same VM as FinAgent
   - Option C: Separate observability cluster

2. **Evaluation frequency?**
   - Option A: Real-time (every trace)
   - Option B: Batch (hourly/daily)
   - Recommendation: Start with batch, move to real-time if needed

3. **Data retention?**
   - How long to keep traces?
   - Recommendation: 30 days for dev, 7 days for prod (configurable)

## Summary: The Decorator Approach

**What we're doing:**
```
┌────────────────────────────────────────────────────────────┐
│  @traced_llm decorator on LLMProvider.complete()          │
│  @traced_llm_stream decorator on LLMProvider.complete_stream() │
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│  Captures for EVERY LLM call (CLI or SDK):                 │
│  ✅ Full prompt (system + user)                            │
│  ✅ Full response                                          │
│  ✅ Latency (automatic)                                    │
│  ✅ Provider name                                          │
│  ✅ Model name                                             │
└────────────────────────────────────────────────────────────┘
```

**Why this approach:**
- **2 lines of code** to instrument all providers
- **Zero changes** to existing provider implementations
- **Graceful fallback** if Phoenix not running
- **Works with CLI tools** that can't be auto-instrumented

**What we accept:**
- No token counts from CLI providers (they don't expose this)
- Manual decorator vs auto-instrumentation trade-off

## Next Steps

1. ✅ Plan reviewed and approved (decorator approach)
2. Implement Phase 1: Create `tracing/` module + apply decorators
3. Test with local Phoenix server
4. Iterate on Phase 2-4
