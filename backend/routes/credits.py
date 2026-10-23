"""Monthly credits for Basic (free) users: 100 credits a month spent on data tools; Pro is unlimited.
Repeat look-ups of the same thing within 24 hours are free so refreshes don't burn credits."""
from datetime import date, datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Literal

from core import db
from deps import current_user, real_user
from models import User

router = APIRouter()
ALLOWANCE = 100
COSTS = {"sold_prices": 5, "rent_comps": 2, "epc": 2, "ai_estimate": 10}
# One-off top-up packs (GBP). Top-up credits never expire and are used after the monthly allowance.
PACKS = {"small": {"credits": 50, "price": 2.99}, "medium": {"credits": 150, "price": 6.99}, "large": {"credits": 500, "price": 14.99}}
LABELS = {"sold_prices": "Sold prices search", "rent_comps": "Rent comparables", "epc": "EPC lookup", "ai_estimate": "AI cost estimate"}


def _period() -> str:
    return date.today().strftime("%Y-%m")


def _resets_on() -> str:
    t = date.today()
    return (date(t.year + 1, 1, 1) if t.month == 12 else date(t.year, t.month + 1, 1)).isoformat()


async def used_this_month(uid: str) -> int:
    agg = await db.credit_log.aggregate([{"$match": {"user_id": uid, "period": _period(), "bonus": {"$ne": True}}}, {"$group": {"_id": None, "n": {"$sum": "$cost"}}}]).to_list(1)
    return agg[0]["n"] if agg else 0


async def charge(user: User, tool: str, key: str = ""):
    """Spend credits for a tool use (no-op for Pro). Raises 402 with an upgrade prompt when the month's allowance is used up."""
    if user.plan == "pro":
        return
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    if await db.credit_log.find_one({"user_id": user.id, "tool": tool, "key": key, "at": {"$gt": since}}):
        return
    cost = COSTS[tool]
    bonus = False
    if await used_this_month(user.id) + cost > ALLOWANCE:
        # Spend top-up credits atomically; only succeeds if enough are left.
        r = await db.users.update_one({"_id": ObjectId(user.id), "bonus_credits": {"$gte": cost}}, {"$inc": {"bonus_credits": -cost}})
        if not r.modified_count:
            raise HTTPException(402, f"You've used your {ALLOWANCE} free credits this month. Upgrade to Pro for unlimited access, buy a credit top-up, or wait until they reset on {_resets_on()}")
        bonus = True
    await db.credit_log.insert_one({"user_id": user.id, "tool": tool, "key": key, "cost": cost, "bonus": bonus, "period": _period(), "at": datetime.now(timezone.utc).isoformat()})


@router.get("/credits")
async def credits(user: User = Depends(current_user)):
    used = await used_this_month(user.id)
    bonus = int((await db.users.find_one({"_id": ObjectId(user.id)}, {"bonus_credits": 1}) or {}).get("bonus_credits") or 0)
    recent = [{"tool": LABELS.get(x["tool"], x["tool"]), "cost": x["cost"], "at": x["at"], "bonus": bool(x.get("bonus"))}
              async for x in db.credit_log.find({"user_id": user.id, "period": _period()}).sort("at", -1).limit(10)]
    return {"unlimited": user.plan == "pro", "allowance": ALLOWANCE, "used": used, "remaining": max(0, ALLOWANCE - used), "resets_on": _resets_on(),
            "bonus": bonus, "total_remaining": max(0, ALLOWANCE - used) + bonus,
            "costs": [{"tool": LABELS[k], "cost": v} for k, v in COSTS.items()], "recent": recent,
            "packs": [{"id": k, **v} for k, v in PACKS.items()]}


class TopUpIn(BaseModel):
    origin_url: str
    pack: Literal["small", "medium", "large"]


@router.post("/credits/checkout")
async def topup_checkout(body: TopUpIn, request: Request, user: User = Depends(real_user)):
    """One-off Stripe checkout for a credit pack; credits land via routes.payments.mark_paid (status polling or webhook)."""
    from emergentintegrations.payments.stripe.checkout import CheckoutSessionRequest
    from core import now_iso
    from routes.payments import stripe_client
    pk = PACKS[body.pack]
    origin = body.origin_url.rstrip("/")
    req = CheckoutSessionRequest(amount=pk["price"], currency="gbp", success_url=f"{origin}/api/payments/done?session_id={{CHECKOUT_SESSION_ID}}",
                                 cancel_url=f"{origin}/api/payments/done?cancelled=1", metadata={"user_id": user.id, "kind": "credits", "pack": body.pack})
    s = await stripe_client(request).create_checkout_session(req)
    await db.payment_transactions.insert_one({"session_id": s.session_id, "user_id": user.id, "amount": pk["price"], "currency": "gbp",
                                              "metadata": {"kind": "credits", "pack": body.pack, "credits": pk["credits"]}, "payment_status": "initiated", "created_at": now_iso()})
    return {"url": s.url, "session_id": s.session_id}
