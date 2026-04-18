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
