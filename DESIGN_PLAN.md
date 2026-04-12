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


## 7. Fund Comparison Feature

### Problem
25% of Reddit questions are "which fund should I pick?" or "is there a better alternative?" Users can't easily compare their funds against category peers.

### Data Source
mfdata.in API (`/api/v1/search?q=...`) returns peer funds with: NAV, expense_ratio, AUM, morningstar rating, category, risk_label. Free, no auth.

### How It Works
1. For each holding, fetch category peers from mfdata.in (e.g., all "Flexi Cap" direct plans)
2. Rank peers by expense ratio and morningstar rating
3. Flag if user's fund is in bottom quartile for its category
4. Suggest cheaper/better-rated alternatives

### UI Cues
- Portfolio panel: funds with cheaper alternatives get a 💡 icon
- Clicking the icon shows: "3 funds in this category have lower expense ratios"
- Suggestion chip: "Are there cheaper alternatives to my funds?"
- Chat response includes comparison table

### Implementation
- `MFAgent.research()` enhanced with live mfdata.in peer lookup
- New endpoint: `GET /compare/{amfi_code}` — returns peer comparison data
- Portfolio panel gets clickable 💡 indicators

---

## 8. POC Deploy Plan (Week 2 — Apr 5-6, 2026)

> Goal: Ship the minimum deployable demo so real users can try FinBestie.
> Scope: Upload CAMS PDF → instant portfolio insights → chat with portfolio.
> No login, no accounts, no insurance. Just the core "wow" moment.

### 8.1 What's Ready

| Component | Status | Notes |
|-----------|--------|-------|
| CAMS PDF parsing | ✅ | casparser, CAMS + KFintech |
| AMFI enrichment | ✅ | mfdata.in, lazy + cached in SQLite |
| MF domain agent | ✅ | Analyze + research + compare modes |
| Intent router + orchestrator | ✅ | LLM classification + keyword fallback |
| FastAPI endpoints | ✅ | `/upload`, `/chat`, `/holdings`, `/clear`, `/compare` |
| Chat UI | ✅ | Single-page, PDF upload, Tailwind, suggestion chips |
| Tests | ✅ | 68 passing, 7 e2e |
| Landing page | ✅ | `suraj1074.github.io/finAgent/` with SVG visuals |

### 8.2 What's Missing

| Gap | Blocker? | Details |
|-----|----------|---------|
| Cloud LLM provider | 🚨 YES | App only has `kiro-cli` — won't run on cloud hosts |
| Deployment config | ❌ | No Dockerfile, Procfile, render.yaml |
| Error handling | ⚠️ | Upload has try/catch but returns raw exception strings |
| Privacy notice | ❌ | Users need to know we don't store their data |
| Rate limiting | ❌ | Free tier abuse prevention |
| Landing page CTA | ❌ | No "Try it Live" button pointing to deployed app |

### 8.3 Task Breakdown

#### Task 1: Gemini API Provider (30 min) — BLOCKER, DO FIRST

**Why:** `kiro-cli` is a local Amazon tool. Cloud hosts (Render/Railway) can't run it. We need a real API provider. Gemini Flash free tier gives 15 RPM + 1M tokens/day — plenty for POC.

**Files to create/modify:**
- **Create** `src/finagent/llm/gemini.py`
  ```python
  class GeminiProvider(LLMProvider):
      """Google Gemini API provider for cloud deployment."""
      # Uses google-generativeai SDK
      # Reads GEMINI_API_KEY from env or config.toml
      # Model: gemini-2.0-flash (free tier)
  ```
- **Modify** `src/finagent/llm/registry.py` — register `"gemini"` provider
- **Modify** `src/pyproject.toml` — add `google-generativeai` to dependencies
- **Modify** `src/config.toml.example` — add gemini config section:
  ```toml
  [llm]
  default = "kiro"  # local dev
  # default = "gemini"  # cloud deploy

  [llm.gemini]
  api_key = ""  # or set GEMINI_API_KEY env var
  model = "gemini-2.0-flash"
  ```

**Acceptance criteria:**
- `get_provider("gemini")` returns working GeminiProvider
- Chat works end-to-end with Gemini: upload PDF → ask question → get answer
- Falls back gracefully if no API key configured

---

#### Task 2: Deploy to Render Free Tier (1.5 hrs)

**Why Render over Railway:** Render has a simpler free tier — no credit card required, auto-sleep after 15 min inactivity (fine for POC), custom domains later.

**Files to create/modify:**
- **Create** `Dockerfile`
  ```dockerfile
  FROM python:3.11-slim
  WORKDIR /app
  COPY src/ ./src/
  RUN pip install ./src/
  ENV PORT=8080
  EXPOSE $PORT
  CMD ["python", "-m", "uvicorn", "finagent.main:app", "--host", "0.0.0.0", "--port", "$PORT"]
  ```
- **Create** `render.yaml` — Render blueprint for one-click deploy
  ```yaml
  services:
    - type: web
      name: finbestie
      runtime: docker
      plan: free
      envVars:
        - key: GEMINI_API_KEY
          sync: false
        - key: FINAGENT_LLM_DEFAULT
          value: gemini
  ```
- **Modify** `src/finagent/main.py`:
  - Read `PORT` from env var (Render sets this)
  - Add CORS middleware allowing `suraj1074.github.io`
  - Bind to `0.0.0.0` instead of `127.0.0.1`
- **Modify** `src/finagent/config.py`:
  - Support env var overrides: `GEMINI_API_KEY`, `FINAGENT_LLM_DEFAULT`, `PORT`
  - Env vars take precedence over config.toml

**Acceptance criteria:**
- `docker build . && docker run -p 8080:8080 -e GEMINI_API_KEY=xxx` works locally
- Render deploy succeeds, app accessible at `finbestie.onrender.com`
- Upload PDF from browser → get insights → chat works end-to-end
- CORS allows requests from GitHub Pages landing page

---

#### Task 3: Error Handling + Privacy (1.5 hrs)

**3a. PDF Error Handling**

Current state: upload endpoint catches exceptions but returns raw error strings. Users see Python tracebacks.

**Modify** `src/finagent/main.py` (upload endpoint):
- Catch `casparser` specific exceptions → friendly messages:
  - Wrong password → "Incorrect password. CAMS statements use your PAN as password (e.g., ABCDE1234F)"
  - Not a CAS PDF → "This doesn't look like a CAMS/KFintech statement. Please upload your Consolidated Account Statement (CAS)"
  - Corrupt file → "Couldn't read this PDF. Please try downloading a fresh copy from your registrar"
- Return structured error JSON: `{"error": true, "message": "...", "hint": "..."}`

**Modify** `src/ui/index.html`:
- Show error messages in a styled toast/banner (not alert())
- Add hint text below error message

**3b. Privacy Notice**

**Modify** `src/ui/index.html`:
- Add banner below upload area: "🔒 Your data stays in your session. We don't store your files or portfolio data. All processing happens in memory and is cleared when you close this tab."
- For cloud deploy: add note that data is processed on server but not persisted

**3c. Rate Limiting**

**Modify** `src/finagent/main.py`:
- Add simple in-memory rate limiter: 10 uploads/hour per IP, 30 chat messages/hour per IP
- Return 429 with friendly message: "You've hit the limit. Try again in a few minutes."
- No external dependency — just a dict of `{ip: [timestamps]}`

**Acceptance criteria:**
- Bad PDF upload shows helpful message, not stack trace
- Privacy notice visible on page load
- 11th upload in an hour returns 429

---

#### Task 4: Landing Page CTA + README (30 min)

**Modify** `website/index.html`:
- Add prominent "Try it Live →" button in hero section
- Link to `https://finbestie.onrender.com` (or whatever the deploy URL is)
- Style: primary CTA color, large, above the fold

**Modify** `README.md`:
- Add "🚀 Live Demo" section at top with deploy URL
- Add "Deploy Your Own" section with Render one-click button
- Update project description to mention FinBestie name

**Acceptance criteria:**
- Landing page has clickable CTA that opens the deployed app
- README has live demo link
- Render deploy button works for others who want to self-host

---

#### Task 5: NAV History Engine (2 hrs)

**Why:** Historical NAV data unlocks ~50% of what Reddit users ask — fund comparison, rolling returns, crash stress tests, SIP simulation, consistency scores. The mfdata.in API (`/mf/{amfi_code}`) returns full daily NAV history back to fund inception (up to ~20 years, ~4900 data points), no auth, no pagination.

**Files to create/modify:**
- **Create** `src/finagent/analytics/nav_history.py`
  ```python
  class NAVHistoryEngine:
      """Fetch + cache historical NAV, compute derived metrics."""
      # fetch(amfi_code) → list of (date, nav) from api.mfapi.in
      # Cache in SQLite: nav_history table (amfi_code, date, nav), refresh weekly
      # Compute: cagr, rolling_returns(1Y/3Y/5Y/10Y), volatility, max_drawdown,
      #          sharpe_ratio, crash_stress_test(covid/gfc/nbfc), sip_simulation,
      #          consistency_score (% of rolling 3Y periods with positive returns)
  ```
- **Modify** `src/finagent/agents/mf.py` — add `deep_dive` mode using NAVHistoryEngine
- **Modify** `src/finagent/storage/sqlite.py` — add `nav_history` table
- **Modify** `src/finagent/api/chat.py` — route deep-dive intents (e.g. "how did X do in COVID?")

**Key metrics to compute from NAV:**
| Metric | Method | User question it answers |
|--------|--------|--------------------------|
| CAGR | `(end/start)^(1/years) - 1` | "How has this fund performed?" |
| Rolling returns | Every possible N-year window | "Is this fund consistent?" |
| Volatility | Annualized std dev of daily returns | "How risky is this fund?" |
| Max drawdown | Worst peak-to-trough | "What's the worst case?" |
| Sharpe ratio | `(CAGR - risk_free) / volatility` | "Is the return worth the risk?" |
| Crash stress test | Drawdown + recovery during known crashes | "How did it do in COVID/2008?" |
| SIP simulation | Monthly investment × NAV units | "What if I did ₹10K SIP since 2015?" |
| Consistency score | % rolling 3Y periods > 0 | "How reliable is this fund?" |

**Acceptance criteria:**
- `engine.fetch(amfi_code)` returns cached NAV history
- `engine.rolling_returns(amfi_code, years=3)` returns all rolling windows
- `engine.crash_test(amfi_code)` returns drawdown + recovery for COVID, GFC, NBFC
- Chat: "How did Parag Parikh do in COVID?" returns specific drawdown % and recovery months

---

### 8.4 Dependency Chain

```
Task 1 (Gemini) ──→ Task 2 (Deploy) ──→ Task 4 (CTA + README)
                         ↑
Task 3 (Errors/Privacy) ─┘

Task 5 (NAV History) ── independent, can run in parallel with Tasks 1-4
```

Tasks 1 and 3 are independent — can be done in parallel.
Task 2 depends on Task 1 (need Gemini provider to deploy).
Task 4 depends on Task 2 (need the live URL for the CTA button).
Task 5 is independent — no deploy dependency, enhances the product post-deploy.

### 8.5 Time Budget

| Task | Estimate | Cumulative |
|------|----------|------------|
| Task 1: Gemini provider | 30 min | 0:30 |
| Task 3: Error handling + privacy | 1.5 hrs | 2:00 |
| Task 2: Render deploy | 1.5 hrs | 3:30 |
| Task 4: Landing page + README | 30 min | 4:00 |
| Task 5: NAV History Engine | 2 hrs | 6:00 |

**Total: ~6 hours across two sessions (deploy sprint + analytics sprint).**

### 8.6 Post-Deploy: CMO Soft Launch

Once the URL is live, the CMO will:
1. Adapt existing Reddit drafts (in `marketing/posts/`) with the live URL
2. Execute the 3-post arc on r/IndiaInvestments (week 1)
3. Expand to r/personalfinance and r/algotrading (week 2)
4. Track: 50+ uploads, 5+ organic mentions, 10+ GitHub stars in 2 weeks

### 8.7 What's Explicitly NOT in This POC

- ❌ User accounts / saved portfolios
- ❌ Insurance / loan analysis
- ❌ Multi-currency (INR only for beachhead)
- ❌ Broker API integration
- ❌ Tax optimization
- ❌ Streaming responses
- ❌ Mobile app

These come after we validate demand with the POC.

---

## 9. Resolved Questions

| Question | Answer | Source |
|----------|--------|--------|
| kiro-cli `--no-interactive` | ✅ Exists. Also supports `--trust-all-tools` and positional `[INPUT]` arg | `kiro-cli chat --help` |
| casparser password handling | `casparser.read_cas_pdf(path, password)` — password is 2nd positional arg. UI needs a password input field | casparser README on GitHub |
| AMFI rate limits | No documented rate limits on amfiindia.com. Cache NAV data in SQLite with 24h TTL as precaution | mftool source + PyPI |
| Deployment without CLI | Gemini Flash free tier (15 RPM, 1M tokens/day). Deploy to Render free tier with Docker | POC deploy plan, Apr 5 |
| Cloud host choice | Render over Railway — no credit card, simpler free tier, auto-sleep OK for POC | CTO sprint planning |

---

*Created: April 4, 2026*
*Updated: April 6, 2026 — added NAV History Engine task (Task 5 in Section 8)*
*Updated: April 11, 2026 — added Section 9: Insight Generation Engine*
*Status: v3 — POC deploy sprint in progress, analytics sprint queued*

---

## 9. Insight Generation Engine

### 9.1 Rationale

From our Reddit research (~120 questions across 23 threads in r/IndiaInvestments), the #1 user need is: **"Tell me what to DO, not just show data."** (User A, 28y SWE, interview).

Most portfolio tools show dashboards — charts, numbers, tables. Users stare at them and don't know what action to take. The insight engine bridges this gap by automatically detecting patterns in portfolio data and surfacing them as actionable cards, each linked to a chat conversation for deeper discussion.

Design principle: **Balance positive reinforcement with actionable warnings.** Users who see only problems feel attacked and bounce. Users who see only praise don't get value. The two-row layout ("What's working" + "Worth a look") validates good behavior first, then surfaces issues.

### 9.2 Architecture

Insights are generated **on the backend** via the `GET /insights` endpoint. The endpoint loads the user's holdings, filters zero-value funds, and runs all 10 rule-based detections server-side. Returns `{good: [...], action: [...]}` JSON. The frontend simply fetches and renders cards — no computation. This keeps logic centralized, testable, and consistent across clients.

Each insight is a card with: icon, title, description, and a pre-filled chat question. Clicking a card switches to the Chat tab and sends the question to the LLM for a detailed, personalized response. This creates a **two-tier system**: fast rule-based detection (frontend) → deep LLM analysis (backend).

### 9.3 Insight Definitions

#### ✅ "What's working" (green row)

| # | Insight | Detection Logic | Threshold | Chat Question |
|---|---------|----------------|-----------|---------------|
| G1 | **Top performer** | Highest XIRR fund | Any fund with XIRR data | "Tell me more about [fund name]" |
| G2 | **All direct plans** | No fund has `plan === 'regular'` | 0 regular funds, >1 total | "How much do direct plans save me?" |
| G3 | **Consistent SIPs** | Funds with ≥3 transactions | ≥2 funds qualify | "How are my SIPs performing?" |
| G4 | **Well diversified** | Distinct asset classes (Equity/Debt/Hybrid) excluding 'Other' | ≥3 asset classes | "Is my diversification good enough?" |
| G5 | **Beating the market** | Average portfolio XIRR vs Nifty 50 long-term average | Avg XIRR > 12% | "How does my portfolio compare to Nifty 50?" |

#### ⚠️ "Worth a look" (amber row)

| # | Insight | Detection Logic | Threshold | Chat Question |
|---|---------|----------------|-----------|---------------|
| A1 | **Underperformers** | Negative return OR XIRR < portfolio avg by >5% | ≥1 fund qualifies | "Which funds should I replace?" |
| A2 | **Regular plan funds** | `plan === 'regular'` | ≥1 fund | "Should I switch from regular to direct plans?" |
| A3 | **Over-diversification** | Total fund count | >7 funds | "Do any of my funds overlap?" |
| A4 | **Small cap heavy** | Small cap value / total portfolio value | >30% | "Do I have too much in small caps?" |
| A5 | **No debt allocation** | Zero value in Debt asset class | 0% debt, >2 funds total | "Should I add debt funds to my portfolio?" |

### 9.4 Display Rules

- Show max 5 cards per row (all that match)
- Always show green row first (positive reinforcement)
- Each card is clickable → switches to Chat tab → sends the question
- Chat tab's "smart suggestions" are sourced from both rows + a generic "Give me a summary"
- Cards use `data-q` attributes + `addEventListener` (not inline onclick) for reliable quote handling

### 9.5 Reddit Research Mapping

Each insight maps to a real Reddit question pattern:

| Insight | Reddit Pattern (% of ~120 questions) | Example Quote |
|---------|--------------------------------------|---------------|
| A1 Underperformers | "Review my portfolio" (25%) | "Am I over-diversified with 7 funds? Should I consolidate?" |
| A2 Regular plans | "Which fund?" (25%) | "Should I switch from regular to direct?" |
| A3 Over-diversification | "Review my portfolio" (25%) | "I have 8 funds — should I consolidate to 4?" |
| A4 Small cap heavy | "Market crash" (5%) | "Portfolio down 18% — should I stop SIPs?" |
| A5 No debt | "FD vs alternatives" (8%) | "₹10L in FD creating tax liability — what else?" |
| G5 Beating market | "Market crash" (5%) | Emotional decisions during volatility |

### 9.6 Parked for Phase 2

| Insight | Why Parked | Dependency |
|---------|-----------|------------|
| **High expense ratio** | mfdata.in is down (502), expense ratio data unavailable | mfdata.in recovery or alternative data source |
| **Category benchmark comparison** | Need category-level 3Y/5Y return benchmarks | Benchmark data source (e.g., AMFI category returns) |
| **Asset allocation vs goals** | Need user's risk profile and investment goals | User onboarding / goal-setting feature |
| **Tax harvesting opportunity** | Need LTCG/STCG computation from transaction history | Tax engine (future domain agent) |
