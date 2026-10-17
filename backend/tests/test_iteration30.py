"""Iteration 30 - Rental & tenancy tracker.

Scope:
- GET /api/rentals?year=YYYY shape, scoping to active project
- POST/PUT/DELETE /api/rentals/tenancies with validation
- PUT /api/rentals/tenancies/{id}/rent/{YYYY-MM} upsert; paid=0 clears; statuses
- POST/PUT/DELETE /api/rentals/expenses with validation
- Deleting a tenancy removes its rent_payments
- Data scoped to active project (other project cannot see it)
"""
import os
import sys
import asyncio
import uuid
from datetime import date

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
sys.path.insert(0, "/app/backend")

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
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


_created = {"tenancies": [], "expenses": []}


@pytest.fixture(scope="module")
def demo_headers():
    r = requests.post(f"{API}/auth/login", json=DEMO, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def active_project(demo_headers):
    r = requests.get(f"{API}/projects", headers=demo_headers, timeout=10)
    assert r.status_code == 200, r.text
    projects = r.json()
    me = requests.get(f"{API}/auth/me", headers=demo_headers, timeout=10).json()
    aid = me.get("active_project_id") or projects[0]["id"]
    return aid


@pytest.fixture(scope="module", autouse=True)
def _teardown(demo_headers):
    yield
    # Clean up via API (uses user_id scope automatically)
    for eid in _created["expenses"]:
        try:
            requests.delete(f"{API}/rentals/expenses/{eid}", headers=demo_headers, timeout=10)
        except Exception:
            pass
    for tid in _created["tenancies"]:
        try:
            requests.delete(f"{API}/rentals/tenancies/{tid}", headers=demo_headers, timeout=10)
        except Exception:
            pass


# ---- Validation on tenancies ------------------------------------------------

class TestTenancyValidation:
    def test_name_required(self, demo_headers):
        r = requests.post(f"{API}/rentals/tenancies", headers=demo_headers,
                          json={"tenant_name": "   ", "rent": 100, "start_date": "2026-01-01"}, timeout=10)
        assert r.status_code == 422, r.text

    def test_rent_positive(self, demo_headers):
        r = requests.post(f"{API}/rentals/tenancies", headers=demo_headers,
                          json={"tenant_name": "TEST_X", "rent": 0, "start_date": "2026-01-01"}, timeout=10)
        assert r.status_code == 422, r.text

    def test_start_date_format(self, demo_headers):
        r = requests.post(f"{API}/rentals/tenancies", headers=demo_headers,
                          json={"tenant_name": "TEST_X", "rent": 100, "start_date": "01/01/2026"}, timeout=10)
        assert r.status_code == 422, r.text

    def test_end_before_start(self, demo_headers):
        r = requests.post(f"{API}/rentals/tenancies", headers=demo_headers,
                          json={"tenant_name": "TEST_X", "rent": 100,
                                "start_date": "2026-06-01", "end_date": "2026-01-01"}, timeout=10)
        assert r.status_code == 400, r.text
        assert "End date" in r.text

    def test_rent_day_range(self, demo_headers):
        r = requests.post(f"{API}/rentals/tenancies", headers=demo_headers,
                          json={"tenant_name": "TEST_X", "rent": 100,
                                "start_date": "2026-01-01", "rent_day": 29}, timeout=10)
        assert r.status_code == 422, r.text


# ---- Tenancy CRUD + yearly summary -----------------------------------------

TEST_YEAR = 2026


class TestTenancyFlow:
    @pytest.fixture(scope="class")
    def tenancy_id(self, demo_headers):
        payload = {
            "tenant_name": f"TEST_iter30_{uuid.uuid4().hex[:6]}",
            "rent": 1000,
            "deposit": 1200,
            "deposit_scheme": "DPS",
            "start_date": f"{TEST_YEAR}-01-01",
            "end_date": f"{TEST_YEAR}-12-31",
            "rent_day": 5,
        }
        r = requests.post(f"{API}/rentals/tenancies", headers=demo_headers, json=payload, timeout=15)
        assert r.status_code == 200, r.text
        tid = r.json()["id"]
        _created["tenancies"].append(tid)
        return tid

    def test_tenancy_appears_in_year(self, demo_headers, tenancy_id):
        r = requests.get(f"{API}/rentals", headers=demo_headers, params={"year": TEST_YEAR}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["year"] == TEST_YEAR
        t = next((x for x in d["tenancies"] if x["id"] == tenancy_id), None)
        assert t is not None, "tenancy missing in response"
        assert t["rent"] == 1000
        assert t["deposit"] == 1200
        assert len(t["schedule"]) == 12
        for row in t["schedule"]:
            assert row["due"] == 1000
            assert row["paid"] == 0.0
            assert row["status"] in ("due", "late", "paid", "partial")
            assert row["due_on"].endswith("-05")  # rent_day 5
        # Summary shape
        sm = d["summary"]
        for k in ("rent_due", "received", "arrears", "expenses", "net", "by_category", "monthly", "active_rent"):
            assert k in sm
        assert len(sm["monthly"]) == 12
        assert sm["rent_due"] >= 12000  # at least 12*1000 due for this tenancy

    def test_update_tenancy(self, demo_headers, tenancy_id):
        r = requests.put(f"{API}/rentals/tenancies/{tenancy_id}", headers=demo_headers,
                         json={"tenant_name": "TEST_iter30_updated", "rent": 1100,
                               "start_date": f"{TEST_YEAR}-01-01", "rent_day": 5}, timeout=10)
        assert r.status_code == 200
        g = requests.get(f"{API}/rentals", headers=demo_headers, params={"year": TEST_YEAR}, timeout=10).json()
        t = next(x for x in g["tenancies"] if x["id"] == tenancy_id)
        assert t["rent"] == 1100
        assert t["tenant_name"] == "TEST_iter30_updated"

    def test_log_rent_full_paid(self, demo_headers, tenancy_id):
        # Pay Feb in full
        r = requests.put(f"{API}/rentals/tenancies/{tenancy_id}/rent/{TEST_YEAR}-02",
                         headers=demo_headers, json={"paid_amount": 1100, "paid_on": f"{TEST_YEAR}-02-05"}, timeout=10)
        assert r.status_code == 200
        d = requests.get(f"{API}/rentals", headers=demo_headers, params={"year": TEST_YEAR}, timeout=10).json()
        t = next(x for x in d["tenancies"] if x["id"] == tenancy_id)
        feb = next(m for m in t["schedule"] if m["month"] == f"{TEST_YEAR}-02")
        assert feb["status"] == "paid"
        assert feb["paid"] == 1100
        assert feb["paid_on"] == f"{TEST_YEAR}-02-05"

    def test_log_rent_partial(self, demo_headers, tenancy_id):
        r = requests.put(f"{API}/rentals/tenancies/{tenancy_id}/rent/{TEST_YEAR}-03",
                         headers=demo_headers, json={"paid_amount": 500, "paid_on": f"{TEST_YEAR}-03-10"}, timeout=10)
        assert r.status_code == 200
        d = requests.get(f"{API}/rentals", headers=demo_headers, params={"year": TEST_YEAR}, timeout=10).json()
        t = next(x for x in d["tenancies"] if x["id"] == tenancy_id)
        mar = next(m for m in t["schedule"] if m["month"] == f"{TEST_YEAR}-03")
        assert mar["status"] == "partial"
        assert mar["paid"] == 500

    def test_log_rent_clear_with_zero(self, demo_headers, tenancy_id):
        # Clear Feb
        r = requests.put(f"{API}/rentals/tenancies/{tenancy_id}/rent/{TEST_YEAR}-02",
                         headers=demo_headers, json={"paid_amount": 0}, timeout=10)
        assert r.status_code == 200
        d = requests.get(f"{API}/rentals", headers=demo_headers, params={"year": TEST_YEAR}, timeout=10).json()
        t = next(x for x in d["tenancies"] if x["id"] == tenancy_id)
        feb = next(m for m in t["schedule"] if m["month"] == f"{TEST_YEAR}-02")
        assert feb["paid"] == 0.0
        assert feb["status"] in ("due", "late")

    def test_log_rent_invalid_month(self, demo_headers, tenancy_id):
        r = requests.put(f"{API}/rentals/tenancies/{tenancy_id}/rent/2026-13",
                         headers=demo_headers, json={"paid_amount": 100}, timeout=10)
        assert r.status_code == 400

    def test_late_status_for_past_month(self, demo_headers, tenancy_id):
        # Pick first month in current year that is before today
        today = date.today()
        target = None
        for m in range(1, 13):
            if date(today.year, m, 28) < today:
                target = f"{today.year}-{m:02d}"
                break
        if not target:
            pytest.skip("no past month available this year")
        # Create a tenancy that covers current year
        r = requests.post(f"{API}/rentals/tenancies", headers=demo_headers,
                          json={"tenant_name": f"TEST_iter30_late_{uuid.uuid4().hex[:6]}",
                                "rent": 500, "start_date": f"{today.year}-01-01", "rent_day": 1}, timeout=10)
        assert r.status_code == 200
        tid2 = r.json()["id"]
        _created["tenancies"].append(tid2)
        d = requests.get(f"{API}/rentals", headers=demo_headers, params={"year": today.year}, timeout=10).json()
        t = next(x for x in d["tenancies"] if x["id"] == tid2)
        row = next(m for m in t["schedule"] if m["month"] == target)
        # Not paid + due_on in the past -> late
        assert row["status"] == "late", f"expected late, got {row}"
        assert t["late_count"] >= 1
        assert t["arrears"] > 0


# ---- Expense CRUD & scoping -------------------------------------------------

class TestExpenses:
    def test_invalid_category(self, demo_headers):
        r = requests.post(f"{API}/rentals/expenses", headers=demo_headers,
                          json={"category": "food", "amount": 10, "date": f"{TEST_YEAR}-02-01"}, timeout=10)
        assert r.status_code == 422

    def test_amount_must_be_positive(self, demo_headers):
        r = requests.post(f"{API}/rentals/expenses", headers=demo_headers,
                          json={"category": "repairs", "amount": 0, "date": f"{TEST_YEAR}-02-01"}, timeout=10)
        assert r.status_code == 422

    def test_bad_date_format(self, demo_headers):
        r = requests.post(f"{API}/rentals/expenses", headers=demo_headers,
                          json={"category": "repairs", "amount": 10, "date": "02-01-2026"}, timeout=10)
        assert r.status_code == 422

    def test_create_update_delete_and_summary(self, demo_headers):
        # Create
        r = requests.post(f"{API}/rentals/expenses", headers=demo_headers,
                          json={"category": "repairs", "amount": 120, "date": f"{TEST_YEAR}-02-10",
                                "description": "TEST_iter30 boiler"}, timeout=10)
        assert r.status_code == 200, r.text
        eid = r.json()["id"]
        _created["expenses"].append(eid)

        # Reflected in summary
        d = requests.get(f"{API}/rentals", headers=demo_headers, params={"year": TEST_YEAR}, timeout=10).json()
        exp_mine = next((e for e in d["expenses"] if e["id"] == eid), None)
        assert exp_mine is not None
        assert exp_mine["category"] == "repairs"
        assert exp_mine["amount"] == 120
        assert d["summary"]["expenses"] >= 120
        assert d["summary"]["by_category"].get("repairs", 0) >= 120

        # Update
        r = requests.put(f"{API}/rentals/expenses/{eid}", headers=demo_headers,
                         json={"category": "letting_agent", "amount": 80, "date": f"{TEST_YEAR}-02-10",
                               "description": "TEST_iter30 agent fee"}, timeout=10)
        assert r.status_code == 200
        d = requests.get(f"{API}/rentals", headers=demo_headers, params={"year": TEST_YEAR}, timeout=10).json()
        exp_updated = next(e for e in d["expenses"] if e["id"] == eid)
        assert exp_updated["category"] == "letting_agent"
        assert exp_updated["amount"] == 80

        # Delete
        r = requests.delete(f"{API}/rentals/expenses/{eid}", headers=demo_headers, timeout=10)
        assert r.status_code == 200
        _created["expenses"].remove(eid)
        d = requests.get(f"{API}/rentals", headers=demo_headers, params={"year": TEST_YEAR}, timeout=10).json()
        assert all(e["id"] != eid for e in d["expenses"])

    def test_update_missing_returns_404(self, demo_headers):
        r = requests.put(f"{API}/rentals/expenses/507f1f77bcf86cd799439011", headers=demo_headers,
                         json={"category": "repairs", "amount": 10, "date": f"{TEST_YEAR}-02-01"}, timeout=10)
        assert r.status_code == 404


# ---- Deleting tenancy cascades rent_payments; project scope -----------------

class TestCascadeAndScope:
    def test_delete_tenancy_removes_rent_payments(self, demo_headers):
        # Create a tenancy, log a payment, delete tenancy, ensure payment doc gone
        r = requests.post(f"{API}/rentals/tenancies", headers=demo_headers,
                          json={"tenant_name": f"TEST_iter30_cascade_{uuid.uuid4().hex[:6]}",
                                "rent": 400, "start_date": f"{TEST_YEAR}-01-01", "rent_day": 1}, timeout=10)
        assert r.status_code == 200
        tid = r.json()["id"]

        r = requests.put(f"{API}/rentals/tenancies/{tid}/rent/{TEST_YEAR}-04",
                         headers=demo_headers, json={"paid_amount": 400, "paid_on": f"{TEST_YEAR}-04-01"}, timeout=10)
        assert r.status_code == 200

        # Verify payment present in db
        def _count(db):
            return db.rent_payments.count_documents({"tenancy_id": tid})
        count_before = _run(_count)
        assert count_before == 1

        r = requests.delete(f"{API}/rentals/tenancies/{tid}", headers=demo_headers, timeout=10)
        assert r.status_code == 200

        count_after = _run(_count)
        assert count_after == 0, f"rent_payments not cleaned up ({count_after})"

    def test_data_scoped_to_active_project(self, demo_headers, active_project):
        # Create a tenancy on active project; switch active project; it should disappear from GET.
        r = requests.get(f"{API}/projects", headers=demo_headers, timeout=10)
        assert r.status_code == 200
        projects = r.json()
        if len(projects) < 2:
            # create a second project
            r = requests.post(f"{API}/projects", headers=demo_headers,
                              json={"name": "TEST_iter30_proj", "address": "nowhere"}, timeout=10)
            assert r.status_code in (200, 201), r.text
            projects = requests.get(f"{API}/projects", headers=demo_headers, timeout=10).json()
        other = next(p for p in projects if p["id"] != active_project)

        # Make sure current active is `active_project`
        requests.post(f"{API}/projects/{active_project}/activate", headers=demo_headers, timeout=10)

        r = requests.post(f"{API}/rentals/tenancies", headers=demo_headers,
                          json={"tenant_name": f"TEST_iter30_scope_{uuid.uuid4().hex[:6]}",
                                "rent": 777, "start_date": f"{TEST_YEAR}-01-01"}, timeout=10)
        assert r.status_code == 200
        tid = r.json()["id"]
        _created["tenancies"].append(tid)

        # Visible on active project
        d = requests.get(f"{API}/rentals", headers=demo_headers, params={"year": TEST_YEAR}, timeout=10).json()
        assert any(t["id"] == tid for t in d["tenancies"])

        # Switch to the other project
        r = requests.post(f"{API}/projects/{other['id']}/activate", headers=demo_headers, timeout=10)
        assert r.status_code == 200
        d2 = requests.get(f"{API}/rentals", headers=demo_headers, params={"year": TEST_YEAR}, timeout=10).json()
        assert all(t["id"] != tid for t in d2["tenancies"]), "tenancy leaked across projects"

        # Switch back for cleanup
        requests.post(f"{API}/projects/{active_project}/activate", headers=demo_headers, timeout=10)

        # Clean up any TEST_iter30_proj we created
        if other["name"].startswith("TEST_iter30_"):
            requests.delete(f"{API}/projects/{other['id']}", headers=demo_headers, timeout=10)
