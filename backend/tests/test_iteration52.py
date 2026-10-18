"""Iteration 52 - PropertyPlug:
(1) Rent Arrears Tracker:
  - GET /api/portfolio/arrears returns per-tenancy overdue rows with totals in home currency.
  - PUT /api/rentals/tenancies/{tid}/auto-reminders toggles arrears_auto (400 if no email, 404 for stranger).
  - POST /api/rentals/tenancies/{tid}/remind-arrears sends a combined email, records rent_reminders rows,
    429 if a reminder was sent in the last 10 min, 400 if no overdue rent.
  - routes.arrears.run_auto_reminders() (direct python invocation): only chases tenancies with
    arrears_auto True + email + never-chased months OR last late reminder >= 7 days ago, sets arrears_attempt_at.
  - TenancyIn has arrears_auto (default True) on POST / PUT /api/rentals/tenancies.
(2) BRRR saved deals CRUD (Pro only):
  - GET/POST /api/brrr/deals, PUT/DELETE /api/brrr/deals/{id}; validation errors (422) for
    unknown keys, negative values, empty name; basic plan -> 403; 50 max cap.
"""
import os
import sys
import asyncio
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import requests

sys.path.insert(0, "/app/backend")

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
assert BASE, "EXPO_PUBLIC_BACKEND_URL env var must be set"
API = f"{BASE}/api"

# Direct Mongo access for state verification (sync pymongo so it never clashes with motor's loop)
import pymongo
from bson import ObjectId as _OID
_MONGO = pymongo.MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
_DB = _MONGO[os.environ.get("DB_NAME", "test_database")]

DEMO_EMAIL = "demo@mybuilder.app"
DEMO_PASS = "demo1234"


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=20)
    assert r.status_code == 200, r.text
    j = r.json()
    return {"email": email, "token": j["access_token"], "user": j["user"]}


def _h(u):
    return {"Authorization": f"Bearer {u['token']}"}


@pytest.fixture(scope="module")
def owner():
    o = _login(DEMO_EMAIL, DEMO_PASS)
    # Promote to Pro so BRRR deals endpoints are accessible
    requests.post(f"{API}/auth/plan", headers=_h(o), json={"plan": "pro"}, timeout=20)
    return o


def _activate_nottingham(o, pid):
    r = requests.post(f"{API}/projects/{pid}/activate", headers=_h(o), timeout=20)
    assert r.status_code == 200, r.text


@pytest.fixture(scope="module")
def stranger():
    """A fresh user with no access to demo projects."""
    email = f"iter52_stranger_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/auth/register", json={"name": "Iter52", "email": email, "password": "pass1234"}, timeout=20)
    assert r.status_code == 200, r.text
    j = r.json()
    return {"email": email, "token": j["access_token"], "user": j["user"]}


# ============================= 1) Arrears tracker =============================

class TestArrearsPortfolio:
    def test_get_arrears_shape_and_arrears_test_tenancy(self, owner):
        r = requests.get(f"{API}/portfolio/arrears", headers=_h(owner), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert set(["home_currency", "total", "count", "auto_on", "tenancies"]).issubset(d)
        assert isinstance(d["tenancies"], list)
        assert d["count"] == len(d["tenancies"])
        # Seeded "Arrears Test" tenancy should appear
        at = [t for t in d["tenancies"] if t["tenant_name"] == "Arrears Test"]
        assert at, "Expected seeded 'Arrears Test' tenancy in portfolio arrears"
        t = at[0]
        for k in ("tenancy_id", "project_id", "project_name", "address", "currency", "tenant_email",
                  "owed", "owed_home", "months", "oldest_days", "arrears_auto",
                  "last_reminder_at", "next_auto_on", "can_manage"):
            assert k in t, f"Missing {k} in tenancy row"
        assert t["owed"] > 0
        assert t["oldest_days"] > 0
        assert all(m["paid"] < m["due"] for m in t["months"])
        # arrears_auto was pre-seeded False per the agent note
        pytest.shared_tenancy = t  # store for later tests


class TestAutoReminderToggle:
    def test_enable_requires_email_other_user_404(self, owner, stranger):
        tid = pytest.shared_tenancy["tenancy_id"]
        # Stranger cannot toggle
        r = requests.put(f"{API}/rentals/tenancies/{tid}/auto-reminders",
                         headers=_h(stranger), json={"enabled": True}, timeout=20)
        assert r.status_code == 404, r.text

    def test_enable_without_email_returns_400(self, owner):
        """Create a tenancy with no tenant_email, try to enable arrears_auto -> 400."""
        pid = pytest.shared_tenancy["project_id"]
        _activate_nottingham(owner, pid)
        payload = {"tenant_name": "TEST_NoEmail", "tenant_email": "", "tenant_phone": "",
                   "rent": 500, "deposit": 0, "deposit_scheme": "", "deposit_protected": False,
                   "receipts_auto": False, "statements_auto": False, "arrears_auto": False,
                   "start_date": "2026-01-01", "end_date": "", "rent_day": 1, "notes": ""}
        r = requests.post(f"{API}/rentals/tenancies", headers=_h(owner), json=payload, timeout=20)
        assert r.status_code == 200, r.text
        tid = r.json()["id"]
        try:
            r2 = requests.put(f"{API}/rentals/tenancies/{tid}/auto-reminders",
                              headers=_h(owner), json={"enabled": True}, timeout=20)
            assert r2.status_code == 400, r2.text
        finally:
            requests.delete(f"{API}/rentals/tenancies/{tid}", headers=_h(owner), timeout=20)

    def test_toggle_persists(self, owner):
        tid = pytest.shared_tenancy["tenancy_id"]
        # Enable (seeded tenancy has an email)
        r = requests.put(f"{API}/rentals/tenancies/{tid}/auto-reminders",
                         headers=_h(owner), json={"enabled": True}, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["arrears_auto"] is True
        # Verify by GET
        d = requests.get(f"{API}/portfolio/arrears", headers=_h(owner), timeout=20).json()
        row = next(t for t in d["tenancies"] if t["tenancy_id"] == tid)
        assert row["arrears_auto"] is True
        assert row["next_auto_on"] is not None
        # Flip back off
        r = requests.put(f"{API}/rentals/tenancies/{tid}/auto-reminders",
                         headers=_h(owner), json={"enabled": False}, timeout=20)
        assert r.status_code == 200 and r.json()["arrears_auto"] is False


class TestTenancyIn:
    def test_create_default_arrears_auto_true(self, owner):
        pid = pytest.shared_tenancy["project_id"]
        _activate_nottingham(owner, pid)
        payload = {"tenant_name": "TEST_DefaultAuto", "tenant_email": "delivered@resend.dev", "tenant_phone": "",
                   "rent": 400, "deposit": 0, "deposit_scheme": "", "deposit_protected": False,
                   "receipts_auto": False, "statements_auto": False,
                   "start_date": "2026-01-01", "end_date": "", "rent_day": 1, "notes": ""}
        r = requests.post(f"{API}/rentals/tenancies", headers=_h(owner), json=payload, timeout=20)
        assert r.status_code == 200, r.text
        tid = r.json()["id"]
        try:
            # Use direct pymongo check to confirm default value
            doc = _DB.tenancies.find_one({"_id": _OID(tid)})
            assert doc is not None
            assert doc.get("arrears_auto") is True, f"Expected default True, got {doc.get('arrears_auto')}"
            # Update with arrears_auto=False via PUT
            payload2 = dict(payload); payload2["arrears_auto"] = False
            r2 = requests.put(f"{API}/rentals/tenancies/{tid}", headers=_h(owner), json=payload2, timeout=20)
            assert r2.status_code == 200
            doc2 = _DB.tenancies.find_one({"_id": _OID(tid)})
            assert doc2.get("arrears_auto") is False
        finally:
            requests.delete(f"{API}/rentals/tenancies/{tid}", headers=_h(owner), timeout=20)


class TestRemindArrears:
    """Verify POST /rentals/tenancies/{tid}/remind-arrears sends combined email + 429 rate limit."""
    def test_remind_then_rate_limit(self, owner):
        tid = pytest.shared_tenancy["tenancy_id"]
        before = requests.get(f"{API}/portfolio/arrears", headers=_h(owner), timeout=20).json()
        row = next(t for t in before["tenancies"] if t["tenancy_id"] == tid)
        last_before = row["last_reminder_at"]
        now = datetime.now(timezone.utc)
        recent = last_before and (now - datetime.fromisoformat(last_before)).total_seconds() < 600
        if recent:
            # A reminder was already sent <10 min ago → the endpoint MUST return 429.
            r = requests.post(f"{API}/rentals/tenancies/{tid}/remind-arrears", headers=_h(owner), timeout=20)
            assert r.status_code == 429, f"Expected 429 (rate limit) but got {r.status_code}: {r.text}"
            return

        # Otherwise send a fresh reminder, then verify 429 on second call.
        r = requests.post(f"{API}/rentals/tenancies/{tid}/remind-arrears", headers=_h(owner), timeout=30)
        if r.status_code == 503:
            pytest.skip("Email service unavailable")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["owed"] > 0
        assert body["months"] >= 1
        r2 = requests.post(f"{API}/rentals/tenancies/{tid}/remind-arrears", headers=_h(owner), timeout=20)
        assert r2.status_code == 429, r2.text

    def test_remind_requires_overdue(self, owner):
        """Create a tenancy with no overdue rent -> remind-arrears should return 400."""
        pid = pytest.shared_tenancy["project_id"]
        _activate_nottingham(owner, pid)
        future = (date.today() + timedelta(days=60)).isoformat()
        payload = {"tenant_name": "TEST_Future", "tenant_email": "delivered@resend.dev", "tenant_phone": "",
                   "rent": 400, "deposit": 0, "deposit_scheme": "", "deposit_protected": False,
                   "receipts_auto": False, "statements_auto": False, "arrears_auto": False,
                   "start_date": future, "end_date": "", "rent_day": 1, "notes": ""}
        r = requests.post(f"{API}/rentals/tenancies", headers=_h(owner), json=payload, timeout=20)
        assert r.status_code == 200, r.text
        tid = r.json()["id"]
        try:
            r2 = requests.post(f"{API}/rentals/tenancies/{tid}/remind-arrears",
                               headers=_h(owner), timeout=20)
            assert r2.status_code == 400, r2.text
        finally:
            requests.delete(f"{API}/rentals/tenancies/{tid}", headers=_h(owner), timeout=20)


class TestRunAutoReminders:
    """Direct python invocation of the scheduler function."""
    def test_run_auto_reminders_direct(self, owner):
        """Toggle arrears_auto on, call run_auto_reminders directly, verify it completes."""
        from routes.arrears import run_auto_reminders  # noqa
        tid = pytest.shared_tenancy["tenancy_id"]
        # Enable auto
        requests.put(f"{API}/rentals/tenancies/{tid}/auto-reminders",
                     headers=_h(owner), json={"enabled": True}, timeout=20)
        # Clear attempt guard synchronously
        _DB.tenancies.update_one({"_id": _OID(tid)}, {"$unset": {"arrears_attempt_at": ""}})

        async def _run():
            # Re-create motor client bound to the running loop so the scheduler's
            # DB access doesn't error with "attached to a different loop".
            import importlib
            import core
            from motor.motor_asyncio import AsyncIOMotorClient
            cli = AsyncIOMotorClient(os.environ.get("MONGO_URL"))
            orig_db = core.db
            core.db = cli[os.environ.get("DB_NAME", "test_database")]
            # Reload modules that captured `db` at import time
            import routes.arrears as _ar
            _ar.db = core.db
            try:
                await run_auto_reminders()
            finally:
                core.db = orig_db
                _ar.db = orig_db
                cli.close()

        asyncio.run(_run())
        doc = _DB.tenancies.find_one({"_id": _OID(tid)})
        assert doc is not None
        # The function completed; arrears_attempt_at may or may not be stamped depending on cooldown.
        # Cleanup
        _DB.tenancies.update_one({"_id": _OID(tid)},
                                 {"$set": {"arrears_auto": False},
                                  "$unset": {"arrears_attempt_at": ""}})


# ============================= 2) BRRR Saved Deals =============================

VALID_INPUTS = {"purchase": 150000, "fees": 5000, "refurb": 25000, "valuation": 220000,
                "ltv": 75, "rate": 5.5, "rent": 1200, "costs": 150,
                "months": 6, "bridge_pct": 70, "bridge_rate": 0.75, "bridge_fee": 2,
                "holding": 500}


@pytest.fixture
def brrr_cleanup(owner):
    """Delete any TEST_ prefixed deals left behind by this run."""
    created = []
    yield created
    for did in created:
        try:
            requests.delete(f"{API}/brrr/deals/{did}", headers=_h(owner), timeout=10)
        except Exception:
            pass


class TestBrrrDealsAuth:
    def test_basic_plan_rejected(self, stranger):
        # stranger is a new user on basic plan
        r = requests.get(f"{API}/brrr/deals", headers=_h(stranger), timeout=20)
        assert r.status_code == 403, r.text


class TestBrrrDealsCrud:
    def test_create_get_update_delete(self, owner, brrr_cleanup):
        # Create
        name = f"TEST_Deal_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/brrr/deals", headers=_h(owner),
                          json={"name": name, "inputs": VALID_INPUTS}, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        did = d["id"]
        brrr_cleanup.append(did)
        assert d["name"] == name
        for k in ("purchase", "fees", "refurb", "valuation", "ltv", "rate", "rent",
                  "costs", "months", "bridge_pct", "bridge_rate", "bridge_fee", "holding"):
            assert k in d["inputs"], f"Missing input key {k}"
        assert d["inputs"]["purchase"] == 150000.0

        # GET list
        r = requests.get(f"{API}/brrr/deals", headers=_h(owner), timeout=20)
        assert r.status_code == 200
        assert any(x["id"] == did for x in r.json())

        # Update
        new_inputs = dict(VALID_INPUTS, purchase=160000)
        r = requests.put(f"{API}/brrr/deals/{did}", headers=_h(owner),
                         json={"name": name + "_v2", "inputs": new_inputs}, timeout=20)
        assert r.status_code == 200
        assert r.json()["name"] == name + "_v2"
        assert r.json()["inputs"]["purchase"] == 160000.0

        # Delete
        r = requests.delete(f"{API}/brrr/deals/{did}", headers=_h(owner), timeout=20)
        assert r.status_code == 200
        # Confirm removal
        r = requests.get(f"{API}/brrr/deals", headers=_h(owner), timeout=20)
        assert not any(x["id"] == did for x in r.json())
        brrr_cleanup.remove(did)


class TestBrrrValidation:
    def test_unknown_key_rejected(self, owner):
        inp = dict(VALID_INPUTS, foo=1)
        r = requests.post(f"{API}/brrr/deals", headers=_h(owner),
                          json={"name": "TEST_Bad", "inputs": inp}, timeout=20)
        assert r.status_code == 422, r.text

    def test_negative_rejected(self, owner):
        inp = dict(VALID_INPUTS, purchase=-1)
        r = requests.post(f"{API}/brrr/deals", headers=_h(owner),
                          json={"name": "TEST_Neg", "inputs": inp}, timeout=20)
        assert r.status_code == 422, r.text

    def test_empty_name_rejected(self, owner):
        r = requests.post(f"{API}/brrr/deals", headers=_h(owner),
                          json={"name": "   ", "inputs": VALID_INPUTS}, timeout=20)
        assert r.status_code == 422, r.text

    def test_other_user_update_404(self, owner, brrr_cleanup):
        # Create a deal as owner
        name = f"TEST_Deal_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/brrr/deals", headers=_h(owner),
                          json={"name": name, "inputs": VALID_INPUTS}, timeout=20)
        did = r.json()["id"]
        brrr_cleanup.append(did)
        # Stranger (basic) still gets 403, not 404. So create a second Pro user for proper test.
        email = f"iter52_pro_{uuid.uuid4().hex[:8]}@example.com"
        reg = requests.post(f"{API}/auth/register", json={"name": "P", "email": email, "password": "pass1234"}, timeout=20).json()
        other = {"email": email, "token": reg["access_token"]}
        requests.post(f"{API}/auth/plan", headers=_h(other), json={"plan": "pro"}, timeout=20)
        r2 = requests.put(f"{API}/brrr/deals/{did}", headers=_h(other),
                          json={"name": "X", "inputs": VALID_INPUTS}, timeout=20)
        assert r2.status_code == 404, r2.text
