# Agentic Actions Architecture — Design Document

**Branch:** `feat/agentic-actions`
**Status:** Design phase
**Date:** 2026-04-18

---

## Problem

FinBestie's intelligence drops to zero after onboarding. The onboarding agent collects data conversationally, but post-onboarding the system becomes a dumb router: user asks → classify intent → call domain agent or generic LLM → return text. The LLM can talk but cannot **act**.

Users expect: "I don't have term insurance" → agent explains why it matters → user asks for options → agent finds them → shows comparison in UI → guides purchase.

Current reality: "I don't have term insurance" → generic LLM advice text.

---

## Core Principle: Advisor, Not Broker

The agent **recommends, explains, and waits for consent** before acting. It never auto-executes financial decisions.

```
Agent detects gap → EXPLAIN why it matters → WAIT for user consent
    → SEARCH options → PRESENT in UI → WAIT for selection
    → GUIDE to purchase (external link) → CONFIRM user completed it → UPDATE profile
```

---

## Solution: Agent Actions

The LLM becomes a **controller** that invokes **actions** — structured backend operations producing both a chat response and a UI output. Actions bridge conversation and interface.

```
User message
    ↓
Orchestrator → classifies intent
    ↓
Agent Loop → LLM decides: respond with text OR call action(s)
    ↓
Action Executor → runs backend logic, streams status, returns structured result
    ↓
Two outputs:
  - Chat: LLM explains the result conversationally
  - UI: Frontend renders structured data (table, chart, card)
```

---

## Universal Module Pattern

Every financial domain follows the same 3-layer architecture. Build the framework once, add modules by dropping folders.

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

### Capability Matrix: With vs Without Document

| Module | Document | Without Doc | With Doc |
|--------|----------|-------------|----------|
| Mutual Funds | CAS statement | Rough estimate from onboarding | Fund-wise XIRR, overlap, sector, rebalance |
| Loans | Loan statement / amortization PDF | "₹2L personal loan" | Exact rate, tenure, prepay savings |
| Insurance | Policy PDF | "₹5L health cover" | Exact terms, exclusions, coverage gaps |
| EPF | EPF passbook | "I have EPF" | Exact balance, employer match, retirement projection |
| Stocks | Demat holding / broker CSV | "₹3L in stocks" | Stock-wise P&L, LTCG/STCG tax liability |
| Salary | Payslip | "₹1.5L/mo salary" | Component breakdown, HRA/80C/NPS tax gaps |

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
    prompts.py
  insurance/
    analyser.py      ← parse policy PDF, coverage adequacy
    actions.py       ← CHECK_COVERAGE, SEARCH_TERM_INSURANCE, COMPARE_PLANS
    prompts.py
  salary/
    analyser.py      ← parse payslip, tax optimization
    actions.py       ← OPTIMISE_TAX, ANALYSE_SALARY_STRUCTURE
    prompts.py
  epf/
    analyser.py      ← parse EPF passbook, corpus projection
    actions.py       ← ANALYSE_EPF, PROJECT_RETIREMENT
    prompts.py
  stocks/
    analyser.py      ← parse demat holding, P&L, tax harvesting
    actions.py       ← ANALYSE_STOCKS, TAX_HARVEST_SUGGESTIONS
    prompts.py
```

### Document Upload Triggers

The agent doesn't dump "upload your CAS" during onboarding. It asks at **natural moments** when the value is obvious.

| Trigger | When | Example |
|---------|------|---------|
| Soft ask | Onboarding complete, module data estimated | "Upload CAS for fund-wise XIRR, overlap detection, sector exposure" |
| Hard ask | User asks about the domain, doc missing | "I need your CAS to answer that accurately" |
| Gap ask | Analysis blocked by missing data | "Can't check for overlap without actual holdings" |

Every module defines triggers in `prompts.py`:

```python
TRIGGERS = {
    "soft_ask": {
        "when": "onboarding_complete AND has_mf_estimate AND NOT has_cas",
        "value_props": ["Fund-wise XIRR", "Overlap detection", "Sector exposure"],
    },
    "hard_ask": {"when": "user_asks_about_mf AND NOT has_cas"},
    "gap_ask": {"when": "gap_analysis_blocked_by_missing_data"},
}
```

### Existing Analysers as Services

The MF analyser already exists. Don't rebuild — wrap it:

```python
# modules/mutual_funds/actions.py → ANALYSE_PORTFOLIO
async def execute(params, user_id, context):
    holdings = await get_holdings(user_id)       # existing API
    xirr = await calculate_xirr(holdings)        # existing analyser
    overlap = await check_overlap(holdings)      # existing analyser
    return {"xirr": xirr, "overlap": overlap}    # thin wrapper
```

Same pattern applies to every future module — the action is a thin wrapper over domain-specific compute.

---

## Current Architecture

```
main.py (1064 lines) — ALL endpoints
├── POST /chat/stream → engine.handle_query_stream()
├── GET/POST/PUT/DELETE /goals/* → goal CRUD
├── GET/PUT /profile → profile CRUD
├── GET /holdings, /insights, /portfolio-history → portfolio data
├── POST /upload → CAS PDF upload
└── GET /suggestions → smart suggestions

orchestrator/
├── engine.py — handle_query() and handle_query_stream()
│   ├── Checks onboarding → routes to onboarding agent
│   ├── Classifies intent via router
│   ├── Dispatches to domain agent (only MFAgent exists)
│   └── Falls back to _advisor_respond() for everything else
└── router.py — keyword-first intent classification, LLM fallback

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
└── Chat sidebar with markdown rendering
```

### Strengths to Preserve
- Deterministic keyword routing (fast, no LLM call for obvious intents)
- SSE streaming with control events (natural extension point)
- LLM provider abstraction
- Profile-aware context passing

### Limitations to Fix
- `main.py` is a monolith — needs route extraction
- No tool/function-calling in LLM layer
- No way for LLM to trigger backend operations
- No mechanism for UI to render structured action results

---

## Proposed Architecture

### Directory Structure

```
src/finagent/
├── main.py                     ← slim: app setup, middleware, mount routers
├── routes/                     ← extracted from main.py
│   ├── auth.py                 ← /auth/*
│   ├── chat.py                 ← /chat/* (+ action execution)
│   ├── holdings.py             ← /holdings, /upload, /insights
│   ├── goals.py                ← /goals/* CRUD
│   ├── profile.py              ← /profile, /suggestions
│   ├── pages.py                ← /, /app, /demo, /about
│   └── dev.py                  ← /dev/seed, /dev/reset
├── actions/                    ← plugin-based action system
│   ├── __init__.py             ← auto-discovery registry
│   ├── base.py                 ← action protocol/contract
│   └── (one file per action)
├── modules/                    ← domain modules (universal pattern)
│   └── (one folder per domain)
├── orchestrator/               ← modified: adds agent loop with tool dispatch
├── agents/                     ← existing, unchanged initially
└── llm/                        ← modified: adds tool-calling support
```

### Action Contract

Every action is a Python file with two exports:

```python
# actions/create_goal.py
SCHEMA = {
    "name": "create_goal",
    "description": "Create a financial goal with target amount and timeline",
    "parameters": {
        "goal_name": {"type": "str", "required": True},
        "target_amount": {"type": "int", "required": True},
        "target_date": {"type": "str", "required": False},
    },
    "ui_component": "goal_card",
    "status_message": "Creating your goal",
}

async def execute(params: dict, user_id: int, context: dict) -> dict:
    # Returns: {message, ui_data, ui_component}
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
            "schema": mod.SCHEMA, "execute": mod.execute,
        }
```

New action = new file. No config, no manual registration.

### LLM Tool Integration

Available actions injected into system prompt dynamically:

```
You have these tools. Call them when the user needs action, not just advice.
To call: [ACTION: tool_name(param1=value1, param2=value2)]

- create_goal(goal_name, target_amount, target_date): Create a financial goal
- search_term_insurance(cover_amount, budget_monthly): Find term insurance plans
...
```

### SSE Events (Streaming Status + Action Results)

Reuse existing SSE stream with new event types:

```
Existing:
  data: [TOKEN] partial text
  data: [STATUS] thinking...
  data: [DONE]

New:
  data: [ACTION_STATUS] 🔍 Searching MaxLife plans...
  data: [ACTION_STATUS] ✅ Found 3 matching plans
  data: [ACTION:comparison_table] {"items": [...]}
```

Frontend renders `[ACTION_STATUS]` as an animated indicator above chat, `[ACTION:component]` as structured UI below the message.

```
┌─────────────────────────────────────┐
│  🔍 Searching MaxLife plans...      │  ← animated status bar
│                                     │
│  🤖 Here are 3 plans that fit...   │  ← chat text
│                                     │
│  ┌──────┐ ┌──────┐ ┌──────┐       │  ← action result cards
│  │Plan A│ │Plan B│ │Plan C│       │
│  └──────┘ └──────┘ └──────┘       │
└─────────────────────────────────────┘
```

### UI Component Library

| Component | Used By | Renders |
|-----------|---------|---------|
| `goal_card` | create_goal | Goal summary with progress bar |
| `comparison_table` | search_mutual_funds, recommend_insurance | Sortable table |
| `gap_visual` | show_gap_analysis | Current vs ideal bar chart |
| `projection_chart` | simulate_sip | Line chart with scenarios |
| `action_items` | create_action_item | Checklist with priority |
| `detail_panel` | explain_product | Expandable product breakdown |

Most actions reuse 2-3 components. 20+ actions ≈ 6 UI components.

---

## Example Flow: Term Insurance (MaxLife)

### Data Source (Phase 1 — Static)

```json
// data/insurance/maxlife_term_plans.json
[{
    "plan_id": "maxlife_smart_secure_plus",
    "name": "Max Life Smart Secure Plus",
    "type": "term",
    "premium_by_age": {"25-30": {"1cr": 850}, "31-35": {"1cr": 1050}},
    "claim_settlement_ratio": 99.51,
    "application_url": "https://www.maxlifeinsurance.com/..."
}]
```

### User Journey

```
🤖 "You're 30, married with a kid, no term insurance. If something happens,
    your family needs ₹60K/mo + ₹2L loan with no income backup.
    ~₹1Cr cover would cost ₹800-1000/mo at your age.
    Want me to find options?"

👤 "Yes"

→ [ACTION_STATUS] 🔍 Searching plans for 30M, non-smoker, ₹1Cr cover...
→ [ACTION:comparison_table] {3 MaxLife plans with premiums, features, CSR}

🤖 "I'd recommend Plan B because [reason]. I can't purchase for you, but:
    → [Link to MaxLife application]
    → You'll need: PAN, Aadhaar, bank details
    Let me know once done."

👤 "Done"

→ [ACTION: UPDATE_INSURANCE] → health score: 62 → 71
🤖 "Profile updated! Term insurance gap: closed ✅"
```

Later phases: live API, multiple providers (HDFC Life, ICICI Pru, LIC).

---

## main.py Split Plan

| New File | Endpoints | Lines (approx) |
|----------|-----------|-----------------|
| `routes/auth.py` | `/auth/google`, `/auth/logout`, `/auth/me` | ~50 |
| `routes/pages.py` | `/`, `/app`, `/demo`, `/about`, `/help/cas`, `/changelog` | ~40 |
| `routes/chat.py` | `/chat`, `/chat/stream`, `/chat/history` | ~80 |
| `routes/holdings.py` | `/holdings`, `/upload`, `/clear`, `/insights`, `/nav-history` | ~350 |
| `routes/goals.py` | `/goals/*` CRUD + templates + allocations | ~180 |
| `routes/profile.py` | `/profile` GET/PUT, `/suggestions` | ~120 |
| `routes/dev.py` | `/dev/seed`, `/dev/reset` | ~50 |
| `main.py` | App setup, middleware, static files, mount routers | ~80 |

Pure extraction using `APIRouter`. Zero behavior change.

---

## Implementation Phases

| Phase | What | Effort |
|-------|------|--------|
| 1 | Action registry + `main.py` split + `CREATE_GOAL` action end-to-end | 1-2 days |
| 2 | SSE status events + `SEARCH_TERM_INSURANCE` (MaxLife static) + comparison cards + consent flow | 2-3 days |
| 3 | Action chaining (multi-step agent loop, max 4 per query) + MF analyser integration as thin wrapper | 2-3 days |
| 4 | UI → Agent feedback (clickable action results send structured messages back) + `UPDATE_INSURANCE` | 2-3 days |
| 5 | Agent memory across sessions + proactive nudges + additional modules (loans, EPF) | 2-3 days |

### Phase 1 Test
"I want to save ₹10L for a vacation in 2 years" → LLM calls `create_goal` → goal appears in Goals tab + confirmation in chat.

### Phase 2 Test
"I don't have term insurance" → agent explains impact → user says "show options" → MaxLife comparison cards appear + chat explains recommendation.

### Phase 3 Test
"Am I financially healthy?" → agent checks profile → finds gaps → chains multiple actions → synthesizes.

### Phase 4 Test
Agent shows 3 insurance options → user clicks one → agent explains in detail → guides to purchase.

### Phase 5 Test
Complete session → return next day → agent: "Last time we discussed term insurance — did you follow up?"

---

## Frontend Changes

The frontend is a single `app.html` (1197 lines). Changes are minimal — no new dependencies, no framework, all within existing file.

### Current SSE Parser (lines 660-678)

```javascript
// Everything that isn't a control event → concatenate into markdown blob
for (const line of text.split('\n')) {
    const d = line.slice(6);
    if (d === '[DONE]') break;
    if (d === '[ONBOARDING_COMPLETE]') { switchTab('goals'); continue; }
    if (d.startsWith('[STATUS] ')) { /* show thinking dots */ continue; }
    full += d; msgEl.innerHTML = marked.parse(full);  // ← everything = markdown
}
```

Problem: no concept of "this is chat text" vs "this is structured UI data."

### New SSE Parser

Add two new event types. Action events render as DOM elements below chat text, not inside the markdown blob.

```javascript
if (d.startsWith('[ACTION_STATUS] ')) {
    refs.status.innerHTML = `<span class="thinking-dots">${esc(d.slice(16))}
        <span>.</span><span>.</span><span>.</span></span>`;
    refs.status.classList.remove('hidden');
    continue;
}

if (d.startsWith('[ACTION:')) {
    const match = d.match(/^\[ACTION:(\w+)\]\s*(.+)$/);
    if (match) {
        refs.status.classList.add('hidden');
        renderActionComponent(match[1], JSON.parse(match[2]), refs);
    }
    continue;
}

// Default: chat text (unchanged)
full += d; refs.chat.innerHTML = marked.parse(full);
```

### Message DOM Structure

Each message becomes three zones instead of one:

```
<div class="msg agent">
  <div class="action-status hidden">   ← ACTION_STATUS (animated, hidden when done)
  <div class="chat-text">              ← markdown text (same as before)
  <div class="action-results">         ← action result cards (new)
</div>
```

`addMsg()` returns refs to all three zones so the SSE parser can target them independently.

### Action Component Renderer

One dispatcher, one renderer per component type:

```javascript
function renderActionComponent(type, data, refs) {
    const el = document.createElement('div');
    el.className = 'action-card mt-3 rounded-lg border border-gray-700 p-3';
    switch(type) {
        case 'comparison_table': renderComparisonTable(el, data); break;
        case 'goal_card':        renderGoalCard(el, data); break;
        case 'gap_visual':       renderGapVisual(el, data); break;
        case 'projection_chart': renderProjectionChart(el, data); break;
        default: el.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
    }
    refs.actions.appendChild(el);
}
```

Each renderer is 10-15 lines of HTML templating. Fallback renders raw JSON so new actions work before their UI component exists.

### Phase 4: Clickable Actions → Back to Chat

Action cards with buttons (e.g., "Select this plan") send structured messages back:

```javascript
function sendActionSelect(action, value) {
    $('chat-input').value = `__action_select__:${action}:${value}`;
    $('chat-form').dispatchEvent(new Event('submit'));
}
```

Backend sees `__action_select__:recommend_insurance:plan_b` → routes to agent with context.

### Change Summary

| What | Lines | Phase |
|------|-------|-------|
| SSE parser: `[ACTION_STATUS]` and `[ACTION:*]` handling | ~20 | 1 |
| `addMsg()` structured refs (status, chat, actions) | ~15 | 1 |
| `renderActionComponent` dispatcher | ~10 | 1 |
| `renderGoalCard` | ~15 | 1 |
| `renderComparisonTable` | ~15 | 2 |
| `renderGapVisual` | ~15 | 2 |
| `renderProjectionChart` (uses existing Chart.js) | ~20 | 3 |
| Clickable action buttons → chat feedback | ~10 | 4 |
| CSS for action cards | ~20 | 1 |
| **Total** | **~140** | |

Tabs (Overview, Holdings, Goals, Profile) stay untouched. Action results live inside chat messages. Tabs = dashboard view, chat = interactive advisor view.

---

## Mobile Rendering

On mobile, chat is fullscreen — action results render inline within the chat flow. No tab switching needed.

Cards stack vertically instead of side-by-side (CSS only):

```css
.action-results { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.action-card { min-width: 280px; flex: 1; }
@media (max-width: 640px) {
    .action-card { min-width: 100%; }
}
```

Comparison tables render as stacked cards on small screens instead of horizontal tables (~10 lines in `renderComparisonTable` checking screen width).

Tab-affecting actions (e.g., `CREATE_GOAL`) show inline confirmation in chat + a "View in Goals tab →" link. Tab updates silently in background.

---

## Design Decisions

1. **Tool-calling format**: Text markers (`[ACTION: ...]`). More robust with streaming. Migrate to structured JSON later if needed.
2. **Async actions**: Streaming + `[ACTION_STATUS]` handles both instant and slow actions naturally.
3. **Error handling**: LLM sees the error and decides whether to retry, skip, or abort. No hard abort.
4. **Rate limiting**: Configurable `MAX_ACTIONS_PER_QUERY` (default unlimited during development, enforce before launch).

---

## Agent-Driven Flow (Replaces Onboarding State Machine)

**Decision date:** 2026-04-18
**Status:** Approved, not yet implemented

### Problem with Current Approach

The current onboarding uses a hardcoded state machine:
```
keyword match ("onboarding") → rigid pillar sequence → wrapup → snapshot → done
```

This is fragile — if the LLM phrases something slightly differently, routing breaks. The wrapup phase exists only to collect age + risk appetite, and the `onboarding_complete` flag creates an artificial boundary between "collecting data" and "being useful."

### New Model: No Onboarding, Just an Agent

There is no onboarding. There is no "finish" concept. The agent continuously collects data and adjusts its behavior based on what it knows.

```
UI Cards (structured data + risk appetite) → Agent starts immediately
         ↓                                          ↓
    User keeps chatting              Agent keeps learning
         ↓                                          ↓
    New data arrives                 Snapshot updates
         ↓                                          ↓
    Agent re-adjusts                 Next conversation is smarter
```

### What Dies

| Component | Why |
|-----------|-----|
| `_onboarding_init` | No separate onboarding mode |
| `_handle_onboarding` | Agent handles everything |
| `_handle_wrapup` | Risk appetite moves to UI card, age to DOB field |
| Pillar tracking state machine | No pillars, no sequence |
| `onboarding_complete` flag | Replaced by: "are required fields populated?" |
| Keyword routing for onboarding | Agent reasons from context |
| `[ONBOARDING_COMPLETE]` SSE event | No completion boundary |

### What Stays

| Component | Notes |
|-----------|-------|
| UI cards for structured input | Add risk appetite selector |
| Goal creation via chat or cards | Unchanged |
| Action system | Unchanged |
| Profile data model | Add `risk_appetite` field if not present |

### Risk Appetite → UI Card

Moves from chat-based collection to a simple 3-option card:

```
┌─────────────────────────┐
│  Risk Appetite          │
│                         │
│  ○ Conservative         │
│    (Preserve capital)   │
│  ○ Moderate             │
│    (Balanced growth)    │
│  ○ Aggressive           │
│    (Maximum growth)     │
└─────────────────────────┘
```

### Agent Context (System Prompt)

Every conversation, the agent receives:

```
User profile: {profile_state}
Missing fields: {missing_fields}
Goals: {goals_summary}
Risk appetite: {risk_appetite}
Last snapshot: {last_snapshot}
Changes since last snapshot: {what_changed}

You are a financial advisor. Help the user based on what you know.
If key data is missing, weave collection into the conversation naturally.
You can generate a financial snapshot anytime the user has enough data.
Never rush data collection — let it happen organically.
```

The agent decides what to do based on what it sees:

| Agent sees | Agent does |
|---|---|
| Has income/expenses but no goals | "What are you saving for?" |
| Has goals but no insurance data | Naturally suggests checking coverage |
| Has everything, no snapshot yet | Generates snapshot |
| Has everything, has snapshot | Helps with whatever user asks |
| User adds new data (CAS upload, new goal) | Re-evaluates, updates snapshot if warranted |

### Persistent Snapshots

The snapshot is the agent's working memory — its analysis of the user's financial state. It persists across sessions and evolves over time.

**Profile vs Snapshot:**

| | Profile | Snapshot |
|---|---|---|
| What | Raw data the user provides | Agent's analysis of that data |
| Example | Income: ₹2.85L, Goals: car in 6mo | "Saving ₹85K/mo but car goal needs ₹15K/mo SIP. No term insurance — critical gap." |
| Who writes | User (via cards/chat) | Agent (LLM-generated) |
| Format | Structured fields in DB | Free-text analysis |
| Changes when | User updates data | Agent decides to re-analyze |

**Storage:**

```sql
CREATE TABLE user_snapshots (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    snapshot_text TEXT NOT NULL,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

Only the latest snapshot is passed to the agent. History is kept for audit/debugging.

**Snapshot lifecycle:**

```
Conversation 1 (just cards): Thin snapshot
  → "Income ₹2.85L, expenses ₹2L. No goals yet. No investments visible."

Conversation 3 (added goals + CAS): Rich snapshot
  → "₹8L in MFs (XIRR 14.2%), car goal needs ₹15K/mo SIP.
     No term insurance — critical gap for married with dependent.
     Emergency fund covers 2.1 months (target: 6)."

Conversation 7 (bought insurance): Updated snapshot
  → "Term insurance gap: closed ✅. Remaining: emergency fund (2.1→6 months),
     home goal needs planning (5yr horizon, current savings rate insufficient)."
```

**GENERATE_SNAPSHOT action:**

```python
SCHEMA = {
    "name": "generate_snapshot",
    "description": "Generate or update the user's financial snapshot based on current data",
    "parameters": {},
    "ui_component": None,
    "status_message": "Analysing your financial profile",
}

async def execute(params, user_id, context):
    # LLM generates snapshot text from profile + goals + holdings
    # Stored in user_snapshots table
    # Returned to chat as the agent's analysis
```

The agent calls this action when it decides a snapshot is warranted — not on a hardcoded trigger.

### Conversation Loop

```
┌──────────────────────────────────────────┐
│           Every Conversation             │
│                                          │
│  Inputs:                                 │
│    - Last snapshot (agent's memory)      │
│    - Current profile + goals + holdings  │
│    - User's message                      │
│                                          │
│  Agent reasons:                          │
│    - What changed since last snapshot?   │
│    - Does snapshot need updating?        │
│    - What should I help with now?        │
│                                          │
│  Outputs:                                │
│    - Chat response                       │
│    - Actions (goal cards, searches...)   │
│    - Updated snapshot (if warranted)     │
└──────────────────────────────────────────┘
```

### Implementation Plan

| Step | What | Effort |
|------|------|--------|
| 1 | Add risk appetite to UI cards, add DOB field | 0.5 day |
| 2 | Create `user_snapshots` table + `GENERATE_SNAPSHOT` action | 0.5 day |
| 3 | Remove onboarding state machine (`_handle_onboarding`, `_handle_wrapup`, pillar tracking) | 0.5 day |
| 4 | Rewrite orchestrator: single agent loop with profile-state-driven prompt | 1 day |
| 5 | Test: cards → agent conversation → snapshot generation → return next day → agent remembers | 0.5 day |
