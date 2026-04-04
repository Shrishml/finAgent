# FinAgent — Prototype Design Plan

> Sprint target: Working demo by Apr 11, 2026 (end of Week 2)
> This document covers implementation decisions not in ARCHITECTURE.md.

---

## 1. Repo Reorganization

The repo currently mixes marketing (landing page, posts, research) with product code. Reorganize by function:

### New Structure

```
finagent/
├── AGENTS.md                 # Agent guide — links all docs, explains repo layout
├── ARCHITECTURE.md           # System design (existing)
├── DESIGN_PLAN.md            # This file — prototype implementation plan
├── ROADMAP.md                # Phase plan (existing)
├── README.md                 # User-facing: what is FinAgent + quick start
├── LICENSE
│
├── src/                      # ← ALL product code lives here
│   ├── pyproject.toml
│   ├── config.toml.example
│   ├── finagent/
│   │   ├── __init__.py
│   │   ├── main.py           # FastAPI app + startup
│   │   ├── config.py         # Load config.toml
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   ├── base.py       # LLMProvider ABC
│   │   │   ├── kiro.py       # KiroCLIProvider
│   │   │   └── registry.py   # get_provider()
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── summary.py    # FinancialSummary
│   │   │   └── mf.py         # MFHolding, MFTransaction
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── base.py       # DomainAgent ABC
│   │   │   └── mf.py         # MFAgent
│   │   ├── connectors/
│   │   │   ├── __init__.py
│   │   │   ├── base.py       # Connector ABC
│   │   │   ├── registry.py   # ConnectorRegistry
│   │   │   └── cams.py       # CAMSConnector (casparser)
│   │   ├── orchestrator/
│   │   │   ├── __init__.py
│   │   │   ├── router.py     # Intent classifier + routing
│   │   │   └── engine.py     # Orchestrator
│   │   ├── storage/
│   │   │   ├── __init__.py
│   │   │   └── sqlite.py     # Per-user SQLite store
│   │   └── api/
│   │       ├── __init__.py
│   │       ├── chat.py        # POST /chat
│   │       └── upload.py      # POST /upload
│   ├── ui/
│   │   └── index.html         # Chat + upload UI
│   └── tests/
│       └── ...
│
├── website/                   # ← Landing page + scenarios
│   ├── index.html             # GitHub Pages landing page
│   ├── scenarios/
│   │   ├── portfolio-review.html
│   │   ├── fd-tax-trap.html
│   │   ├── insurance-gaps.html
│   │   └── market-crash.html
│   ├── assets/
│   │   ├── architecture.svg
│   │   ├── mockup.svg
│   │   └── terminal-demo.svg
│   └── WEBSITE_SITUATIONS.md
│
├── research/                  # ← User research + Reddit analysis
│   ├── user-pain-point/
│   │   ├── REDDIT_ANALYSIS.md
│   │   ├── RESEARCH_SUMMARY.md
│   │   ├── USER_RESEARCH.md
│   │   └── raw-discussion-reddit/
│   └── fetch_reddit_thread.py
│
├── marketing/                 # ← Posts + content
│   └── posts/
│       ├── linkedin-announcement.md
│       ├── post1-linkedin-FINAL.md
│       └── ...
│
└── docs/                      # ← Internal docs (persona reviews, etc.)
    └── persona-reviews.md
```

### Key Changes
- `src/` — all product code, isolated from marketing/research
- `website/` — landing page assets (GitHub Pages can be configured to serve from here)
- `research/` — user research data, Reddit analysis
- `marketing/` — content posts
- `AGENTS.md` — the glue document (see below)

### AGENTS.md Purpose

This file is for AI agents (me, next time) working on this repo. It contains:
- Repo layout map — what lives where
- Links to key docs: ARCHITECTURE.md (design), DESIGN_PLAN.md (implementation), ROADMAP.md (timeline)
- Coding conventions (Python style, import order, etc.)
- How to run/test the project
- Current sprint status and what's in progress
- Known gotchas and decisions that shouldn't be revisited

---

## 2. LLM Strategy: CLI-First with API Escape Hatch

### Problem
LLM API calls are expensive during prototyping. Gemini Flash rate-limits aggressively. We need unlimited LLM calls at zero cost during development.

### Decision: Pluggable LLM Provider with CLI as Default

```
User query → Orchestrator → LLMProvider.complete(prompt) → response
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              KiroCLIProvider  GeminiCLI      APIProvider
              (default)        Provider       (future)
```

**Why CLI works for us:**
- MeshClaw (our own tooling) runs on this exact pattern — kiro-cli subprocess calls via `asyncio.create_subprocess_exec`
- User installs FinAgent locally → uses their own CLI subscription → zero marginal cost
- Structured JSON output via system prompts eliminates brittle stdout parsing
- `asyncio.create_subprocess_exec` gives us proper process lifecycle management

**Why we need the abstraction:**
- Swap CLI → API without touching business logic
- Different providers for different tasks (cheap provider for parsing, quality provider for reasoning)
- Users pick their provider based on what they have installed

### LLMProvider Interface

```python
class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, prompt: str, system: str = "", json_mode: bool = False) -> str:
        """Send prompt, get response. json_mode forces JSON output."""

    @abstractmethod
    async def complete_stream(self, prompt: str, system: str = "") -> AsyncIterator[str]:
        """Streaming response for chat UI."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier for logging."""
```

### CLI Provider Implementation Pattern

Learned from MeshClaw's `transcribe.py` and `subagent.py`:

```python
class KiroCLIProvider(LLMProvider):
    """Uses kiro-cli chat as LLM backend."""

    async def complete(self, prompt: str, system: str = "", json_mode: bool = False) -> str:
        full_prompt = self._build_prompt(prompt, system, json_mode)
        proc = await asyncio.create_subprocess_exec(
            "kiro-cli", "chat", "--no-interactive", "--trust-all-tools",
            full_prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=120
        )
        return self._extract_response(stdout.decode())
```

Key design choices:
- `--no-interactive` flag confirmed to exist — suppresses interactive prompts
- `--trust-all-tools` auto-approves tool calls (no user confirmation needed)
- Prompt passed as positional `[INPUT]` argument — no stdin piping needed
- `asyncio.wait_for` with 120s timeout — financial analysis prompts can be long
- `_extract_response()` strips CLI chrome (banners, status lines) from output
- `_build_prompt()` injects JSON schema when `json_mode=True`

### Provider Selection

```python
# config.toml
[llm]
default = "kiro"        # or "gemini-cli", "claude-cli", "api"
parsing = "kiro"         # cheap/fast provider for PDF extraction
reasoning = "kiro"       # quality provider for financial analysis

[llm.api]                # only needed if using API provider
gemini_key = ""
claude_key = ""
```

### Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| CLI output format changes between versions | `_extract_response()` uses heuristics (strip known prefixes/suffixes) + integration test |
| CLI startup latency (~2-3s per call) | Batch prompts where possible; cache parsed results in SQLite |
| ToS concerns for programmatic CLI use | Local/personal use only, not a hosted service. Documented clearly |
| CLI not installed | Graceful error: "kiro-cli not found. Install it or configure an API key in config.toml" |

---

## 3. One-Command Install

The entire project must be installable and runnable with a single command. The install script:

1. Checks Python 3.11+ is installed
2. Creates a virtual environment
3. Installs all dependencies via `pip install -e .`
4. Checks for an LLM CLI tool (kiro-cli, claude, gemini) — warns if none found
5. Creates default `config.toml` if missing
6. Launches the chat UI in the browser

### Usage

```bash
git clone https://github.com/suraj1074/finAgent.git
cd finAgent
./start.sh
```

### `start.sh` Script

```bash
#!/bin/bash
set -e
cd "$(dirname "$0")/src"

# Check Python
python3 --version | grep -qE "3\.(1[1-9]|[2-9][0-9])" || {
    echo "❌ Python 3.11+ required"; exit 1
}

# Create venv if needed
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate

# Install deps
pip install -e . --quiet

# Check LLM CLI
if command -v kiro-cli &>/dev/null; then
    echo "✅ kiro-cli found"
elif command -v claude &>/dev/null; then
    echo "✅ claude CLI found"
elif command -v gemini &>/dev/null; then
    echo "✅ gemini CLI found"
else
    echo "⚠️  No LLM CLI found. Install kiro-cli, claude, or gemini CLI."
    echo "   Or configure an API key in config.toml"
fi

# Default config
[ -f config.toml ] || cp config.toml.example config.toml

# Launch
echo "🚀 Starting FinAgent..."
python -m finagent.main
```

This means your friends just need: `git clone` + `./start.sh`. No Docker, no manual pip installs.

---

## 4. Build Order (This Weekend)

### Session 1: Foundation (~2 hrs)

**Step 1: Repo Reorganization**
- Move files into `website/`, `research/`, `marketing/`, `docs/` structure
- Create `src/` directory with `pyproject.toml`
- Create `AGENTS.md`
- Create `start.sh`

**Step 2: LLM Provider Layer**
- `LLMProvider` ABC in `llm/base.py`
- `KiroCLIProvider` in `llm/kiro.py`
- `get_provider()` registry in `llm/registry.py`
- Smoke test: `await provider.complete("What is 2+2?")`

**Step 3: Core Models**
- `FinancialSummary` dataclass in `models/summary.py`
- `MFHolding`, `MFTransaction` in `models/mf.py`
- `DomainAgent` ABC in `agents/base.py`
- `Connector` ABC in `connectors/base.py`

### Session 2: MF Pipeline (~3 hrs)

**Step 4: CAMS Connector**
- `CAMSConnector` wraps casparser
- Upload PDF → parse with password → list of `MFHolding` objects
- casparser API: `casparser.read_cas_pdf(path, password)` — password is 2nd positional arg
- AMFI enrichment via mftool (live NAV, scheme metadata) — cache in SQLite with 24h TTL

**Step 5: MF Agent — Analyze Mode**
- Expense ratio analysis (flag funds > 1%, suggest direct plan alternatives)
- Portfolio overlap detection (compare top holdings across funds)
- XIRR calculation per fund and portfolio-level
- Uses LLM for natural language response generation only — computation is deterministic

**Step 6: SQLite Storage**
- Per-user SQLite DB in `data/users/{user_id}.db`
- Store parsed MFHoldings
- Simple schema: `holdings` table with JSON blob per holding

### Session 3: Chat + UI (~1.5 hrs)

**Step 7: Intent Router**
- Single LLM call to classify: `{domain, mode, entities}`
- Deterministic dispatch to agent + mode
- Fallback: if classification fails, ask user to clarify

**Step 8: API + UI**
- `POST /upload` — accept PDF + password, run through connector registry, store results
- `POST /chat` — accept query, route through orchestrator, return response
- `GET /` — serve `ui/index.html` (Tailwind, single page, upload + chat)
- Auto-opens browser on `start.sh`

---

## 5. What's NOT in the Prototype

Explicitly deferred to keep scope tight:

- ❌ Insurance/Loan agents (Phase 2)
- ❌ Cross-domain reasoning (Phase 2 — needs 2+ agents)
- ❌ Knowledge graph (Phase 2 — needs cross-domain)
- ❌ Streaming responses (nice-to-have, add after core works)
- ❌ User auth (prototype is single-user local)
- ❌ Multiple CLI providers (start with kiro only, add others when needed)
- ❌ API provider (add when we need hosted version)
- ❌ Broker API integrations (Phase 3)
- ❌ Cloud deployment (Phase 2 — prototype is local-only, friends install locally)

---

## 6. Success Criteria for Prototype

By Apr 11 (end of Week 2), the prototype should:

1. ✅ Install and run via `./start.sh` (one command)
2. ✅ Accept a CAMS/KFintech PDF upload (with password field)
3. ✅ Parse it into structured MF holdings
4. ✅ Answer: "What are my expense ratios?" with fund-by-fund breakdown
5. ✅ Answer: "Do any of my funds overlap?" with holding comparison
6. ✅ Answer: "What's my portfolio XIRR?" with per-fund and aggregate returns
7. ✅ Suggest direct plan alternatives for regular plan funds
8. ✅ Work entirely via CLI LLM (zero API cost)
9. ✅ Have a chat UI that a non-technical person can use

---

## 7. Resolved Questions

| Question | Answer | Source |
|----------|--------|--------|
| kiro-cli `--no-interactive` | ✅ Exists. Also supports `--trust-all-tools` and positional `[INPUT]` arg | `kiro-cli chat --help` |
| casparser password handling | `casparser.read_cas_pdf(path, password)` — password is 2nd positional arg. UI needs a password input field | casparser README on GitHub |
| AMFI rate limits | No documented rate limits on amfiindia.com. Cache NAV data in SQLite with 24h TTL as precaution | mftool source + PyPI |
| Deployment without CLI | Deferred. Prototype is local-only. Cloud deployment (Phase 2) will use API provider | Design feedback #2 |

---

*Created: April 4, 2026*
*Updated: April 4, 2026 — incorporated design review feedback*
*Status: v2 — pending final approval*
