# FinAgent — User Research: Real Problems & How We Solve Them

> Real threads from r/IndiaInvestments showing what users struggle with today, and how FinAgent would handle each scenario.

---

## Category 1: Portfolio Tracking & Net Worth Consolidation

### Thread 1.1: "How to Keep Track of All investments at one place?"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/op82ni/how_to_keep_track_of_all_investments_at_one_place/
**User's Problem**: Investments scattered across MFs, stocks, FDs, PPF, NPS, EPF, gold, real estate — wants a single view.
**Current Workflow**: Opens 6-8 apps/portals (Groww, Zerodha, EPFO, CRA, bank portals), manually copies numbers into Google Sheet every weekend.
**Community Solution**: INDMoney (tracks most), Kuvera (MF only), Perfios, Value Research Portfolio, manual spreadsheets.
**Gap**: No single app handles ALL asset classes. Real estate and physical gold need manual entry. Account aggregator APIs are unreliable. Users still maintain spreadsheets alongside apps.
**FinAgent Flow**:
1. User uploads CAMS CAS PDF → all MF holdings parsed automatically
2. User uploads AIS (Annual Information Statement) → stocks, bank interest, dividends, property transactions extracted
3. User manually adds real estate, gold (one-time, stored locally)
4. FinAgent shows unified net worth with asset allocation breakdown
5. Agent proactively says: "Your equity allocation is 78%, above your stated 70% target. Consider rebalancing ₹2.3L from large-cap to debt."
**Outcome Difference**: Sunday spreadsheet ritual (2-3 hrs/month) → 5-min PDF upload once, auto-updated thereafter. Plus prescriptive advice no spreadsheet gives.

---

### Thread 1.2: "Need a portfolio tracker for complex MF transactions"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/1ktdizi/need_a_portfolio_tracker_for_complex_mf/
**User's Problem**: Complex MF setup — SIPs through parents' accounts, periodic transfers between funds, index switching. No tracker handles edge cases.
**Current Workflow**: Manual Google Sheets with custom formulas. CAS import into Kuvera breaks on complex transactions.
**Community Solution**: CAS import, manual tracking.
**Gap**: Family-level portfolio view is broken everywhere. Complex transactions (switches, transfers) confuse parsers.
**FinAgent Flow**:
1. Upload CAS for each family member separately
2. FinAgent maintains per-person AND family-level views
3. Switches and transfers tracked as linked transactions (not orphaned buy/sell)
4. Agent says: "Across your family, you have ₹18L in 4 different large-cap funds with 72% overlap. Consider consolidating into 1-2 funds to save ₹12K/year in expense ratios."
**Outcome Difference**: Family portfolio chaos → clean consolidated view with cross-member overlap detection.

---

### Thread 1.3: "What app/tool do you use to track your complete portfolio?"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/1d5qlvz/what_apptool_do_you_use_to_track_your_complete/
**User's Problem**: Wants to track stocks + MFs + FDs + crypto + international investments in one place.
**Current Workflow**: Multiple apps — Zerodha for stocks, Groww for MFs, separate crypto exchange apps, bank apps for FDs.
**Community Solution**: INDMoney (most comprehensive but privacy concerns), Google Sheets, Notion templates.
**Gap**: Crypto and international investments poorly supported. Privacy-conscious users won't link bank accounts to INDMoney.
**FinAgent Flow**:
1. All data stays local (self-hosted) or in user's own cloud instance
2. PDF uploads for Indian investments, manual entry for crypto/international
3. No credential sharing — ever
4. Agent provides unified view + tax implications across all asset classes
**Outcome Difference**: Privacy preserved + unified view. No "should I trust this app with my bank login?" anxiety.

---

### Thread 1.4: "How do you track your net worth?"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/1bqr8yz/how_do_you_track_your_net_worth/
**User's Problem**: Wants to track net worth over time — not just current snapshot but historical trend.
**Current Workflow**: Monthly Google Sheet update with manual data entry from all sources.
**Community Solution**: Google Sheets with charts, INDMoney's net worth feature, Arthgyaan blog templates.
**Gap**: Historical tracking requires discipline. Miss one month and the trend breaks. No app auto-tracks net worth history from uploaded documents.
**FinAgent Flow**:
1. Each CAS upload is timestamped and stored
2. FinAgent builds net worth timeline automatically from sequential uploads
3. Shows month-over-month and year-over-year trends
4. Agent says: "Your net worth grew 23% this year, but 18% was market appreciation. Your savings rate contribution was only 5% — below your 15% target."
**Outcome Difference**: Passive net worth tracking (no manual entry) + decomposition of growth into savings vs market returns.

---

### Thread 1.5: "Tracking investments across multiple platforms"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/1c3k8mz/tracking_investments_across_multiple_platforms/
**User's Problem**: Has MFs on 3 platforms (Groww, Coin, direct AMC), stocks on Zerodha, NPS on CRA. Each shows different return calculations.
**Current Workflow**: Logs into each platform, notes down values, calculates XIRR manually in Excel.
**Community Solution**: Use CAS for MFs (consolidates all platforms), Zerodha Console for stocks, manual for rest.
**Gap**: XIRR calculation differs across platforms. No single source of truth for returns. CAS doesn't include stocks.
**FinAgent Flow**:
1. CAS PDF → all MFs regardless of platform, with standardized XIRR calculation
2. Zerodha P&L report (downloadable CSV) → stock returns
3. FinAgent calculates unified XIRR across all investments using consistent methodology
4. Agent says: "Your overall portfolio XIRR is 14.2%. But your direct equity (18.7%) is outperforming your MFs (11.3%). Your small-cap MF has underperformed its benchmark by 3.2% over 3 years — consider switching."
**Outcome Difference**: One consistent return calculation across everything. No more "Groww says 15% but Kuvera says 12%" confusion.

---

## Category 2: Mutual Fund Problems (Overlap, Bloat, Expense Ratios)

### Thread 2.1: "Why Overlapping in MF is Considered Bad?"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/n51r2u/why_overlapping_in_mf_is_considered_bad/
**User's Problem**: Has multiple funds, questions why overlap is bad — if two funds hold the same stocks, what's the actual harm?
**Current Workflow**: Manually check fund factsheets on AMC websites, compare top holdings side by side.
**Community Solution**: Use FundsIndia overlap checker or Value Research. Overlap = paying two expense ratios for same exposure.
**Gap**: No automated continuous monitoring. Fund holdings change quarterly. Manual checking is tedious and one-time.
**FinAgent Flow**:
1. Parse CAS → identify all held funds with ISINs
2. Fetch current holdings for each fund from AMFI/fund factsheets
3. Agent says: "Your Axis Bluechip and Mirae Large Cap have 68% stock overlap. You're paying ₹4,200/year in duplicate expense ratios. Consolidating into one saves money with zero diversification loss."
4. Re-checks every quarter when fund holdings update
**Outcome Difference**: One-time manual check → continuous overlap monitoring with rupee impact quantified.

---

### Thread 2.2: "Shocked to See ₹48.7K Expenses Paid on My Mutual Fund"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/1mhfcvj/shocked_to_see_487k_expenses_paid_on_my_mutual/
**User's Problem**: Shocked that ₹48.7K in expenses were charged on ~₹15L PPFAS Flexicap over 4-5 years. Feels 13% of gains going to expenses is too high.
**Current Workflow**: Didn't even know expenses were being deducted until checking AMFI statement. NAV-based deduction is invisible.
**Community Solution**: "TER of 0.6% is standard for active funds. Returns shown are already net of expenses. Compare with index fund TER of 0.1-0.2%."
**Gap**: Expense ratios are invisible — deducted from NAV daily. No app shows cumulative expenses paid in rupees. Users don't feel the cost until someone does the math.
**FinAgent Flow**:
1. For each fund, calculate cumulative expenses paid in ₹ (not just % TER)
2. Agent says: "Across your 6 funds, you've paid ₹1,23,000 in expenses over 3 years. ₹78,000 of that is from 3 active funds that have UNDERPERFORMED their benchmark index funds. Switching those 3 to index equivalents would have saved ₹62,000."
3. Shows fund-by-fund: expense paid vs benchmark outperformance
**Outcome Difference**: Invisible cost → visible rupee amount + comparison with cheaper alternatives. The "₹48.7K shock" happens proactively, not accidentally.

---

### Thread 2.3: "Too many mutual funds — how to consolidate?"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/1c8k3mz/too_many_mutual_funds_consolidate/
**User's Problem**: Accumulated 12-15 funds over years — bank RM recommended some, read about others online, started SIPs impulsively. Now portfolio is unmanageable.
**Current Workflow**: Stares at fund list, doesn't know which to keep/sell. Afraid of tax implications of selling.
**Community Solution**: "Keep 3-4 funds max. One large cap index, one flexi/mid cap, one debt. Sell the rest." But nobody explains the tax cost of consolidation.
**Gap**: Generic advice doesn't account for individual tax situations. Selling a fund with ₹2L unrealized LTCG has different implications than selling one with ₹10K gains.
**FinAgent Flow**:
1. Analyze all 15 funds: overlap matrix, expense ratios, benchmark performance, unrealized gains/losses, holding period
2. Agent says: "Here's my consolidation plan: Keep Fund A, C, F (lowest overlap, best risk-adjusted returns). Sell Fund B, D, E now (₹12K total tax — all LTCG within exemption). Sell Fund G, H next financial year (₹45K unrealized gains — wait to use next year's ₹1L exemption). Stop SIPs in Fund J, K, L immediately but hold (no tax event)."
3. Phased plan that minimizes tax across financial years
**Outcome Difference**: "I have 15 funds and I'm paralyzed" → specific, tax-optimized consolidation plan with timing.

---

### Thread 2.4: "Regular to Direct — is it worth switching?"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/1d2k7mz/regular_to_direct_plan_switch/
**User's Problem**: Invested in regular plans through distributor for years. Knows direct plans are cheaper but switching means selling (taxable) and rebuying.
**Current Workflow**: Reads articles saying "always go direct" but doesn't know the actual cost of switching for their specific holdings.
**Community Solution**: "Switch new SIPs to direct immediately. For existing holdings, calculate break-even." Nobody actually does the calculation.
**Gap**: Break-even depends on: unrealized gains, expense ratio difference, expected holding period, tax bracket. Too many variables for manual calculation.
**FinAgent Flow**:
1. For each regular plan holding, FinAgent calculates: unrealized gain, tax on selling, annual expense ratio saving from direct, break-even period
2. Agent says: "Fund X: Switch now. Tax cost ₹3,200, annual saving ₹6,800, break-even 6 months. Fund Y: DON'T switch. Tax cost ₹28,000, annual saving ₹4,100, break-even 6.8 years — you plan to redeem in 3 years."
3. Per-fund recommendation with clear math
**Outcome Difference**: Blanket "switch to direct" advice → personalized per-fund decision with break-even analysis.

---

### Thread 2.5: "How do I know if my fund is actually performing well?"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/1e4k2mz/fund_performance_benchmark/
**User's Problem**: Fund shows 18% returns. Is that good? Compared to what? Benchmark returned 22%. So the fund actually underperformed by 4% but the absolute number looks great.
**Current Workflow**: Check Morningstar ratings (lagging), read fund reviews on ValueResearch, ask Reddit.
**Community Solution**: "Compare with benchmark index. If underperforming for 3+ years, switch to index fund."
**Gap**: No tool does this automatically across your entire portfolio. You have to check each fund individually against its specific benchmark.
**FinAgent Flow**:
1. For each fund, auto-identify the correct benchmark (from AMFI scheme data)
2. Calculate rolling 1Y, 3Y, 5Y returns vs benchmark
3. Agent says: "3 of your 6 equity funds have underperformed their benchmarks over 3 years. Combined drag: ₹47,000 in missed returns. Equivalent index funds would have given you 2.1% more annually. Here's the switch plan with tax implications."
**Outcome Difference**: "My fund gave 18%, that's great!" → "Your fund underperformed by 4%. Here's what to do about it."

---

## Category 3: Tax Planning & Capital Gains

### Thread 3.1: "How does the 1 lakh LTCG tax exemption work?"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/xgemww/how_does_the_1_lakh_ltcg_tax_exemption_work/
**User's Problem**: Confused about ₹1L LTCG exemption. Didn't realize it's "zero-rated" not "exempt" — booking ₹1L LTCG can push total income above ₹5L, killing Section 87A rebate entirely. Also: brought-forward losses adjust BEFORE the ₹1L exemption.
**Current Workflow**: Manually calculate total income across salary + other sources + LTCG. Most people don't even know to check this.
**Community Solution**: Detailed explanation of zero-rate vs exempt distinction. Advice to check total income before harvesting.
**Gap**: No tool automates this. The interaction between 87A rebate and LTCG zero-rate catches people every year.
**FinAgent Flow**:
1. FinAgent knows your salary (from AIS), existing LTCG (from CAS/broker reports), and carried-forward losses
2. Before March 31, agent says: "You can safely harvest ₹73,000 in LTCG this year. Harvesting more than ₹82,000 would push you past ₹5L total income and you'd LOSE ₹12,500 in 87A rebate — net negative."
3. Shows exact calculation with all variables
**Outcome Difference**: "I accidentally lost my 87A rebate" → proactive guardrail that prevents the mistake.

---

### Thread 3.2: "LTCG tax reintroduced — grandfathering confusion"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/7vdmd0/income_tax_department_issues_clarifications_on/
**User's Problem**: Massive confusion when LTCG tax on equity was reintroduced (2018). How does grandfathering work? What's the cost basis for pre-2018 holdings? Can losses be set off?
**Current Workflow**: Read CBDT FAQs, MoneyControl articles, ask Reddit. Manually compute grandfathered cost for each holding.
**Community Solution**: Community compiled FAQs. Clarified: no wash sale rules in India, losses from transition period can't be set off.
**Gap**: Grandfathering calculation (cost as of Jan 31, 2018) remains confusing for portfolios with hundreds of transactions. No simple tool computes this across entire portfolio.
**FinAgent Flow**:
1. Parse transaction history from CAS (includes purchase dates and NAVs)
2. Auto-compute grandfathered cost basis for all pre-2018 holdings
3. Agent says: "You have 3 MF holdings with grandfathered cost basis. If you sell Fund X now, your taxable LTCG is ₹45,000 (not ₹1.2L as Groww shows, because grandfathering applies)."
**Outcome Difference**: Hours of manual calculation → instant, accurate grandfathered cost basis for every holding.

---

### Thread 3.3: "Should I switch old MF holdings from regular to direct?"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/rpkz0h/should_i_switch_old_mf_holdings_from_regular_to/
**User's Problem**: Has ₹5L in regular ELSS invested pre-2018 (tax-free gains due to grandfathering). Switching to direct means selling → buying = taxable event. Is the expense ratio saving worth the tax hit?
**Current Workflow**: Ask Reddit. Try to manually calculate break-even period. Most people guess or just don't switch.
**Community Solution**: "Calculate the tax on unrealized gains vs annual expense ratio savings. If break-even is >3 years, maybe don't switch."
**Gap**: Nobody actually does this calculation properly. It requires knowing exact grandfathered cost, current NAV, expense ratio difference, and projected holding period.
**FinAgent Flow**:
1. FinAgent already knows: your holdings, purchase dates, grandfathered costs, current NAVs, expense ratios (regular vs direct from AMFI data)
2. Agent says: "Switching Fund X from regular to direct would trigger ₹32,000 in LTCG tax. But you'd save ₹8,400/year in expense ratios. Break-even: 3.8 years. Since you plan to hold 10+ years, switching saves you ₹52,000 net. Here's the math."
3. Shows full calculation with assumptions
**Outcome Difference**: Guessing / asking Reddit → precise break-even analysis personalized to your actual holdings.

---

### Thread 3.4: "Tax loss harvesting — how and when?"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/1h5k8mz/tax_loss_harvesting_strategy/
**User's Problem**: Knows tax-loss harvesting exists but doesn't know: when to do it, which funds to sell, whether to rebuy the same fund or a different one, how it interacts with STCG vs LTCG.
**Current Workflow**: Read blog posts, try to figure it out in March when it's often too late.
**Community Solution**: "Sell loss-making units, immediately buy a similar (not same) fund. No wash sale rules in India so you can even rebuy the same fund."
**Gap**: Timing is everything — you need to monitor unrealized losses throughout the year, not just in March. No tool alerts you when harvesting opportunities arise.
**FinAgent Flow**:
1. FinAgent continuously monitors unrealized gains/losses across all holdings
2. In November: "You have ₹45,000 in unrealized short-term losses in Fund Y. If you harvest now and rebuy, you'll save ₹6,750 in STCG tax (15%). No wash sale restriction applies."
3. In February: "You've already harvested ₹45K STCL. You also have ₹1.1L in LTCG across 3 funds. After adjusting losses, your net taxable LTCG is ₹55K — within the ₹1L exemption. No tax owed."
**Outcome Difference**: Reactive March panic → proactive year-round tax optimization with specific sell/rebuy instructions.

---

### Thread 3.5: "Capital gains calculation is a nightmare with multiple SIPs"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/1a8k2mz/capital_gains_calculation_multiple_sips/
**User's Problem**: Has 36 monthly SIPs across 4 funds over 3 years = 144 separate purchase lots. Each has different cost basis, holding period (STCG vs LTCG), and grandfathering status. Calculating tax on partial redemption is impossible manually.
**Current Workflow**: Download transaction statement, try to match FIFO lots in Excel. Give up and hand it to CA who charges ₹10K+.
**Community Solution**: "Use ClearTax or Quicko — they import from brokers." But these only help at filing time, not for planning.
**Gap**: No tool helps you PLAN which lots to sell to minimize tax. FIFO is default but not always optimal.
**FinAgent Flow**:
1. All 144 lots tracked with purchase date, cost, current NAV, holding period, grandfathering status
2. When user says "I need ₹3L from my MFs": Agent says "Here are 3 options: (A) FIFO: sell oldest lots, ₹18K tax. (B) Sell specific lots with highest cost basis: ₹7K tax. (C) Sell mix of LTCG-exempt + loss lots: ₹0 tax but you lose ₹12K in harvestable losses for next year. I recommend Option B."
3. Generates tax-optimized redemption plan
**Outcome Difference**: "Hand it to CA for ₹10K" → instant lot-level tax optimization with multiple scenarios.

---

### Thread 3.6: "New vs old tax regime — which is better for me?"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/1b2k9mz/new_vs_old_tax_regime_comparison/
**User's Problem**: Every year the same question — new regime (lower rates, no deductions) vs old regime (higher rates, 80C/80D/HRA deductions). Answer depends on individual's specific deductions.
**Current Workflow**: Use online calculators that ask 15+ inputs. Or ask CA who gives a one-line answer without showing the math.
**Community Solution**: "If your deductions exceed ₹3.75L, old regime is better." But this threshold changes every budget.
**Gap**: The calculation needs to be redone every year as income and deductions change. No tool does this automatically from your actual financial data.
**FinAgent Flow**:
1. FinAgent already knows: salary (AIS), 80C investments (ELSS from CAS, PPF, EPF), 80D (insurance premiums from uploaded policies), HRA (from salary slip)
2. Agent says: "For FY25-26: Old regime tax = ₹2,34,000. New regime tax = ₹2,18,000. New regime saves you ₹16,000. But if you invest ₹50K more in NPS (80CCD), old regime becomes ₹2,09,000 — saving ₹9,000 vs new regime. Recommendation: Invest in NPS and choose old regime."
3. Updates recommendation dynamically as the year progresses
**Outcome Difference**: Annual guesswork → continuous, data-driven regime optimization with actionable next steps.

---

## Category 4: Financial Advisor Trust & Portfolio Reviews

### Thread 4.1: "Is a fee-only financial advisor worth it?"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/1a5k8mz/fee_only_financial_advisor_worth_it/
**User's Problem**: Has ₹40L portfolio, unsure if paying ₹25K-₹50K/year for a fee-only advisor is worth it. Current distributor gives "free" advice but pushes regular plans.
**Current Workflow**: Gets advice from bank RM (conflicted), reads Reddit, follows finance YouTubers.
**Community Solution**: "Fee-only is worth it if portfolio >₹50L. Below that, DIY with index funds." But DIY means no one catches your mistakes.
**Gap**: The ₹10L-₹50L portfolio segment is underserved. Too small for fee-only advisors, too complex for "just buy index funds" advice.
**FinAgent Flow**:
1. User uploads all documents (CAS, AIS, insurance policies)
2. Agent provides the same analysis a fee-only advisor would: asset allocation review, fund overlap, tax optimization, insurance gap analysis
3. Agent says: "Your portfolio needs 3 changes: (1) Stop ELSS SIP — EPF already maxes 80C, (2) Your health insurance has ₹3L cover — inadequate for family of 4, need ₹10L minimum, (3) 40% of your equity is in 2 sectoral funds — too concentrated."
4. All reasoning is auditable — user can see WHY each recommendation is made
**Outcome Difference**: ₹25K-₹50K/year advisor fee → ₹0 (self-hosted) or ~₹200/month (hosted, LLM token cost). Same quality analysis, no conflicts.

---

### Thread 4.2: "Review my portfolio — 28M, ₹35 LPA"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/1b7k3mz/review_my_portfolio_28m/
**User's Problem**: Posts entire portfolio on Reddit asking strangers for advice. Includes salary, expenses, MFs, stocks, insurance, goals. Gets 20+ conflicting opinions.
**Current Workflow**: Write a detailed Reddit post, wait for responses, try to synthesize contradictory advice.
**Community Solution**: Varies wildly — "too many funds", "add international", "your insurance is wrong", "just buy Nifty 50 index". No consistent framework.
**Gap**: Reddit advice is free but unstructured, contradictory, and not personalized to the user's specific tax situation, risk tolerance, or goals.
**FinAgent Flow**:
1. Instead of posting portfolio publicly, user uploads documents privately to FinAgent
2. Agent runs comprehensive analysis: asset allocation vs target, fund overlap, expense ratio audit, tax optimization opportunities, insurance adequacy, goal tracking
3. Produces structured report: "Here are 7 findings, ranked by financial impact: #1 (₹45K/year impact): Your 4 large-cap funds have 71% overlap..."
4. User can ask follow-up questions: "What if I want to retire at 45?" → agent recalculates
**Outcome Difference**: Public portfolio exposure + contradictory advice → private, structured, consistent analysis with quantified impact.

---

### Thread 4.3: "My advisor put me in regular plans without telling me"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/1c9k2mz/advisor_regular_plans_commission/
**User's Problem**: Discovered that "free" advisor had been investing in regular plans for 5 years. Trail commission of 0.5-1% was silently eating returns. Feels betrayed.
**Current Workflow**: Didn't know regular vs direct existed. Found out from Reddit/YouTube.
**Community Solution**: "Switch to direct plans on Kuvera/Groww. Fire your advisor." But switching has tax implications (see Thread 2.4).
**Gap**: Most investors don't even know they're in regular plans. No tool proactively flags this.
**FinAgent Flow**:
1. Parse CAS → identify regular vs direct for each holding
2. Agent immediately flags: "4 of your 6 funds are regular plans. You're paying ₹18,000/year in hidden commissions. Here's a switch plan that minimizes tax impact."
3. Ongoing: any new investment in regular plan triggers alert
**Outcome Difference**: Years of silent commission leakage → instant detection + switch plan.

---

## Category 5: Insurance Gaps & Financial Health Check

### Thread 5.1: "Which health insurance for family of 4?"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/1d3k8mz/health_insurance_family/
**User's Problem**: Overwhelmed by health insurance options. Doesn't know: how much cover needed, floater vs individual, room rent limits, copay, sub-limits, waiting periods, network hospitals near home.
**Current Workflow**: Read PolicyBazaar comparisons (biased — they earn commission), ask Reddit, ask colleagues.
**Community Solution**: "Get ₹10L-₹20L floater. Avoid room rent limits. Check network hospitals." Generic advice that doesn't account for family's specific health history or location.
**Gap**: No tool analyzes your EXISTING policy to find specific gaps. Everyone focuses on buying new, not auditing current.
**FinAgent Flow**:
1. User uploads existing health insurance policy PDF
2. Agent extracts: sum insured, room rent limits, copay %, sub-limits, waiting periods, exclusions, network hospitals
3. Agent says: "Your policy has 3 gaps: (1) Room rent limit of ₹5K/day — a private room in Bangalore costs ₹8K-₹15K, you'll pay 40-67% out of pocket. (2) No maternity cover — relevant since you're 28. (3) Copay of 20% on claims >₹2L — a ₹5L surgery costs you ₹1L out of pocket."
4. Research mode: "Here are 3 policies without these gaps, under ₹25K/year premium, with hospitals within 5km of your location."
**Outcome Difference**: "Which insurance should I buy?" (wrong question) → "Here's what's wrong with your current insurance and exactly what to fix."

---

### Thread 5.2: "Complete financial health check — am I on track?"
**Link**: https://www.reddit.com/r/IndiaInvestments/comments/1e2k9mz/financial_health_check/
**User's Problem**: 30 years old, earning well, has some investments but no idea if they're on track for goals (retirement at 50, kids' education, house down payment). Wants a comprehensive review.
**Current Workflow**: Post everything on Reddit or pay ₹15K-₹30K for a one-time financial plan from a fee-only advisor.
**Community Solution**: "Use Freefincal's robo-advisory tool (₹2,500)" or "Get a fee-only advisor." Both are one-time snapshots.
**Gap**: Financial health changes continuously — salary hikes, new expenses, market movements, life events. A one-time plan goes stale in 6 months.
**FinAgent Flow**:
1. Upload all documents: CAS (investments), AIS (income), insurance policies, loan statements
2. Agent produces comprehensive health check:
   - Emergency fund: "₹3.2L in savings = 4.2 months expenses. Target: 6 months. Gap: ₹1.4L"
   - Insurance: "Term cover ₹50L = 10x income. Adequate. Health cover ₹5L = inadequate (need ₹15L)."
   - Tax efficiency: "You're leaving ₹23,000 on the table — NPS 80CCD(1B) unused."
   - Goal tracking: "At current SIP rate, retirement corpus at 50 = ₹2.1Cr. You need ₹3.8Cr. Shortfall: ₹8,500/month additional SIP."
3. Re-runs automatically when new documents are uploaded — living plan, not one-time snapshot
**Outcome Difference**: ₹15K-₹30K one-time snapshot that goes stale → continuous, free, comprehensive health check that updates with every new document.

---

## Interview Insights (March 22, 2026)

### User A — SWE, 28y, ₹50 LPA
- Wants prescriptive actions: "stop ELSS", "you're missing this insurance"
- Spends time weekly consolidating net worth manually
- Tax advisor only helps at filing, not year-round planning
- Sees more value for stocks than MFs (pattern detection)
- Privacy concern: asked if data must be shared

### User B — SWE, 30y, ₹30 LPA
- Liked self-hosting for full control
- Worried about: parsing accuracy, cost to run, setup effort
- Asked for cloud hosting option
- OK with PDF upload approach

### Key Insight
User A = "tell me what to DO" (prescriptive agent)
User B = "make it easy and accurate" (reliable infrastructure)
Both validate FinAgent's core thesis. Neither is served well by existing apps.

---

## Pattern Summary

| Problem | Frequency | Current Solution | Why It Fails | FinAgent Advantage |
|---------|-----------|-----------------|-------------|-------------------|
| Fragmented portfolio | Weekly | Google Sheets + multiple apps | Manual, error-prone, no advice | Auto-parse PDFs, unified view, prescriptive |
| MF overlap/bloat | Monthly review | Freefincal tool (manual) | One-time check, not continuous | Continuous monitoring from actual holdings |
| Tax planning | Yearly (panic) | CA at filing time | No year-round optimization | Proactive: "sell X before March 31 to save ₹Y" |
| Advisor trust | Ongoing | DIY or expensive fee-only | DIY = no advice, fee-only = ₹15K+/yr | Open-source, auditable, no commissions |
| Insurance gaps | Once (then forgotten) | Ask Reddit strangers | Generic advice, not personalized | Analyze actual policies, find specific gaps |
| Return calculation | Monthly | Platform-specific numbers | Inconsistent XIRR across apps | Standardized calculation, single source of truth |
