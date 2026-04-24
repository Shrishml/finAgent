"""Action: collect_profile_data — collect or auto-save structured profile data."""
import logging
from finagent.storage.sqlite import save_assets

log = logging.getLogger(__name__)

SCHEMA = {
    "name": "collect_profile_data",
    "description": "Collect structured profile data from the user. If you have ALL details from the "
                   "conversation, pass them in prefill and they'll be saved directly. If partial, "
                   "shows an editable form card for the user to complete. "
                   "Use when user mentions assets, loans, or financial details.",
    "parameters": {
        "card_type": {
            "type": "string",
            "required": True,
            "description": "One of: fd, realestate, gold, esop, loan, epf_ppf, nps, stocks, insurance, tax"
        },
        "prefill": {
            "type": "object",
            "required": False,
            "description": "Data extracted from conversation. Keys must match card fields. "
                           "fd: bank, amount, rate, maturity, tax_saver. "
                           "realestate: type, location, current_value, purchase_price, usage, linked_loan. "
                           "gold: type, value. esop: company, vested, unvested, next_vesting. "
                           "loan: loan_type, outstanding, rate, emi. "
                           "epf_ppf: epf_balance, ppf_balance, epf_monthly. "
                           "nps: nps_balance, nps_monthly. stocks: demat_value. "
                           "insurance: type, cover, premium. tax: regime."
        }
    },
    "ui_component": "profile_card",
    "status_message": "Processing..."
}

VALID_TYPES = {"fd", "realestate", "gold", "esop", "loan",
               "epf_ppf", "nps", "stocks", "insurance", "tax"}

REQUIRED_FIELDS = {
    "fd": {"bank", "amount", "rate"},
    "realestate": {"type", "location", "current_value"},
    "gold": {"type", "value"},
    "esop": {"company", "vested"},
    "loan": {"loan_type", "outstanding", "rate"},
    "epf_ppf": {"epf_balance"},
    "nps": {"nps_balance"},
    "stocks": {"demat_value"},
    "insurance": {"type", "cover"},
    "tax": {"regime"},
}


TYPE_ALIASES = {
    "provident_fund": "epf_ppf", "pf": "epf_ppf", "epf": "epf_ppf", "ppf": "epf_ppf",
    "stock": "stocks", "demat": "stocks", "equity": "stocks",
    "life_insurance": "insurance", "health_insurance": "insurance",
    "real_estate": "realestate", "property": "realestate",
    "fixed_deposit": "fd",
}

async def execute(params: dict, user_id: int, context: dict) -> dict:
    card_type = params.get("card_type", "").lower()
    card_type = TYPE_ALIASES.get(card_type, card_type)
    if card_type not in VALID_TYPES:
        return {"error": f"Unknown card type '{card_type}'. Use one of: {', '.join(sorted(VALID_TYPES))}"}

    prefill = params.get("prefill") or {}
    if isinstance(prefill, str):
        import json
        try: prefill = json.loads(prefill)
        except Exception: prefill = {}
    required = REQUIRED_FIELDS.get(card_type, set())
    has_all = required and required.issubset(prefill.keys())

    if has_all:
        save_assets(user_id, card_type, [prefill])
        log.info(f"[action] collect_profile_data: auto-saved {card_type} for user {user_id}")
        return {
            "message": f"✅ Saved to your profile.",
            "ui_component": "profile_card_saved",
            "ui_data": {"card_type": card_type, "data": prefill}
        }

    log.info(f"[action] collect_profile_data: showing form for {card_type}")
    return {
        "message": "Please fill in the details below and hit Save.",
        "ui_component": "profile_card",
        "ui_data": {"card_type": card_type, "prefill": prefill}
    }
