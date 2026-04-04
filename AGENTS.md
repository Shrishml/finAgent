# AGENTS.md — FinAgent Project Guide

> This file is for AI agents working on this repo. Read this first.

## Repo Layout

```
finagent/
├── src/              # Product code (Python + FastAPI)
│   ├── finagent/     # Main package
│   │   ├── llm/      # LLM provider abstraction (CLI-first)
│   │   ├── models/   # Dataclasses (FinancialSummary, MFHolding, etc.)
│   │   ├── agents/   # Domain agents (MF, Insurance, Loan)
│   │   ├── connectors/ # PDF parsers + data ingestion
│   │   ├── orchestrator/ # Intent routing + cross-domain reasoning
│   │   ├── storage/  # SQLite per-user storage
│   │   └── api/      # FastAPI endpoints
│   ├── ui/           # Chat + upload web UI
│   └── tests/        # Test suite
├── website/          # Landing page (GitHub Pages) — DO NOT mix with src/
├── research/         # User research, Reddit analysis — reference only
├── marketing/        # Content posts — reference only
└── docs/             # Internal docs (persona reviews, etc.)
```

## Key Documents

| Document | Purpose |
|----------|---------|
| `ARCHITECTURE.md` | System design — domain-rich adapter-thin pattern, routing, data models |
| `DESIGN_PLAN.md` | Implementation plan — LLM strategy, build order, success criteria |
| `ROADMAP.md` | 4-phase timeline with weekly targets |
| `README.md` | User-facing: what is FinAgent + quick start |

## Architecture Decisions (Do Not Revisit)

- **Deterministic routing** — intent classifier → route to agent. No LLM tool-picking.
- **Rich domain models** — each domain has its own dataclasses. No flat schemas.
- **Thin cross-domain adapter** — `FinancialSummary` is the only type the orchestrator sees.
- **No agent frameworks** — no LangChain, CrewAI, AutoGen. Custom routing is simpler.
- **CLI-first LLM** — `KiroCLIProvider` via `asyncio.create_subprocess_exec`. API provider is future.
- **Local-first** — SQLite per user, data never leaves their machine.
- **Global architecture** — India beachhead, but code is market-agnostic. Multi-currency, pluggable connectors.

## Coding Conventions

- Python 3.11+, type hints everywhere
- `dataclasses` for models, `ABC` for interfaces
- `async/await` throughout — FastAPI is async
- Dependency flow: `api → orchestrator → agents → {models, llm}` ← `connectors → models`
- No circular imports — models and llm are leaf modules

## How to Run

```bash
./start.sh          # One-command: venv + deps + launch
```

## Current Sprint

- **Phase 1, Week 2** (target: Apr 11, 2026)
- Focus: MF domain agent + CAMS connector + chat UI
- LLM provider: kiro-cli (zero cost)
- See `DESIGN_PLAN.md` Section 4 for build order
