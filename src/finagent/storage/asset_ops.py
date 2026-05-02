"""Unified asset layer operations."""
import logging
from dataclasses import asdict
from datetime import date, datetime, timezone
from difflib import SequenceMatcher

from sqlalchemy import select, delete

from finagent.storage.database import get_db
from finagent.storage.models import UserAsset
from finagent.models.mf import MFHolding, MFTransaction

log = logging.getLogger("finagent.storage")


def _scheme_match(verified_name: str, declared_name: str) -> bool:
    """Fuzzy-match scheme names. Handles 'Parag Parikh Flexi Cap' vs full CAS name."""
    if not verified_name or not declared_name:
        return False
    v = verified_name.lower().split(" - ")[0].strip()
    d = declared_name.lower().split(" - ")[0].strip()
    if v.startswith(d) or d.startswith(v):
        return True
    return SequenceMatcher(None, v, d).ratio() > 0.75


def _holding_to_asset_data(h: MFHolding) -> dict:
    """Convert MFHolding to dict for user_assets storage."""
    data = asdict(h)
    for t in data.get("transactions", []):
        if hasattr(t.get("date"), "isoformat"):
            t["date"] = t["date"].isoformat()
    return data


def _asset_to_holding(d: dict) -> MFHolding:
    """Convert user_assets dict → MFHolding. Handles both verified (full) and declared (partial)."""
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
    return MFHolding(
        scheme_name=d.get("scheme_name") or d.get("scheme", ""),
        folio=d.get("folio", ""),
        amc=d.get("amc", ""),
        isin=d.get("isin", ""),
        amfi_code=d.get("amfi_code", ""),
        plan=d.get("plan", ""),
        rta=d.get("rta", ""),
        units=float(d.get("units") or 0),
        nav=float(d.get("nav") or 0),
        current_value=float(d.get("current_value") or 0),
        invested_value=float(d.get("invested_value") or 0),
        expense_ratio=float(d.get("expense_ratio") or 0),
        annual_expense=float(d.get("annual_expense") or 0),
        category=d.get("category", ""),
        nav_date=d.get("nav_date", ""),
        day_change=float(d.get("day_change", 0)),
        day_change_pct=float(d.get("day_change_pct", 0)),
        morningstar=int(d.get("morningstar", 0)),
        aum=float(d.get("aum", 0)),
        risk_label=d.get("risk_label", ""),
        xirr=float(d.get("xirr", 0)),
        tax_section=d.get("tax_section", ""),
        transactions=txns,
    )


async def reconcile_and_save(user_id: int, asset_type: str, verified_items: list,
                             source_detail: str = "cas_upload") -> dict:
    """Save verified assets, reconciling against existing declared entries.

    For MF: verified_items is list[MFHolding].
    For other types: verified_items is list[dict].

    Returns {"saved": N, "replaced": N, "new": N}.
    """
    now = datetime.now(timezone.utc)
    replaced, new = 0, 0

    async with get_db() as db:
        # Load existing declared entries for this asset type
        result = await db.execute(
            select(UserAsset).where(
                UserAsset.user_id == user_id,
                UserAsset.asset_type == asset_type,
                UserAsset.source == "declared"
            )
        )
        declared_rows = result.scalars().all()

        declared = [(r.id, r.data or {}) for r in declared_rows]
        matched_ids = set()

        # Delete existing verified entries for this type (full replace on re-upload)
        await db.execute(
            delete(UserAsset).where(
                UserAsset.user_id == user_id,
                UserAsset.asset_type == asset_type,
                UserAsset.source == "verified"
            )
        )

        for item in verified_items:
            if isinstance(item, MFHolding):
                data = _holding_to_asset_data(item)
                match_name = item.scheme_name
            else:
                data = item
                match_name = item.get("scheme_name", item.get("scheme", ""))

            # Find matching declared entry
            for did, dd in declared:
                if did in matched_ids:
                    continue
                d_name = dd.get("scheme_name") or dd.get("scheme", "")
                if asset_type == "mf" and _scheme_match(match_name, d_name):
                    matched_ids.add(did)
                    replaced += 1
                    break
            else:
                new += 1

            asset = UserAsset(
                user_id=user_id,
                asset_type=asset_type,
                data=data,
                source="verified",
                source_detail=source_detail,
                verified_at=now
            )
            db.add(asset)

        # Remove matched declared entries (superseded by verified)
        for did in matched_ids:
            await db.execute(delete(UserAsset).where(UserAsset.id == did))

    total = len(verified_items)
    log.info(f"[reconcile] {asset_type}: saved {total} verified ({replaced} replaced declared, {new} new)")
    return {"saved": total, "replaced": replaced, "new": new}


async def load_mf_assets(user_id: int) -> list[MFHolding]:
    """Load all MF assets (verified + declared) as MFHolding objects.

    Single read path for all MF consumers: agent, holdings API, overview, goals.
    """
    async with get_db() as db:
        result = await db.execute(
            select(UserAsset).where(
                UserAsset.user_id == user_id,
                UserAsset.asset_type == "mf"
            )
        )
        rows = result.scalars().all()

        holdings = []
        for row in rows:
            d = row.data or {}
            d["_source"] = row.source
            h = _asset_to_holding(d)
            if h.current_value > 0 or h.units > 0 or (h.scheme_name and row.source == "declared"):
                holdings.append(h)
        return holdings


async def clear_mf_assets(user_id: int):
    """Clear all MF assets (verified + declared) for a user."""
    async with get_db() as db:
        await db.execute(
            delete(UserAsset).where(
                UserAsset.user_id == user_id,
                UserAsset.asset_type.in_(["mf", "mf_declared", "mf_sips"])
            )
        )


async def save_assets(user_id: int, asset_type: str, items: list[dict], source: str = None) -> int:
    """Save assets, replacing existing entries of the same type (and source if specified)."""
    async with get_db() as db:
        if source:
            await db.execute(
                delete(UserAsset).where(
                    UserAsset.user_id == user_id,
                    UserAsset.asset_type == asset_type,
                    UserAsset.source == source
                )
            )
            for item in items:
                asset = UserAsset(
                    user_id=user_id,
                    asset_type=asset_type,
                    data=item,
                    source=source
                )
                db.add(asset)
        else:
            await db.execute(
                delete(UserAsset).where(
                    UserAsset.user_id == user_id,
                    UserAsset.asset_type == asset_type
                )
            )
            for item in items:
                asset = UserAsset(
                    user_id=user_id,
                    asset_type=asset_type,
                    data=item
                )
                db.add(asset)
    return len(items)


async def load_assets(user_id: int, asset_type: str = None) -> list[dict]:
    """Load assets for a user, optionally filtered by type."""
    async with get_db() as db:
        query = select(UserAsset).where(UserAsset.user_id == user_id)
        if asset_type:
            query = query.where(UserAsset.asset_type == asset_type)
        result = await db.execute(query)
        rows = result.scalars().all()

        return [
            {
                "id": r.id,
                "asset_type": r.asset_type,
                **(r.data or {}),
                "updated_at": r.created_at.isoformat() if r.created_at else None
            }
            for r in rows
        ]


async def clear_assets(user_id: int):
    """Clear all user assets."""
    async with get_db() as db:
        await db.execute(delete(UserAsset).where(UserAsset.user_id == user_id))
