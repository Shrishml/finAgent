# FinAgent — Prototype Design Plan

> Sprint target: Working demo by Apr 11, 2026 (end of Week 2)
> This document covers implementation decisions not in ARCHITECTURE.md.

---

## 1. LLM Strategy: CLI-First with API Escape Hatch

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
            "kiro-cli", "chat", "--no-interactive",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(full_prompt.encode()),
            timeout=120
        )
        return self._extract_response(stdout.decode())
```

Key design choices:
- `--no-interactive` flag to suppress prompts (verify flag exists, fallback to piped stdin)
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

Users configure once. Code uses:
```python
llm = get_provider("parsing")   # returns configured provider
llm = get_provider("reasoning") # may be different provider
```

### Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| CLI output format changes between versions | `_extract_response()` uses heuristics (strip known prefixes/suffixes) + integration test that runs on CI |
| CLI startup latency (~2-3s per call) | Batch prompts where possible; cache parsed results in SQLite |
| ToS concerns for programmatic CLI use | This is local/personal use, not a hosted service. Users run their own subscription. Document this clearly |
| CLI not installed | Graceful error: "kiro-cli not found. Install it or configure an API key in config.toml" |

---

## 2. Project Structure

```
finagent/
├── pyproject.toml
├── config.toml.example
├── finagent/
│   ├── __init__.py
│   ├── main.py              # FastAPI app + startup
│   ├── config.py            # Load config.toml
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── base.py          # LLMProvider ABC
│   │   ├── kiro.py          # KiroCLIProvider
│   │   └── registry.py      # get_provider()
│   ├── models/
│   │   ├── __init__.py
│   │   ├── summary.py       # FinancialSummary
│   │   └── mf.py            # MFHolding, MFTransaction
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py          # DomainAgent ABC
│   │   └── mf.py            # MFAgent
│   ├── connectors/
│   │   ├── __init__.py
│   │   ├── base.py          # Connector ABC
│   │   ├── registry.py      # ConnectorRegistry
│   │   └── cams.py          # CAMSConnector (casparser)
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── router.py        # Intent classifier + routing
│   │   └── engine.py        # Orchestrator
│   ├── storage/
│   │   ├── __init__.py
│   │   └── sqlite.py        # Per-user SQLite store
│   └── api/
│       ├── __init__.py
│       ├── chat.py           # POST /chat
│       └── upload.py         # POST /upload
├── ui/
│   └── index.html            # Single-page chat + upload UI
├── tests/
│   └── ...
└── data/                     # .gitignored, user data
    └── users/
```

### Why This Structure
- `llm/` is isolated — swap providers without touching agents
- `models/` holds dataclasses only — no logic, no imports from other modules
- `agents/` depends on `models/` and `llm/` only
- `connectors/` depends on `models/` only
- `orchestrator/` depends on `agents/` and `llm/`
- `api/` is the thin HTTP layer over orchestrator

Dependency flow: `api → orchestrator → agents → {models, llm}` ← `connectors → models`

---

## 3. Build Order (This Weekend)

### Session 1: Foundation (~2 hrs)

**Step 1: Scaffolding**
- `pyproject.toml` with deps: `fastapi`, `uvicorn`, `casparser`, `mftool`, `python-multipart`
- Directory structure as above
- `config.toml.example`

**Step 2: LLM Provider Layer**
- `LLMProvider` ABC in `llm/base.py`
- `KiroCLIProvider` in `llm/kiro.py`
- `get_provider()` registry in `llm/registry.py`
- Smoke test: `await provider.complete("What is 2+2?")` returns "4"

**Step 3: Core Models**
- `FinancialSummary` dataclass in `models/summary.py`
- `MFHolding`, `MFTransaction` in `models/mf.py`
- `DomainAgent` ABC in `agents/base.py`
- `Connector` ABC in `connectors/base.py`

### Session 2: MF Pipeline (~3 hrs)

**Step 4: CAMS Connector**
- `CAMSConnector` wraps casparser
- Upload PDF → parse → list of `MFHolding` objects
- AMFI enrichment via mftool (live NAV, scheme metadata)

**Step 5: MF Agent — Analyze Mode**
- Expense ratio analysis (flag funds > 1%, suggest direct plan alternatives)
- Portfolio overlap detection (compare top holdings across funds)
- XIRR calculation per fund and portfolio-level
- Uses LLM for natural language response generation only — computation is deterministic

**Step 6: SQLite Storage**
- Per-user SQLite DB in `data/users/{user_id}.db`
- Store parsed MFHoldings
- Simple schema: `holdings` table with JSON blob per holding

### Session 3: Chat + Deploy (~2 hrs)

**Step 7: Intent Router**
- Single LLM call to classify: `{domain, mode, entities}`
- Deterministic dispatch to agent + mode
- Fallback: if classification fails, ask user to clarify

**Step 8: API + UI**
- `POST /upload` — accept PDF, run through connector registry, store results
- `POST /chat` — accept query, route through orchestrator, return response
- `GET /` — serve `ui/index.html` (Tailwind, single page, upload + chat)

**Step 9: Deploy**
- Dockerfile (Python 3.11 + deps)
- Railway/Render free tier
- Wire landing page CTA to live demo URL

---

## 4. What's NOT in the Prototype

Explicitly deferred to keep scope tight:

- ❌ Insurance/Loan agents (Phase 2)
- ❌ Cross-domain reasoning (Phase 2 — needs 2+ agents)
- ❌ Knowledge graph (Phase 2 — needs cross-domain)
- ❌ Streaming responses (nice-to-have, add after core works)
- ❌ User auth (prototype is single-user local)
- ❌ Multiple CLI providers (start with kiro only, add others when needed)
- ❌ API provider (add when we need hosted version)
- ❌ Broker API integrations (Phase 3)

---

## 5. Success Criteria for Prototype

By Apr 11 (end of Week 2), the prototype should:

1. ✅ Accept a CAMS/KFintech PDF upload
2. ✅ Parse it into structured MF holdings
3. ✅ Answer: "What are my expense ratios?" with fund-by-fund breakdown
4. ✅ Answer: "Do any of my funds overlap?" with holding comparison
5. ✅ Answer: "What's my portfolio XIRR?" with per-fund and aggregate returns
6. ✅ Suggest direct plan alternatives for regular plan funds
7. ✅ Work entirely via CLI LLM (zero API cost)
8. ✅ Be deployable to Railway/Render
9. ✅ Have a chat UI that a non-technical person can use

---

## 6. Open Questions

1. **kiro-cli `--no-interactive` flag** — Does it exist? Need to verify. Fallback: pipe prompt via stdin and read stdout.
2. **casparser password handling** — CAMS PDFs are password-protected (PAN-based). How to handle in upload flow? Options: ask user for password in UI, or try common patterns (PAN + DOB).
3. **AMFI rate limits** — mftool wraps amfiindia.com. No documented rate limits, but should we cache NAV data in SQLite with TTL?
4. **Deployment with CLI** — Railway/Render won't have kiro-cli. Hosted version needs API provider. Keep CLI for local dev, API for hosted.

---

*Created: April 4, 2026*
*Status: Draft — awaiting review*
