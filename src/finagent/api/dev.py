"""Dev routes — seed and reset for development/testing."""
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from finagent.models.goal import Goal
from finagent.storage.sqlite import reconcile_and_save, clear_mf_assets, save_goal, clear_goals
from finagent.api.deps import _DEV_MODE, _get_dev_user_id, DEMO_USER_ID

log = logging.getLogger("finagent")
router = APIRouter(tags=["dev"])


@router.post("/dev/seed")
async def dev_seed():
    if not _DEV_MODE:
        raise HTTPException(status_code=404)
    from finagent.api.holdings import demo
    from finagent.storage.sqlite import load_mf_assets
    demo_holdings = load_mf_assets(DEMO_USER_ID)
    if not demo_holdings:
        await demo()
        demo_holdings = load_mf_assets(DEMO_USER_ID)
    dev_uid = _get_dev_user_id()
    clear_mf_assets(dev_uid)
    reconcile_and_save(dev_uid, "mf", demo_holdings, source_detail="demo")
    clear_goals(dev_uid)
    sample_goals = [
        Goal(user_id=dev_uid, name="Retirement at 50", template="retirement", target_amount=5_000_000, target_date="2048-01-01",
             linked_folios=[{"folio": "DEMO-001/Parag Parikh Flexi Cap Fund - Direct Plan - Growth", "pct": 40},
                            {"folio": "DEMO-004/ICICI Prudential Balanced Advantage Fund - Direct Plan - Growth", "pct": 60}]),
        Goal(user_id=dev_uid, name="Dream Home", template="house", target_amount=3_000_000, target_date="2030-06-01",
             linked_folios=[{"folio": "DEMO-002/HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth", "pct": 50},
                            {"folio": "DEMO-006/HDFC Corporate Bond Fund - Direct Plan - Growth", "pct": 50}]),
        Goal(user_id=dev_uid, name="Emergency Fund", template="emergency", target_amount=300_000, target_date="2027-01-01",
             linked_folios=[{"folio": "DEMO-006/HDFC Corporate Bond Fund - Direct Plan - Growth", "pct": 100}]),
    ]
    for g in sample_goals:
        save_goal(g)
    log.info(f"DEV_MODE: seeded {len(demo_holdings)} holdings + {len(sample_goals)} goals for dev user {dev_uid}")
    return JSONResponse({"status": "ok", "holdings_count": len(demo_holdings), "goals_count": len(sample_goals)})


@router.post("/dev/reset")
async def dev_reset():
    if not _DEV_MODE:
        raise HTTPException(status_code=404)
    dev_uid = _get_dev_user_id()
    clear_mf_assets(dev_uid)
    clear_goals(dev_uid)
    log.info(f"DEV_MODE: cleared dev user {dev_uid}")
    return JSONResponse({"status": "ok"})
