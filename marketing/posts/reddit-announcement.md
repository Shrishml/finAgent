# Reddit Post — r/IndiaInvestments
**When to post:** Thursday Mar 27, 7-9 PM IST
**Flair:** Discussion
**Status:** Draft v3

---

**Title:** A friend calculated his LIC policy's actual XIRR. It was 6.5%. His home loan rate is 8.5%. Nobody told him.

---

Last week a friend finally sat down and reverse-calculated the actual return on his LIC endowment policy. The agent had sold it as "3x maturity in 20 years." Sounds impressive until you compute the CAGR — it's ~6.5%.

His home loan interest rate? 8.5%.

He's been servicing 8.5% debt while his "investment" compounds at 6.5%. For years. The agent didn't mention this. The policy document buries it. No app shows these two numbers side by side.

His reaction: *"Agents tell you what you want to hear, not what's actually happening."*

That conversation sent me down a rabbit hole. I went through ~23 threads on this very subreddit (Jan-Mar 2026 bi-weekly advice threads + standalone posts) and categorized roughly 120 questions. Some patterns:

- **46%** are portfolio review / allocation questions
- **13%** are tax confusion (LTCG, 87A, grandfathering)
- **10%** are insurance mis-selling

What struck me is that most of these are **fundamentally computational**. They have correct answers. XIRR of your LIC policy. The ₹ amount (not %) you've paid in MF expense ratios. Whether consolidating your 15 funds triggers ₹3K or ₹30K in tax. The break-even period for switching regular to direct.

But the people selling you products have no incentive to compute these for you. And the free tools that exist don't connect the dots across products — your LIC return vs your loan rate vs what an index fund would've done over the same period.

So I've started building something — very early stage, open source — that just does the honest math:
- Real XIRR/CAGR across products (MFs, insurance, FDs)
- Cumulative expenses in ₹, not hidden in NAV
- Cross-product comparison ("what if this money was in X instead?")
- Runs locally, no data leaves your machine

Nowhere near ready, but architecture is done and I'm starting implementation this week.

**Questions I genuinely want your take on:**

1. My friend's LIC vs home loan situation — is this common, or was he an outlier? How many people here have actually computed their insurance policy's XIRR?

2. If a tool showed you "you've paid ₹1.2L in MF expenses over 3 years, ₹78K of that on funds that underperformed their index" — would you actually act on it?

3. What's the one number about your own finances you suspect is bad but haven't calculated because it's too annoying?

Not linking anything — just want to know if this resonates. Happy to share GitHub if curious.
