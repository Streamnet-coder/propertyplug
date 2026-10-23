"""Monthly credits for Basic (free) users: 100 credits a month spent on data tools; Pro is unlimited.
Repeat look-ups of the same thing within 24 hours are free so refreshes don't burn credits."""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from core import db
from deps import current_user
from models import User

router = APIRouter()
ALLOWANCE = 100
COSTS = {"sold_prices": 5, "rent_comps": 2, "epc": 2, "ai_estimate": 10}
LABELS = {"sold_prices": "Sold prices search", "rent_comps": "Rent comparables", "epc": "EPC lookup", "ai_estimate": "AI cost estimate"}


def _period() -> str:
    return date.today().strftime("%Y-%m")


def _resets_on() -> str:
    t = date.today()
    return (date(t.year + 1, 1, 1) if t.month == 12 else date(t.year, t.month + 1, 1)).isoformat()


async def used_this_month(uid: str) -> int:
    agg = await db.credit_log.aggregate([{"$match": {"user_id": uid, "period": _period()}}, {"$group": {"_id": None, "n": {"$sum": "$cost"}}}]).to_list(1)
    return agg[0]["n"] if agg else 0


async def charge(user: User, tool: str, key: str = ""):
    """Spend credits for a tool use (no-op for Pro). Raises 402 with an upgrade prompt when the month's allowance is used up."""
    if user.plan == "pro":
        return
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    if await db.credit_log.find_one({"user_id": user.id, "tool": tool, "key": key, "at": {"$gt": since}}):
        return
    cost = COSTS[tool]
    if await used_this_month(user.id) + cost > ALLOWANCE:
        raise HTTPException(402, f"You've used your {ALLOWANCE} free credits this month. Upgrade to Pro for unlimited access, or wait until they reset on {_resets_on()}")
    await db.credit_log.insert_one({"user_id": user.id, "tool": tool, "key": key, "cost": cost, "period": _period(), "at": datetime.now(timezone.utc).isoformat()})


@router.get("/credits")
async def credits(user: User = Depends(current_user)):
    used = await used_this_month(user.id)
    recent = [{"tool": LABELS.get(x["tool"], x["tool"]), "cost": x["cost"], "at": x["at"]}
              async for x in db.credit_log.find({"user_id": user.id, "period": _period()}).sort("at", -1).limit(10)]
    return {"unlimited": user.plan == "pro", "allowance": ALLOWANCE, "used": used, "remaining": max(0, ALLOWANCE - used), "resets_on": _resets_on(),
            "costs": [{"tool": LABELS[k], "cost": v} for k, v in COSTS.items()], "recent": recent}
