from emergentintegrations.payments.stripe.checkout import StripeCheckout, CheckoutSessionRequest
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from bson import ObjectId
from core import db, logger, now_iso, STRIPE_API_KEY, PRO_PRICE_GBP
from models import User
from deps import current_user

router = APIRouter()


class CheckoutIn(BaseModel):
    origin_url: str


def stripe_client(request: Request):
    host = str(request.base_url).rstrip("/")
    return StripeCheckout(api_key=STRIPE_API_KEY, webhook_url=f"{host}/api/webhook/stripe")


@router.post("/payments/checkout")
async def create_checkout(body: CheckoutIn, request: Request, user: User = Depends(current_user)):
    sc = stripe_client(request)
    origin = body.origin_url.rstrip("/")
    req = CheckoutSessionRequest(amount=PRO_PRICE_GBP, currency="gbp",
                                 success_url=f"{origin}/api/payments/done?session_id={{CHECKOUT_SESSION_ID}}",
                                 cancel_url=f"{origin}/api/payments/done?cancelled=1",
                                 metadata={"user_id": user.id, "plan": "pro"})
    s = await sc.create_checkout_session(req)
    await db.payment_transactions.insert_one({"session_id": s.session_id, "user_id": user.id, "amount": PRO_PRICE_GBP,
                                              "currency": "gbp", "metadata": {"plan": "pro"}, "payment_status": "initiated",
                                              "created_at": now_iso()})
    return {"url": s.url, "session_id": s.session_id}


async def mark_paid(session_id: str):
    tx = await db.payment_transactions.find_one({"session_id": session_id})
    if not tx or tx.get("payment_status") == "paid":
        return
    await db.payment_transactions.update_one({"session_id": session_id}, {"$set": {"payment_status": "paid", "paid_at": now_iso()}})
    await db.users.update_one({"_id": ObjectId(tx["user_id"])}, {"$set": {"plan": "pro", "paid_pro": True}})


@router.get("/payments/status/{session_id}")
async def payment_status(session_id: str, request: Request, user: User = Depends(current_user)):
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
