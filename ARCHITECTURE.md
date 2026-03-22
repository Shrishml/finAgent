# FinAgent — Architecture Document

> **Your money, your agent, your rules.**

This document explains not just *what* FinAgent's architecture looks like, but *why* every design decision was made. It's written for contributors, early users, and anyone evaluating whether this approach is sound.

---

## The Problem: Financial Advisory Has a Principal-Agent Problem

Every financial app and advisor today has a fundamental conflict of interest:

| Who | Their Incentive | Your Cost |
|-----|----------------|-----------|
| Mutual fund distributors | Earn commission on Regular plans | You pay 0.5-1.5% higher expense ratio — compounding against you for decades |
| Insurance agents | Earn 30-40% first-year commission on ULIPs/endowment | You get locked into a bad product for 15+ years |
| Financial advisors (AUM-based) | Earn more when your assets grow — but also when you *don't* withdraw | They'll never tell you to prepay your home loan |
| Fintech apps (INDMoney, Groww) | Earn from product distribution, cross-selling | "Recommendations" are ads in disguise |

**The deeper problem**: No tool sees your complete financial picture. Your MF app doesn't know about your insurance. Your insurance app doesn't know about your loans. Your tax planner sees neither. You're left stitching together a financial picture from 5 different apps — each with its own agenda.

This isn't a UI problem. It's a **structural** problem. The incentives are misaligned, and the data is siloed.

## Why an Open-Source AI Agent Fixes This

An open-source agent flips the principal-agent relationship:

1. **You employ the agent** — it works for you, not for a company
2. **No commissions** — the agent has no products to sell
3. **Cross-product reasoning** — it sees everything because it works for *you*, not for one product category
4. **Auditable** — every recommendation traces back to open-source logic
5. **Local-first** — your financial data stays on your machine (or your server)

The business model is simple: open source the agent, charge a margin on LLM tokens for the hosted version. Users who don't trust that can self-host. Incentives stay aligned.

---

## Design Philosophy

Three principles drive every architectural decision:

### 1. Domain-Rich, Adapter-Thin

Financial products are complex. An insurance policy has exclusions, waiting periods, co-pay clauses, sub-limits, riders. A mutual fund has expense ratios, exit loads, lock-in periods, dividend history, benchmark tracking error.

**We model this complexity faithfully in domain agents.** Each domain agent has a rich internal model that captures every nuance. But when the orchestrator needs to compare across products, it sees only a thin summary — just enough for cross-product reasoning.

Why? Because a home loan agent shouldn't need to understand insurance riders to answer "should I prepay my loan or invest more?" It just needs to know: *this insurance costs ₹25K/year, covers ₹10L, and is tax-deductible under 80D.*

### 2. Three Modes, Not Three Agents

Each domain agent operates in three modes:

- **Analyze** — Reason over the user's stored data ("What are my expense ratios?")
- **Research** — Search the market for better options ("Find me a better health insurance policy")
- **Cross-domain** — Contribute thin summaries for holistic reasoning ("Should I prepay my loan or invest more?")

Why modes instead of separate agents? Because the same domain knowledge powers all three. The MF agent that analyzes your portfolio is the same one that knows how to search for better funds — it has the domain context to compare meaningfully.

### 3. Deterministic Routing, Not LLM Roulette

Production finance apps (Mezzi, Monarch Money, Copilot) all learned the same lesson: **don't let the LLM decide which tool to call.** LLM-driven routing degrades with 10+ tools and produces unpredictable behavior.

FinAgent uses **intent classification → deterministic routing**:

```
User query → Intent Classifier → Route to domain agent + mode
                                    ↓
                              "analyze:mf" → MF Agent (analyze mode)
                              "research:insurance" → Insurance Agent (research mode)  
                              "cross-domain" → Orchestrator (collects thin summaries)
```

The intent classifier is an LLM call, but the routing is deterministic. Once we know "this is a mutual fund analysis question," it always goes to the MF agent. No ambiguity, no tool-selection hallucinations.


---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        USER LAYER                           │
│  Web UI / Chat / API                                        │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                      ORCHESTRATOR                           │
│                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │   Intent     │  │  Cross-Domain │  │  Conversation     │  │
│  │  Classifier  │  │  Reasoner     │  │  Memory           │  │
│  └──────┬──────┘  └──────▲───────┘  └───────────────────┘  │
│         │                │                                   │
│         │         thin summaries only                        │
└─────────┼────────────────┼──────────────────────────────────┘
          │                │
    ┌─────▼────────────────┼─────────────────────┐
    │           DOMAIN AGENT LAYER                │
    │                                             │
    │  ┌──────────┐ ┌──────────┐ ┌──────────┐    │
    │  │ MF Agent │ │Insurance │ │  Loan    │    │
    │  │          │ │  Agent   │ │  Agent   │ …  │
    │  │ 3 modes: │ │ 3 modes: │ │ 3 modes: │    │
    │  │ analyze  │ │ analyze  │ │ analyze  │    │
    │  │ research │ │ research │ │ research │    │
    │  │ summary  │ │ summary  │ │ summary  │    │
    │  └────┬─────┘ └────┬─────┘ └────┬─────┘    │
    │       │             │            │           │
    └───────┼─────────────┼────────────┼──────────┘
            │             │            │
    ┌───────▼─────────────▼────────────▼──────────┐
    │            CONNECTOR LAYER                   │
    │                                              │
    │  ┌────────┐ ┌────────┐ ┌────────┐ ┌──────┐  │
    │  │  PDF   │ │  API   │ │ Email  │ │ Open │  │
    │  │ Parser │ │Connect │ │ Import │ │Banking│  │
    │  └────────┘ └────────┘ └────────┘ └──────┘  │
    └──────────────────────────────────────────────┘
            │             │            │
    ┌───────▼─────────────▼────────────▼──────────┐
    │            DATA LAYER                        │
    │                                              │
    │  SQLite (per-user, local-first)              │
    │  Rich domain models stored faithfully        │
    │  User financial knowledge graph              │
    └──────────────────────────────────────────────┘
```

### Layer Responsibilities

**User Layer** — FastAPI endpoints + simple web UI. Accepts document uploads and natural language queries. Stateless — all state lives in the data layer.

**Orchestrator** — The brain. Three jobs:
1. Classify intent (which domain? which mode?)
2. Route to the right domain agent
3. For cross-domain queries, collect thin summaries from multiple agents and reason holistically

**Domain Agent Layer** — Deep expertise per financial product. Each agent owns its rich domain model and exposes a thin `FinancialSummary` adapter for cross-domain use. Each operates in 3 modes.

**Connector Layer** — Pluggable data ingestion. Detects document type, parses it, and routes the structured data to the appropriate domain agent. New data sources = new connectors, zero changes to agents.

**Data Layer** — SQLite per user. Stores rich domain models (not flattened). The knowledge graph tracks relationships between financial products (e.g., "ELSS fund X is linked to Section 80C, which is also claimed by EPF").


---

## Data Models: Rich Inside, Thin Outside

### The Thin Summary (What the Orchestrator Sees)

```python
@dataclass
class FinancialSummary:
    product_type: str        # "mutual_fund", "insurance", "loan"
    product_name: str        # "Axis Bluechip Fund - Direct Growth"
    annual_cost: float       # Total annual cost to the user (₹)
    current_value: float     # Current value or coverage amount (₹)
    tax_sections: list[str]  # ["80C", "80D"] — which tax sections apply
    risk_tags: list[str]     # ["equity", "large_cap", "high_expense"]
    liquidity: str           # "instant", "t+3", "locked_3yr", "illiquid"
    metadata: dict           # Agent-specific extras
```

This is deliberately minimal. The orchestrator doesn't need to know your fund's benchmark tracking error to answer "should I prepay my loan or invest more?" It needs: cost, value, tax impact, risk, liquidity.

### The Rich Model (What the Domain Agent Knows)

Example — Mutual Fund holding:

```python
@dataclass
class MFHolding:
    # Identity
    scheme_name: str
    isin: str
    amfi_code: str
    folio: str
    amc: str
    plan: str               # "direct" or "regular"
    
    # Current state
    units: float
    nav: float
    current_value: float
    invested_value: float
    
    # Cost analysis
    expense_ratio: float
    annual_expense: float    # expense_ratio × current_value
    exit_load: str
    
    # Performance
    returns_absolute: float
    xirr: float
    benchmark: str
    benchmark_returns: float
    
    # Tax
    tax_section: str         # "80C" for ELSS, None for others
    ltcg_grandfathered: float
    holding_period_days: int
    
    # Transactions
    transactions: list[MFTransaction]
    
    def to_summary(self) -> FinancialSummary:
        """Adapter: rich model → thin summary for orchestrator"""
        return FinancialSummary(
            product_type="mutual_fund",
            product_name=self.scheme_name,
            annual_cost=self.annual_expense,
            current_value=self.current_value,
            tax_sections=["80C"] if self.tax_section == "80C" else [],
            risk_tags=self._compute_risk_tags(),
            liquidity="locked_3yr" if self.tax_section == "80C" else "t+3",
            metadata={"xirr": self.xirr, "expense_ratio": self.expense_ratio}
        )
```

Every domain agent follows this pattern: rich internal model with a `to_summary()` adapter. The orchestrator never touches the rich model directly.


---

## Domain Agent Deep Dive

### The Agent Interface

```python
class DomainAgent(ABC):
    """Every financial domain implements this interface."""
    
    @abstractmethod
    def analyze(self, query: str, user_data: list) -> str:
        """Mode 1: Reason over user's stored data."""
        
    @abstractmethod
    def research(self, query: str, constraints: dict) -> str:
        """Mode 2: Search the market for options matching constraints."""
        
    @abstractmethod
    def get_summaries(self, user_data: list) -> list[FinancialSummary]:
        """Mode 3: Return thin summaries for cross-domain reasoning."""
    
    @abstractmethod
    def supported_connectors(self) -> list[str]:
        """Which data sources this agent can ingest."""
```

### Mode 1: Analyze — "What do I have?"

The user uploads a document. A connector parses it into the rich domain model. The agent stores it and can now answer questions:

```
User: "Which of my funds have expense ratios above 1%?"
→ Intent: analyze:mf
→ MF Agent scans stored MFHoldings, filters by expense_ratio > 0.01
→ Returns ranked list with how much each costs annually
```

This mode is **deterministic + LLM-enhanced**. The filtering/computation is code. The LLM formats the response and adds context ("This fund's direct plan alternative would save you ₹4,200/year").

### Mode 2: Research — "What should I get?"

The agent searches external data sources to find options matching the user's needs:

```
User: "Find me an index fund tracking Nifty 50 with the lowest expense ratio"
→ Intent: research:mf
→ MF Agent queries AMFI data for all Nifty 50 index funds
→ Compares expense ratios, AUM, tracking error
→ Returns top 3 recommendations with reasoning
```

Research mode tools vary by domain:
- **MF**: AMFI NAV API (free), fund factsheets, Value Research/Morningstar data
- **Insurance**: PolicyBazaar comparison data, IRDAI public disclosures
- **Loans**: Bank rate comparison APIs, RBI published rates

### Mode 3: Cross-Domain — "What should I do?"

The orchestrator collects thin summaries from all domain agents and reasons across them:

```
User: "Should I prepay my home loan or invest more in mutual funds?"
→ Intent: cross-domain
→ Orchestrator calls get_summaries() on MF Agent and Loan Agent
→ Compares: loan interest rate (8.5%) vs portfolio XIRR (12.3%)
→ Factors in: tax benefit on loan interest (Section 24b) vs LTCG tax on MF gains
→ Returns recommendation with full math shown
```

The orchestrator **never** accesses rich domain models. It works only with `FinancialSummary` objects. This keeps cross-domain reasoning simple and prevents the orchestrator from becoming a god object.


---

## Connector Layer: Pluggable Data Ingestion

### The Connector Interface

```python
class Connector(ABC):
    @abstractmethod
    def detect(self, file_or_data) -> bool:
        """Can this connector handle this input?"""
    
    @abstractmethod
    def parse(self, file_or_data) -> list:
        """Parse input into rich domain model objects."""
    
    @abstractmethod
    def target_domain(self) -> str:
        """Which domain agent receives the parsed data."""
```

Connectors are the **only** way data enters the system. The flow:

```
Upload → Connector Registry (tries each connector's detect()) 
       → Matching connector parses → Rich domain objects 
       → Stored in user's data layer 
       → Domain agent can now analyze
```

### Phase 1 Connectors (India — MF Focus)

| Connector | Library | What It Extracts | Limitations |
|-----------|---------|-----------------|-------------|
| CAMS PDF | `casparser` (MIT) | Folios, schemes, ISIN, units, NAV, transactions, dividends | No stocks/bonds in demat CAS; ISIN DB needs periodic updates |
| KFintech PDF | `casparser` | Same as CAMS (auto-detected) | Same limitations |
| AMFI Enrichment | `mftool` (MIT) | Live NAV, historical NAV, scheme metadata | Rate-limited; no expense ratio directly (needs scraping) |

**casparser details** (v0.8.1):
- Handles password-protected PDFs natively
- Extracts 14 transaction types (PURCHASE, SIP, REDEMPTION, SWITCH, DIVIDEND, etc.)
- Companion `casparser-isin` maps scheme names → ISIN + AMFI codes
- Beta: capital gains report generation (Schedule 112A for ITR)
- License note: MIT with PDFMiner backend; AGPL if using PyMuPDF (`casparser[fast]`)

**mftool details** (v3.2):
- Wraps AMFI India's public NAV API (amfiindia.com)
- `get_scheme_quote(code)` → live NAV, date, scheme name
- `get_scheme_historical_nav(code)` → full NAV history
- `calculate_balance_units_value(code, balance)` → current value
- No auth required, no rate limits documented, MIT license

### Future Connectors (Global Expansion)

| Region | Connector | Library/API | Cost |
|--------|-----------|-------------|------|
| US | Brokerage OFX | `ofxparse` | Free |
| US | Account aggregation | Plaid Investments API | $0.30/connection/mo |
| EU/UK | Open Banking | Nordigen/GoCardless | **Free** (2,300+ banks, 31 countries) |
| Global | PDF statements | `pdfplumber` + templates | Free |
| Global | Fund data | Yahoo Finance (unofficial) | Free |
| Global | ISIN lookup | OpenFIGI API | Free |
| India Phase 2 | AIS (Annual Info Statement) | PDF parser (custom) | Free |
| India Phase 3 | Zerodha | Kite Connect API | ₹2K/mo |
| India Phase 3 | Angel One | SmartAPI | Free |
| India Phase 4 | Account Aggregator | RBI-regulated FIU | Partnership required |

The connector interface means adding a new country or data source is **one new class** — zero changes to domain agents or orchestrator.


---

## Orchestrator: Intent Classification → Deterministic Routing

### Why Not Let the LLM Pick Tools?

Frameworks like LangChain let the LLM decide which tool to call via function descriptions. This works for demos but breaks in production:

- **Degrades at scale**: LLM tool selection accuracy drops significantly beyond 10-15 tools
- **Unpredictable**: Same query can route differently on different runs
- **Expensive**: Every routing decision costs a full LLM call with all tool descriptions
- **Hard to debug**: "Why did it call the insurance agent for a tax question?"

Production finance apps (Mezzi, Monarch, Copilot Money) all converged on the same pattern: **pre-computed analytics + deterministic pipelines + LLM at the presentation layer.**

### FinAgent's Routing

```
User: "Does my health insurance cover knee surgery?"

Step 1 — Intent Classification (one LLM call):
  → domain: insurance
  → mode: analyze
  → entities: ["health insurance", "knee surgery"]

Step 2 — Deterministic Route:
  → InsuranceAgent.analyze(query, user_insurance_data)

Step 3 — Domain Agent Execution:
  → Agent searches user's stored policy for exclusions, sub-limits, waiting periods
  → Checks if "knee surgery" falls under any exclusion clause
  → LLM generates human-readable response with specific policy references
```

The intent classifier is the **only** LLM call in the routing path. Everything after is deterministic code calling the right agent with the right mode.

### Knowledge Graph: Connecting the Dots

A lightweight property graph (NetworkX, upgradeable to Neo4j) tracks relationships:

```
[ELSS Fund X] ──claims──→ [Section 80C] ←──claims── [EPF]
                                ↑
                            limit: ₹1.5L
                                ↑
                          [PPF] ──claims──→ [Section 80C]
```

This enables queries like:
- "Am I over-investing in 80C?" → Sum all products claiming 80C, compare to ₹1.5L limit
- "What happens if I surrender this policy?" → Trace all tax sections and coverage that would be lost
- "Show me my complete tax picture" → Traverse all tax-related edges

The graph is built incrementally as documents are uploaded. Each domain agent registers its products' tax sections, risk relationships, and dependencies.

---

## Query Flow: End to End

```
1. User: "I'm paying ₹45K/year for health insurance. Is that too much?"

2. Intent Classifier:
   → domain: insurance | mode: analyze | subtype: cost_assessment

3. Router: InsuranceAgent.analyze()

4. Insurance Agent:
   a. Loads user's health insurance policies from data store
   b. Finds: ₹45K/year, ₹10L cover, family floater, 2 adults + 1 child
   c. Computes: cost per lakh of coverage = ₹4,500
   d. Research sub-call: checks market rates for similar profiles
   e. Finds: comparable policies at ₹28-35K for same coverage
   f. Checks knowledge graph: policy claims Section 80D (₹25K limit)

5. Response:
   "Your policy costs ₹4,500 per lakh of coverage. For a family floater 
    with ₹10L cover (2 adults, 1 child), the market range is ₹28-35K. 
    You're paying ~30% above market rate.
    
    However, ₹25K of this is tax-deductible under Section 80D, bringing 
    your effective cost to ₹33,750 (assuming 30% tax bracket).
    
    Want me to research specific alternatives that match your coverage needs?"
```

Notice: the agent combined **analyze** (your data) with a lightweight **research** sub-call (market comparison) and **cross-domain** context (tax impact from knowledge graph) — all within a single query. The modes aren't rigid walls; they're capabilities the agent draws on as needed.


---

## Why This Architecture? (Decision Log)

| Decision | What We Chose | What We Rejected | Why |
|----------|--------------|-----------------|-----|
| Routing | Intent classifier → deterministic | LLM picks tools (LangChain-style) | Predictable, debuggable, scales to 20+ tools |
| Domain models | Rich per-domain dataclasses | Single flat schema for all products | Insurance exclusions ≠ MF expense ratios. Flattening loses critical nuance |
| Cross-domain | Thin adapter summaries | Orchestrator reads rich models | Prevents god-object orchestrator; domains stay independent |
| Agent framework | Custom (no framework) | LangChain / CrewAI / AutoGen | Frameworks add abstraction tax; our routing is simpler than what they solve for |
| Data storage | SQLite per user | PostgreSQL / MongoDB | Local-first philosophy; user's data never leaves their machine by default |
| PDF parsing | casparser (India) + pdfplumber (global) | Build custom parser | casparser is battle-tested for Indian MF statements; pdfplumber handles everything else |
| LLM usage | Parsing: Gemini Flash (cheap). Reasoning: Claude/GPT | Single model for everything | Parsing is high-volume, low-complexity. Reasoning is low-volume, high-complexity. Optimize cost. |
| Knowledge graph | NetworkX (in-memory) | Neo4j | Overkill for MVP. Upgrade path exists when we need persistence/scale |

## How This Compares to Existing Approaches

```
                    Closed Source          Open Source
                   ┌──────────────────┬──────────────────┐
                   │                  │                  │
  Agent-first      │  Mezzi           │  FinAgent ← US  │
  (AI reasons      │  (US, invest-    │                  │
   over your data) │   ment only)     │  EMPTY QUADRANT  │
                   │                  │                  │
                   ├──────────────────┼──────────────────┤
                   │                  │                  │
  Dashboard-first  │  Monarch Money   │  Ghostfolio      │
  (shows data,     │  Copilot Money   │  Maybe Finance   │
   AI is a feature)│  INDMoney        │  Firefly III     │
                   │                  │  (no AI)         │
                   │                  │                  │
                   └──────────────────┴──────────────────┘
```

FinAgent occupies the **open-source + agent-first** quadrant — currently empty globally. The closest competitor (Mezzi) is closed-source, US-only, and investment-only (no insurance, no loans, no cross-product reasoning).

## Tech Stack Summary

| Component | Technology | Why |
|-----------|-----------|-----|
| Backend | Python + FastAPI | Ecosystem (casparser, mftool, LLM SDKs all Python) |
| LLM (parsing) | Gemini Flash | Cheapest for high-volume structured extraction |
| LLM (reasoning) | Claude / GPT-4 | Best for nuanced financial reasoning |
| Storage | SQLite | Local-first, zero infrastructure, per-user isolation |
| Knowledge graph | NetworkX | Lightweight, in-memory, sufficient for MVP |
| PDF parsing (India) | casparser + casparser-isin | MIT, battle-tested, extracts 14 transaction types |
| Fund data (India) | mftool (AMFI API) | MIT, free, no auth, daily updated NAV data |
| PDF parsing (global) | pdfplumber + camelot-py | Handles any tabular PDF with templates |
| Fund data (global) | Yahoo Finance (yfinance) | Free, unofficial, covers global markets |
| Account aggregation | Nordigen (EU, free) / Plaid (US, paid) | Future phases |
| Frontend | HTML + Tailwind CSS | Simple, no build step, ships fast |
| Hosting | Railway / Render free tier | Zero cost to start |

---

## What's Next: Phase 1 Build Plan

Phase 1 delivers the **MF domain agent** as proof of the architecture:

1. **Core abstractions** — `FinancialSummary`, `DomainAgent` ABC, `Connector` ABC, `Orchestrator` skeleton
2. **MF rich model** — `MFHolding`, `MFTransaction` with full casparser field mapping
3. **CAMS connector** — Upload PDF → casparser → `MFHolding` objects → stored
4. **AMFI enrichment** — mftool lookup for live NAV, scheme metadata
5. **MF analyze mode** — Answer questions about user's portfolio (expense ratios, returns, tax)
6. **MF research mode** — Search AMFI data for better fund alternatives
7. **Intent classifier + router** — Classify query → route to agent + mode
8. **Knowledge graph** — Track tax sections, risk relationships
9. **Chat API** — FastAPI endpoint for natural language queries
10. **Web UI** — Upload documents + chat interface
11. **Deploy** — Railway/Render free tier

Each step is independently testable. The architecture doc you're reading now is step 0 — making sure the design is sound before writing code.

---

*This is a living document. As we build, we'll update it with lessons learned, performance data, and architectural changes.*

*Last updated: March 22, 2026*
