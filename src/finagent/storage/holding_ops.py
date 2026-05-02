"""Legacy holdings operations (migrated to user_assets)."""
import logging
from dataclasses import asdict
from datetime import date

from sqlalchemy import select, delete

from finagent.storage.database import get_db
from finagent.storage.models import Holding
from finagent.models.mf import MFHolding, MFTransaction

log = logging.getLogger("finagent.storage")


def _merge_transactions(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Merge transaction lists, dedup by (date, amount, units)."""
    seen = {(t.get("date"), t.get("amount"), t.get("units")) for t in existing}
    merged = list(existing)
    for t in incoming:
        key = (t.get("date"), t.get("amount"), t.get("units"))
        if key not in seen:
            seen.add(key)
            merged.append(t)
    merged.sort(key=lambda t: t.get("date", ""))
    return merged


async def save_holdings(holdings: list[MFHolding], user_id: int | None = None, merge: bool = False):
    """Upsert holdings. If merge=True, merge transactions with existing data."""
    async with get_db() as db:
        for h in holdings:
            data = asdict(h)
            for t in data.get("transactions", []):
                if hasattr(t.get("date"), "isoformat"):
                    t["date"] = t["date"].isoformat()

            if merge:
                result = await db.execute(
                    select(Holding).where(
                        Holding.user_id == user_id,
                        Holding.folio == h.folio,
                        Holding.scheme_name == h.scheme_name
                    )
                )
                existing = result.scalar_one_or_none()
                if existing:
                    old = existing.data or {}
                    data["transactions"] = _merge_transactions(
                        old.get("transactions", []), data.get("transactions", [])
                    )

            # Upsert
            result = await db.execute(
                select(Holding).where(
                    Holding.user_id == user_id,
                    Holding.folio == h.folio,
                    Holding.scheme_name == h.scheme_name
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.data = data
            else:
                new_holding = Holding(
                    user_id=user_id,
                    folio=h.folio,
                    scheme_name=h.scheme_name,
                    data=data
                )
                db.add(new_holding)


async def load_holdings(user_id: int | None = None) -> list[MFHolding]:
    """Load stored holdings for a user (or all if no user_id)."""
    async with get_db() as db:
        if user_id is not None:
            result = await db.execute(select(Holding).where(Holding.user_id == user_id))
        else:
            result = await db.execute(select(Holding).where(Holding.user_id.is_(None)))

        rows = result.scalars().all()
        holdings = []
        for row in rows:
            d = row.data or {}
            txns = [
                MFTransaction(
                    date=date.fromisoformat(t["date"]) if isinstance(t.get("date"), str) else t.get("date", date.today()),
                    description=t.get("description", ""),
                    amount=float(t.get("amount", 0)),
                    units=t.get("units"),
                    nav=t.get("nav"),
                    balance=t.get("balance"),
                    type=t.get("type", ""),
                )
                for t in d.get("transactions", [])
            ]
            holdings.append(MFHolding(
                scheme_name=d["scheme_name"], folio=d["folio"], amc=d["amc"],
                isin=d.get("isin", ""), amfi_code=d.get("amfi_code", ""),
                plan=d.get("plan", ""), rta=d.get("rta", ""),
                units=d.get("units", 0), nav=d.get("nav", 0),
                current_value=d.get("current_value", 0),
                invested_value=d.get("invested_value", 0),
                expense_ratio=d.get("expense_ratio", 0),
                annual_expense=d.get("annual_expense", 0),
                xirr=d.get("xirr", 0), tax_section=d.get("tax_section", ""),
                category=d.get("category", ""),
                nav_date=d.get("nav_date", ""),
                day_change=d.get("day_change", 0),
                day_change_pct=d.get("day_change_pct", 0),
                morningstar=d.get("morningstar", 0),
                aum=d.get("aum", 0),
                risk_label=d.get("risk_label", ""),
                transactions=txns,
            ))
        return [h for h in holdings if h.current_value > 0]


async def clear_holdings(user_id: int | None = None):
    """Clear holdings for a user (or legacy null-user holdings)."""
    async with get_db() as db:
        if user_id is not None:
            await db.execute(delete(Holding).where(Holding.user_id == user_id))
        else:
            await db.execute(delete(Holding).where(Holding.user_id.is_(None)))
