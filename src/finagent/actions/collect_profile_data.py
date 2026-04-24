"""Action: collect_profile_data — emit a profile card into chat for structured data collection."""
import logging

log = logging.getLogger(__name__)

SCHEMA = {
    "name": "collect_profile_data",
    "description": "Show an inline form card in chat to collect structured profile data from the user. "
                   "Use when the user mentions assets, loans, insurance, or other profile details that "
                   "need structured input (e.g. 'I have 3 FDs', 'I own a flat in Bangalore', 'I have ESOPs').",
    "parameters": {
        "card_type": {
            "type": "string",
            "required": True,
            "description": "Type of card to show. One of: fd, realestate, gold, esop, loan"
        },
        "prefill": {
            "type": "object",
            "required": False,
            "description": "Optional prefill data extracted from conversation (e.g. {bank: 'SBI', amount: '5L'})"
        }
    },
    "ui_component": "profile_card",
    "status_message": "Preparing input form..."
}

VALID_TYPES = {"fd", "realestate", "gold", "esop", "loan"}


async def execute(params: dict, user_id: int, context: dict) -> dict:
    card_type = params.get("card_type", "").lower()
    if card_type not in VALID_TYPES:
        return {"error": f"Unknown card type '{card_type}'. Use one of: {', '.join(sorted(VALID_TYPES))}"}

    count = 1
    prefill = params.get("prefill", {})

    log.info(f"[action] collect_profile_data: type={card_type}")

    return {
        "message": f"Please fill in the details below and hit Save.",
        "ui_component": "profile_card",
        "ui_data": {
            "card_type": card_type,
            "prefill": prefill
        }
    }
