# Arize Phoenix Integration Guide

LLM observability and tracing for FinAgent using Arize Phoenix.

## Overview

Phoenix traces all LLM calls automatically via decorators on the base `LLMProvider` class. When enabled, you can:

- View all LLM inputs/outputs in a web UI
- See latency for each call
- Group traces by user session
- Run evaluations on traces

## Quick Start

### 1. Install Dependencies

```bash
pip install arize-phoenix-otel openinference-semantic-conventions
```

Or install with the tracing extra:

```bash
pip install -e ".[tracing]"
```

### 2. Start Phoenix Server

**Option A: Podman/Docker**
```bash
# Create persistent volume
podman volume create phoenix_data

# Run Phoenix
podman run -d --name phoenix \
  -p 6006:6006 \
  -v phoenix_data:/data \
  -e PHOENIX_WORKING_DIR=/data \
  arizephoenix/phoenix:latest
```

**Option B: Python**
```bash
pip install arize-phoenix
python -m phoenix.server.main serve --port 6006
```

### 3. Enable Tracing

```bash
export PHOENIX_ENABLED=1
export PHOENIX_ENDPOINT="http://localhost:6006/v1/traces"  # optional, this is default
export PHOENIX_PROJECT_NAME="finagent"  # optional, default is "finagent"
```

### 4. Run FinAgent

```bash
./start.sh
```

### 5. View Traces

Open http://localhost:6006 in your browser.

## Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `PHOENIX_ENABLED` | Enable tracing (`1` or `true`) | Disabled | Yes, to enable |
| `PHOENIX_ENDPOINT` | OTLP collector URL | `http://localhost:6006/v1/traces` | No |
| `PHOENIX_PROJECT_NAME` | Project name in UI | `finagent` | No |
| `PHOENIX_API_KEY` | API key (Phoenix Cloud only) | None | Only for cloud |

## What Gets Traced

### LLM Calls (`@traced_llm`)

Every `LLMProvider.complete()` and `complete_stream()` call:

| Field | Description |
|-------|-------------|
| `input.system` | System prompt |
| `input.prompt` | User prompt |
| `output` | Full LLM response |
| `llm.provider` | Provider name (gemini-api, kiro, etc) |
| `llm.model_name` | Model identifier |
| `llm.invocation_parameters.json_mode` | JSON mode flag |
| Latency | Automatic from span duration |

### Orchestrator (`@traced_orchestrator`)

Each `handle_query()` call creates a parent span:

| Field | Description |
|-------|-------------|
| `input` | User query |
| `output` | Final response |
| `session.id` | User ID for grouping |
| `user.id` | User identifier |

### Intent Classification (`@traced_chain`)

```
orchestrator.handle_query
├── chain.intent_classifier
├── llm.gemini-api (or llm.kiro)
└── ...
```

## Graceful Degradation

Tracing is **opt-in** and fails gracefully:

- If `PHOENIX_ENABLED` is not set → tracing disabled, no overhead
- If Phoenix server is down → traces dropped silently, app continues
- If `arize-phoenix-otel` not installed → tracing disabled, no import errors

You can safely deploy without Phoenix configured.

## Production Setup

### Phoenix Cloud (Recommended)

1. Sign up at https://app.phoenix.arize.com
2. Create a project, get API key
3. Configure:

```bash
export PHOENIX_ENABLED=1
export PHOENIX_ENDPOINT="https://app.phoenix.arize.com/v1/traces"
export PHOENIX_API_KEY="your-api-key"
export PHOENIX_PROJECT_NAME="finagent-prod"
```

### Self-Hosted (Kubernetes)

See `docs/ARIZE_PHOENIX_INTEGRATION_PLAN.md` for Kubernetes deployment manifests.

## Local Development Commands

```bash
# Start Phoenix
podman start phoenix

# Stop Phoenix
podman stop phoenix

# View logs
podman logs -f phoenix

# Check status
podman ps --filter name=phoenix

# Remove container (keeps data)
podman rm phoenix

# List volumes
podman volume ls
```

## Troubleshooting

### Traces not appearing

1. Check Phoenix is running: `curl http://localhost:6006/health`
2. Check `PHOENIX_ENABLED=1` is set
3. Check endpoint is correct: `echo $PHOENIX_ENDPOINT`
4. Check logs for errors: `podman logs phoenix`

### Import errors

Install the tracing dependencies:

```bash
pip install arize-phoenix-otel openinference-semantic-conventions
```

### High latency

Traces are sent asynchronously and shouldn't impact latency. If you notice slowdown:

1. Check Phoenix server resources
2. Consider using Phoenix Cloud for better performance
3. Use batch span processor (configure in `tracing/__init__.py`)

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  FinAgent                       │
│                                                 │
│  @traced_orchestrator                           │
│  handle_query() ─────────────────────┐          │
│       │                              │          │
│       ├── @traced_chain              │          │
│       │   classify_intent()          │          │
│       │                              │          │
│       └── @traced_llm               │          │
│           LLMProvider.complete()     │          │
│                                      ▼          │
│                              ┌──────────────┐   │
│                              │   Tracer     │   │
│                              │  (phoenix)   │   │
│                              └──────┬───────┘   │
└─────────────────────────────────────┼───────────┘
                                      │ OTLP/HTTP
                                      ▼
                          ┌───────────────────────┐
                          │   Phoenix Server      │
                          │   localhost:6006      │
                          └───────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `tracing/__init__.py` | Tracer initialization |
| `tracing/decorators.py` | `@traced_llm`, `@traced_chain`, `@traced_orchestrator` |
| `llm/base.py` | LLM base class with `@traced_llm` |
| `orchestrator/engine.py` | Orchestrator with `@traced_orchestrator` |
| `orchestrator/router.py` | Intent classifier with `@traced_chain` |
