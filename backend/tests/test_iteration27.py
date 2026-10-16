"""Iteration 27 — Auto-renewing Pro subscriptions (monthly/yearly) via live Stripe + /subscription/cancel|resume endpoints + webhook safety.

CRITICAL: Stripe key is LIVE. Only create checkout sessions and EXPIRE them immediately. Never complete a payment.
Scope:
- POST /api/payments/checkout tier=monthly|yearly -> returns url + session_id for mode=subscription with amount 1999/19900 GBP (verified via stripe.checkout.Session.retrieve). Session expired afterwards.
- POST /api/payments/checkout tier=lifetime -> still one-off (emergentintegrations flow, mode=payment).
- GET /api/payments/status/{session_id} for open subscription session -> status open/unpaid; NOT grant Pro.
- POST /api/payments/subscription/cancel|resume -> 404 "No subscription" when user has none.
- GET /api/auth/me includes auto_renew, has_subscription, sub_status.
- POST /api/webhook/stripe-subscriptions: malformed body -> 400; forged event for unknown sub id must NOT grant Pro; duplicate event ids ignored.
"""
import os
import sys
import json
import asyncio
import pytest
import requests
import stripe
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
sys.path.insert(0, "/app/backend")

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
DEMO = {"email": "demo@mybuilder.app", "password": "demo1234"}


def _run(fn):
    from motor.motor_asyncio import AsyncIOMotorClient
    loop = asyncio.new_event_loop()
    try:
        async def _wrap():
            cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
            try:
                return await fn(cli[os.environ["DB_NAME"]])
            finally:
                cli.close()
        return loop.run_until_complete(_wrap())
    finally:
        loop.close()


@pytest.fixture(scope="module")
def demo_token():
    r = requests.post(f"{API}/auth/login", json=DEMO, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def demo_id(demo_token):
    r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {demo_token}"}, timeout=10)
    assert r.status_code == 200
    return r.json()["id"]


@pytest.fixture(scope="module")
def created_sessions():
    """Track every checkout session created; expire them all at teardown."""
    sessions = []
    yield sessions
    for sid in sessions:
        try:
            stripe.checkout.Session.expire(sid)
        except Exception as e:
            print(f"Could not expire {sid}: {e}")


# ---------- auth/me shape ----------
class TestAuthMeShape:
    def test_me_has_subscription_fields(self, demo_token):
        r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {demo_token}"}, timeout=10)
        assert r.status_code == 200
        u = r.json()
        for k in ("auto_renew", "has_subscription", "sub_status"):
            assert k in u, f"{k} missing from /auth/me"
        # demo has no subscription seeded
        assert u["auto_renew"] is False
        assert u["has_subscription"] is False
        assert u["sub_status"] in (None, "canceled")


# ---------- cancel/resume with no sub ----------
class TestSubscriptionManageNoSub:
    def test_cancel_no_sub_404(self, demo_token):
        r = requests.post(f"{API}/payments/subscription/cancel", headers={"Authorization": f"Bearer {demo_token}"}, timeout=10)
        assert r.status_code == 404
        assert "No subscription" in r.text

    def test_resume_no_sub_404(self, demo_token):
        r = requests.post(f"{API}/payments/subscription/resume", headers={"Authorization": f"Bearer {demo_token}"}, timeout=10)
        assert r.status_code == 404
        assert "No subscription" in r.text


# ---------- subscription checkout: monthly / yearly ----------
class TestSubscriptionCheckout:
    def test_monthly_creates_subscription_session_at_1999_gbp(self, demo_token, created_sessions):
        r = requests.post(f"{API}/payments/checkout",
                          headers={"Authorization": f"Bearer {demo_token}"},
                          json={"origin_url": BASE_URL, "tier": "monthly"}, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("url", "").startswith("https://checkout.stripe.com/")
        sid = body["session_id"]
        created_sessions.append(sid)
        s = stripe.checkout.Session.retrieve(sid, expand=["line_items"])
        assert s["mode"] == "subscription"
        assert s["currency"] == "gbp"
        assert s["amount_total"] == 1999, f"expected £19.99 (1999 pence), got {s['amount_total']}"
        li = s["line_items"]["data"][0]
        assert li["price"]["recurring"]["interval"] == "month"

    def test_yearly_creates_subscription_session_at_19900_gbp(self, demo_token, created_sessions):
        r = requests.post(f"{API}/payments/checkout",
                          headers={"Authorization": f"Bearer {demo_token}"},
                          json={"origin_url": BASE_URL, "tier": "yearly"}, timeout=20)
        assert r.status_code == 200, r.text
        sid = r.json()["session_id"]
        created_sessions.append(sid)
        s = stripe.checkout.Session.retrieve(sid, expand=["line_items"])
        assert s["mode"] == "subscription"
        assert s["currency"] == "gbp"
        assert s["amount_total"] == 19900, f"expected £199.00 (19900 pence), got {s['amount_total']}"
        li = s["line_items"]["data"][0]
        assert li["price"]["recurring"]["interval"] == "year"

    def test_status_open_subscription_does_not_grant_pro(self, demo_token, created_sessions):
        r = requests.post(f"{API}/payments/checkout",
                          headers={"Authorization": f"Bearer {demo_token}"},
                          json={"origin_url": BASE_URL, "tier": "monthly"}, timeout=20)
        assert r.status_code == 200
        sid = r.json()["session_id"]
        created_sessions.append(sid)
        st = requests.get(f"{API}/payments/status/{sid}",
                          headers={"Authorization": f"Bearer {demo_token}"}, timeout=15)
        assert st.status_code == 200, st.text
        body = st.json()
        # open subscription session is not yet complete; payment_status should NOT be paid
        assert body.get("status") in ("open", "expired"), body
        assert body.get("payment_status") != "paid", body
        # verify demo still basic
        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {demo_token}"}, timeout=10).json()
        assert me["plan"] == "basic", "Open subscription session should not grant Pro"
        assert me["has_subscription"] is False


# ---------- lifetime still uses emergent one-off flow ----------
class TestLifetimeStillOneOff:
    def test_lifetime_checkout_is_one_off(self, demo_token):
        r = requests.post(f"{API}/payments/checkout",
                          headers={"Authorization": f"Bearer {demo_token}"},
                          json={"origin_url": BASE_URL, "tier": "lifetime"}, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("session_id")
        # The lifetime flow uses emergentintegrations (test key sk_test_emergent); verify the DB tx row kind is NOT 'subscription'
        sid = body["session_id"]
        async def _check(db):
            tx = await db.payment_transactions.find_one({"session_id": sid})
            return tx
        tx = _run(_check)
        assert tx is not None
        assert tx.get("kind") != "subscription", f"lifetime should be one-off; got kind={tx.get('kind')}"
        assert tx["amount"] == 499.0
        assert (tx.get("metadata") or {}).get("tier") == "lifetime"


# ---------- webhook safety ----------
class TestWebhookSafety:
    def test_malformed_body_400(self):
        r = requests.post(f"{API}/webhook/stripe-subscriptions",
                          data="not-json",
                          headers={"Content-Type": "application/json"}, timeout=10)
        assert r.status_code == 400

    def test_forged_event_for_unknown_sub_does_not_grant_pro(self, demo_token, demo_id):
        # Craft a plausible-looking event JSON. Since STRIPE_WEBHOOK_SECRET is empty, server will accept parsed JSON,
        # but the handler re-fetches the subscription from Stripe. sub_FORGED does not exist => sync fails => 500 (handler raises Retry later).
        evt_id = f"evt_FORGED_{os.urandom(6).hex()}"
        payload = {
            "id": evt_id,
            "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_FORGED_doesnotexist", "status": "active", "customer": "cus_FORGED",
                                 "cancel_at_period_end": False, "metadata": {"user_id": demo_id, "tier": "monthly"},
                                 "items": {"data": [{"current_period_end": 9999999999}]}}}
        }
        r = requests.post(f"{API}/webhook/stripe-subscriptions", data=json.dumps(payload),
                          headers={"Content-Type": "application/json"}, timeout=15)
        # Expected: handler raises HTTPException(500, "Retry later") because stripe.Subscription.retrieve fails for forged id
        assert r.status_code in (500, 400), f"forged webhook must not succeed with 200, got {r.status_code}: {r.text}"
        # Confirm demo still basic
        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {demo_token}"}, timeout=10).json()
        assert me["plan"] == "basic", "Forged webhook granted Pro — security hole!"
        assert me["has_subscription"] is False
        # And no event row should have been inserted (because handler raised before insert)
        async def _check(db):
            return await db.stripe_events.find_one({"_id": evt_id})
        row = _run(_check)
        assert row is None, "Forged event id was persisted even though sync failed"

    def test_duplicate_event_ids_ignored(self, demo_token):
        # Seed a stripe_events row, then POST a webhook with the same id and ensure handler short-circuits with 200.
        evt_id = f"evt_DUPTEST_{os.urandom(6).hex()}"

        async def _seed(db):
            await db.stripe_events.insert_one({"_id": evt_id, "type": "customer.subscription.updated", "at": "2026-01-01T00:00:00Z"})
        _run(_seed)

        payload = {"id": evt_id, "type": "customer.subscription.updated",
                   "data": {"object": {"id": "sub_IGNORED", "status": "active", "cancel_at_period_end": False, "customer": "cus_X"}}}
        try:
            r = requests.post(f"{API}/webhook/stripe-subscriptions", data=json.dumps(payload),
                              headers={"Content-Type": "application/json"}, timeout=10)
            assert r.status_code == 200
            assert r.json().get("received") is True
            # ensure demo still basic
            me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {demo_token}"}, timeout=10).json()
            assert me["plan"] == "basic"
        finally:
            async def _cleanup(db):
                await db.stripe_events.delete_one({"_id": evt_id})
            _run(_cleanup)
