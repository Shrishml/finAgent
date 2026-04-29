"""Profile data extraction utilities.

Provides:
- extract_profile_data(): LLM-based extraction from user messages
- apply_extractions(): Apply extracted data to profile
"""
import json
import logging

from finagent.llm import get_provider
from finagent.models.profile import UserProfile
from finagent.storage.sqlite import save_assets, load_assets

log = logging.getLogger("finagent")


def _fmt_inr(n: float) -> str:
    """Format number in Indian comma style: 1,10,000."""
    s = str(int(n))
    if len(s) <= 3:
        return s
    last3 = s[-3:]
    rest = s[:-3]
    parts = []
    while rest:
        parts.append(rest[-2:])
        rest = rest[:-2]
    return ",".join(reversed(parts)) + "," + last3


EXTRACTION_PROMPT = """You are Arth. Extract any financial data from the user's message.

CURRENT PROFILE:
{profile_json}

USER SAID: "{user_message}"

Extract into these fields (only include fields with actual data):
- name, age, occupation, employer, location, marital_status, kids, dependents
- dependent_parents (e.g. "2 parents"), parents_health_insurance ("yes"|"no")
- risk_tolerance ("Conservative"|"Moderate"|"Aggressive")
- monthly_income, annual_bonus, spouse_income, other_income (numbers in INR)
- annual_rsu (annual RSU/stock vesting value in INR — this is recurring compensation, not a one-time asset)
- monthly_sip (total monthly SIP investment amount in INR)
- total_monthly_expenses, rent, groceries, utilities, dining, annual_big_ticket, emis (numbers in INR)
- loans: [{{"type": "home|car|education|personal|credit_card", "principal": N, "rate": N, "emi": N, "remaining_months": N}}]
- term_cover, term_premium, health_cover, health_premium (INR), health_employer_only (bool)
- tax_regime ("old"|"new"), section_80c_used
- esop_company, esop_vested (INR), esop_unvested (INR), esop_next_vesting (YYYY-MM)
- ppf_balance (INR), ppf_contribution (annual PPF contribution in INR), epf_balance (INR), epf_contribution (monthly EPF contribution in INR, employee + employer)
- nps_balance (INR), nps_contribution (monthly NPS contribution in INR)
- mf_sips: [{{"scheme": "fund name", "monthly_sip": N, "current_value": N, "allocation_pct": N, "category": "large_cap|mid_cap|small_cap|flexi_cap|index|debt|gold|international|other"}}]
- fds: [{{"bank": "bank/fund name", "amount": N, "rate": N, "maturity": "YYYY-MM", "tax_saver": "yes"|"no"}}]
- gold: [{{"type": "physical|sgb|digital|etf", "value": N, "amount_invested": N, "weight_grams": N}}]
- real_estate: [{{"type": "self_occupied|rented|plot|commercial", "location": "city/area", "current_value": N, "purchase_price": N, "rental_income": N}}]

Rules:
- Convert lakhs to actual numbers (1.1 lakh = 110000, 40L = 4000000, 1Cr = 10000000)
- Only extract what's explicitly stated, don't infer
- RSU, ESOP, stock grants, vesting income are NOT other_income — extract into esop_* fields

Respond as JSON: {{"extractions": {{...}}, "has_data": true/false}}"""


async def extract_profile_data(user_message: str, profile: UserProfile) -> dict:
    """Extract financial data from a user message using LLM."""
    from dataclasses import asdict
    full = asdict(profile)
    for k in ("user_id", "pillars_completed", "pillars_skipped", "onboarding_complete", "financial_snapshot"):
        full.pop(k, None)
    profile_json = json.dumps({k: v for k, v in full.items() if v}, separators=(',', ':'))

    llm = get_provider("default")
    try:
        raw = await llm.complete(
            EXTRACTION_PROMPT.format(profile_json=profile_json, user_message=user_message),
            json_mode=True,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        result = json.loads(raw)
        return result.get("extractions", {})
    except Exception as e:
        log.error(f"[extraction] failed: {e}")
        return {}


def apply_extractions(profile: UserProfile, extractions: dict) -> bool:
    """Apply extracted data to profile. Returns True if anything changed."""
    changed = False

    # Handle ESOP/RSU fields → save to user_assets
    esop_keys = {k: v for k, v in extractions.items() if k.startswith("esop_") and v is not None}
    if esop_keys:
        esop_data = {}
        key_map = {"esop_company": "company", "esop_vested": "vested",
                    "esop_unvested": "unvested", "esop_next_vesting": "next_vesting"}
        for k, v in esop_keys.items():
            field = key_map.get(k)
            if field:
                esop_data[field] = v
        if esop_data:
            existing = load_assets(profile.user_id, "esop")
            # Match by company if updating existing
            matched = None
            if existing and "company" in esop_data:
                matched = next((e for e in existing if
                                str(e.get("company", "")).lower() == str(esop_data["company"]).lower()), None)
            if matched:
                clean = {k: v for k, v in matched.items() if k not in ("id", "asset_type")}
                clean.update(esop_data)
                items = [{k: v for k, v in e.items() if k not in ("id", "asset_type")} for e in existing]
                idx = next(i for i, e in enumerate(existing) if e is matched)
                items[idx] = clean
            else:
                items = [{k: v for k, v in e.items() if k not in ("id", "asset_type")} for e in existing]
                items.append(esop_data)
            save_assets(profile.user_id, "esop", items)
            log.info(f"[extraction] saved esop data: {esop_data}")
            changed = True

    # Handle EPF/PPF fields → save to user_assets
    epf_ppf_keys = {k: v for k, v in extractions.items() if k in ("epf_balance", "ppf_balance", "epf_contribution", "ppf_contribution") and v is not None}
    if epf_ppf_keys:
        existing = load_assets(profile.user_id, "epf_ppf")
        current = {k: v for k, v in existing[0].items() if k not in ("id", "asset_type")} if existing else {}
        current.update(epf_ppf_keys)
        save_assets(profile.user_id, "epf_ppf", [current])
        log.info(f"[extraction] saved epf_ppf data: {epf_ppf_keys}")
        changed = True

    # Handle NPS fields → save to user_assets
    nps_keys = {k: v for k, v in extractions.items() if k in ("nps_balance", "nps_contribution") and v is not None}
    if nps_keys:
        existing = load_assets(profile.user_id, "nps")
        current = {k: v for k, v in existing[0].items() if k not in ("id", "asset_type")} if existing else {}
        current.update(nps_keys)
        save_assets(profile.user_id, "nps", [current])
        log.info(f"[extraction] saved nps data: {nps_keys}")
        changed = True

    # Handle declared MF SIPs → save to user_assets
    mf_sips = extractions.get("mf_sips")
    if isinstance(mf_sips, list) and mf_sips:
        existing = load_assets(profile.user_id, "mf_declared")
        existing_schemes = {e.get("scheme", "").lower() for e in existing}
        new_items = [{k: v for k, v in e.items() if k not in ("id", "asset_type")} for e in existing]
        for sip in mf_sips:
            if not isinstance(sip, dict) or not sip.get("scheme"):
                continue
            if sip["scheme"].lower() in existing_schemes:
                # Update existing
                for item in new_items:
                    if item.get("scheme", "").lower() == sip["scheme"].lower():
                        item.update(sip)
                        break
            else:
                new_items.append(sip)
        save_assets(profile.user_id, "mf_declared", new_items)
        log.info(f"[extraction] saved {len(mf_sips)} declared MF SIPs")
        changed = True

    # Handle FDs → save to user_assets
    fds = extractions.get("fds")
    if isinstance(fds, list) and fds:
        existing = load_assets(profile.user_id, "fd")
        existing_banks = {e.get("bank", "").lower() for e in existing}
        new_items = [{k: v for k, v in e.items() if k not in ("id", "asset_type")} for e in existing]
        for fd in fds:
            if not isinstance(fd, dict) or not fd.get("bank"):
                continue
            if fd["bank"].lower() in existing_banks:
                for item in new_items:
                    if item.get("bank", "").lower() == fd["bank"].lower():
                        item.update(fd)
                        break
            else:
                new_items.append(fd)
        save_assets(profile.user_id, "fd", new_items)
        log.info(f"[extraction] saved {len(fds)} FDs")
        changed = True

    # Handle Gold → save to user_assets
    gold_items = extractions.get("gold")
    if isinstance(gold_items, list) and gold_items:
        existing = load_assets(profile.user_id, "gold")
        new_items = [{k: v for k, v in e.items() if k not in ("id", "asset_type")} for e in existing]
        for g in gold_items:
            if not isinstance(g, dict):
                continue
            # Normalize: extraction may use current_value, storage uses value
            if "current_value" in g and "value" not in g:
                g["value"] = g.pop("current_value")
            g_type = str(g.get("type", "")).lower()
            matched = next((i for i, e in enumerate(new_items) if str(e.get("type", "")).lower() == g_type), None)
            if matched is not None:
                new_items[matched].update(g)
            else:
                new_items.append(g)
        save_assets(profile.user_id, "gold", new_items)
        log.info(f"[extraction] saved {len(gold_items)} gold entries")
        changed = True

    # Handle Real Estate → save to user_assets
    re_items = extractions.get("real_estate")
    if isinstance(re_items, list) and re_items:
        existing = load_assets(profile.user_id, "realestate")
        new_items = [{k: v for k, v in e.items() if k not in ("id", "asset_type")} for e in existing]
        for prop in re_items:
            if not isinstance(prop, dict):
                continue
            loc = str(prop.get("location", "")).lower()
            matched = next((i for i, e in enumerate(new_items) if str(e.get("location", "")).lower() == loc), None) if loc else None
            if matched is not None:
                new_items[matched].update(prop)
            else:
                new_items.append(prop)
        save_assets(profile.user_id, "realestate", new_items)
        log.info(f"[extraction] saved {len(re_items)} real estate entries")
        changed = True

    field_map = {
        "name", "age", "dependents", "occupation", "employer", "risk_tolerance",
        "location", "marital_status", "kids",
        "dependent_parents", "parents_health_insurance",
        "monthly_income", "annual_bonus", "spouse_income", "other_income",
        "annual_rsu", "monthly_sip",
        "total_monthly_expenses", "rent", "groceries", "utilities", "dining",
        "annual_big_ticket", "emis",
        "term_cover", "term_premium", "health_cover", "health_premium",
        "health_employer_only",
        "tax_regime", "section_80c_used",
    }
    str_fields = {"name", "occupation", "employer", "risk_tolerance", "tax_regime",
                  "location", "marital_status", "dependent_parents", "parents_health_insurance"}
    for key, value in extractions.items():
        if key == "loans" and isinstance(value, list):
            profile.loans = value
            changed = True
        elif key in field_map and value is not None:
            if isinstance(value, str) and key not in str_fields:
                try:
                    value = float(value.replace(",", ""))
                except ValueError:
                    continue
            old = getattr(profile, key, None)
            if old != value:
                setattr(profile, key, value)
                changed = True
    return changed
