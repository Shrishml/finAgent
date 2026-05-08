---
platform: reddit
subreddit: r/IndiaInvestments
arc: 3-post series
position: 2 of 3 — "The Math"
flair: Mutual Funds
status: draft
---

# I ran XIRR on every fund in my portfolio. The numbers don't match what my apps show me.

Last week I posted about the [expense ratio drag between regular and direct plans](). That rabbit hole went deeper than I expected.

I export my CAMS statement every quarter. This time, instead of glancing at the summary, I actually computed returns at the transaction level — every SIP, every lump sum, every switch. Here's what I found.

---

## 1. Your "returns" number is probably wrong

Most apps show you absolute returns or trailing CAGR. Neither accounts for *when* you invested. If you did a big lump sum right before a crash and kept SIP-ing through recovery, your actual return is very different from what the fund's 3Y CAGR says.

XIRR (Extended Internal Rate of Return) weights every transaction by date. Here's what it looked like for my top 5 holdings:

| Fund | App shows (abs.) | Fund 3Y CAGR | My actual XIRR |
|------|----------------:|-------------:|--------------:|
| Large cap fund A | +38.2% | 14.1% | 11.3% |
| Flexi cap fund B | +29.7% | 12.8% | 9.1% |
| Mid cap fund C | +51.4% | 18.2% | 16.7% |
| ELSS fund D | +22.1% | 11.5% | 8.4% |
| Small cap fund E | +64.3% | 22.1% | 19.8% |

Fund C and E look great in absolute terms. But my XIRR tells me I timed my entries poorly on A and D — the gap between fund CAGR and my XIRR is 3-4%. That's not the fund underperforming. That's *me* underperforming.

**Takeaway:** If you're not computing XIRR per fund using your actual transaction dates, you're looking at someone else's returns, not yours.

---

## 2. I accidentally own the same stocks three times

I always thought I was "diversified" — large cap, flexi cap, mid cap, ELSS, small cap. Five funds, five categories. Solid, right?

Then I pulled the category breakdown:

| Category | No. of funds | % of portfolio |
|----------|------------:|--------------:|
| Large Cap | 3 | 52% |
| Mid Cap | 2 | 28% |
| Small Cap | 1 | 20% |

Wait — three large cap funds? I only picked *one* large cap fund.

Turns out my flexi cap is 65% large cap. My ELSS is 80% large cap. So my "diversified" portfolio is actually a large cap portfolio with some mid/small cap seasoning. The overlap in top 10 holdings across these three funds was ~60%.

I was paying three expense ratios for essentially the same exposure.

---

## 3. My portfolio vs just buying Nifty 50

This one hurt. I compared my portfolio's money-weighted return against what I'd have earned putting the exact same amounts on the exact same dates into a Nifty 50 index fund:

| | My portfolio | Nifty 50 (same cashflows) |
|--|------------:|--------------------------:|
| XIRR | 12.4% | 13.1% |
| Total invested | ₹8.2L | ₹8.2L |
| Current value | ₹11.1L | ₹11.4L |
| Difference | — | +₹30K |

I spent hours researching funds, paid higher expense ratios for "active management," and ended up 0.7% behind a single index fund. The ₹30K gap isn't huge in absolute terms, but the trend line is diverging — the longer I hold, the wider that gap gets.

**The kicker:** If I'd gone with a Nifty 50 index fund at 0.1% expense ratio instead of my average 0.65%, that's another ₹4-5K/year saved on my corpus. Small amounts that compound into real money.

---

## What I'm doing about it

I've started building a spreadsheet that automates this — pull CAMS data, compute XIRR per fund, flag category overlaps, compare against benchmarks. It's grown beyond a spreadsheet at this point.

The exercise was humbling. I thought I was a reasonably informed investor. Turns out I was making decisions based on the wrong numbers, had fake diversification, and was underperforming a passive index.

**Has anyone else done this kind of deep analysis on their own portfolio?** I'm curious whether the XIRR gap (your return vs fund return) is common, or if I'm just bad at timing.

I'll share what the full analysis looks like in a follow-up post if there's interest.

---

**TL;DR:** Exported my CAMS statement, computed XIRR per fund (very different from what apps show), discovered I accidentally hold 3 large-cap funds disguised as different categories, and my entire portfolio underperforms Nifty 50 on a money-weighted basis. Uncomfortable but useful numbers.
