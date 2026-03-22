# FinAgent

**Your money, your agent, your rules.**

An open-source AI agent that works exclusively for you on all financial matters. No commissions, no hidden incentives, no conflicts of interest. You employ the agent — not the other way around.

## The Problem

Every financial app and advisor has a conflict of interest. They recommend products that earn *them* commissions. They show you *their* platform's funds. They can't see your insurance, loans, and investments together — because that would mean admitting their product isn't enough.

**No tool today gives you a single, honest, cross-product view of your finances.**

Your mutual funds don't know about your insurance. Your insurance app doesn't know about your loans. Your tax planner doesn't see any of it. You're left stitching together a financial picture from 5 different apps — each with its own agenda.

## The Solution

FinAgent is an AI agent that:

- **Sees everything** — Upload any financial document (MF statements, insurance policies, loan agreements, tax forms). Each one joins your complete financial picture.
- **Reasons across products** — "Your ELSS is pointless because EPF already maxes Section 80C." No app today can tell you this because no app sees both.
- **Researches on your behalf** — "Find me health insurance without copay under ₹25K/year that covers my pre-existing conditions." The agent searches the market for *you*, not for commission.
- **Is fully open source** — Every recommendation is auditable. No black-box algorithms deciding what's "best" for you.

## How It Works

```
You: Upload CAMS mutual fund statement
FinAgent: Parses 47 holdings, enriches with live NAV data, flags 3 funds 
          with expense ratios 2x higher than index alternatives

You: "Should I prepay my home loan or invest more in mutual funds?"
FinAgent: Compares your loan interest rate (8.5%) against your portfolio 
          returns (12.3% CAGR), factors in tax benefits on both sides, 
          and gives you a clear recommendation with the math shown
```

## Architecture

FinAgent uses a **domain-rich, adapter-thin** architecture with specialized domain agents:

- **Domain Agents** — Deep expertise per financial product (mutual funds, insurance, loans, tax). Each agent has 3 modes: analyze your data, research the market, and contribute to cross-product reasoning.
- **Orchestrator** — Routes your questions to the right agent(s). For cross-product questions, it combines thin summaries from multiple agents to reason holistically.
- **Connectors** — Pluggable data ingestion (PDFs today, APIs tomorrow, Account Aggregator eventually).

> 📐 Detailed architecture document: [ARCHITECTURE.md](./ARCHITECTURE.md)

## Current Status

🚧 **Early development** — We're building in public. Star the repo to follow along.

**Phase 1 (Now):** Architecture + Mutual Fund domain agent (CAMS PDF parsing, AMFI enrichment, analysis + research modes)

**Phase 2:** Insurance domain agent, more document types (AIS, credit card statements)

**Phase 3:** Broker API integrations (Zerodha, Angel One, Upstox)

**Phase 4:** Account Aggregator integration (RBI-regulated, 272M+ linked accounts)

## Roadmap

See [ROADMAP.md](./ROADMAP.md) for the detailed week-by-week plan.

## Tech Stack

- Python + FastAPI
- LLM-powered reasoning (Gemini Flash for parsing, Claude/GPT for analysis)
- SQLite (local-first, your data stays with you)
- Open-source PDF parsing (`casparser` for Indian MF statements)

## Contributing

We're just getting started. If you're interested in:
- Adding support for financial products in your country
- Building new domain agents
- Improving the reasoning engine

Open an issue or reach out. Architecture doc is the best place to start understanding the system.

## License

[MIT](./LICENSE) — Use it, fork it, build on it. Your finances are your business.

---

*Built by [Suraj Jha](https://www.linkedin.com/in/suraj-jha-profile/) — Software Engineer, 7+ years at Amazon. Building the financial tool I wish existed.*
