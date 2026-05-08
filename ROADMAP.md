# Roadmap

> **FinBestie** — Unified investment tracker for salaried professionals.
> Live at [captwist.in](https://captwist.in) · 185+ commits

---

## ✅ Done

### Mutual Funds (Core)
- [x] CAMS/KFintech PDF parsing + AMFI NAV enrichment
- [x] Portfolio dashboard with holdings, allocation, growth chart
- [x] Per-fund and portfolio XIRR returns
- [x] Benchmark comparison (Nifty 50, Midcap, Smallcap, Gold, Debt)
- [x] 10 AI-generated insights (what's working + worth a look)
- [x] AI chat with portfolio context
- [x] Google Sign-In + per-user data isolation
- [x] Responsive UI (desktop + mobile)
- [x] Google Analytics ([#7](https://github.com/Suraj1074/finagent/issues/7))

### Goal-Based Planning ([#8](https://github.com/Suraj1074/finagent/issues/8)–[#11](https://github.com/Suraj1074/finagent/issues/11))
- [x] Goal data model + SQLite CRUD ([#9](https://github.com/Suraj1074/finagent/issues/9))
- [x] 8 templates: retirement, house, education, car, marriage, emergency, travel, custom ([#10](https://github.com/Suraj1074/finagent/issues/10))
- [x] Progress tracking with projection math (SIP detection, on-track analysis) ([#11](https://github.com/Suraj1074/finagent/issues/11))
- [x] Fund allocation percentages per goal with over-allocation validation
- [x] Goals tab UI with template picker + edit

### Infrastructure
- [x] CI/CD: GitHub Actions auto-deploy dev → beta.captwist.in
- [x] DEV_MODE for autonomous testing (magic cookie auth)
- [x] Demo portfolio for unauthenticated visitors
- [x] One-command local setup (`./start.sh`)

---

## 🔜 Up Next — Unified Investment Tracker ([#12](https://github.com/Suraj1074/finagent/issues/12))

### EPF/VPF ([#13](https://github.com/Suraj1074/finagent/issues/13))
- [ ] EPFO passbook PDF parser
- [ ] EPF balance + interest tracking
- [ ] VPF contribution insights

### NPS ([#14](https://github.com/Suraj1074/finagent/issues/14))
- [ ] CRA statement parser
- [ ] Tier I/II allocation tracking
- [ ] NPS insights (asset mix, returns)

### Stocks ([#15](https://github.com/Suraj1074/finagent/issues/15))
- [ ] Broker holdings import (Zerodha, Angel One)
- [ ] Manual stock entry
- [ ] Stock-level returns tracking

### ESOP/RSU ([#16](https://github.com/Suraj1074/finagent/issues/16))
- [ ] Manual input with vesting schedule
- [ ] Vested vs unvested tracking
- [ ] Tax event projections

### Real Estate ([#18](https://github.com/Suraj1074/finagent/issues/18))
- [ ] Plot, flat, house manual entry
- [ ] Loan netting (asset value minus outstanding)
- [ ] EMI vs prepayment analysis

### Gold ([#19](https://github.com/Suraj1074/finagent/issues/19))
- [ ] Physical, digital, SGB, ETF forms
- [ ] Auto-pricing from market data
- [ ] Gold allocation insights

### Cross-Asset Insights ([#17](https://github.com/Suraj1074/finagent/issues/17))
- [ ] Unified net worth dashboard
- [ ] Cross-product reasoning ("Your ELSS is redundant — EPF maxes 80C")
- [ ] Asset allocation analysis across all categories
- [ ] Tax optimization across instruments

---

## 🐛 Open Bugs
- [ ] NSDL CAS PDF routing bug ([#6](https://github.com/Suraj1074/finagent/issues/6))
- [ ] Financial terminology Q&A gaps ([#3](https://github.com/Suraj1074/finagent/issues/3))

---

## 📊 Growth Targets
- 100 GitHub stars
- 50 users
- 10 repeat users
