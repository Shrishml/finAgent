# Persona Reviews

## Review v2 (2026-03-29) — Post-fixes

### Scores
| Persona | v1 | v2 | Weight |
|---------|----|----|--------|
| 🚀 Arjun (26, dev) | 7 | **8** | 50% |
| 🧐 Priya (35, PM) | 7 | **8** | 35% |
| 🏦 Ramesh (52, senior) | 3 | **5** | 15% |
| **Weighted avg** | 5.7 | **7.55** | |

### Fixes that worked
- Mockup above the fold — universally praised as biggest improvement
- Currency consistency (₹18,400 across all assets) — "finally feels real"
- Disclaimer in footer — trust signal for all personas

### Remaining backlog (by priority)

#### High (Arjun)
- [ ] GitHub stars badge on page — social proof
- [ ] Replace Google Form with inline email input — Form feels like "side project that might die"
- [ ] Demo GIF/video — static SVGs aren't enough

#### Medium (Priya)
- [ ] "Takes 2 minutes" line near mockup — time commitment is her #1 filter
- [ ] Terminal demo scares non-devs — consider placing lower or toggling
- [ ] Mobile screenshot

#### Low (Ramesh — defer to Year 2)
- [ ] Dedicated privacy/data section
- [ ] Builder credentials/background
- [ ] XIRR claim caveats
- [ ] "This is a tool, not a replacement for your advisor" messaging

### Key quotes
- Arjun: "I'd drop this in my office Slack's #investing channel"
- Priya: "Finally, someone who gets it"
- Ramesh: "I'm no longer dismissing it outright — which is progress"

---

## Review v3 (2026-04-15) — Post-Login Dashboard

Reviewed against beta.captwist.in with DEV_MODE + seeded data (6 holdings, portfolio XIRR 69.73%).

### Scores
| Persona | Landing v2 | Post-Login v3 | Delta | Weight |
|---------|-----------|---------------|-------|--------|
| 🚀 Arjun (26, dev) | 8 | **6.4** | -1.6 | 50% |
| 🧐 Priya (35, PM) | 8 | **5.8** | -2.2 | 35% |
| 🏦 Ramesh (52, senior) | 5 | **3.8** | -1.2 | 15% |
| **Weighted avg** | 7.55 | **5.7** | **-1.85** | |

### Dimension Breakdown

#### 🚀 Arjun
| Dimension | Score | Notes |
|-----------|-------|-------|
| First Impression | 7 | Clean layout, tabs make sense. "Demo Mode" badge is honest. |
| Data Clarity | 7 | XIRR per fund is killer — Groww doesn't show this. But 69.73% demo XIRR looks unrealistic. |
| Actionability | 5 | "What's working" / "Worth a look" — great concept but no real content. No rebalancing nudges. |
| Trust | 7 | Open-source, local data. AI "audited your portfolio" is bold — does it deliver? |
| Delight | 6 | Benchmark toggles are cool. No dark mode, no export, no keyboard shortcuts. |

#### 🧐 Priya
| Dimension | Score | Notes |
|-----------|-------|-------|
| First Impression | 7 | Tabs intuitive. Immediately see value vs invested. |
| Data Clarity | 6 | No TOTAL row. Have to mentally add 6 rows for total invested/current/gain. |
| Actionability | 5 | Goals tab empty — that's the feature I'd use most. "Link Holdings to Goals" = exactly right but not working. |
| Trust | 6 | "Demo Mode" confusing — real data or fake? XIRRs look too good. |
| Delight | 5 | No notifications, no "SIP due", no "market crashed but you're fine". Dashboard, not assistant. |

#### 🏦 Ramesh
| Dimension | Score | Notes |
|-----------|-------|-------|
| First Impression | 4 | Looks like student project. CA's Excel has 40 columns. Where's folio, purchase date, units, NAV date? |
| Data Clarity | 5 | XIRR correct concept but 173% on a fund? No date range — since when? |
| Actionability | 3 | No tax view. No LTCG/STCG breakdown. No "if you redeem, you pay ₹X tax." |
| Trust | 4 | "AI audited" — audited how? No methodology shown. No SEBI disclaimer. |
| Delight | 3 | 50+ funds across 4 AMCs — no search, filter, sort. No PDF export. |

### Key Quotes
- Arjun: "XIRR per fund is the killer feature — nobody else shows this so cleanly. But the dashboard needs to DO something with the data."
- Priya: "I can see my numbers but I can't DO anything with them. Groww lets me invest more, Kuvera shows tax harvesting. This shows me a table."
- Ramesh: "For ₹3.5L portfolio this is fine. For ₹2Cr+, I need folio-level detail, tax computation, and a PDF for my CA."

### Universal Insight
The landing page sells the dream; the dashboard doesn't yet deliver it. Gap between "here are your numbers" and "here's what to do about them" is the #1 issue.

### Priority Fixes
| # | Fix | Impact | Personas |
|---|-----|--------|----------|
| 1 | 🔴 Summary card with totals at top | High | Priya, Arjun |
| 2 | 🔴 Real portfolio insights with specific recommendations | High | All 3 |
| 3 | 🔴 Realistic demo data (14-18% XIRR, not 173%) | High | Arjun, Priya |
| 4 | 🟡 Goals feature working end-to-end | Med | Priya |
| 5 | 🟡 Tax view — LTCG/STCG breakdown | Med | Ramesh, Priya |
| 6 | 🟡 Export to PDF/CSV | Med | Ramesh, Arjun |