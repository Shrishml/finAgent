"""SIP simulation — what-if historical SIP returns for a fund."""
import logging
from finagent.analytics.nav_history import NAVHistoryEngine

log = logging.getLogger("finagent")
_nav = NAVHistoryEngine()

SCHEMA = {
    "name": "fund_sip_simulate",
    "description": "Simulate historical SIP returns for a fund. Use when user asks 'what if I did ₹X SIP in Y fund' or 'SIP simulation'.",
    "parameters": {
        "match": {"type": "str", "required": True, "description": "Fund name keyword"},
        "monthly_amount": {"type": "float", "required": False, "description": "Monthly SIP amount (default ₹10,000)"},
        "start_year": {"type": "int", "required": False, "description": "Year to start SIP from (default: fund inception)"},
    },
    "status_message": "Simulating SIP returns...",
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

    monthly = float(params.get("monthly_amount") or 10000)
    start_year = int(params["start_year"]) if params.get("start_year") else None

    sip = _nav.sip_simulation(matched.amfi_code, monthly, start_year)
    if not sip:
        return {"error": f"No NAV data for SIP simulation of {matched.scheme_name}."}

    lines = [
        f"## SIP Simulation: {matched.scheme_name}",
        f"Monthly SIP: ₹{sip['monthly_amount']:,.0f} from {sip['start_date']} ({sip['months']} months)",
        f"Total Invested: ₹{sip['total_invested']:,.0f}",
        f"Current Value: ₹{sip['final_value']:,.0f}",
        f"Gain: ₹{sip['absolute_gain']:,.0f}",
    ]
    if sip.get("xirr_pct"):
        lines.append(f"XIRR: {sip['xirr_pct']}%")

    return {"message": "\n".join(lines), "silent": False}
