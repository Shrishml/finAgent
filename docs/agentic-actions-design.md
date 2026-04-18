# Agentic Actions Architecture — Design Document

**Branch:** `feat/agentic-actions`
**Status:** Design phase
**Date:** 2026-04-18

---

## Problem

FinBestie's intelligence drops to zero after onboarding. The onboarding agent collects data conversationally, but post-onboarding the system becomes a dumb router: user asks → classify intent → call domain agent or generic LLM → return text. The LLM can talk but cannot **act**.

Users expect: "I don't have term insurance" → agent finds options, shows comparison, helps them decide.
Current reality: "I don't have term insurance" → generic LLM advice text.

## Solution: Agent Actions

The LLM becomes a **controller** that can invoke **actions** — structured backend operations that produce both a chat response and a UI output. Actions are the bridge between conversation and interface.

```
User message
    ↓
Orchestrator (existing) → classifies intent
    ↓
Agent Loop (NEW) → LLM decides: respond with text OR call action(s)
    ↓
Action Executor (NEW) → runs backend logic, returns structured result
    ↓
Two outputs:
  - Chat: LLM explains the result conversationally
  - UI: Frontend renders structured data (table, chart, card)
```

---

## Current Architecture (what we have)

```
main.py (1064 lines) — ALL endpoints: auth, chat, holdings, goals, profile, insights, nav-history
├── POST /chat/stream → engine.handle_query_stream()
├── GET/POST/PUT/DELETE /goals/* → goal CRUD
├── GET/PUT /profile → profile CRUD
├── GET /holdings, /insights, /portfolio-history → portfolio data
├── POST /upload → CAS PDF upload
└── GET /suggestions → smart suggestions

orchestrator/
├── engine.py (200 lines) — handle_query() and handle_query_stream()
│   ├── Checks onboarding status → routes to onboarding agent
│   ├── Classifies intent via router
│   ├── Dispatches to domain agent (only MFAgent exists)
│   └── Falls back to _advisor_respond() for everything else
└── router.py (91 lines) — keyword-first intent classification, LLM fallback

agents/
├── onboarding.py — conversational 7-pillar onboarding + snapshot
└── mf.py — mutual fund analysis (deterministic compute + LLM presentation)

llm/
├── base.py — LLMProvider ABC (complete, complete_stream)
├── registry.py — auto-detect provider (kiro → gemini-api → gemini-cli)
└── kiro.py, gemini.py, gemini_api.py — provider implementations

Frontend: single app.html (1197 lines)
├── SSE reader handles [STATUS], [ONBOARDING_COMPLETE], [DONE] events
├── Tab system: Overview, Holdings, Goals, Profile
└── Chat sidebar with markdown rendering via marked.js
```

### Key Strengths to Preserve
- Deterministic keyword routing (fast, no LLM call for obvious intents)
- SSE streaming with control events (natural extension point for actions)
- LLM provider abstraction (tool-calling adds to this, doesn't replace it)
- Profile-aware context passing to LLM

### Key Limitations to Fix
- `main.py` is a monolith — split into route modules
- No tool/function-calling in LLM layer
- No way for LLM to trigger backend operations
- No mechanism for UI to render structured action results
- Post-onboarding LLM has no tools, only text generation

---

## Proposed Architecture

### New Directory Structure

```
src/finagent/
├── main.py                  ← slim: app setup, middleware, mount routers
├── routes/                  ← NEW: extracted from main.py
│   ├── auth.py              ← /auth/* endpoints
│   ├── chat.py              ← /chat, /chat/stream (+ action execution)
│   ├── holdings.py          ← /holdings, /upload, /clear, /insights
│   ├── goals.py             ← /goals/* CRUD
│   ├── profile.py           ← /profile GET/PUT, /suggestions
│   ├── pages.py             ← /, /app, /demo, /about, /help/cas, /changelog
│   └── dev.py               ← /dev/seed, /dev/reset
├── actions/                 ← NEW: plugin-based action system
│   ├── __init__.py          ← auto-discovery registry
│   ├── base.py              ← Action protocol/contract
│   ├── create_goal.py       ← Phase 1
│   ├── search_mutual_funds.py  ← Phase 2
│   ├── show_gap_analysis.py    ← Phase 2
│   ├── recommend_insurance.py  ← Phase 3
│   └── simulate_sip.py        ← Phase 3
├── orchestrator/
│   ├── engine.py            ← MODIFIED: adds agent loop with tool dispatch
│   └── router.py            ← MODIFIED: adds action-intent detection
├── agents/                  ← existing, unchanged
├── llm/
│   ├── base.py              ← MODIFIED: add complete_with_tools() method
│   └── tools.py             ← NEW: schema builder from action registry
└── (rest unchanged)
```

### Action Contract

Every action is a Python file with two exports:

```python
# actions/create_goal.py

SCHEMA = {
    "name": "create_goal",
    "description": "Create a financial goal with target amount and timeline",
    "parameters": {
        "goal_name": {"type": "str", "required": True, "description": "Name of the goal"},
        "target_amount": {"type": "int", "required": True, "description": "Target amount in INR"},
        "target_date": {"type": "str", "required": False, "description": "Target date YYYY-MM-DD"},
    },
    "ui_component": "goal_card",
}

async def execute(params: dict, user_id: int, context: dict) -> dict:
    """
    Returns:
        message: str — text for chat (LLM may rephrase)
        ui_data: dict — structured data for frontend rendering
        ui_component: str — which frontend component to use
    """
```

### Auto-Discovery Registry

```python
# actions/__init__.py
import importlib, pkgutil

ACTION_REGISTRY: dict[str, dict] = {}

for _, name, _ in pkgutil.iter_modules(__path__):
    mod = importlib.import_module(f".{name}", __package__)
    if hasattr(mod, "SCHEMA") and hasattr(mod, "execute"):
        ACTION_REGISTRY[mod.SCHEMA["name"]] = {
            "schema": mod.SCHEMA,
            "execute": mod.execute,
        }
```

### LLM Tool Integration

The LLM receives available actions as tool descriptions in its system prompt:

```
You have these tools available. Call them when the user's request requires action, not just advice.

- create_goal(goal_name, target_amount, target_date): Create a financial goal
- search_mutual_funds(category, risk_level, min_returns): Find mutual funds matching criteria
...

To call a tool, respond with:
[ACTION: tool_name(param1=value1, param2=value2)]

You can call multiple tools. After each tool result, you'll see the output and can decide next steps.
```

### SSE Action Events (Frontend)

The chat stream already handles control events. Actions add:

```
data: [ACTION:goal_card] {"goal_name": "Vacation", "target": 1000000, ...}
data: [ACTION:comparison_table] {"items": [...], "columns": [...]}
data: [ACTION:projection_chart] {"labels": [...], "datasets": [...]}
```

Frontend SSE reader parses `[ACTION:component_name]` → renders the matching UI component below the chat message.

---

## Implementation Phases

### Phase 1: Foundation (action registry + main.py split + one action)
**Goal:** Prove the pattern works end-to-end

1. Split `main.py` into `routes/` modules (pure refactor, no behavior change)
2. Create `actions/` with auto-discovery registry and base contract
3. Implement `create_goal` action
4. Add tool prompt injection in `engine.py` — LLM sees available tools
5. Parse `[ACTION:...]` in LLM response → execute action → stream result
6. Frontend: parse `[ACTION:goal_card]` SSE event → render goal card below chat message

**Test:** "I want to save ₹10L for a vacation in 2 years" → LLM calls create_goal → goal appears in Goals tab + confirmation in chat

**Estimated effort:** 1-2 days

### Phase 2: Dual-Channel Output (2-3 more actions + UI components)
**Goal:** Both chat and UI work as output channels

1. Add `search_mutual_funds` action (queries AMFI data, filters by criteria)
2. Add `show_gap_analysis` action (compares current vs ideal allocation)
3. Build frontend components: `comparison_table`, `gap_visual`
4. Action results feed back into LLM context for follow-up references
5. LLM can reference displayed data: "As shown in the table above..."

**Test:** "What mutual funds should I invest in?" → MF table appears + chat explains reasoning

**Estimated effort:** 2-3 days

### Phase 3: Action Chaining (agent loop)
**Goal:** Agent can think multi-step

1. Enable agent loop: LLM calls action → sees result → decides next action
2. Add `simulate_sip` and `recommend_insurance` actions
3. Max 3-4 chained actions per query (prevent runaway)
4. Each action result appended to LLM context for next decision

**Test:** "Am I financially healthy?" → agent checks profile → finds gaps → calls multiple actions → synthesizes

**Estimated effort:** 2-3 days

### Phase 4: UI → Agent Feedback (bidirectional)
**Goal:** User can interact with action results

1. UI action components get clickable elements ("Select this", "Tell me more")
2. Clicks send structured messages back to chat: `__action_select__:recommend_insurance:option_2`
3. Agent receives selection, continues workflow
4. Add `create_action_item` and `explain_product` actions

**Test:** Agent shows 3 insurance options → user clicks one → agent explains in detail

**Estimated effort:** 2-3 days

### Phase 5: Persistent Agent Memory
**Goal:** Agent remembers across sessions

1. Track recommendations made, user selections, pending items
2. On session start: "Last time we discussed term insurance — did you follow up?"
3. Action history becomes part of user profile context

**Test:** Complete session with recommendations → return next day → agent picks up where left off

**Estimated effort:** 2-3 days

---

## main.py Split Plan

Current `main.py` (1064 lines) → split into:

| New File | Endpoints | Lines (approx) |
|---|---|---|
| `routes/auth.py` | `/auth/google`, `/auth/logout`, `/auth/me` | ~50 |
| `routes/pages.py` | `/`, `/app`, `/demo` (page), `/about`, `/help/cas`, `/changelog` | ~40 |
| `routes/chat.py` | `/chat`, `/chat/stream`, `/chat/history` | ~80 + action execution |
| `routes/holdings.py` | `/holdings`, `/upload`, `/clear`, `/insights`, `/compare`, `/nav-history`, `/benchmarks`, `/portfolio-history` | ~350 |
| `routes/goals.py` | `/goals/*` CRUD + templates + allocations | ~180 |
| `routes/profile.py` | `/profile` GET/PUT, `/suggestions` | ~120 |
| `routes/dev.py` | `/dev/seed`, `/dev/reset` | ~50 |
| `main.py` | App setup, middleware, static files, mount routers | ~80 |

Each route file uses `APIRouter` prefix. Zero behavior change — pure extraction.

---

## UI Component Library (reusable across actions)

| Component | Used By | Renders |
|---|---|---|
| `goal_card` | create_goal | Goal summary card with progress bar |
| `comparison_table` | search_mutual_funds, recommend_insurance | Sortable table with highlight |
| `gap_visual` | show_gap_analysis | Current vs ideal bar chart |
| `projection_chart` | simulate_sip | Line chart with scenarios |
| `action_items` | create_action_item | Checklist with priority |
| `detail_panel` | explain_product | Expandable product breakdown |

Most actions reuse 2-3 components. Adding 20 actions ≈ 5-6 UI components.

---

## Open Questions

1. **LLM tool-calling format**: Use structured JSON (`{"action": "...", "params": {...}}`) or text markers (`[ACTION: ...]`)? JSON is cleaner but needs reliable JSON extraction from LLM output. Text markers are more robust with streaming.

2. **Action execution: sync or async?** Some actions are instant (create_goal = DB write), others slow (search_mutual_funds = API calls). Streaming handles this naturally — show [STATUS] while executing.

3. **Error handling**: What if action fails mid-chain? Options: (a) LLM sees error and adapts, (b) abort and tell user, (c) skip and continue with remaining actions.

4. **Rate limiting**: Should there be a max actions-per-query limit? Proposed: 4 actions max per user message.


---

## Consent-Driven Action Flow

The agent is an **advisor, not a broker**. It never auto-executes financial decisions. Every action that affects the user's finances follows: **recommend → explain → wait for consent → act**.

```
Agent detects gap (e.g., no term insurance)
    ↓
EXPLAIN: Why this matters, personalized to user's profile
    ↓
WAIT: "Want me to find options?" — user must say yes
    ↓
SEARCH: Only now does the agent call the action
    ↓
PRESENT: Show options in UI (comparison cards)
    ↓
WAIT: "Would you like to go with one of these?"
    ↓
GUIDE: Provide application link + checklist (no auto-purchase)
    ↓
CONFIRM: "Let me know once you've done it" → user confirms → update profile
```

### Example: Term Insurance for Rahul (30M, married, 1 kid, no term cover)

```
🤖 "Looking at your profile — you're 30, married with a kid, and have no term
    insurance. If something happens to you, your family would need to cover
    ₹60K/mo expenses + ₹2L loan with no income backup.
    A term plan of ~₹1Cr would cost roughly ₹800-1000/mo at your age.
    Want me to find specific options?"

👤 "Yes, show me options"

→ [ACTION: SEARCH_TERM_INSURANCE] — searches MaxLife plans
→ [STATUS: 🔍 Searching plans for 30M, non-smoker, ₹1Cr cover...]
→ UI renders comparison cards (3-4 plans)

🤖 "Here are 3 MaxLife plans. I'd recommend Plan B because [reason]."

👤 "Plan B looks good"

🤖 "I can't purchase this for you, but here's what to do:
    → [Link to MaxLife Plan B application]
    → You'll need: PAN, Aadhaar, bank details
    Once purchased, let me know and I'll update your profile."

👤 "Done"

→ [ACTION: UPDATE_INSURANCE] → health score: 62 → 71
🤖 "Health score updated! Term insurance gap: closed ✅"
```

---

## MaxLife Integration (Phase 1 — Static Data)

Start with curated plan data, not live API. Enough to prove the flow.

```
data/
  insurance/
    maxlife_term_plans.json
```

```json
[
  {
    "plan_id": "maxlife_smart_secure_plus",
    "name": "Max Life Smart Secure Plus",
    "type": "term",
    "cover_options": [5000000, 10000000, 20000000, 50000000],
    "premium_by_age": {
      "25-30": {"1cr": 850, "2cr": 1600},
      "31-35": {"1cr": 1050, "2cr": 1950}
    },
    "features": ["Return of premium option", "Critical illness rider", "Accidental death benefit"],
    "claim_settlement_ratio": 99.51,
    "application_url": "https://www.maxlifeinsurance.com/term-insurance-plans/smart-secure-plus",
    "min_entry_age": 18,
    "max_entry_age": 65
  }
]
```

The action filters plans by user's age, cover need (10x annual income), and budget:

```python
# actions/search_term_insurance.py
SCHEMA = {
    "name": "SEARCH_TERM_INSURANCE",
    "description": "Find term insurance plans matching user's profile",
    "parameters": {
        "cover_amount": {"type": "int", "description": "Desired cover in INR"},
        "budget_monthly": {"type": "int", "required": False, "description": "Max monthly premium"},
    },
    "ui_component": "comparison_table",
    "status_message": "Searching term insurance plans for your profile"
}
```

Later phases: live API integration, multiple providers (HDFC Life, ICICI Pru, LIC).

---

## SSE Status Events (Keeping Users Updated)

Long-running actions (3-10s) need visible progress. Reuse existing SSE stream with a new event type.

### Event Types

```
Existing:
  data: [TOKEN] partial text          ← chat streaming
  data: [STATUS] thinking...          ← existing status
  data: [DONE]                        ← stream end

New:
  data: [ACTION_STATUS] 🔍 Searching MaxLife plans...     ← action progress
  data: [ACTION_STATUS] 📊 Comparing 4 plans...           ← multi-step progress
  data: [ACTION_STATUS] ✅ Found 3 matching plans          ← completion
  data: [ACTION:comparison_table] {"items": [...]}         ← result render
```

### Backend (minimal addition to action executor)

```python
async def execute_with_status(action, params, send_event):
    await send_event(f"[ACTION_STATUS] {action.schema['status_message']}...")
    result = await action.execute(params)
    await send_event(f"[ACTION_STATUS] ✅ Done")
    await send_event(f"[ACTION:{action.schema['ui_component']}] {json.dumps(result)}")
```

### Frontend (render as animated indicator above chat)

```
┌─────────────────────────────────────┐
│  🔍 Searching MaxLife plans...      │  ← fading status bar
│                                     │
│  🤖 Here are 3 plans that fit...   │  ← chat text
│                                     │
│  ┌──────┐ ┌──────┐ ┌──────┐       │  ← action result cards
│  │Plan A│ │Plan B│ │Plan C│       │
│  └──────┘ └──────┘ └──────┘       │
└─────────────────────────────────────┘
```

~10 lines of frontend JS to handle `[ACTION_STATUS]` events as a temporary indicator.

---

## Universal Module Pattern

Every financial domain (MFs, loans, insurance, EPF, stocks, salary) follows the same 3-layer architecture. Build the framework once, add modules by dropping folders.

### The Pattern

```
┌──────────────────────────────────────────────┐
│  Layer 1: Agent Actions (thin wrappers)      │
│  ANALYSE_X / SUGGEST_X / COMPARE_X           │
├──────────────────────────────────────────────┤
│  Layer 2: Domain Analyser (heavy lifting)    │
│  Parse docs, calculate metrics, score health │
├──────────────────────────────────────────────┤
│  Layer 3: Document Upload (data entry point) │
│  CAS / loan statement / policy PDF / payslip │
└──────────────────────────────────────────────┘
```

Every module:
1. Has a **document** that unlocks deep analysis
2. Has an **analyser** that extracts and crunches the data
3. Has **agent actions** that orchestrate and explain
4. Works in **degraded mode** without the document (estimates from onboarding)
5. Agent knows **when to ask** for the document and **why it matters**

### Module Directory Structure

```
modules/
  mutual_funds/
    analyser.py      ← parse CAS, XIRR, overlap, sector exposure
    actions.py       ← ANALYSE_PORTFOLIO, SUGGEST_REBALANCE, COMPARE_FUNDS
    prompts.py       ← when to ask for CAS, how to explain with/without
  loans/
    analyser.py      ← parse loan statement, prepay calc, refinance
    actions.py       ← ANALYSE_LOANS, SUGGEST_REFINANCE, PREPAY_CALCULATOR
    prompts.py       ← when to ask for loan statement
  insurance/
    analyser.py      ← parse policy PDF, coverage adequacy
    actions.py       ← CHECK_COVERAGE, SEARCH_TERM_INSURANCE, COMPARE_PLANS
    prompts.py       ← when to ask for policy document
  epf/
    analyser.py      ← parse EPF passbook, corpus projection
    actions.py       ← ANALYSE_EPF, PROJECT_RETIREMENT
    prompts.py
  stocks/
    analyser.py      ← parse demat holding, P&L, tax harvesting
    actions.py       ← ANALYSE_STOCKS, TAX_HARVEST_SUGGESTIONS
    prompts.py
  salary/
    analyser.py      ← parse payslip, tax optimization
    actions.py       ← OPTIMISE_TAX, ANALYSE_SALARY_STRUCTURE
    prompts.py
```

### Capability Matrix: With vs Without Document

| Module | Document | Without Doc | With Doc |
|--------|----------|-------------|----------|
| Mutual Funds | CAS statement | Rough estimate from onboarding | Fund-wise XIRR, overlap, sector, rebalance |
| Loans | Loan statement / amortization PDF | "₹2L personal loan" | Exact rate, tenure, prepay savings |
| Insurance | Policy PDF | "₹5L health cover" | Exact terms, exclusions, coverage gaps |
| EPF | EPF passbook | "I have EPF" | Exact balance, employer match, retirement projection |
| Stocks | Demat holding / broker CSV | "₹3L in stocks" | Stock-wise P&L, LTCG/STCG tax liability |
| Salary | Payslip | "₹1.5L/mo salary" | Component breakdown, HRA/80C/NPS tax gaps |

### Shared Infrastructure (built once)

- **Document upload pipeline**: PDF parsing, OCR (if needed), extraction, storage — reusable across modules. Only per-document-type parsing logic is unique.
- **Action registry**: Auto-discovers actions from all module folders.
- **SSE status events**: Same progress indicator for any long-running action.
- **UI component library**: comparison_table, gap_visual, projection_chart — reused across modules.
- **Degraded mode framework**: Every action checks if document exists, returns estimate-based or full analysis accordingly.

---

## CAS Upload Triggers (When to Ask for Documents)

The agent doesn't dump "upload your CAS" during onboarding. It asks at **natural moments** when the value is obvious.

### Trigger 1: Onboarding Wrapup (Soft Ask)

After financial snapshot, when MF gap is visible:

```
🤖 "You mentioned ₹8L in mutual funds. I can give you much deeper insights
    if you upload your CAS statement:

    ✅ Exact fund-wise returns (XIRR, not just NAV change)
    ✅ Hidden overlap between your funds
    ✅ Sector concentration risk
    ✅ Whether your SIPs are actually on track

    Without CAS, I can only work with the ₹8L estimate.

    [Upload CAS]  [Maybe Later]"
```

### Trigger 2: User Asks About the Domain (Hard Ask)

```
👤 "How are my mutual funds performing?"

🤖 "I don't have your actual fund data yet — just the ₹8L estimate.
    To tell you real performance, I need your CAS.

    📄 Download it from MFCentral app (instant) or CAMS/KFintech website.
    Takes 2 minutes. Want me to walk you through it?"
```

### Trigger 3: Agent Spots an Unanalysable Gap

```
🤖 "I notice you have ₹8L in MFs but I can't check for overlap or
    sector over-exposure without your actual holdings. Upload your CAS
    and I'll run a full portfolio health check."
```

### Universal Trigger Pattern (applies to all modules)

Every module defines its triggers in `prompts.py`:

```python
# modules/mutual_funds/prompts.py
TRIGGERS = {
    "soft_ask": {
        "when": "onboarding_complete AND has_mf_estimate AND NOT has_cas",
        "message": "Upload CAS for deeper MF insights",
        "value_props": ["Fund-wise XIRR", "Overlap detection", "Sector exposure", "SIP tracking"],
    },
    "hard_ask": {
        "when": "user_asks_about_mf AND NOT has_cas",
        "message": "I need your CAS to answer that accurately",
    },
    "gap_ask": {
        "when": "gap_analysis_blocked_by_missing_data",
        "message": "Can't analyse this without actual holdings",
    },
}
```

The agent framework checks triggers after every interaction and surfaces the right ask at the right moment.

---

## Updated Phase Plan

| Phase | What | Effort |
|-------|------|--------|
| Phase 1 | Action registry + CREATE_GOAL + main.py split | 1-2 days |
| Phase 2 | SSE status events + SEARCH_TERM_INSURANCE (MaxLife static data) + comparison cards + consent flow | 2-3 days |
| Phase 3 | Action chaining + UPDATE_INSURANCE + MF analyser integration (thin wrapper over existing) | 2-3 days |
| Phase 4 | Universal module framework + CAS upload triggers + ANALYSE_PORTFOLIO action | 2-3 days |
| Phase 5 | Agent memory + proactive nudges + additional modules (loans, EPF) | 2-3 days |