"""AMFI enrichment: fetch live NAV and metadata for holdings via mftool."""
import logging

from finagent.models.mf import MFHolding
from finagent.storage.sqlite import save_nav_cache, get_cached_nav

log = logging.getLogger("finagent.enrichment.amfi")


def enrich_holdings(holdings: list[MFHolding]) -> list[MFHolding]:
    """Enrich holdings with live NAV from AMFI. Updates current_value and annual_expense."""
    from mftool import Mftool
    mf = Mftool()

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

        # Fetch from AMFI
        try:
            quote = mf.get_scheme_quote(h.amfi_code)
            if quote and "nav" in quote:
                nav = float(quote["nav"])
                log.info(f"AMFI {h.amfi_code} ({h.scheme_name}): NAV={nav}")
                save_nav_cache(h.amfi_code, nav, quote.get("scheme_name", ""))
                _apply_nav(h, nav)
            else:
                log.warning(f"No NAV data for AMFI {h.amfi_code}")
        except Exception as e:
            log.warning(f"AMFI fetch failed for {h.amfi_code}: {e}")

    return holdings


def _apply_nav(h: MFHolding, nav: float):
    """Update holding with fresh NAV data."""
    h.nav = nav
    h.current_value = h.units * nav
    # Estimate annual expense if we have expense_ratio
    if h.expense_ratio > 0:
        h.annual_expense = h.current_value * h.expense_ratio
