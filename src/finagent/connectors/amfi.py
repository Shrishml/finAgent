"""AMFI enrichment: fetch NAV, expense ratio, and metadata from mfdata.in API."""
import json
import logging
import urllib.request
import urllib.parse

from finagent.models.mf import MFHolding
from finagent.storage import save_nav_cache, get_cached_nav

log = logging.getLogger("finagent.enrichment.amfi")

MFDATA_API = "https://mfdata.in/api/v1/schemes"
MFAPI_URL = "https://api.mfapi.in/mf"


def _fetch_category_from_mfapi(amfi_code: str) -> str:
    """Fallback: get category from mfapi.in's scheme_category field."""
    url = f"{MFAPI_URL}/{amfi_code}/latest"
    req = urllib.request.Request(url, headers={"User-Agent": "Arth/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            raw = data.get("meta", {}).get("scheme_category", "")
            # "Equity Scheme - Flexi Cap Fund" → "Flexi Cap"
            if " - " in raw:
                return raw.split(" - ", 1)[1].replace(" Fund", "").replace(" Scheme", "").strip()
            return raw
    except Exception as e:
        log.debug(f"mfapi.in category fetch failed for {amfi_code}: {e}")
    return ""


async def enrich_holdings(holdings: list[MFHolding]) -> list[MFHolding]:
    """Enrich holdings with live data from mfdata.in. Updates NAV, expense ratio, value."""
    for h in holdings:
        if not h.amfi_code:
            log.debug(f"Skipping {h.scheme_name}: no AMFI code")
            continue

        # Check cache first (24h TTL) — returns {nav, expense_ratio} or None
        cached = await get_cached_nav(h.amfi_code)
        if cached:
            _apply_data(h, cached["nav"], cached["expense_ratio"])
            if h.category:
                continue
            # Category missing — fetch from mfapi.in
            h.category = _fetch_category_from_mfapi(h.amfi_code)
            if h.category:
                continue

        # Fetch from mfdata.in
        try:
            data = _fetch_scheme(h.amfi_code)
            if data:
                nav = float(data.get("nav", 0))
                expense = float(data.get("expense_ratio", 0)) / 100  # API returns percentage
                log.info(f"AMFI {h.amfi_code}: NAV={nav}, ER={expense*100:.2f}%, category={data.get('category')}")
                await save_nav_cache(h.amfi_code, nav, data.get("name", ""), expense)
                _apply_data(h, nav, expense)
                h.category = data.get("category", "")
                if not h.category:
                    h.category = _fetch_category_from_mfapi(h.amfi_code)
                h.nav_date = data.get("nav_date", "")
                h.day_change = float(data.get("day_change", 0))
                h.day_change_pct = float(data.get("day_change_pct", 0))
                h.morningstar = int(data.get("morningstar", 0))
                h.aum = float(data.get("aum", 0))
                h.risk_label = data.get("risk_label", "")
            else:
                log.warning(f"No data for AMFI {h.amfi_code}")
        except Exception as e:
            log.warning(f"mfdata.in fetch failed for {h.amfi_code}: {e}")

        # Fallback: always try mfapi.in for category if still missing
        if not h.category:
            h.category = _fetch_category_from_mfapi(h.amfi_code)

    return holdings


def _fetch_scheme(amfi_code: str) -> dict | None:
    """Fetch scheme data from mfdata.in API."""
    url = f"{MFDATA_API}/{amfi_code}"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "FinAgent/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            if result.get("status") == "success":
                return result.get("data", {})
    except Exception as e:
        log.debug(f"API call failed: {e}")
    return None


def _apply_data(h: MFHolding, nav: float, expense_ratio: float = 0):
    """Update holding with fresh NAV and expense ratio."""
    h.nav = nav
    h.current_value = h.units * nav
    if expense_ratio > 0:
        h.expense_ratio = expense_ratio
        h.annual_expense = h.current_value * expense_ratio


def fetch_category_peers(amfi_code: str) -> list[dict]:
    """Fetch peer funds in the same category for comparison."""
    scheme = _fetch_scheme(amfi_code)
    if not scheme or not scheme.get("category"):
        return []

    category = scheme["category"]
    plan_type = scheme.get("plan_type", "direct")

    # Search for peers in same category
    url = f"https://mfdata.in/api/v1/search?q={urllib.parse.quote(category)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "FinAgent/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            if result.get("status") != "success":
                return []
            peers = [
                p for p in result.get("data", [])
                if p.get("plan_type") == plan_type and p.get("amfi_code") != amfi_code
            ]
            # Sort by expense ratio
            peers.sort(key=lambda p: float(p.get("expense_ratio", 99)))
            return peers[:10]  # top 10 cheapest
    except Exception as e:
        log.debug(f"Peer fetch failed: {e}")
        return []
