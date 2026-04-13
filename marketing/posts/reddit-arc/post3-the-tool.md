---
post: 3 of 3
arc: "The Pattern → The Math → The Tool"
subreddit: r/IndiaInvestments
flair: Discussion
status: draft
created: 2026-04-13
author_voice: fellow investor who built something for themselves
tone: show-don't-tell, humble, feedback-seeking
constraints:
  - no reddit usernames
  - no self-promotion tone
  - must be useful without clicking any link
  - anonymized sample data only
---

# I built an open-source tool that does the portfolio analysis I've been posting about — here's what it found on a sample portfolio

A few weeks ago I shared my analysis on how expense ratios silently compound against us — the difference between a 0.3% and 1.8% fund over 20 years was ₹8.4L on a ₹50K SIP. Then I went deeper into XIRR calculations, category overlap, and benchmark comparisons, and realized I was spending hours in spreadsheets every quarter doing the same thing.

So I built a tool to automate all of it. It's open source, free, and I want your honest feedback on whether it's actually useful or if I'm solving a problem only I have.

## What it actually does (sample output)

I ran it on an anonymized portfolio (8 funds, ~₹32L invested over 4 years). Here's what it spit out:

**Portfolio XIRR: 14.2%** (vs Nifty 50 XIRR of 12.8% over same period)

| Fund | Category | XIRR | Expense Ratio | Overlap Flag |
|------|----------|------|---------------|-------------|
| Large Cap Fund - Direct | Large Cap | 13.1% | 0.58% | ⚠️ 72% overlap with Index Fund |
| Nifty 50 Index Fund - Direct | Large Cap | 12.9% | 0.20% | — |
| Flexi Cap Fund - Direct | Flexi Cap | 16.4% | 0.68% | — |
| Mid Cap Fund - Direct | Mid Cap | 18.7% | 0.42% | — |
| Small Cap Fund - Direct | Small Cap | 22.1% | 0.54% | — |
| ELSS Fund - Regular | ELSS | 11.3% | 1.72% | ⚠️ Regular plan |
| Short Duration Fund - Direct | Debt | 6.8% | 0.32% | ⚠️ 68% overlap with Corp Bond |
| Corporate Bond Fund - Direct | Debt | 7.1% | 0.38% | ⚠️ 68% overlap with Short Duration |

**AI-generated insights (3 of 10 shown):**

> *"Your Large Cap Fund and Nifty 50 Index Fund have 72% portfolio overlap. The Index Fund delivers nearly identical returns at one-third the expense ratio — the active fund's 0.38% premium isn't earning its keep."*

> *"Your ELSS fund is a Regular plan with a 1.72% expense ratio. The Direct plan equivalent charges 0.68%. On your current ELSS corpus of ₹4.2L, that's roughly ₹4,400/year going to the distributor."*

> *"Your Small Cap allocation (28% of equity) is delivering the highest XIRR at 22.1%, but this concentration means a 30% small-cap correction would drag your overall portfolio down ~8.4%."*

## How it works

1. Upload your CAMS or KFintech consolidated PDF (the one you download from camsonline.com or kfintech.com)
2. It parses every transaction, enriches with AMFI data, calculates per-fund XIRR
3. Runs category breakdown, expense ratio comparison, benchmark overlay (Nifty 50, Midcap, Smallcap)
4. Generates 10 plain-English insights using an LLM — not generic tips, but specific observations about YOUR portfolio

**Privacy:** Your data never leaves your browser/device. No account creation, no linking to brokers, no tracking. The code is on GitHub — you can verify.

## What it does NOT do

- ❌ Does not give buy/sell recommendations
- ❌ Does not predict market movements
- ❌ Does not replace your financial advisor
- ❌ Does not access your demat/trading account

Think of it as a portfolio X-ray — it shows you what's inside, but the treatment decisions are yours.

## Links

- **Live demo:** https://captwist.in (upload a CAMS PDF and see results instantly)
- **GitHub:** https://github.com/Suraj1074/finagent (Python + FastAPI, MIT license)
- **Name:** FinBestie (अर्थमित्र — your financial friend)

## What I'd love feedback on

1. Is the XIRR + benchmark comparison actually useful, or is it just interesting?
2. What's missing? What would make you use this quarterly?
3. Is the CAMS PDF upload flow clear enough, or did you get stuck?
4. Any insights that felt wrong or misleading?

This started as a personal spreadsheet and grew into something I thought others might find useful. Built it over ~3 weeks as a side project. Happy to answer any questions about the methodology or the code.
