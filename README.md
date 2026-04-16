<p align="center">
  <h1 align="center">FinBestie</h1>
  <p align="center"><strong>Your money, your agent, your rules.</strong></p>
  <p align="center">
    <a href="https://captwist.in">Live Demo</a> · <a href="#-quick-start">Local Setup</a> · <a href="./ARCHITECTURE.md">Architecture</a> · <a href="./ROADMAP.md">Roadmap</a>
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-3.11+-blue" alt="Python 3.11+">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
    <img src="https://img.shields.io/badge/status-live-brightgreen" alt="Live">
  </p>
</p>

---

An open-source AI financial agent that works exclusively for **you**. No commissions, no hidden incentives, no conflicts of interest. You employ the agent — not the other way around.

## 🚀 Quick Start

Get FinBestie running locally in under 2 minutes.

### Prerequisites

- Python 3.11+
- An LLM provider (any one of these):
  - [Gemini API key](https://aistudio.google.com/apikey) (free tier works) — set in `config.toml`
  - `kiro-cli`, `claude`, or `gemini` CLI installed locally

### Option A: One-liner (recommended)

```bash
git clone https://github.com/Suraj1074/finagent.git
cd finagent
./start.sh
```

`start.sh` handles everything — creates a virtual environment, installs dependencies, copies default config, and starts the server.

### Option B: Manual setup

```bash
git clone https://github.com/Suraj1074/finagent.git
cd finagent/src

# Create and activate virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .

# Configure
cp config.toml.example config.toml
# Edit config.toml — add your Gemini API key or set default = "auto" for CLI

# Run
python -m finagent.main
```

Open **http://localhost:8000** — you should see the FinBestie dashboard.

### Upload Your First Statement

1. Download your mutual fund statement from [CAMS](https://www.camsonline.com/Investors/Statements/Consolidated-Account-Statement) or [KFintech](https://mfs.kfintech.com/investor/) (PDF format, "Detailed" statement)
2. Click **Review My Portfolio** on the landing page
3. Upload the PDF
4. Within seconds: parsed holdings, live NAV enrichment, portfolio insights, and benchmark comparisons

> 💡 Your data stays on your machine. The PDF is parsed locally, stored in a local SQLite database, and never sent anywhere except to the LLM for analysis.

## The Problem

Every financial app and advisor has a conflict of interest. They recommend products that earn *them* commissions. They show you *their* platform's funds. They can't see your insurance, loans, and investments together — because that would mean admitting their product isn't enough.

**No tool today gives you a single, honest, cross-product view of your finances.**

Your mutual funds don't know about your insurance. Your insurance app doesn't know about your loans. Your tax planner doesn't see any of it. You're left stitching together a financial picture from 5 different apps — each with its own agenda.

## The Solution

FinBestie is an AI agent that:

- **Sees everything** — Upload any financial document (MF statements, insurance policies, loan agreements, tax forms). Each one joins your complete financial picture.
- **Reasons across products** — "Your ELSS is pointless because EPF already maxes Section 80C." No app today can tell you this because no app sees both.
- **Researches on your behalf** — "Find me health insurance without copay under ₹25K/year that covers my pre-existing conditions." The agent searches the market for *you*, not for commission.
- **Is fully open source** — Every recommendation is auditable. No black-box algorithms deciding what's "best" for you.

## How It Works

```
You: Upload CAMS mutual fund statement
FinBestie: Parses 47 holdings, enriches with live NAV data, flags 3 funds
           with expense ratios 2x higher than index alternatives

You: "Should I prepay my home loan or invest more in mutual funds?"
FinBestie: Compares your loan interest rate (8.5%) against your portfolio
           returns (12.3% CAGR), factors in tax benefits on both sides,
           and gives you a clear recommendation with the math shown
```

## What You Get Today

- 📊 **Portfolio Dashboard** — Holdings, allocation breakdown, portfolio growth chart
- 📈 **Returns Analysis** — Per-fund and portfolio-level XIRR, gains tracking
- 🏆 **Benchmark Comparison** — Compare your returns against Nifty 50, Midcap, Smallcap, Gold (money-weighted)
- 💡 **10 AI-Generated Insights** — "What's working" + "Worth a look" grounded in your actual data
- 💬 **AI Chat** — Ask questions about your portfolio in natural language
- 🔐 **Google Sign-In** — Your portfolio is tied to your account, private to you
- 📱 **Responsive UI** — Works on desktop and mobile

## Architecture

FinBestie uses a **domain-rich, adapter-thin** architecture:

- **Domain Agents** — Deep expertise per financial product (mutual funds, insurance, loans, tax)
- **Orchestrator** — Routes questions to the right agent(s), combines cross-product reasoning
- **Connectors** — Pluggable data ingestion (CAMS/KFintech PDFs today, APIs tomorrow)

> 📐 Full architecture: [ARCHITECTURE.md](./ARCHITECTURE.md)

## Configuration

The config file lives at `src/config.toml` (copied from `config.toml.example` on first run):

```toml
[llm]
default = "auto"        # "auto" picks whatever CLI is installed
                        # "gemini", "kiro", "claude", or "api" for explicit choice

[llm.api]
# gemini_key = ""       # needed only if default = "api"

[server]
host = "0.0.0.0"
port = 8000
```

| Setting | What it does |
|---------|-------------|
| `llm.default = "auto"` | Auto-detects installed LLM CLI (kiro-cli, claude, gemini) |
| `llm.default = "api"` | Uses API key from `[llm.api]` section instead of CLI |
| `server.port` | Change the port (default 8000) |

## Project Structure

```
finagent/
├── start.sh                 # One-command setup + launch
├── src/
│   ├── config.toml.example  # Config template
│   ├── pyproject.toml       # Python dependencies
│   ├── finagent/
│   │   ├── main.py          # FastAPI app + routes
│   │   ├── auth.py          # Google OAuth
│   │   ├── config.py        # Config loader
│   │   ├── agents/          # Domain-specific AI agents
│   │   ├── connectors/      # PDF parsers (CAMS, KFintech)
│   │   ├── analytics/       # Returns, benchmarks, insights
│   │   ├── llm/             # LLM provider abstraction
│   │   └── storage/         # SQLite persistence
│   ├── ui/                  # Frontend (HTML + JS + CSS)
│   └── tests/               # pytest suite
└── docs/                    # Research + persona reviews
```

## Current Status

✅ **Live** at [captwist.in](https://captwist.in) — 185+ commits.

| Feature | Status |
|---------|--------|
| Mutual Fund analysis (CAMS/KFintech) | ✅ Live |
| Portfolio dashboard + charts | ✅ Live |
| Benchmark comparison (5 indices) | ✅ Live |
| AI insights engine (10 insights) | ✅ Live |
| AI chat | ✅ Live |
| Google Sign-In | ✅ Live |
| Goal-based planning (8 templates) | ✅ Live |
| Fund allocation per goal | ✅ Live |
| EPF/NPS/Stocks connectors | 🔜 Next |
| Cross-asset unified dashboard | 🔜 Planned |

> See [ROADMAP.md](./ROADMAP.md) for the full plan.

## Contributing

FinBestie is built in public. Contributions welcome:

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Run tests: `cd src && pip install -e ".[dev]" && pytest`
4. Submit a PR

## License

MIT — see [LICENSE](./LICENSE).

---

<p align="center">
  <strong>Try it now:</strong> <a href="https://captwist.in">captwist.in</a> · <strong>Run locally:</strong> <code>./start.sh</code>
</p>
