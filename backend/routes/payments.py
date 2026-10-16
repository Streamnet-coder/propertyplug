from emergentintegrations.payments.stripe.checkout import StripeCheckout, CheckoutSessionRequest
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional
from bson import ObjectId
from core import db, logger, now_iso, STRIPE_API_KEY, PRO_TIERS
from models import User
from deps import real_user

router = APIRouter()


class CheckoutIn(BaseModel):
    origin_url: str
    tier: Literal["monthly", "yearly", "lifetime"] = "monthly"


@router.get("/payments/tiers")
async def tiers():
    return [{"id": k, **v} for k, v in PRO_TIERS.items()]


def stripe_client(request: Request):
    host = str(request.base_url).rstrip("/")
    return StripeCheckout(api_key=STRIPE_API_KEY, webhook_url=f"{host}/api/webhook/stripe")


@router.post("/payments/checkout")
async def create_checkout(body: CheckoutIn, request: Request, user: User = Depends(real_user)):
    if user.pro_tier == "lifetime" and user.plan == "pro":
        raise HTTPException(400, "You already have lifetime Pro")
    price = PRO_TIERS[body.tier]["price"]  # amount always from the server, never the client
    sc = stripe_client(request)
    origin = body.origin_url.rstrip("/")
    req = CheckoutSessionRequest(amount=price, currency="gbp",
                                 success_url=f"{origin}/api/payments/done?session_id={{CHECKOUT_SESSION_ID}}",
                                 cancel_url=f"{origin}/api/payments/done?cancelled=1",
                                 metadata={"user_id": user.id, "plan": "pro", "tier": body.tier})
    s = await sc.create_checkout_session(req)
    await db.payment_transactions.insert_one({"session_id": s.session_id, "user_id": user.id, "amount": price,
                                              "currency": "gbp", "metadata": {"plan": "pro", "tier": body.tier}, "payment_status": "initiated",
                                              "created_at": now_iso()})
    return {"url": s.url, "session_id": s.session_id}


async def mark_paid(session_id: str):
    tx = await db.payment_transactions.find_one({"session_id": session_id})
    if not tx or tx.get("payment_status") == "paid":
        return
    await db.payment_transactions.update_one({"session_id": session_id}, {"$set": {"payment_status": "paid", "paid_at": now_iso()}})
    tier = (tx.get("metadata") or {}).get("tier", "lifetime")  # pre-tier purchases were one-off lifetime upgrades
    u = await db.users.find_one({"_id": ObjectId(tx["user_id"])}, {"pro_until": 1, "pro_tier": 1})
    upd = {"plan": "pro", "paid_pro": True, "pro_tier": tier}
    days = PRO_TIERS[tier]["days"]
    if days is None:
        upd["pro_until"] = None
    elif (u or {}).get("pro_tier") != "lifetime":
        now = datetime.now(timezone.utc)
        cur = (u or {}).get("pro_until")
        base = max(now, datetime.fromisoformat(cur)) if cur else now  # renewing early stacks on the remaining time
        upd["pro_until"] = (base + timedelta(days=days)).isoformat()
    else:
        upd.pop("pro_tier")
    await db.users.update_one({"_id": ObjectId(tx["user_id"])}, {"$set": upd})


@router.get("/payments/status/{session_id}")
async def payment_status(session_id: str, request: Request, user: User = Depends(real_user)):
    tx = await db.payment_transactions.find_one({"session_id": session_id, "user_id": user.id})
    if not tx:
        raise HTTPException(404, "Payment not found")
    st = await stripe_client(request).get_checkout_status(session_id)
    if st.payment_status == "paid":
        await mark_paid(session_id)
    elif st.status == "expired":
        await db.payment_transactions.update_one({"session_id": session_id}, {"$set": {"payment_status": "expired"}})
    return {"status": st.status, "payment_status": st.payment_status}


@router.get("/payments/done", response_class=HTMLResponse)
async def payment_done(session_id: Optional[str] = None, cancelled: Optional[str] = None):
    msg = "Payment cancelled." if cancelled else "Payment received! You can now return to Builder Assist."
    return f"<html><body style='font-family:sans-serif;text-align:center;padding:60px'><h2>{msg}</h2></body></html>"


@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    body = await request.body()
    try:
        ev = await stripe_client(request).handle_webhook(body, request.headers.get("Stripe-Signature"))
        if ev.payment_status == "paid" and ev.session_id:
            await mark_paid(ev.session_id)
    except Exception as e:
        logger.warning(f"Webhook error: {e}")
    return {"received": True}
