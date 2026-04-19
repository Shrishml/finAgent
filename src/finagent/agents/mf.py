"""Mutual Fund Domain Agent — analyze, research, and summarize."""
from finagent.agents.base import DomainAgent
from finagent.analytics.nav_history import NAVHistoryEngine
from finagent.llm import get_provider
from finagent.models.mf import MFHolding
from finagent.models.summary import FinancialSummary

_nav_engine = NAVHistoryEngine()


class MFAgent(DomainAgent):
    """Mutual fund analysis agent with deterministic computation + LLM presentation."""

    def supported_connectors(self) -> list[str]:
        return ["cams"]

    def get_summaries(self, user_data: list) -> list[FinancialSummary]:
        return [h.to_summary() for h in user_data if isinstance(h, MFHolding)]

    async def analyze(self, query: str, user_data: list) -> str:
        holdings = [h for h in user_data if isinstance(h, MFHolding)]
        if not holdings:
            return "No mutual fund data found. Please upload a CAMS/KFintech PDF first."

        # Compute analytics deterministically
        analysis = self._compute_analysis(holdings)

        # Use LLM only for natural language presentation
        llm = get_provider("reasoning")
        prompt = self._analyze_prompt(query, analysis)
        return await llm.complete(prompt)

    async def analyze_stream(self, query: str, user_data: list):
        """Streaming version of analyze — yields chunks as LLM generates."""
        holdings = [h for h in user_data if isinstance(h, MFHolding)]
        if not holdings:
            yield "No mutual fund data found. Please upload a CAMS/KFintech PDF first."
            return

        analysis = self._compute_analysis(holdings)
        llm = get_provider("reasoning")
        prompt = self._analyze_prompt(query, analysis)
        async for chunk in llm.complete_stream(prompt):
            yield chunk

    def _analyze_prompt(self, query: str, analysis: str) -> str:
        return f"""You are a mutual fund analyst. Based on this portfolio data, answer the user's question.
Do NOT use any tools, search files, or access external data. Answer ONLY from the data below.

Portfolio Analysis:
{analysis}

User Question: {query}

Respond in clear, actionable language. Show specific numbers. If suggesting changes, explain why. Use **bold** for key figures, bullet lists for comparisons, and ### headings if covering multiple topics."""

    async def research(self, query: str, constraints: dict | None = None) -> str:
        llm = get_provider("reasoning")
        prompt = f"""You are a mutual fund research analyst. Help the user find better investment options.
Do NOT use any tools, search files, or access external data.

User Question: {query}
Constraints: {constraints or 'None specified'}

Provide specific fund recommendations with reasoning. Note: this is research mode — you're searching for options, not analyzing the user's existing portfolio."""

        return await llm.complete(prompt)

    async def deep_dive(self, query: str, amfi_code: str, scheme_name: str = "") -> str:
        """Deep dive into a fund using historical NAV data."""
        report = _nav_engine.full_report(amfi_code)
        if not report.get("cagr_since_inception") and not report.get("volatility"):
            return f"No historical NAV data available for {scheme_name or amfi_code}. The fund may be too new or the AMFI code may be incorrect."

        # Format report for LLM
        lines = [f"## Deep Dive: {scheme_name or amfi_code}\n"]
        if report["cagr_since_inception"] is not None:
            lines.append(f"CAGR (inception): {report['cagr_since_inception']*100:.1f}%")
        for period in ["1y", "3y", "5y", "10y"]:
            val = report.get(f"cagr_{period}")
            if val is not None:
                lines.append(f"CAGR ({period}): {val*100:.1f}%")
        if report["volatility"] is not None:
            lines.append(f"Volatility: {report['volatility']*100:.1f}%")
        if report["sharpe_ratio"] is not None:
            lines.append(f"Sharpe Ratio: {report['sharpe_ratio']}")
        if report["consistency_score_3y"] is not None:
            lines.append(f"Consistency (3Y rolling): {report['consistency_score_3y']}%")
        dd = report.get("max_drawdown")
        if dd:
            lines.append(f"Max Drawdown: -{dd['drawdown']}% (peak {dd['peak_date']} → trough {dd['trough_date']})")
            if dd.get("recovery_months"):
                lines.append(f"  Recovery: {dd['recovery_months']} months")
        crashes = report.get("crash_stress_test", [])
        if crashes:
            lines.append("\nCrash Stress Tests:")
            for c in crashes:
                rec = f", recovered in {c['recovery_months']}mo" if c.get("recovery_months") else ", not yet recovered"
                lines.append(f"  {c['label']}: -{c['drawdown_pct']}%{rec}")
        sip = report.get("sip_simulation")
        if sip:
            lines.append(f"\nSIP Simulation (₹{sip['monthly_amount']:,.0f}/mo from {sip['start_date']}):")
            lines.append(f"  Invested: ₹{sip['total_invested']:,.0f} → Value: ₹{sip['final_value']:,.0f}")
            lines.append(f"  Gain: ₹{sip['absolute_gain']:,.0f}" + (f" | XIRR: {sip['xirr_pct']}%" if sip.get("xirr_pct") else ""))

        analysis = "\n".join(lines)
        llm = get_provider("reasoning")
        prompt = f"""You are a mutual fund analyst. Using this historical analysis, answer the user's question.
Do NOT use any tools, search files, or access external data. Answer ONLY from the data below.

{analysis}

User Question: {query}

Be specific with numbers. If the user asks about a crash, focus on the stress test data. If asking about SIP, focus on simulation. Always mention both risk and return."""

        return await llm.complete(prompt)

    def _compute_analysis(self, holdings: list[MFHolding]) -> str:
        """Deterministic computation — no LLM needed."""
        lines = []

        # Portfolio overview
        total_value = sum(h.current_value for h in holdings)
        total_invested = sum(h.invested_value for h in holdings)
        total_expense = sum(h.annual_expense for h in holdings)
        lines.append(f"Total Portfolio Value: ₹{total_value:,.0f}")
        lines.append(f"Total Invested: ₹{total_invested:,.0f}")
        if total_invested > 0:
            lines.append(f"Overall Gain: ₹{total_value - total_invested:,.0f} ({(total_value/total_invested - 1)*100:.1f}%)")
        lines.append(f"Total Annual Expenses: ₹{total_expense:,.0f}")
        lines.append(f"Number of Schemes: {len(holdings)}")
        lines.append("")

        # Per-fund breakdown
        lines.append("Per-Fund Details:")
        for h in sorted(holdings, key=lambda x: x.current_value, reverse=True):
            pct = (h.current_value / total_value * 100) if total_value else 0
            lines.append(f"  {h.scheme_name}")
            lines.append(f"    Value: ₹{h.current_value:,.0f} ({pct:.1f}% of portfolio)")
            lines.append(f"    Plan: {h.plan} | Expense Ratio: {h.expense_ratio*100:.2f}%")
            if h.xirr:
                lines.append(f"    XIRR: {h.xirr*100:.1f}%")
            if h.plan == "regular":
                lines.append(f"    ⚠️ Regular plan — direct plan alternative likely saves 0.5-1.5% annually")
            if h.expense_ratio > 0.01:
                lines.append(f"    ⚠️ High expense ratio (>{1}%)")
            lines.append("")

        # Flags
        regular_plans = [h for h in holdings if h.plan == "regular"]
        high_expense = [h for h in holdings if h.expense_ratio > 0.01]
        if regular_plans:
            savings = sum(h.current_value * 0.007 for h in regular_plans)  # ~0.7% avg saving
            lines.append(f"💡 {len(regular_plans)} fund(s) on regular plan. Switching to direct could save ~₹{savings:,.0f}/year")
        if high_expense:
            lines.append(f"💡 {len(high_expense)} fund(s) with expense ratio > 1%")

        return "\n".join(lines)
