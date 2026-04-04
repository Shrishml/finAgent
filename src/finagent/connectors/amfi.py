"""AMFI enrichment: fetch NAV, expense ratio, and metadata from mfdata.in API."""
import json
import logging
import urllib.request

from finagent.models.mf import MFHolding
from finagent.storage.sqlite import save_nav_cache, get_cached_nav

log = logging.getLogger("finagent.enrichment.amfi")

MFDATA_API = "https://mfdata.in/api/v1/schemes"


def enrich_holdings(holdings: list[MFHolding]) -> list[MFHolding]:
    """Enrich holdings with live data from mfdata.in. Updates NAV, expense ratio, value."""
    for h in holdings:
        if not h.amfi_code:
            log.debug(f"Skipping {h.scheme_name}: no AMFI code")
            continue

        # Check cache first (24h TTL)
        cached = get_cached_nav(h.amfi_code)
        if cached:
            log.debug(f"Cache hit for {h.amfi_code}: NAV={cached}")
            _apply_nav(h, cached)
            continue

        # Fetch from mfdata.in
        try:
            data = _fetch_scheme(h.amfi_code)
            if data:
                nav = float(data.get("nav", 0))
                expense = float(data.get("expense_ratio", 0)) / 100  # API returns percentage
                log.info(f"AMFI {h.amfi_code}: NAV={nav}, ER={expense*100:.2f}%, category={data.get('category')}")
                save_nav_cache(h.amfi_code, nav, data.get("name", ""))
                _apply_nav(h, nav)
                if expense > 0:
                    h.expense_ratio = expense
                    h.annual_expense = h.current_value * expense
            else:
                log.warning(f"No data for AMFI {h.amfi_code}")
        except Exception as e:
            log.warning(f"mfdata.in fetch failed for {h.amfi_code}: {e}")

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


def _apply_nav(h: MFHolding, nav: float):
    """Update holding with fresh NAV data."""
    h.nav = nav
    h.current_value = h.units * nav
    if h.expense_ratio > 0:
        h.annual_expense = h.current_value * h.expense_ratio
