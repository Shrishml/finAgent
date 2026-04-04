"""CAMS/KFintech CAS PDF connector using casparser."""
from datetime import datetime
from pathlib import Path

from .base import Connector
from finagent.models.mf import MFHolding, MFTransaction


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

        for folio_obj in data.folios:
            folio = folio_obj.folio or ""
            amc = folio_obj.amc or ""

            for scheme in folio_obj.schemes:
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

                units = _safe_float(scheme.open) or (
                    transactions[-1].balance if transactions else 0.0
                )
                nav = _safe_float(scheme.close) or (
                    transactions[-1].nav if transactions else 0.0
                )

                scheme_name = scheme.scheme or ""
                plan = "direct" if "direct" in scheme_name.lower() else "regular"
                value = _safe_float(scheme.valuation) or (units * nav if units and nav else 0.0)

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
                    transactions=transactions,
                ))

        return holdings


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
