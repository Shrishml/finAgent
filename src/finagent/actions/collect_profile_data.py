"""Action: collect_profile_data — collect or auto-save structured profile data."""
import logging
from finagent.storage.sqlite import save_assets, load_assets

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
                           "loan: loan_type, principal, emi, start_date, tenure. "
                           "epf_ppf: epf_balance, ppf_balance, epf_contribution, ppf_contribution. "
                           "nps: nps_balance, nps_contribution. stocks: demat_value. "
                           "mf_declared: scheme, monthly_sip, allocation_pct, category. "
                           "insurance: type, cover, premium. tax: regime."
        }
    },
    "ui_component": "profile_card",
    "status_message": "Processing..."
}

VALID_TYPES = {"fd", "realestate", "gold", "esop", "loan",
               "epf_ppf", "nps", "stocks", "insurance", "tax", "mf_declared"}

REQUIRED_FIELDS = {
    "fd": {"bank", "amount", "rate"},
    "realestate": {"type", "location", "current_value"},
    "gold": {"type", "value"},
    "esop": {"company", "vested"},
    "loan": {"loan_type", "principal", "emi"},
    "epf_ppf": {"epf_balance"},
    "nps": {"nps_balance"},
    "stocks": {"demat_value"},
    "insurance": {"type", "cover"},
    "tax": {"regime"},
    "mf_declared": {"scheme"},
}


TYPE_ALIASES = {
    "provident_fund": "epf_ppf", "pf": "epf_ppf", "epf": "epf_ppf", "ppf": "epf_ppf",
    "stock": "stocks", "demat": "stocks", "equity": "stocks",
    "life_insurance": "insurance", "health_insurance": "insurance",
    "real_estate": "realestate", "property": "realestate",
    "fixed_deposit": "fd", "savings": "fd", "emergency_fund": "fd", "liquid_fund": "fd",
    "mutual_fund": "mf_declared", "mf": "mf_declared", "sip": "mf_declared",
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

    # Load existing data for this type
    existing = load_assets(user_id, card_type)
    required = REQUIRED_FIELDS.get(card_type, set())

    # If user has existing data and prefill is partial → merge update
    if existing and prefill and not required.issubset(prefill.keys()):
        # Find best matching item (for card types with multiple items like loans/FDs)
        target = existing[0]  # default to first
        # Try to match by identifying field (loan_type, bank, company, type)
        for key in ("loan_type", "bank", "company", "type"):
            if key in prefill:
                match = [e for e in existing if e.get(key) == prefill[key]]
                if match:
                    target = match[0]
                    break
        # Merge: existing fields + new fields overlay
        merged = {k: v for k, v in target.items() if k not in ("id", "asset_type")}
        merged.update(prefill)
        # Rebuild full list with the updated item
        all_items = []
        for e in existing:
            item = {k: v for k, v in e.items() if k not in ("id", "asset_type")}
            if e is target:
                item = merged
            all_items.append(item)
        save_assets(user_id, card_type, all_items)
        log.info(f"[action] collect_profile_data: merge-updated {card_type} for user {user_id}")
        return {
            "message": f"✅ Updated your {card_type} profile.",
            "ui_component": "profile_card_saved",
            "ui_data": {"card_type": card_type, "data": merged}
        }

    has_all = required and required.issubset(prefill.keys())
    if has_all:
        items = [e for e in existing if True] if existing else []
        # Add new item (strip id/asset_type from existing format)
        items = [{k: v for k, v in e.items() if k not in ("id", "asset_type")} for e in items]
        items.append(prefill)
        save_assets(user_id, card_type, items)
        log.info(f"[action] collect_profile_data: saved new {card_type} for user {user_id}")
        return {
            "message": f"✅ Saved to your profile.",
            "ui_component": "profile_card_saved",
            "ui_data": {"card_type": card_type, "data": prefill}
        }

    # Show form — prefill with existing data if available
    form_prefill = prefill
    if existing and not prefill:
        form_prefill = {k: v for k, v in existing[0].items() if k not in ("id", "asset_type")}
    log.info(f"[action] collect_profile_data: showing form for {card_type}")
    return {
        "message": "Please fill in the details below and hit Save.",
        "ui_component": "profile_card",
        "ui_data": {"card_type": card_type, "prefill": form_prefill}
    }
