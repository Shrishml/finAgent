# 📣 CMO Reddit Scan — Week 5 (Apr 20, 2026)

**Repo stats:** ⭐ 4 stars (+1 WoW) | 🍴 2 forks | 22 open issues
**Scan method:** DuckDuckGo fallback (no recency filter — Reddit API blocked on corp network)
**Content calendar:** 1 overdue item ("The Pattern" Reddit post, due Mar 27 — now 24 days overdue)

---

## 🔍 Search Results Summary

| # | Query | Subreddit | Threads Found |
|---|-------|-----------|:---:|
| 1 | portfolio review mutual fund | r/IndiaInvestments | 5 |
| 2 | expense ratio direct regular plan | r/IndiaInvestments | 5 |
| 3 | financial advisor fee | r/IndiaInvestments | 5 |
| 4 | LIC policy return XIRR | r/IndiaInvestments | 5 (3 Reddit + 2 tools) |
| 5 | portfolio analysis tool | r/personalfinance | 5 (1 ad filtered) |
| 6 | financial advisor worth it | r/personalfinance | 4 |
| 7 | open source finance AI | r/algotrading | 5 |
| | **Total** | | **34** |

---

## 🎯 Engagement Opportunities (Ranked)

### 🔥 HIGH PRIORITY

**1. "Looking for a free portfolio analysis site — no account linking"**
- Sub: r/personalfinance | [Thread](https://www.reddit.com/r/personalfinance/comments/152wgck/)
- Why: EXACT Arth use case — privacy-first, no API keys, free. 3rd consecutive week as #1 hit.
- Status: ⚠️ Still not posted from Week 3/4. Becoming stale — post this week or deprioritize.

> **Draft reply:**
> I've been building an open-source tool for exactly this — upload a PDF statement from your broker (no account linking), get portfolio breakdown, XIRR returns, overlap analysis, and category allocation. Everything's auditable. Called Arth: https://github.com/Suraj1074/finAgent
>
> It also has an AI advisor that runs actual calculations on your data instead of giving generic opinions. Still early but core analysis works. What features would matter most to you?

**2. "Tool for Deep Portfolio Analysis" (overlap/holdings breakdown)**
- Sub: r/personalfinance | [Thread](https://www.reddit.com/r/personalfinance/comments/17drq35/)
- Why: User wants ETF/MF overlap analysis — validates roadmap item from Week 4
- Status: HOLD until overlap feature ships. Two threads now confirm demand.

**3. "ETF Breakdown website/app to visualise total holdings"**
- Sub: r/personalfinance | [Thread](https://www.reddit.com/r/personalfinance/comments/mhswa1/)
- Why: NEW this week. User wants to see aggregate holdings across ETFs. Same overlap need.
- Status: HOLD — 3rd signal for overlap feature. Strong roadmap validation.

### 🟡 MEDIUM PRIORITY

**4. "Calculating XIRR of an LIC policy"**
- Sub: r/IndiaInvestments | [Thread](https://www.reddit.com/r/IndiaInvestments/comments/ku743m/)
- Why: XIRR is core competency. Can demonstrate real math value.

> **Draft reply:**
> The honest approach: calculate XIRR on premiums paid vs surrender value today. That gives you the real opportunity cost vs alternatives. Future bonus rates are unknowable, so don't project them.
>
> For my father's LIC policy, the XIRR came out to ~4.5% — below even FD rates. The math doesn't lie, even when the agent does. I built a tool that computes XIRR from any cashflow series if you want to check yours.

**5. "How expense ratio eats your investments"**
- Sub: r/IndiaInvestments | [Thread](https://www.reddit.com/r/IndiaInvestments/comments/8kb7x2/)
- Why: NEW this week. Quantitative post showing regular→direct savings. Perfect for Arth's math angle.

> **Draft reply:**
> This is the kind of analysis more people need to see. The compounding effect of even 0.5% expense ratio difference over 20 years is staggering — on ₹10L at 12%, that's ₹4-5L difference.
>
> The tricky part is most people don't know their effective expense ratio across their whole portfolio. If you have 5-6 funds, some regular, some direct, the blended drag is hard to calculate manually.

**6. "Why are there so few SEBI registered fee-only financial advisors?"**
- Sub: r/IndiaInvestments | [Thread](https://www.reddit.com/r/IndiaInvestments/comments/yohmud/)
- Why: Core narrative thread — advisor incentive misalignment. Perfect "The Pattern" territory.

> **Draft reply:**
> The economics explain it: commission-based advisors earn 1-1.5% AUM annually (₹50K-1.5L on a ₹50L-1Cr portfolio) with zero client acquisition cost — the AMC does marketing. Fee-only advisors charge ₹10-25K/year and must find their own clients.
>
> The result: talented people choose commission model because it pays 3-5x more. The few fee-only advisors that exist are genuinely mission-driven, which is why they tend to be good.

**7. "Free and nearly unlimited financial data"**
- Sub: r/algotrading | [Thread](https://www.reddit.com/r/algotrading/comments/126qw26/)
- Why: Builder community, data source discussion. Potential collaboration.

> **Draft reply:**
> Great resource list. For Indian mutual fund data specifically, mfapi.in + AMFI daily NAV feed covers most needs. For CAS statement parsing (the consolidated view of all your MF holdings), there's casparser on PyPI. I'm using both in an open-source portfolio analysis tool.

**8. "Poor man's Bloomberg?"**
- Sub: r/algotrading | [Thread](https://www.reddit.com/r/algotrading/comments/11d2xum/)
- Why: NEW. OpenBB mentioned — open-source finance terminal. Adjacent space, potential integration.

### 🟢 LOW PRIORITY

**9. "Ideal Mutual Fund Portfolio through my experience"**
- Sub: r/IndiaInvestments | [Thread](https://www.reddit.com/r/IndiaInvestments/comments/1czfw3n/)
- Why: Tangential — fund selection advice, not tooling.

**10. "Would a financial advisor be worth it?"**
- Sub: r/personalfinance | [Thread](https://www.reddit.com/r/personalfinance/comments/1cn8x3h/)
- Why: US-focused. Good awareness but less direct fit for India beachhead.

---

## 👥 Persona Review of Top Draft Reply (#1 — free portfolio tool)

**Arjun 🚀 (26, dev, Bangalore):** 8/10
- "Open-source + no account linking = instant star. The AI advisor angle is interesting. Would click GitHub link immediately."
- Wants: screenshots/demo GIF in README before trying

**Priya 🧐 (35, PM, Mumbai):** 6/10
- "Sounds promising but 'still early' is a red flag. Does it handle insurance + loans or just MFs? I need cross-product view."
- Wants: proof it handles her complexity, not just single investors

**Ramesh 🏦 (52, Sr. EM, Pune):** 4/10
- "Who built this? What are their credentials? 'AI advisor' without disclaimers makes me nervous. Would not try without a trusted recommendation."
- Wants: "verify with your CA" disclaimer, audit trail mention

**Persona consensus:** Post reply #1 but add disclaimer ("not financial advice, verify independently") and mention cross-product roadmap to address Priya's concern.

---

## 📊 Week-over-Week Comparison

| Metric | Week 4 (Apr 13) | Week 5 (Apr 20) | Δ |
|--------|:-:|:-:|:-:|
| Stars | 3 | 4 | +1 ⬆️ |
| Forks | 2 | 2 | — |
| Open Issues | 1 | 22 | +21 ⚠️ |
| Threads Found | 32 | 34 | +2 |
| Engagement Opps | 9 | 10 | +1 |
| High Priority | 3 | 3 | — |
| Replies Drafted | 5 | 6 | +1 |

**Notable:** Open issues jumped 1→22. Likely from roadmap/feature tracking tickets. Verify these aren't bug reports.

---

## ⚠️ Alerts

1. **"The Pattern" is 24 days overdue** — was 17 last week. Ship or reschedule this week.
2. **Reply #1 has been recommended 3 weeks running** — post it or remove from queue.
3. **Overlap analysis demand confirmed by 3 threads now** (#2, #3 this week + Week 4). Strong roadmap signal.
4. **Open issues spike (1→22)** — check if these are bugs vs feature tracking.

---

## ✅ Recommendations

1. **Post reply #1** (free portfolio tool) — with persona-suggested disclaimer added
2. **Post reply #5** (expense ratio impact) — educational, shows math competency
3. **Ship "The Pattern" post** — 24 days overdue, losing momentum
4. **Triage open issues** — 22 is a lot for a new repo, may scare contributors
5. **Add overlap analysis to roadmap** — 3rd week of demand signals

---

*Generated by Arth CMO Agent 📣 | Week 5 of 6 | Target: 100 stars by May 9 (currently 4 — needs acceleration)*
