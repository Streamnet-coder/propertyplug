"""Iteration 53 - PropertyPlug Arrears Payment Plans:
 - POST /api/rentals/tenancies/{tid}/payment-plan validation + success + emailed field.
 - GET /api/rentals/tenancies/{tid}/payment-plan returns plan with schedule / null when none.
 - POST /api/payment-plans/{pid}/payments applies oldest-first to rent_payments; 400 over remaining; completed when fully paid.
 - DELETE /api/payment-plans/{pid} cancels; reminders resume (next_auto_on populated).
 - Broken detection via direct Mongo start_date mutation: on_track=False, status='broken'.
 - GET /api/portfolio/arrears: each tenancy has plan field; on-track covering plan -> next_auto_on=None,
   POST remind-arrears -> 400 "Nothing to chase...". run_auto_reminders() skips covered months.
 - Tenant portal GET /api/t/{token} shows payment-plan card.
 - Deleting a tenancy also deletes its payment plans.
"""
import os
import sys
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import requests

sys.path.insert(0, "/app/backend")

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
assert BASE, "EXPO_PUBLIC_BACKEND_URL env var must be set"
API = f"{BASE}/api"

import pymongo
from bson import ObjectId as _OID

_MONGO = pymongo.MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
_DB = _MONGO[os.environ.get("DB_NAME", "test_database")]

DEMO_EMAIL = "demo@mybuilder.app"
DEMO_PASS = "demo1234"
TENANT_EMAIL = "delivered@resend.dev"

# -- helpers -----------------------------------------------------------------

def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=20)
    assert r.status_code == 200, r.text
    j = r.json()
    return {"email": email, "token": j["access_token"], "user": j["user"]}


def _h(u):
    return {"Authorization": f"Bearer {u['token']}"}


def _server_today():
    """Server date - trust the environment note (~2026-10-19)."""
    return date.today()


@pytest.fixture(scope="module")
def owner():
    return _login(DEMO_EMAIL, DEMO_PASS)


@pytest.fixture(scope="module")
def active_pid(owner):
    # Pick any demo project (Nottingham)
    r = requests.get(f"{API}/projects", headers=_h(owner), timeout=20)
    assert r.status_code == 200, r.text
    projects = r.json()
    assert projects, "Demo user should have at least one project"
    pid = projects[0]["id"]
    requests.post(f"{API}/projects/{pid}/activate", headers=_h(owner), timeout=20)
    return pid


def _make_tenancy(owner, pid, name_suffix, start_date, rent=900, email=TENANT_EMAIL, arrears_auto=True):
    """Create a tenancy; returns tenancy id."""
    requests.post(f"{API}/projects/{pid}/activate", headers=_h(owner), timeout=20)
    payload = {"tenant_name": f"TEST_{name_suffix}", "tenant_email": email, "tenant_phone": "",
               "rent": rent, "deposit": 0, "deposit_scheme": "", "deposit_protected": False,
               "receipts_auto": False, "statements_auto": False, "arrears_auto": arrears_auto,
               "start_date": start_date, "end_date": "", "rent_day": 1, "notes": ""}
    r = requests.post(f"{API}/rentals/tenancies", headers=_h(owner), json=payload, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _delete_tenancy(owner, tid):
    requests.delete(f"{API}/rentals/tenancies/{tid}", headers=_h(owner), timeout=20)


_created_tids = []


@pytest.fixture
def tenancy_factory(owner, active_pid):
    """Factory that cleans up tenancies at end of test."""
    local = []

    def _f(suffix, start_date="2026-01-01", rent=900, email=TENANT_EMAIL, arrears_auto=True):
        tid = _make_tenancy(owner, active_pid, f"{suffix}_{uuid.uuid4().hex[:6]}", start_date, rent, email, arrears_auto)
        local.append(tid)
        _created_tids.append(tid)
        return tid

    yield _f
    for tid in local:
        _delete_tenancy(owner, tid)


@pytest.fixture(scope="module", autouse=True)
def _module_cleanup(owner):
    yield
    # Cleanup "Plan Test" tenancy created by main agent, and any remaining TEST_ ones
    r = requests.get(f"{API}/projects", headers=_h(owner), timeout=20)
    if r.status_code == 200:
        for p in r.json():
            requests.post(f"{API}/projects/{p['id']}/activate", headers=_h(owner), timeout=20)
            tr = requests.get(f"{API}/rentals/tenancies", headers=_h(owner), timeout=20)
            if tr.status_code != 200:
                continue
            for t in tr.json():
                if t["tenant_name"].startswith("TEST_") or t["tenant_name"] == "Plan Test":
                    requests.delete(f"{API}/rentals/tenancies/{t['id']}", headers=_h(owner), timeout=20)


# ============================= Payment plan CRUD =============================


class TestCreatePlanValidation:
    def test_create_no_arrears_returns_400(self, owner, tenancy_factory):
        # Future-start tenancy -> no arrears yet
        future = (_server_today() + timedelta(days=60)).isoformat()
        tid = tenancy_factory("NoArrears", start_date=future, rent=500)
        r = requests.post(f"{API}/rentals/tenancies/{tid}/payment-plan",
                          headers=_h(owner),
                          json={"instalment": 100, "frequency": "monthly",
                                "start_date": _server_today().isoformat(), "notify": False},
                          timeout=20)
        assert r.status_code == 400, r.text
        assert "overdue" in r.text.lower()

    def test_start_date_too_far_past(self, owner, tenancy_factory):
        tid = tenancy_factory("PastStart", start_date="2026-01-01", rent=900)
        past = (_server_today() - timedelta(days=20)).isoformat()
        r = requests.post(f"{API}/rentals/tenancies/{tid}/payment-plan",
                          headers=_h(owner),
                          json={"instalment": 200, "frequency": "monthly",
                                "start_date": past, "notify": False}, timeout=20)
        assert r.status_code == 400, r.text
        assert "past" in r.text.lower() or "week" in r.text.lower()

    def test_bad_date_format(self, owner, tenancy_factory):
        tid = tenancy_factory("BadDate", start_date="2026-01-01", rent=900)
        r = requests.post(f"{API}/rentals/tenancies/{tid}/payment-plan",
                          headers=_h(owner),
                          json={"instalment": 200, "frequency": "monthly",
                                "start_date": "not-a-date", "notify": False}, timeout=20)
        assert r.status_code == 400, r.text

    def test_instalment_too_small_104_cap(self, owner, tenancy_factory):
        # Rent 900 x many months of arrears → amount is big; a tiny instalment overflows 104.
        tid = tenancy_factory("TooSmall", start_date="2026-01-01", rent=900)
        r = requests.post(f"{API}/rentals/tenancies/{tid}/payment-plan",
                          headers=_h(owner),
                          json={"instalment": 1, "frequency": "weekly",
                                "start_date": _server_today().isoformat(), "notify": False},
                          timeout=20)
        assert r.status_code == 400, r.text
        assert "104" in r.text or "small" in r.text.lower()


class TestPlanLifecycle:
    def test_full_lifecycle(self, owner, tenancy_factory):
        """Create plan → GET returns schedule → log instalment → GET /portfolio/arrears owed decreased
           → duplicate POST 409 → DELETE plan → GET returns null → remind-arrears resumes."""
        tid = tenancy_factory("Life", start_date="2026-01-01", rent=900)

        # Pre: GET plan should be null
        r = requests.get(f"{API}/rentals/tenancies/{tid}/payment-plan", headers=_h(owner), timeout=20)
        assert r.status_code == 200 and r.json() is None

        # Initial arrears
        arr0 = requests.get(f"{API}/portfolio/arrears", headers=_h(owner), timeout=20).json()
        row0 = next(t for t in arr0["tenancies"] if t["tenancy_id"] == tid)
        owed0 = row0["owed"]
        assert owed0 > 0
        assert row0["plan"] is None

        # Create plan
        body = {"instalment": 300, "frequency": "monthly",
                "start_date": _server_today().isoformat(), "notify": True}
        r = requests.post(f"{API}/rentals/tenancies/{tid}/payment-plan",
                          headers=_h(owner), json=body, timeout=30)
        assert r.status_code == 200, r.text
        plan = r.json()
        assert plan["status"] == "active"
        assert plan["amount"] == owed0, f"plan.amount {plan['amount']} should equal arrears {owed0}"
        assert plan["instalment"] == 300
        assert plan["frequency"] == "monthly"
        assert plan["paid"] == 0.0
        assert plan["remaining"] == owed0
        assert plan["on_track"] is True
        assert isinstance(plan["schedule"], list) and len(plan["schedule"]) >= 1
        assert all({"n", "due_on", "amount", "status"}.issubset(r.keys()) for r in plan["schedule"])
        assert all(r["status"] == "due" for r in plan["schedule"])
        assert "emailed" in plan  # may be "sent" or "failed"
        assert plan["emailed"] in ("sent", "failed", None)
        assert isinstance(plan["months"], list) and len(plan["months"]) >= 1
        pid_plan = plan["id"]

        # Duplicate create -> 409
        r = requests.post(f"{API}/rentals/tenancies/{tid}/payment-plan",
                          headers=_h(owner), json=body, timeout=20)
        assert r.status_code == 409, r.text

        # GET returns same plan
        g = requests.get(f"{API}/rentals/tenancies/{tid}/payment-plan", headers=_h(owner), timeout=20).json()
        assert g["id"] == pid_plan
        assert g["amount"] == plan["amount"]

        # Arrears portfolio: tenancy has plan, next_auto_on is None (fully covered on-track)
        arr1 = requests.get(f"{API}/portfolio/arrears", headers=_h(owner), timeout=20).json()
        row1 = next(t for t in arr1["tenancies"] if t["tenancy_id"] == tid)
        assert row1["plan"] is not None
        assert row1["plan"]["id"] == pid_plan
        assert row1["next_auto_on"] is None, f"Expected next_auto_on None when fully covered, got {row1['next_auto_on']}"

        # remind-arrears should 400 "Nothing to chase..."
        r = requests.post(f"{API}/rentals/tenancies/{tid}/remind-arrears",
                          headers=_h(owner), timeout=20)
        assert r.status_code == 400, r.text
        assert "nothing to chase" in r.text.lower()

        # Log instalment: pay first month fully
        oldest_month = plan["months"][0]
        pay_amt = min(300, owed0)
        r = requests.post(f"{API}/payment-plans/{pid_plan}/payments",
                          headers=_h(owner),
                          json={"amount": pay_amt, "paid_on": _server_today().isoformat()},
                          timeout=20)
        assert r.status_code == 200, r.text
        plan2 = r.json()
        assert plan2["paid"] == pay_amt
        assert plan2["remaining"] == round(owed0 - pay_amt, 2)
        # First instalment row should be marked paid
        assert plan2["schedule"][0]["status"] == "paid"

        # rent_payments doc updated for oldest month
        rp = _DB.rent_payments.find_one({"tenancy_id": tid, "month": oldest_month})
        assert rp is not None, f"Expected rent_payments doc for month {oldest_month}"
        assert rp["paid_amount"] > 0

        # Over-pay rejected
        r = requests.post(f"{API}/payment-plans/{pid_plan}/payments",
                          headers=_h(owner),
                          json={"amount": owed0 * 10, "paid_on": _server_today().isoformat()},
                          timeout=20)
        assert r.status_code == 400, r.text
        assert "left" in r.text.lower()

        # portfolio arrears owed dropped
        arr2 = requests.get(f"{API}/portfolio/arrears", headers=_h(owner), timeout=20).json()
        row2 = next((t for t in arr2["tenancies"] if t["tenancy_id"] == tid), None)
        assert row2 is None or row2["owed"] <= owed0 - pay_amt + 0.01

        # DELETE plan
        r = requests.delete(f"{API}/payment-plans/{pid_plan}", headers=_h(owner), timeout=20)
        assert r.status_code == 200 and r.json()["ok"] is True

        # Verify plan status cancelled in mongo
        pdoc = _DB.payment_plans.find_one({"_id": _OID(pid_plan)})
        assert pdoc is not None and pdoc["status"] == "cancelled"

        # GET plan returns null now
        r = requests.get(f"{API}/rentals/tenancies/{tid}/payment-plan", headers=_h(owner), timeout=20)
        assert r.status_code == 200 and r.json() is None

        # Reminders resume: next_auto_on should be populated (there's remaining owed)
        arr3 = requests.get(f"{API}/portfolio/arrears", headers=_h(owner), timeout=20).json()
        row3 = next((t for t in arr3["tenancies"] if t["tenancy_id"] == tid), None)
        if row3:  # could be fully paid if partial = all arrears
            assert row3["plan"] is None
            if row3["owed"] > 0 and row3["tenant_email"]:
                assert row3["next_auto_on"] is not None

    def test_full_payoff_marks_completed(self, owner, tenancy_factory):
        tid = tenancy_factory("Payoff", start_date="2026-01-01", rent=900)
        arr = requests.get(f"{API}/portfolio/arrears", headers=_h(owner), timeout=20).json()
        row = next(t for t in arr["tenancies"] if t["tenancy_id"] == tid)
        owed = row["owed"]
        r = requests.post(f"{API}/rentals/tenancies/{tid}/payment-plan",
                          headers=_h(owner),
                          json={"instalment": owed, "frequency": "monthly",
                                "start_date": _server_today().isoformat(), "notify": False},
                          timeout=30)
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        # Pay in full
        r = requests.post(f"{API}/payment-plans/{pid}/payments",
                          headers=_h(owner),
                          json={"amount": owed, "paid_on": _server_today().isoformat()},
                          timeout=20)
        assert r.status_code == 200, r.text
        pdoc = _DB.payment_plans.find_one({"_id": _OID(pid)})
        assert pdoc["status"] == "completed", f"Expected completed got {pdoc['status']}"
        assert pdoc.get("completed_at")


# ============================= Broken detection =============================


class TestBrokenDetection:
    def test_broken_when_start_date_old_and_unpaid(self, owner, tenancy_factory):
        tid = tenancy_factory("Broken", start_date="2026-01-01", rent=900)
        r = requests.post(f"{API}/rentals/tenancies/{tid}/payment-plan",
                          headers=_h(owner),
                          json={"instalment": 300, "frequency": "monthly",
                                "start_date": _server_today().isoformat(), "notify": False},
                          timeout=30)
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        # Simulate missed instalment: push start_date 10 days back directly in Mongo
        back = (_server_today() - timedelta(days=10)).isoformat()
        _DB.payment_plans.update_one({"_id": _OID(pid)}, {"$set": {"start_date": back}})
        # GET plan -> on_track False, status broken
        g = requests.get(f"{API}/rentals/tenancies/{tid}/payment-plan", headers=_h(owner), timeout=20).json()
        assert g["on_track"] is False
        assert g["status"] == "broken"
        # Mongo doc flipped + broken_at set
        pdoc = _DB.payment_plans.find_one({"_id": _OID(pid)})
        assert pdoc["status"] == "broken"
        assert pdoc.get("broken_at")


# ============================= Scheduler covers =============================


class TestRunAutoReminders:
    def test_run_auto_reminders_skips_covered_months(self, owner, tenancy_factory):
        """Direct call to routes.arrears.run_auto_reminders(): a tenancy fully covered by an on-track plan
           must NOT receive new rent_reminders entries."""
        tid = tenancy_factory("Scheduler", start_date="2026-01-01", rent=900)
        # Create on-track plan covering all overdue months
        r = requests.post(f"{API}/rentals/tenancies/{tid}/payment-plan",
                          headers=_h(owner),
                          json={"instalment": 500, "frequency": "monthly",
                                "start_date": _server_today().isoformat(), "notify": False},
                          timeout=30)
        assert r.status_code == 200, r.text

        before = _DB.rent_reminders.count_documents({"tenancy_id": tid})

        # Need to clear last-attempt stamp so scheduler actually processes it
        _DB.tenancies.update_one({"_id": _OID(tid)}, {"$unset": {"arrears_attempt_at": ""}})

        # Direct call
        from routes.arrears import run_auto_reminders
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run_auto_reminders())
        finally:
            loop.close()

        after = _DB.rent_reminders.count_documents({"tenancy_id": tid})
        assert after == before, f"Scheduler should skip covered months; reminders went from {before} to {after}"


# ============================= Tenant portal =============================


class TestTenantPortalPlanCard:
    def test_portal_shows_payment_plan(self, owner, tenancy_factory):
        tid = tenancy_factory("Portal", start_date="2026-01-01", rent=900)
        # Create a plan
        r = requests.post(f"{API}/rentals/tenancies/{tid}/payment-plan",
                          headers=_h(owner),
                          json={"instalment": 450, "frequency": "monthly",
                                "start_date": _server_today().isoformat(), "notify": False},
                          timeout=30)
        assert r.status_code == 200, r.text
        # Mint portal token
        r = requests.post(f"{API}/rentals/tenancies/{tid}/portal",
                          headers=_h(owner), json={"origin_url": BASE}, timeout=20)
        assert r.status_code == 200, r.text
        url = r.json()["url"]
        # Fetch the HTML
        page = requests.get(url, timeout=20)
        assert page.status_code == 200, page.text[:400]
        html = page.text
        assert "id='payment-plan'" in html or 'id="payment-plan"' in html, "payment-plan card not found"
        assert "Your payment plan" in html
        # Schedule row present (£450 appears in Amount col)
        assert "450" in html


# ============================= Delete tenancy cascades =============================


class TestDeleteCascade:
    def test_deleting_tenancy_removes_plans(self, owner, active_pid):
        tid = _make_tenancy(owner, active_pid, f"Cascade_{uuid.uuid4().hex[:6]}",
                            "2026-01-01", 900, TENANT_EMAIL, True)
        r = requests.post(f"{API}/rentals/tenancies/{tid}/payment-plan",
                          headers=_h(owner),
                          json={"instalment": 400, "frequency": "monthly",
                                "start_date": _server_today().isoformat(), "notify": False},
                          timeout=30)
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        # Delete tenancy
        r = requests.delete(f"{API}/rentals/tenancies/{tid}", headers=_h(owner), timeout=20)
        assert r.status_code == 200, r.text
        # Payment plan should be deleted (or at least not findable active)
        pdoc = _DB.payment_plans.find_one({"_id": _OID(pid)})
        assert pdoc is None, f"Expected plan {pid} to be deleted with tenancy, still in db: {pdoc}"
