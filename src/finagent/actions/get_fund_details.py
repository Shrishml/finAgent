"""Retrieve detailed MF fund data including transactions, XIRR, and NAV history."""
import logging
from finagent.storage import load_mf_assets

log = logging.getLogger("finagent")

SCHEMA = {
    "name": "get_fund_details",
    "description": "Get detailed info for a specific mutual fund — transactions, XIRR, NAV, expense ratio. Use when user asks about SIP history, returns, or fund-level detail.",
    "parameters": {
        "match": {"type": "str", "required": True, "description": "Fund name keyword (e.g. 'Parag Parikh', 'ICICI Small Cap')"},
    },
    "ui_component": None,
    "status_message": "Looking up fund details...",
}


async def execute(params: dict, user_id: int, context: dict) -> dict:
    match_kw = (params.get("match") or "").strip().lower()
    if not match_kw:
        return {"error": "Please specify which fund to look up."}

    holdings = await load_mf_assets(user_id)
    if not holdings:
        return {"error": "No mutual fund holdings found."}

    # Substring match, then fuzzy fallback
    matched = next((h for h in holdings if match_kw in h.scheme_name.lower()), None)
    if not matched:
        from difflib import SequenceMatcher
        kw = match_kw.split(" - ")[0].strip()
        for h in holdings:
            sn = h.scheme_name.lower().split(" - ")[0].strip()
            if sn.startswith(kw) or kw.startswith(sn) or SequenceMatcher(None, sn, kw).ratio() > 0.7:
                matched = h
                break

    if not matched:
        names = ", ".join(h.scheme_name for h in holdings[:5])
        return {"error": f"No fund matching '{match_kw}'. Available: {names}"}

    detail = {
        "scheme_name": matched.scheme_name,
        "folio": matched.folio or None,
        "amc": matched.amc or None,
        "units": matched.units,
        "nav": matched.nav,
        "current_value": matched.current_value,
        "invested_value": matched.invested_value,
        "xirr": getattr(matched, "xirr", None),
        "expense_ratio": matched.expense_ratio,
        "category": getattr(matched, "category", None),
        "transactions": [
            {"date": str(t.date), "type": t.type, "amount": t.amount, "units": t.units, "nav": t.nav}
            for t in (matched.transactions or [])[-20:]  # Last 20 transactions
        ],
        "transaction_count": len(matched.transactions or []),
    }
    # Remove None values for cleaner output
    detail = {k: v for k, v in detail.items() if v is not None}

    log.info(f"[action] get_fund_details for '{matched.scheme_name}': {len(matched.transactions or [])} txns")
    return {"message": f"Details for {matched.scheme_name}:\n```json\n{__import__('json').dumps(detail, indent=2)}\n```", "silent": False}
