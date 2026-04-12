"""CAMS/KFintech CAS PDF connector using casparser."""
import logging
from datetime import datetime
from pathlib import Path

from .base import Connector
from finagent.models.mf import MFHolding, MFTransaction

log = logging.getLogger("finagent.connector.cams")


class CAMSConnector(Connector):
    """Parses CAMS and KFintech Consolidated Account Statement PDFs."""

    def detect(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".pdf"

    def target_domain(self) -> str:
        return "mf"

    def parse(self, file_path: Path, password: str = "") -> list[MFHolding]:
        import casparser

        data = casparser.read_cas_pdf(str(file_path), password)
        holdings = []

        log.debug("=== RAW CASPARSER OUTPUT ===")
        log.debug(f"CAS type: {data.cas_type}, File type: {data.file_type}")
        log.debug(f"Period: {data.statement_period}")
        log.debug(f"Investor: {data.investor_info}")
        log.debug(f"Number of folios: {len(data.folios)}")

        for folio_obj in data.folios:
            folio = folio_obj.folio or ""
            amc = folio_obj.amc or ""
            log.debug(f"\n--- Folio: {folio} | AMC: {amc} ---")
            log.debug(f"  Schemes in folio: {len(folio_obj.schemes)}")

            for scheme in folio_obj.schemes:
                log.debug(f"  Scheme: {scheme.scheme}")
                log.debug(f"    ISIN: {scheme.isin} | AMFI: {scheme.amfi} | RTA: {scheme.rta}")
                log.debug(f"    open(units): {scheme.open} | close(nav): {scheme.close}")
                log.debug(f"    close_calculated: {scheme.close_calculated} | valuation: {scheme.valuation}")
                log.debug(f"    Transactions: {len(scheme.transactions or [])}")
                for i, t in enumerate(scheme.transactions or []):
                    log.debug(f"      [{i}] {t.date} | {t.type} | amt={t.amount} | units={t.units} | nav={t.nav} | bal={t.balance}")

                transactions = [
                    MFTransaction(
                        date=_parse_date(t.date),
                        description=t.description or "",
                        amount=float(t.amount or 0),
                        units=_safe_float(t.units),
                        nav=_safe_float(t.nav),
                        balance=_safe_float(t.balance),
                        type=t.type or "",
                    )
                    for t in (scheme.transactions or [])
                ]

                units = _safe_float(scheme.close) or _safe_float(scheme.close_calculated) or (
                    transactions[-1].balance if transactions else 0.0
                )

                # NAV and value come from the valuation object
                val = scheme.valuation
                if val:
                    nav = _safe_float(getattr(val, 'nav', None))
                    value = _safe_float(getattr(val, 'value', None))
                    invested = _safe_float(getattr(val, 'cost', None))
                else:
                    nav = transactions[-1].nav if transactions else 0.0
                    value = units * nav if units and nav else 0.0
                    invested = 0.0

                scheme_name = scheme.scheme or ""
                plan = "direct" if "direct" in scheme_name.lower() else "regular"

                holdings.append(MFHolding(
                    scheme_name=scheme_name,
                    folio=folio,
                    amc=amc,
                    isin=scheme.isin or "",
                    amfi_code=scheme.amfi or "",
                    plan=plan,
                    rta=scheme.rta or "",
                    units=units,
                    nav=nav,
                    current_value=value,
                    invested_value=invested,
                    transactions=transactions,
                ))
                log.debug(f"    → MFHolding: units={units}, nav={nav}, value={value}, plan={plan}")

        log.debug(f"\n=== TOTAL: {len(holdings)} holdings parsed ===")
        return _merge_by_isin(holdings)


def _merge_by_isin(holdings: list[MFHolding]) -> list[MFHolding]:
    """Merge holdings with same ISIN (same fund across multiple folios)."""
    by_isin: dict[str, MFHolding] = {}
    for h in holdings:
        key = h.isin or f"{h.scheme_name}:{h.folio}"  # fallback if no ISIN
        if key in by_isin:
            existing = by_isin[key]
            existing.units += h.units
            existing.current_value += h.current_value
            existing.invested_value += h.invested_value
            existing.transactions.extend(h.transactions)
            existing.folio = f"{existing.folio},{h.folio}"
            log.info(f"Merged duplicate ISIN {h.isin}: {h.scheme_name} (folios: {existing.folio})")
        else:
            by_isin[key] = h
    merged = list(by_isin.values())
    if len(merged) < len(holdings):
        log.info(f"Merged {len(holdings)} → {len(merged)} holdings (deduplicated by ISIN)")
    return merged


def _parse_date(val) -> datetime:
    if val is None:
        return datetime(1970, 1, 1).date()
    if hasattr(val, 'date'):
        return val.date() if callable(getattr(val, 'date')) else val
    if hasattr(val, 'year'):
        return val
    if isinstance(val, str) and val:
        for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(val, fmt).date()
            except ValueError:
                continue
    return datetime(1970, 1, 1).date()


def _safe_float(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0
