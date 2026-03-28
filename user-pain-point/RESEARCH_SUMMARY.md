# FinAgent — User Research Summary

> Consolidated findings from interviews, Reddit analysis, and competitive research. Last updated: March 24, 2026.

---

## Data Collected
- 2 friend interviews (User A: 28y ₹50L SWE, User B: 30y ₹30L SWE)
- 23 Reddit threads from r/IndiaInvestments (Jan–Mar 2026)
- ~120 individual user questions categorized
- Detailed docs: [REDDIT_ANALYSIS.md](REDDIT_ANALYSIS.md) | [USER_RESEARCH.md](USER_RESEARCH.md)

---

## Core Finding

**80% of r/IndiaInvestments questions are things FinAgent can answer.**

| Category | % | MVP Priority |
|---|---|---|
| Portfolio review + MF selection | 46% | 🔴 P0 — this IS the product |
| Tax planning | 13% | 🔴 P0 — killer wedge, highest intensity |
| Insurance gaps | 10% | 🟡 P1 — high value, 2nd domain agent |
| Debt/FD alternatives | 8% | 🟡 P1 — simple post-tax math |
| NRI complexity | 7% | 🟢 P2 — future, massive if solved |
| Retirement/NPS | 6% | 🟡 P1 — fits cross-domain mode |
| Out of scope | 10% | ❌ |

---

## 3 Strongest Validation Signals

1. **u/Prudent-Fortune3420** (Jan 8, 2026): *"Uses INDMoney for visibility but can't make decisions. Advisors too expensive. Is there a financial advisor minus the human and 1% fee?"* — literally our product described by someone who doesn't know we exist.

2. **Tax-loss harvesting guide author**: wrote an encyclopedic post but admits *"you'll have to maintain cost basis manually across years"* — FinAgent automates exactly this.

3. **Both interview users** confirmed weekly manual net worth consolidation pain + tax advisor only helps at filing time, not year-round.

---

## Interview Insights

| Signal | Source | Impact on MVP |
|---|---|---|
| "Tell me what to DO, not just show data" | User A | Output must be prescriptive, not dashboards |
| Self-hosting = privacy solved | User B | Open-source positioning is right |
| "Would you offer cloud hosting?" | User B | Need hosted tier from early on |
| Parsing accuracy = trust | Both | Need validation checksums, confidence scores |
| Stocks more exciting than MFs | User A | But MFs safer to start (less regulatory risk) |

### User Personas

| | User A (Power User) | User B (Pragmatist) |
|---|---|---|
| Core need | "Tell me what to DO" | "Show me everything in one place" |
| Willing to | Upload data if privacy handled | Self-host if easy enough |
| Blocker | AI accuracy skepticism | Setup friction + cost |
| Would pay for | Actionable advice | Hosted solution that just works |

---

## 7 Recurring Reddit Patterns

1. **"Review my portfolio"** (25%) — users post full finances on Reddit, get conflicting opinions
2. **"Which fund should I pick?"** (25%) — beginners with zero context, get generic advice
3. **"Tax confusion"** (13%) — LTCG/STCG, harvesting, regime selection, 80C optimization
4. **"Insurance — what do I need?"** (10%) — even advisory platforms have trust issues
5. **"Market crash — what do I do?"** (5%) — emotional decisions, no personalized framework
6. **"FD vs alternatives"** (8%) — post-tax math poorly understood
7. **"NRI investing"** (7%) — 10x complexity, most NRIs just avoid India entirely

---

## Gaps in Research

1. **Only interviewed SWEs** — need non-tech users and someone happy with their advisor
2. **India-only data** — "global audience" decision but no US/UK/EU validation
3. **No pricing validation** — would people pay ₹200/month for hosted?
4. **No Mezzi deep-dive** — closest competitor (closed-source, US-only)

---

## What's Ready vs Missing

| Artifact | Status |
|---|---|
| Problem validation | ✅ Strong — 120 real questions, 2 interviews |
| User personas | ✅ Two clear personas |
| Before/after flows | ✅ 21 thread analyses in USER_RESEARCH.md |
| MVP feature prioritization | ✅ Data-driven from Reddit distribution |
| Competitive landscape | ⚠️ High-level done, needs Mezzi deep-dive |
| Pricing validation | ❌ Not started |
| Non-tech user validation | ❌ Not started |
| Global market validation | ❌ Not started |

---

## Recommendation

Research is solid enough to start building. Portfolio review + tax optimization cover 59% of all questions and map directly to our architecture. More research has diminishing returns — a working demo will be more convincing in the next interview than another doc.

One pre-code action: interview someone **happy with their financial advisor** to stress-test our thesis.
