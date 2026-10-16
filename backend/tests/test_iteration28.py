"""Iteration 28 — Billing History + Request Reminders.

Scope:
- GET /api/payments/history (auth): returns one-off paid payment_transactions rows (kind != subscription)
  shape: {id: session_id, date, description 'Builder Assist Pro (Lifetime)', amount, currency 'GBP', status 'paid', receipt 'local'}.
  Must NOT create real Stripe objects (key is LIVE); seed a paid tx row directly in db.payment_transactions.
- GET /api/payments/receipt/{session_id}?t=<JWT> returns printable HTML (name, email, £499.00).
  Wrong user token OR unpaid tx -> 404.
- Portal doc requests: _req_out includes days_waiting, overdue (>=3), can_remind, reminders.
- POST /api/portal/projects/{pid}/doc-requests/{rid}/remind:
    * 400 when < NUDGE_DAYS (3) days old
    * After backdating created_at by 4 days: 200, emails owner (allow 503 if 429 rate-limited),
      increments reminders, sets reminded_at
    * Second remind within 24h: 400
- Owner GET /api/portal-doc-requests/overdue lists only open 3+ day old requests on active project.
"""
import os
import sys
import asyncio
from datetime import datetime, timedelta, timezone
import pytest
import requests
import jwt
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
sys.path.insert(0, "/app/backend")

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]
PORTAL_SECRET = JWT_SECRET + "|portal"
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


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def demo_token():
    r = requests.post(f"{API}/auth/login", json=DEMO, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def demo_user(demo_token):
    r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {demo_token}"}, timeout=10)
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def demo_id(demo_user):
    return demo_user["id"]


@pytest.fixture
def seeded_paid_tx(demo_id):
    """Seed a paid lifetime tx row directly; teardown deletes it."""
    sid = f"cs_test_iter28_{os.urandom(6).hex()}"
    now = datetime.now(timezone.utc).isoformat()

    async def _ins(db):
        await db.payment_transactions.insert_one({
            "session_id": sid,
            "user_id": demo_id,
            "amount": 499.0,
            "currency": "gbp",
            "metadata": {"tier": "lifetime"},
            "payment_status": "paid",
            "created_at": now,
            "paid_at": now,
        })
    _run(_ins)
    yield sid

    async def _del(db):
        await db.payment_transactions.delete_many({"session_id": sid})
    _run(_del)


# ---------------- Billing history ----------------
class TestBillingHistory:
    def test_requires_auth(self):
        r = requests.get(f"{API}/payments/history", timeout=10)
        assert r.status_code in (401, 403), r.status_code

    def test_history_includes_seeded_paid_lifetime(self, demo_token, seeded_paid_tx):
        r = requests.get(f"{API}/payments/history", headers={"Authorization": f"Bearer {demo_token}"}, timeout=15)
        assert r.status_code == 200, r.text
        rows = r.json()
        assert isinstance(rows, list)
        row = next((x for x in rows if x["id"] == seeded_paid_tx), None)
        assert row is not None, f"seeded session {seeded_paid_tx} not in {rows}"
        assert row["amount"] == 499.0
        assert row["currency"] == "GBP"
        assert row["status"] == "paid"
        assert row["receipt"] == "local"
        assert "Builder Assist Pro" in row["description"]
        assert "Lifetime" in row["description"]
        assert row.get("url") in (None, "")

    def test_history_excludes_subscription_rows(self, demo_token, demo_id):
        """kind='subscription' rows must NOT appear in /payments/history."""
        sid = f"sub_test_iter28_{os.urandom(6).hex()}"
        now = datetime.now(timezone.utc).isoformat()

        async def _ins(db):
            await db.payment_transactions.insert_one({
                "session_id": sid, "user_id": demo_id, "amount": 19.99, "currency": "gbp",
                "metadata": {"tier": "monthly"}, "payment_status": "paid",
                "kind": "subscription",
                "created_at": now, "paid_at": now,
            })
        _run(_ins)
        try:
            r = requests.get(f"{API}/payments/history", headers={"Authorization": f"Bearer {demo_token}"}, timeout=15)
            assert r.status_code == 200
            ids = [x["id"] for x in r.json()]
            assert sid not in ids, "subscription-kind row leaked into /payments/history"
        finally:
            async def _del(db):
                await db.payment_transactions.delete_many({"session_id": sid})
            _run(_del)


# ---------------- Receipt ----------------
class TestReceipt:
    def test_receipt_html_contains_name_email_amount(self, demo_token, demo_user, seeded_paid_tx):
        r = requests.get(f"{API}/payments/receipt/{seeded_paid_tx}", params={"t": demo_token}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.text
        assert "Builder Assist" in body
        assert demo_user["name"] in body
        assert demo_user["email"] in body
        assert "£499.00" in body
        assert "Lifetime" in body
        assert "<html" in body.lower()

    def test_receipt_wrong_user_token_404(self, seeded_paid_tx):
        """A different user's JWT must NOT be able to view the receipt."""
        # register a fresh user
        email = f"TEST_other_{os.urandom(4).hex()}@example.com"
        reg = requests.post(f"{API}/auth/register", json={"name": "Other", "email": email, "password": "pass12345"}, timeout=15)
        assert reg.status_code == 200, reg.text
        other_token = reg.json()["access_token"]
        other_id = reg.json()["user"]["id"]
        try:
            r = requests.get(f"{API}/payments/receipt/{seeded_paid_tx}", params={"t": other_token}, timeout=10)
            assert r.status_code == 404, f"expected 404 for cross-user access, got {r.status_code}: {r.text[:200]}"
        finally:
            async def _cleanup(db):
                from bson import ObjectId
                try:
                    await db.users.delete_one({"_id": ObjectId(other_id)})
                except Exception:
                    pass
                await db.projects.delete_many({"user_id": other_id})
            _run(_cleanup)

    def test_receipt_unpaid_tx_404(self, demo_token, demo_id):
        """Unpaid tx must 404."""
        sid = f"cs_unpaid_iter28_{os.urandom(6).hex()}"
        now = datetime.now(timezone.utc).isoformat()

        async def _ins(db):
            await db.payment_transactions.insert_one({
                "session_id": sid, "user_id": demo_id, "amount": 499.0, "currency": "gbp",
                "metadata": {"tier": "lifetime"}, "payment_status": "unpaid",
                "created_at": now,
            })
        _run(_ins)
        try:
            r = requests.get(f"{API}/payments/receipt/{sid}", params={"t": demo_token}, timeout=10)
            assert r.status_code == 404
        finally:
            async def _del(db):
                await db.payment_transactions.delete_many({"session_id": sid})
            _run(_del)


# ---------------- Portal lead setup + doc-request reminders ----------------
def _mint_portal_token(email: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": email, "typ": "portal", "iat": now, "exp": now + timedelta(days=7)}, PORTAL_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def lead_ctx(demo_token, demo_id):
    """Create a stakeholder lead on demo's active project. Returns dict(pid, lead_email, lead_token)."""
    H = {"Authorization": f"Bearer {demo_token}"}
    me = requests.get(f"{API}/auth/me", headers=H, timeout=10).json()
    pid = me.get("active_project_id")
    assert pid, "demo user has no active_project_id — seed data missing"

    lead_email = f"iter28_lead_{os.urandom(4).hex()}@delivered.resend.dev"
    inv = requests.post(f"{API}/portal-members", headers=H, json={
        "email": lead_email, "name": "Iter28 Lead",
        "role": "contractor", "company": "Iter28 Co",
        "origin_url": BASE_URL, "doc_ids": [], "digest": False,
    }, timeout=20)
    assert inv.status_code in (200, 201), inv.text
    member = inv.json()
    mid = member["id"]

    # Promote to lead
    put = requests.put(f"{API}/portal-members/{mid}", headers=H, json={"is_lead": True, "company": "Iter28 Co"}, timeout=10)
    assert put.status_code == 200, put.text

    lead_token = _mint_portal_token(lead_email)

    # verify portal/me works
    r = requests.get(f"{API}/portal/me", headers={"Authorization": f"Bearer {lead_token}"}, timeout=10)
    assert r.status_code == 200, r.text

    ctx = {"pid": pid, "lead_email": lead_email, "lead_token": lead_token, "mid": mid}
    yield ctx

    # cleanup member + any requests
    async def _cleanup(db):
        from bson import ObjectId
        try:
            await db.portal_members.delete_one({"_id": ObjectId(mid)})
        except Exception:
            pass
        await db.portal_doc_requests.delete_many({"email": lead_email})
        await db.portal_codes.delete_many({"email": lead_email})
        await db.portal_accounts.delete_many({"email": lead_email})
    _run(_cleanup)


def _create_doc_request(ctx, title="Latest building control certificate", note="Needed asap"):
    r = requests.post(f"{API}/portal/projects/{ctx['pid']}/doc-requests",
                      headers={"Authorization": f"Bearer {ctx['lead_token']}"},
                      json={"title": title, "note": note}, timeout=20)
    assert r.status_code in (200, 201), r.text
    return r.json()


class TestDocRequestRemind:
    def test_fresh_request_cannot_be_reminded_400(self, lead_ctx):
        req = _create_doc_request(lead_ctx)
        rid = req["id"]
        try:
            assert req["days_waiting"] == 0
            assert req["overdue"] is False
            assert req["can_remind"] is False
            assert req["reminders"] == 0

            r = requests.post(f"{API}/portal/projects/{lead_ctx['pid']}/doc-requests/{rid}/remind",
                              headers={"Authorization": f"Bearer {lead_ctx['lead_token']}"}, timeout=15)
            assert r.status_code == 400, r.text
        finally:
            async def _del(db):
                from bson import ObjectId
                await db.portal_doc_requests.delete_one({"_id": ObjectId(rid)})
            _run(_del)

    def test_overdue_request_remind_200_then_second_within_24h_400(self, lead_ctx, demo_id):
        req = _create_doc_request(lead_ctx, title="Updated valuation PDF")
        rid = req["id"]
        # Owner email `demo@mybuilder.app` is blocked by Resend's deliverability shield.
        # Temporarily route reminder to a known-deliverable address, then restore.
        original_email = None

        async def _set_safe_email(db):
            nonlocal original_email
            from bson import ObjectId
            u = await db.users.find_one({"_id": ObjectId(demo_id)}, {"email": 1})
            original_email = u["email"]
            await db.users.update_one({"_id": ObjectId(demo_id)}, {"$set": {"email": "delivered@resend.dev"}})
        _run(_set_safe_email)

        try:
            # Backdate created_at 4 days
            backdate = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()

            async def _back(db):
                from bson import ObjectId
                await db.portal_doc_requests.update_one({"_id": ObjectId(rid)}, {"$set": {"created_at": backdate}})
            _run(_back)

            # List reflects overdue=True, can_remind=True
            lst = requests.get(f"{API}/portal/projects/{lead_ctx['pid']}/doc-requests",
                               headers={"Authorization": f"Bearer {lead_ctx['lead_token']}"}, timeout=10).json()
            row = next(x for x in lst if x["id"] == rid)
            assert row["overdue"] is True
            assert row["can_remind"] is True
            assert row["days_waiting"] >= 3

            # First remind
            r = requests.post(f"{API}/portal/projects/{lead_ctx['pid']}/doc-requests/{rid}/remind",
                              headers={"Authorization": f"Bearer {lead_ctx['lead_token']}"}, timeout=20)
            if r.status_code == 503:
                pytest.skip("Email send rate-limited (503); handler path verified independently")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["reminders"] == 1
            assert body["reminded_at"] is not None
            assert body["can_remind"] is False  # just reminded; must wait 24h

            # Second remind within 24h
            r2 = requests.post(f"{API}/portal/projects/{lead_ctx['pid']}/doc-requests/{rid}/remind",
                               headers={"Authorization": f"Bearer {lead_ctx['lead_token']}"}, timeout=15)
            assert r2.status_code == 400, r2.text
        finally:
            async def _del(db):
                from bson import ObjectId
                await db.portal_doc_requests.delete_one({"_id": ObjectId(rid)})
                if original_email:
                    await db.users.update_one({"_id": ObjectId(demo_id)}, {"$set": {"email": original_email}})
            _run(_del)


class TestOwnerOverdueEndpoint:
    def test_overdue_lists_only_open_old_requests(self, demo_token, lead_ctx):
        # Fresh req
        fresh = _create_doc_request(lead_ctx, title="Fresh PAT testing cert")
        # Old open req
        old = _create_doc_request(lead_ctx, title="Old gas safe certificate")
        # Old fulfilled req (should NOT appear)
        done = _create_doc_request(lead_ctx, title="Old but done cert")

        backdate = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()

        async def _setup(db):
            from bson import ObjectId
            await db.portal_doc_requests.update_one({"_id": ObjectId(old["id"])}, {"$set": {"created_at": backdate}})
            await db.portal_doc_requests.update_one({"_id": ObjectId(done["id"])}, {"$set": {"created_at": backdate, "status": "fulfilled"}})
        _run(_setup)

        try:
            r = requests.get(f"{API}/portal-doc-requests/overdue",
                             headers={"Authorization": f"Bearer {demo_token}"}, timeout=10)
            assert r.status_code == 200, r.text
            rows = r.json()
            ids = {x["id"] for x in rows}
            assert old["id"] in ids, "old open request missing from overdue list"
            assert fresh["id"] not in ids, "fresh (<3 day) request wrongly flagged overdue"
            assert done["id"] not in ids, "fulfilled request wrongly in overdue list"
            # Shape check on the overdue row
            row = next(x for x in rows if x["id"] == old["id"])
            assert row["days_waiting"] >= 3
            assert row["overdue"] is True
            assert row["status"] == "open"
            assert row["name"]  # lead name present
        finally:
            async def _del(db):
                from bson import ObjectId
                for rid in (fresh["id"], old["id"], done["id"]):
                    await db.portal_doc_requests.delete_one({"_id": ObjectId(rid)})
            _run(_del)
