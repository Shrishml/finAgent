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

        data = casparser.read_cas_pdf(str(file_path), password, output="dict")
        holdings = []

        for folio_data in data.get("folios", []):
            folio = folio_data.get("folio", "")
            amc = folio_data.get("amc", "")

            for scheme in folio_data.get("schemes", []):
                transactions = [
                    MFTransaction(
                        date=_parse_date(t.get("date", "")),
                        description=t.get("description", ""),
                        amount=float(t.get("amount", 0)),
                        units=_safe_float(t.get("units")),
                        nav=_safe_float(t.get("nav")),
                        balance=_safe_float(t.get("balance")),
                        type=t.get("type", ""),
                    )
                    for t in scheme.get("transactions", [])
                ]

                # Determine current units/nav from last transaction or scheme data
                units = _safe_float(scheme.get("open")) or (
                    transactions[-1].balance if transactions else 0.0
                )
                nav = _safe_float(scheme.get("close")) or (
                    transactions[-1].nav if transactions else 0.0
                )

                plan = "direct" if "direct" in scheme.get("scheme", "").lower() else "regular"

                holdings.append(MFHolding(
                    scheme_name=scheme.get("scheme", ""),
                    folio=folio,
                    amc=amc,
                    isin=scheme.get("isin", ""),
                    amfi_code=scheme.get("amfi", ""),
                    plan=plan,
                    rta=scheme.get("rta", ""),
                    units=units,
                    nav=nav,
                    current_value=units * nav if units and nav else 0.0,
                    transactions=transactions,
                ))

        return holdings


def _parse_date(val) -> datetime:
    if isinstance(val, datetime):
        return val.date() if hasattr(val, 'date') else val
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
