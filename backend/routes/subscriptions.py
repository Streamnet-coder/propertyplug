"""Auto-renewing Pro subscriptions (monthly/yearly) on the owner's own Stripe account via the official SDK.
Stripe is the source of truth: webhook events are only used as hints and every update re-fetches the subscription."""
import os
from datetime import datetime, timezone

import stripe
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from core import db, logger, now_iso, PRO_TIERS
from deps import real_user
from models import User

router = APIRouter()
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
INTERVAL = {"monthly": "month", "yearly": "year"}
ACTIVE = ("active", "trialing", "past_due")  # past_due keeps access while Stripe retries the card


def _period_end(sub) -> int | None:
    # Newer Stripe API versions moved current_period_end onto the subscription items.
    end = sub.get("current_period_end")
    if not end:
        items = (sub.get("items") or {}).get("data") or []
        end = items[0].get("current_period_end") if items else None
    return end


async def sync_subscription(sub_id: str) -> dict | None:
    """Pull the subscription from Stripe and mirror it onto the user. Returns the updated user fields."""
    sub = await run_in_threadpool(stripe.Subscription.retrieve, sub_id)
    uid = (sub.get("metadata") or {}).get("user_id")
    u = await db.users.find_one({"_id": ObjectId(uid)}) if uid and ObjectId.is_valid(uid) else await db.users.find_one({"stripe_subscription_id": sub_id})
    if not u:
        logger.warning(f"Subscription {sub_id} has no matching user")
        return None
    if u.get("pro_tier") == "lifetime" and u.get("plan") == "pro":
        return None  # lifetime wins; any leftover subscription is cancelled at lifetime purchase
    tier = (sub.get("metadata") or {}).get("tier") or u.get("pro_tier") or "monthly"
    end = _period_end(sub)
    upd = {"stripe_subscription_id": sub_id, "stripe_customer_id": sub.get("customer"), "sub_status": sub["status"],
           "cancel_at_period_end": bool(sub.get("cancel_at_period_end")), "pro_tier": tier,
           "pro_until": datetime.fromtimestamp(end, timezone.utc).isoformat() if end else u.get("pro_until")}
    if sub["status"] in ACTIVE:
        upd.update(plan="pro", paid_pro=True)
    elif sub["status"] in ("canceled", "unpaid", "incomplete_expired"):
        upd["plan"] = "basic"
    await db.users.update_one({"_id": u["_id"]}, {"$set": upd})
    return upd


async def refresh_if_lapsed(u: User) -> bool:
    """Called when a subscriber's paid period has passed: renewals may have happened. True if still Pro."""
    if not (u.stripe_subscription_id and stripe.api_key):
        return False
    try:
        upd = await sync_subscription(u.stripe_subscription_id)
    except Exception as e:
        logger.warning(f"Subscription refresh failed: {e}")
        return True  # don't downgrade because Stripe was unreachable
    return bool(upd and upd.get("plan") == "pro" and upd["pro_until"] > datetime.now(timezone.utc).isoformat())


async def create_subscription_checkout(user: User, tier: str, origin: str) -> dict:
    if not stripe.api_key:
        raise HTTPException(503, "Subscriptions aren't set up yet")
    if user.stripe_subscription_id and user.sub_status in ACTIVE and not user.cancel_at_period_end:
        raise HTTPException(400, "You already have an auto-renewing plan. Manage it below")
    t = PRO_TIERS[tier]
    params = dict(
        mode="subscription",
        line_items=[{"quantity": 1, "price_data": {"currency": "gbp", "unit_amount": round(t["price"] * 100), "recurring": {"interval": INTERVAL[tier]},
                                                  "product_data": {"name": f"Builder Assist Pro ({t['label']})"}}}],
        success_url=f"{origin}/api/payments/done?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{origin}/api/payments/done?cancelled=1",
        client_reference_id=user.id,
        metadata={"user_id": user.id, "tier": tier},
        subscription_data={"metadata": {"user_id": user.id, "tier": tier}},
    )
    if user.stripe_customer_id:
        params["customer"] = user.stripe_customer_id
    else:
        params["customer_email"] = user.email
    s = await run_in_threadpool(lambda: stripe.checkout.Session.create(**params))
    await db.payment_transactions.insert_one({"session_id": s.id, "user_id": user.id, "amount": t["price"], "currency": "gbp", "kind": "subscription",
                                              "metadata": {"plan": "pro", "tier": tier}, "payment_status": "initiated", "created_at": now_iso()})
    return {"url": s.url, "session_id": s.id}


async def subscription_session_status(tx: dict) -> dict:
    s = await run_in_threadpool(stripe.checkout.Session.retrieve, tx["session_id"])
    if s.status == "complete" and s.get("subscription"):
        await sync_subscription(s["subscription"])
        await db.payment_transactions.update_one({"_id": tx["_id"]}, {"$set": {"payment_status": "paid", "paid_at": now_iso()}})
        return {"status": "complete", "payment_status": "paid"}
    if s.status == "expired":
        await db.payment_transactions.update_one({"_id": tx["_id"]}, {"$set": {"payment_status": "expired"}})
    return {"status": s.status, "payment_status": s.payment_status}


async def cancel_subscription_now(sub_id: str):
    try:
        await run_in_threadpool(stripe.Subscription.cancel, sub_id)
    except Exception as e:
        logger.warning(f"Could not cancel subscription {sub_id}: {e}")


async def _set_auto_renew(user: User, on: bool):
    if not user.stripe_subscription_id:
        raise HTTPException(404, "No subscription")
    await run_in_threadpool(lambda: stripe.Subscription.modify(user.stripe_subscription_id, cancel_at_period_end=not on))
    return await sync_subscription(user.stripe_subscription_id)


@router.post("/payments/subscription/cancel")
async def cancel_auto_renew(user: User = Depends(real_user)):
    """Stops renewal; Pro stays until the end of the period already paid for."""
    return await _set_auto_renew(user, False)


@router.post("/payments/subscription/resume")
async def resume_auto_renew(user: User = Depends(real_user)):
    return await _set_auto_renew(user, True)


@router.post("/webhook/stripe-subscriptions")
async def subscription_webhook(request: Request):
    payload = await request.body()
    try:
        if WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(payload, request.headers.get("stripe-signature"), WEBHOOK_SECRET)
        else:
            event = stripe.Event.construct_from(__import__("json").loads(payload), stripe.api_key)
    except Exception:
        raise HTTPException(400, "Invalid webhook")
    if await db.stripe_events.find_one({"_id": event["id"]}):
        return {"received": True}
    obj = event["data"]["object"]
    sub_id = obj.get("subscription") if event["type"].startswith(("checkout.", "invoice.")) else obj.get("id")
    if isinstance(sub_id, dict):
        sub_id = sub_id.get("id")
    if sub_id and event["type"] in ("checkout.session.completed", "customer.subscription.updated", "customer.subscription.deleted",
                                    "invoice.payment_succeeded", "invoice.paid", "invoice.payment_failed"):
        try:
            await sync_subscription(sub_id)  # re-fetched from Stripe, so an unsigned/forged payload can't grant access
        except Exception as e:
            logger.warning(f"Webhook sync failed: {e}")
            raise HTTPException(500, "Retry later")
    await db.stripe_events.insert_one({"_id": event["id"], "type": event["type"], "at": now_iso()})
    return {"received": True}


# ---------------- Billing history ----------------
from fastapi import Query  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from core import E  # noqa: E402
from deps import load_user, decode_uid  # noqa: E402


@router.get("/payments/history")
async def billing_history(user: User = Depends(real_user)):
    """One-off Pro payments recorded here + Stripe invoices for auto-renewing plans (with Stripe's own receipt links)."""
    out = []
    async for t in db.payment_transactions.find({"user_id": user.id, "payment_status": "paid", "kind": {"$ne": "subscription"}}).sort("created_at", -1):
        tier = (t.get("metadata") or {}).get("tier", "lifetime")
        out.append({"id": t["session_id"], "date": t.get("paid_at") or t["created_at"], "description": f"Builder Assist Pro ({PRO_TIERS.get(tier, PRO_TIERS['lifetime'])['label']})",
                    "amount": float(t["amount"]), "currency": t.get("currency", "gbp").upper(), "status": "paid", "receipt": "local", "url": None})
    if user.stripe_customer_id and stripe.api_key:
        try:
            inv = await run_in_threadpool(lambda: stripe.Invoice.list(customer=user.stripe_customer_id, limit=50))
            for i in inv.auto_paging_iter():
                if i.status in ("paid", "open", "uncollectible"):
                    line = (i.lines.data[0].description if i.lines and i.lines.data else None) or "Builder Assist Pro"
                    out.append({"id": i.id, "date": datetime.fromtimestamp(i.created, timezone.utc).isoformat(), "description": line,
                                "amount": i.amount_paid / 100 if i.status == "paid" else i.amount_due / 100, "currency": i.currency.upper(),
                                "status": "paid" if i.status == "paid" else "failed" if i.status == "uncollectible" else "due",
                                "receipt": "stripe", "url": i.hosted_invoice_url or i.invoice_pdf})
        except Exception as e:
            logger.warning(f"Invoice list failed: {e}")
    return sorted(out, key=lambda x: x["date"], reverse=True)


@router.get("/payments/receipt/{session_id}", response_class=HTMLResponse)
async def receipt_page(session_id: str, t: str = Query(...)):
    """Printable receipt for one-off payments (Stripe invoices use Stripe's hosted receipt instead)."""
    user = await load_user(decode_uid(t))
    tx = await db.payment_transactions.find_one({"session_id": session_id, "user_id": user.id, "payment_status": "paid"})
    if not tx:
        raise HTTPException(404, "Receipt not found")
    tier = (tx.get("metadata") or {}).get("tier", "lifetime")
    d = datetime.fromisoformat(tx.get("paid_at") or tx["created_at"]).strftime("%d %B %Y")
    return HTMLResponse(f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Receipt</title>
<style>body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#0f172a;max-width:560px;margin:24px auto;padding:0 16px}}h1{{color:#0f766e}}
table{{width:100%;border-collapse:collapse;margin:16px 0}}td{{padding:10px 0;border-bottom:1px solid #e2e8f0}}.r{{text-align:right}}.cap{{color:#64748b;font-size:13px}}button{{padding:10px 16px;border-radius:8px;border:0;background:#0f766e;color:#fff;font-weight:600}}@media print{{button{{display:none}}}}</style></head>
<body><h1>Builder Assist</h1><h2>Receipt</h2><p class="cap">Receipt no. {E(session_id[-12:].upper())} · {d}</p>
<p><b>Billed to</b><br>{E(user.name)}<br>{E(user.email)}</p>
<table><tr><td>Builder Assist Pro ({E(PRO_TIERS.get(tier, PRO_TIERS['lifetime'])['label'])})</td><td class="r">£{float(tx['amount']):,.2f}</td></tr>
<tr><td><b>Total paid</b></td><td class="r"><b>£{float(tx['amount']):,.2f}</b></td></tr></table>
<p class="cap">Paid by card via Stripe. Status: paid.</p><button onclick="window.print()">Print / save as PDF</button></body></html>""")
