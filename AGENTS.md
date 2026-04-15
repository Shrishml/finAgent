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

## Development & Testing

### Environments

| Environment | URL | Branch | Auth |
|-------------|-----|--------|------|
| **Prod** | https://captwist.in | `main` | Google OAuth required |
| **Beta** | https://beta.captwist.in | `dev` | `DEV_MODE=1` — no login needed |

### Build → Test → Deploy Workflow

> **⚠️ A feature is NOT complete until it is tested and verified on beta.captwist.in.**
> Testing on beta is the agent's responsibility. Do not report a feature as done without confirming it works on beta.

```bash
# 1. Work on dev branch
git checkout dev

# 2. Make changes, run unit tests
cd src && python -m pytest tests/

# 3. Commit (GPG keyring may not persist — use unsigned commits on dev)
git -c commit.gpgsign=false commit -m "feat: description"

# 4. Push to dev → GitHub Actions auto-deploys to beta (~60s)
git push origin dev

# 5. Seed test data on beta (one-time, persists across deploys)
curl -X POST https://beta.captwist.in/dev/seed

# 6. Verify
curl https://beta.captwist.in/auth/me          # → Dev User
curl https://beta.captwist.in/holdings          # → 6 sample holdings
curl https://beta.captwist.in/insights          # → portfolio insights
curl https://beta.captwist.in/suggestions       # → chat suggestions

# 7. Reset dev data if needed
curl -X POST https://beta.captwist.in/dev/reset
```

### DEV_MODE Details

Set via `DEV_MODE=1` environment variable in the beta systemd service.

- `/auth/me` returns `{"status": "ok", "user": {"name": "Dev User"}}` — frontend skips OAuth
- `require_auth` and `_get_user_id` return a persistent dev user (stored in SQLite)
- `POST /dev/seed` — copies demo portfolio (6 MF holdings) to dev user
- `POST /dev/reset` — clears dev user data
- Both `/dev/*` endpoints return 404 when `DEV_MODE` is off (safe for prod)

### CI/CD

- **Trigger**: Push to `dev` branch
- **Workflow**: `.github/workflows/deploy-beta.yml`
- **Script**: `scripts/update-beta.sh` (runs on Azure VM via SSH)
- **Secrets required**: `BETA_HOST`, `BETA_USER`, `BETA_SSH_KEY`

### Branch Protection

- `main` branch requires PRs + GPG-signed commits
- `dev` branch has no restrictions — direct push OK
- Merge to main: create PR from dev, ensure GPG signing
