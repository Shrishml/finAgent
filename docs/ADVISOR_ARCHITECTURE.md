# FinBestie Advisor Architecture

> Conversational financial advisor that onboards users through chat, populates their dashboard, and provides a financial health score with actionable recommendations.

## Design Decisions

1. **Strict pillar-based onboarding** — fixed order, not free-form
2. **Chat for intake, dashboard for edits** — users talk to build profile, click to correct
3. **Progressive health score** — show with minimum data (income + assets), improve as user adds more. Never gate features behind "complete your profile"

## Current Architecture (Before)

```
User → /chat → classify_intent(domain, mode) → MFAgent → LLM → response
                                                   ↓
                                             load_holdings()
```

- Single domain agent (MF)
- No user profile beyond Google OAuth identity
- No conversation memory
- No financial health assessment

## Target Architecture (After)

```
User → /chat → Orchestrator
                    │
                    ├─ Profile incomplete? → OnboardingAgent
                    │                            │
                    │                    extract structured data
                    │                            │
                    │                    save to UserProfile
                    │                            │
                    │                    generate follow-up question
                    │
                    ├─ Profile sufficient? → classify_intent() → Domain Agents
                    │                                              (MF, Insurance, Loan...)
                    │
                    └─ "how am I doing?" → HealthScore engine → Action Plan
```

## Component Design

### 1. UserProfile Model

```python
# models/profile.py
@dataclass
class UserProfile:
    user_id: int
    
    # Pillar 1: Income
    monthly_income: float = 0        # in-hand salary
    annual_bonus: float = 0
    spouse_income: float = 0
    other_income: float = 0          # rental, freelance, etc.
    
    # Pillar 2: Expenses
    monthly_expenses: float = 0      # total estimated
    rent: float = 0
    emis: float = 0                  # total EMI outflow
    
    # Pillar 3: Assets (summary — detail in holdings/goals tables)
    # No fields here — computed from existing holdings + goals tables
    
    # Pillar 4: Liabilities
    loans: list[dict] = field(default_factory=list)
    # [{"type": "home", "principal": 4000000, "rate": 8.5, 
    #   "emi": 35000, "remaining_months": 180}]
    
    # Pillar 5: Insurance
    term_cover: float = 0
    health_cover: float = 0
    health_employer_only: bool = True
    
    # Pillar 6: Goals (already exists in goals table)
    # No fields here — computed from existing goals table
    
    # Demographics
    age: int = 0
    dependents: int = 0
    occupation: str = ""
    employer: str = ""
    risk_tolerance: str = ""         # conservative | moderate | aggressive
    
    # Tax
    tax_regime: str = ""             # old | new
    section_80c_used: float = 0
    
    # Onboarding state
    pillars_completed: list[str] = field(default_factory=list)
    # Ordered: ["income", "expenses", "assets", "liabilities", "insurance", "goals"]
    onboarding_complete: bool = False
```

**Storage:** `user_profiles` table with JSON blob (same pattern as holdings).

```sql
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id INTEGER PRIMARY KEY,
    data JSON NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 2. Conversation Memory

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,          -- "user" | "assistant" | "system"
    content TEXT NOT NULL,
    metadata JSON DEFAULT '{}', -- {"pillar": "income", "extractions": {...}}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, created_at);
```

Stores last N messages for onboarding context. Pruned to 50 messages per user.

### 3. OnboardingAgent

The core new component. Strict pillar order:

```
income → expenses → assets → liabilities → insurance → goals
```

**Flow per pillar:**

1. Agent asks about current pillar
2. User responds (may be partial, may overshare into next pillar)
3. LLM extracts structured data from response
4. Data saved to UserProfile
5. If pillar has enough data → mark complete, move to next
6. If not → ask targeted follow-up within same pillar

**LLM Prompt Structure:**

```
You are FinBestie, a friendly financial advisor onboarding a new user.

Current profile state: {profile_json}
Pillars completed: {completed}
Current pillar: {current_pillar}
Conversation so far: {last_10_messages}

User just said: "{user_message}"

Tasks:
1. Extract any financial data from the user's message. Return as JSON matching UserProfile fields.
2. Decide if current pillar has enough data to move on.
3. Generate a natural, warm follow-up — either a follow-up within the same pillar or transition to the next one.
4. If user shared info about a future pillar, extract it but still complete current pillar first.

Respond as JSON:
{
  "extractions": {"monthly_income": 110000, "occupation": "software engineer", ...},
  "pillar_complete": true,
  "response": "Great! ₹1.1L in-hand as a software dev. Any bonuses or RSUs on top of that?",
  "dashboard_updates": ["income"]  // which dashboard cards to refresh
}
```

**Pillar completion criteria:**

| Pillar | Minimum to complete |
|--------|-------------------|
| income | monthly_income > 0 |
| expenses | monthly_expenses > 0 |
| assets | User confirms what they have (even if "nothing") |
| liabilities | User confirms loans or "no loans" |
| insurance | User confirms coverage or "no insurance" |
| goals | At least 1 goal stated |

**Skip logic:** User can say "skip" or "I'll add this later" → pillar marked as skipped (not completed), move to next. Health score adjusts for missing data.

### 4. Health Score Engine

Pure math, no LLM. Computes from profile + holdings + goals.

```python
# analytics/health_score.py

# Minimum data: income + assets (from holdings table)
# Score improves in accuracy as more pillars are filled

WEIGHTS = {
    "savings_rate": 15,      # needs: income, expenses
    "emergency_fund": 15,    # needs: expenses, liquid holdings
    "debt_ratio": 10,        # needs: income, liabilities
    "insurance_cover": 15,   # needs: income, insurance
    "investment_rate": 15,   # needs: income, holdings
    "diversification": 10,   # needs: holdings
    "goal_readiness": 10,    # needs: goals, holdings
    "tax_efficiency": 10,    # needs: tax info, holdings
}

def compute_health_score(profile, holdings, goals) -> dict:
    scores = {}
    gaps = []
    max_possible = 0  # only count pillars with data
    
    # Savings rate (0-100 scaled to weight)
    if profile.monthly_income > 0 and profile.monthly_expenses > 0:
        rate = (profile.monthly_income - profile.monthly_expenses) / profile.monthly_income
        scores["savings_rate"] = min(100, rate * 200)  # 50%+ = 100
        max_possible += WEIGHTS["savings_rate"]
        if rate < 0.20:
            gaps.append({"area": "savings", "severity": "red",
                        "msg": f"Savings rate {rate:.0%} — aim for 20%+"})
    
    # Emergency fund
    if profile.monthly_expenses > 0:
        liquid = sum(h.current_value for h in holdings 
                    if "liquid" in h.category.lower() or "money market" in h.category.lower())
        needed = profile.monthly_expenses * 6
        ratio = min(1.0, liquid / needed) if needed > 0 else 0
        scores["emergency_fund"] = ratio * 100
        max_possible += WEIGHTS["emergency_fund"]
        if ratio < 1.0:
            gaps.append({"area": "emergency_fund", "severity": "red",
                        "msg": f"₹{liquid:,.0f} vs ₹{needed:,.0f} needed (6 months)"})
    
    # Insurance
    if profile.monthly_income > 0:
        annual = profile.monthly_income * 12
        term_multiple = profile.term_cover / annual if annual > 0 else 0
        scores["insurance_cover"] = min(100, term_multiple * 10)  # 10x = 100
        max_possible += WEIGHTS["insurance_cover"]
        if term_multiple < 10:
            recommended = annual * 15
            gaps.append({"area": "insurance", "severity": "red",
                        "msg": f"Term cover {term_multiple:.0f}x income — need 10-15x (₹{recommended:,.0f})"})
    
    # Debt-to-income
    if profile.monthly_income > 0 and profile.emis > 0:
        dti = profile.emis / profile.monthly_income
        scores["debt_ratio"] = max(0, (1 - dti / 0.5) * 100)  # 50%+ DTI = 0
        max_possible += WEIGHTS["debt_ratio"]
        if dti > 0.40:
            gaps.append({"area": "debt", "severity": "red",
                        "msg": f"EMIs are {dti:.0%} of income — above 40% danger zone"})
    
    # Investment rate
    if profile.monthly_income > 0 and holdings:
        total_invested = sum(h.invested_value for h in holdings)
        annual_income = profile.monthly_income * 12
        invest_ratio = total_invested / annual_income if annual_income > 0 else 0
        scores["investment_rate"] = min(100, invest_ratio * 50)  # 2x annual = 100
        max_possible += WEIGHTS["investment_rate"]
    
    # Diversification (equity/debt/gold split)
    if holdings:
        equity = sum(h.current_value for h in holdings if "equity" in h.category.lower())
        debt = sum(h.current_value for h in holdings if "debt" in h.category.lower())
        total = sum(h.current_value for h in holdings)
        if total > 0:
            eq_pct = equity / total
            # Ideal: 60-80% equity for young investors
            scores["diversification"] = 100 - abs(eq_pct - 0.7) * 200
            scores["diversification"] = max(0, min(100, scores["diversification"]))
            max_possible += WEIGHTS["diversification"]
    
    # Goal readiness
    if goals:
        on_track = sum(1 for g in goals if g.get("on_track", False))
        scores["goal_readiness"] = (on_track / len(goals)) * 100
        max_possible += WEIGHTS["goal_readiness"]
    
    # Weighted score (only from available data)
    if max_possible == 0:
        return {"score": None, "message": "Add income or assets to see your health score"}
    
    weighted = sum(
        scores.get(k, 0) * WEIGHTS[k] / 100 
        for k in WEIGHTS if k in scores
    )
    final_score = int(weighted / max_possible * 100)
    
    # Sort gaps by severity
    severity_order = {"red": 0, "yellow": 1, "green": 2}
    gaps.sort(key=lambda g: severity_order.get(g["severity"], 9))
    
    return {
        "score": final_score,
        "max_possible": max_possible,
        "data_completeness": f"{len(scores)}/{len(WEIGHTS)} areas assessed",
        "breakdown": {k: {"score": int(scores[k]), "weight": WEIGHTS[k]} 
                     for k in scores},
        "gaps": gaps,
        "missing_pillars": [p for p in ["income", "expenses", "assets", "liabilities", "insurance", "goals"]
                           if p not in profile.pillars_completed],
    }
```

**Progressive disclosure:** The score shows "58/100 (5/8 areas assessed)" and lists which pillars are missing: "Add insurance info to improve accuracy."

### 5. API Endpoints

```
GET  /profile                → user's financial profile
PUT  /profile                → update profile fields (dashboard edits)
GET  /health-score           → computed score + gaps + action plan
GET  /conversation?limit=20  → recent chat history
POST /chat                   → (modified) routes to onboarding if profile incomplete
```

### 6. Orchestrator Changes

```python
async def handle_query(query: str, user_id: int) -> str:
    profile = load_profile(user_id)
    
    # New user or incomplete profile → onboarding
    if not profile or not profile.onboarding_complete:
        return await onboarding_agent.handle(query, user_id)
    
    # "How am I doing?" / health check intent
    intent = await classify_intent(query)
    if intent["domain"] == "health_check":
        score = compute_health_score(profile, load_holdings(user_id), load_goals(user_id))
        return format_health_score(score)
    
    # Existing domain routing
    ...
```

### 7. Dashboard Overview Tab

New default tab showing:
- Health score donut chart
- Gap alerts (red/yellow/green cards)
- Profile summary cards (income, net worth, savings rate)
- Action plan (prioritized list)
- "Add more info" prompts for missing pillars

## Implementation Phases

| # | Phase | What | Effort | Dependencies |
|---|-------|------|--------|-------------|
| P1 | Data Layer | UserProfile model + table + CRUD | 2hr | — |
| P2 | Conversation Memory | conversations table + CRUD | 1hr | — |
| P3 | Onboarding Agent | LLM extraction + strict pillar flow | 4hr | P1, P2 |
| P4 | Orchestrator Update | Route incomplete profiles to onboarding | 1hr | P3 |
| P5 | Health Score | Pure math engine + /health-score API | 3hr | P1 |
| P6 | Profile API | GET/PUT /profile + dashboard edit support | 2hr | P1 |
| P7 | Dashboard UI | Overview tab with score, gaps, action plan | 4hr | P5, P6 |

**Total: ~17 hours** (fits in ~2 weekends at your pace)

P1+P2 are parallel. P3 is the core. P5 is parallel with P3/P4.

## GitHub Issues

### Issue #20: UserProfile model + storage (P1)
- Add `UserProfile` dataclass in `models/profile.py`
- Add `user_profiles` table in `storage/sqlite.py`
- CRUD: `save_profile()`, `load_profile()`, `update_profile()`
- Unit tests

### Issue #21: Conversation memory (P2)
- Add `conversations` table in `storage/sqlite.py`
- CRUD: `save_message()`, `load_conversation(user_id, limit)`
- Auto-prune to 50 messages per user

### Issue #22: OnboardingAgent — conversational intake (P3)
- New `agents/onboarding.py` with strict pillar order
- LLM prompt for extraction + follow-up generation
- Pillar completion criteria + skip logic
- Integration with UserProfile storage

### Issue #23: Orchestrator routing for onboarding (P4)
- Modify `handle_query()` to check profile completeness
- Route to OnboardingAgent when profile incomplete
- Add "health_check" intent to classifier

### Issue #24: Financial health score engine (P5)
- New `analytics/health_score.py`
- Weighted scoring across 8 areas
- Progressive — works with partial data
- Gap detection with severity levels
- `GET /health-score` endpoint

### Issue #25: Profile API + dashboard edits (P6)
- `GET /profile` — return profile data
- `PUT /profile` — update fields from dashboard
- Profile settings page in UI

### Issue #26: Dashboard Overview tab (P7)
- Health score visualization (donut/gauge)
- Gap alert cards
- Profile summary cards
- Action plan display
- "Add more info" prompts for missing pillars
