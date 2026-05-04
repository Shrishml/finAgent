"""Fund performance — CAGR across periods + consistency score."""
import logging
from finagent.analytics.nav_history import NAVHistoryEngine
from finagent.actions.get_fund_details import execute as _get_fund  # reuse fund matching

log = logging.getLogger("finagent")
_nav = NAVHistoryEngine()

SCHEMA = {
    "name": "fund_performance",
    "description": "Get historical performance (CAGR 1/3/5/10Y, consistency score) for a specific fund. Use when user asks 'how has X performed'.",
    "parameters": {
        "match": {"type": "str", "required": True, "description": "Fund name keyword"},
    },
    "status_message": "Fetching performance data...",
}


async def execute(params: dict, user_id: int, context: dict) -> dict:
    from finagent.storage.sqlite import load_mf_assets
    match_kw = (params.get("match") or "").strip().lower()
    if not match_kw:
        return {"error": "Please specify which fund."}

    holdings = load_mf_assets(user_id)
    if not holdings:
        return {"error": "No mutual fund holdings found."}

    # Reuse fuzzy matching from get_fund_details
    matched = next((h for h in holdings if match_kw in h.scheme_name.lower()), None)
    if not matched:
        from difflib import SequenceMatcher
        kw = match_kw.split(" - ")[0].strip()
        for h in holdings:
            sn = h.scheme_name.lower().split(" - ")[0].strip()
            if sn.startswith(kw) or kw.startswith(sn) or SequenceMatcher(None, sn, kw).ratio() > 0.7:
                matched = h
                break
    if not matched or not matched.amfi_code:
        return {"error": f"No fund matching '{match_kw}' with AMFI code."}

    code = matched.amfi_code
    lines = [f"## Performance: {matched.scheme_name}"]

    cagr_i = _nav.cagr(code)
    if cagr_i is not None:
        lines.append(f"CAGR (inception): {cagr_i * 100:.1f}%")
    for years in [1, 3, 5, 10]:
        val = _nav.cagr(code, years)
        if val is not None:
            lines.append(f"CAGR ({years}Y): {val * 100:.1f}%")

    cs = _nav.consistency_score(code)
    if cs is not None:
        lines.append(f"Consistency (3Y rolling positive): {cs}%")

    if len(lines) == 1:
        return {"error": f"No historical NAV data for {matched.scheme_name}. Fund may be too new."}

    return {"message": "\n".join(lines), "silent": False}
