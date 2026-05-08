"""Fund crash stress test — GFC, NBFC, COVID drawdown and recovery."""
import logging
from finagent.analytics.nav_history import NAVHistoryEngine

log = logging.getLogger("finagent")
_nav = NAVHistoryEngine()

SCHEMA = {
    "name": "fund_stress_test",
    "description": "Show how a fund performed during major crashes (2008 GFC, 2018 NBFC, COVID). Use when user asks 'how did X do in a crash' or 'stress test'.",
    "parameters": {
        "match": {"type": "str", "required": True, "description": "Fund name keyword"},
    },
    "status_message": "Running crash stress tests...",
}


async def execute(params: dict, user_id: int, context: dict) -> dict:
    from finagent.storage.sqlite import load_mf_assets
    from finagent.actions.fund_risk import _find_holding
    match_kw = (params.get("match") or "").strip().lower()
    if not match_kw:
        return {"error": "Please specify which fund."}

    holdings = load_mf_assets(user_id)
    matched = _find_holding(match_kw, holdings) if holdings else None
    if not matched or not matched.amfi_code:
        return {"error": f"No fund matching '{match_kw}' with AMFI code."}

    crashes = _nav.crash_stress_test(matched.amfi_code)
    if not crashes:
        return {"error": f"No crash data for {matched.scheme_name}. Fund may be too new."}

    lines = [f"## Crash Stress Test: {matched.scheme_name}"]
    for c in crashes:
        rec = f", recovered in {c['recovery_months']}mo" if c.get("recovery_months") else ", not yet recovered"
        lines.append(f"  {c['label']}: -{c['drawdown_pct']}%{rec}")

    return {"message": "\n".join(lines), "silent": False}
