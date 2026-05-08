"""Fund risk metrics — volatility, max drawdown, Sharpe ratio."""
import logging
from finagent.analytics.nav_history import NAVHistoryEngine

log = logging.getLogger("finagent")
_nav = NAVHistoryEngine()

SCHEMA = {
    "name": "fund_risk",
    "description": "Get risk metrics (volatility, max drawdown, Sharpe ratio) for a specific fund. Use when user asks 'how risky is X' or 'drawdown'.",
    "parameters": {
        "match": {"type": "str", "required": True, "description": "Fund name keyword"},
    },
    "status_message": "Calculating risk metrics...",
}


def _find_holding(match_kw: str, holdings: list):
    matched = next((h for h in holdings if match_kw in h.scheme_name.lower()), None)
    if not matched:
        from difflib import SequenceMatcher
        kw = match_kw.split(" - ")[0].strip()
        for h in holdings:
            sn = h.scheme_name.lower().split(" - ")[0].strip()
            if sn.startswith(kw) or kw.startswith(sn) or SequenceMatcher(None, sn, kw).ratio() > 0.7:
                return h
    return matched


async def execute(params: dict, user_id: int, context: dict) -> dict:
    from finagent.storage.sqlite import load_mf_assets
    match_kw = (params.get("match") or "").strip().lower()
    if not match_kw:
        return {"error": "Please specify which fund."}

    holdings = load_mf_assets(user_id)
    matched = _find_holding(match_kw, holdings) if holdings else None
    if not matched or not matched.amfi_code:
        return {"error": f"No fund matching '{match_kw}' with AMFI code."}

    code = matched.amfi_code
    lines = [f"## Risk: {matched.scheme_name}"]

    vol = _nav.volatility(code)
    if vol is not None:
        lines.append(f"Annualized Volatility: {vol * 100:.1f}%")

    sharpe = _nav.sharpe_ratio(code)
    if sharpe is not None:
        lines.append(f"Sharpe Ratio: {sharpe}")

    dd = _nav.max_drawdown(code)
    if dd:
        lines.append(f"Max Drawdown: -{dd['drawdown']}% (peak {dd['peak_date']} → trough {dd['trough_date']})")
        if dd.get("recovery_months"):
            lines.append(f"  Recovery: {dd['recovery_months']} months")
        elif dd.get("recovery_date"):
            lines.append(f"  Recovered: {dd['recovery_date']}")

    if len(lines) == 1:
        return {"error": f"No historical NAV data for {matched.scheme_name}."}

    return {"message": "\n".join(lines), "silent": False}
