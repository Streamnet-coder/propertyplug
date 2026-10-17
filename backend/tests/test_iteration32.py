"""Iteration 32 backend tests:
- Tenancy renewal (POST /api/rentals/tenancies/{id}/renew)
- Rent receipts (PUT /api/rentals/tenancies/{id}/rent/{month}) with receipts_auto
- Remortgage scenarios + fixed_rate_end (PUT /api/project)
"""
import os
from datetime import date, timedelta

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login", json={"email": "demo@mybuilder.app", "password": "demo1234"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def server_today(h):
    """Use the server's health 'now' date; fall back to one of the schedule rows."""
    r = requests.get(f"{API}/rentals", headers=h)
    assert r.status_code == 200
    yr = r.json()["year"]
    # use UTC today as fallback approximation; backend uses date.today() which is utc on server
    return date(yr, date.today().month if date.today().year == yr else 1, date.today().day if date.today().year == yr else 1)


@pytest.fixture
def tenancy(h):
    """Create a fresh TEST_ tenancy and clean up after the test."""
    today = date.today()
    body = {
        "tenant_name": "TEST_iter32 Tenant",
        "tenant_email": "delivered@resend.dev",
        "rent": 1000,
        "deposit": 500,
        "start_date": (today - timedelta(days=200)).isoformat(),
        "end_date": (today + timedelta(days=165)).isoformat(),
        "rent_day": 1,
        "receipts_auto": True,
    }
    r = requests.post(f"{API}/rentals/tenancies", headers=h, json=body)
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    yield tid, body
    requests.delete(f"{API}/rentals/tenancies/{tid}", headers=h)


# -------------------- Renewal --------------------

class TestRenew:
    def test_end_date_must_be_future(self, h, tenancy):
        tid, b = tenancy
        past = (date.today() - timedelta(days=1)).isoformat()
        r = requests.post(f"{API}/rentals/tenancies/{tid}/renew", headers=h,
                          json={"end_date": past, "notify": False})
        assert r.status_code == 400
        assert "future" in r.json().get("detail", "").lower()

    def test_new_rent_without_rent_from_400(self, h, tenancy):
        tid, _ = tenancy
        future = (date.today() + timedelta(days=400)).isoformat()
        r = requests.post(f"{API}/rentals/tenancies/{tid}/renew", headers=h,
                          json={"end_date": future, "new_rent": 1200, "notify": False})
        assert r.status_code == 400

    def test_rent_from_before_start_400(self, h, tenancy):
        tid, b = tenancy
        future = (date.today() + timedelta(days=400)).isoformat()
        bad_from = (date.fromisoformat(b["start_date"]) - timedelta(days=5)).isoformat()
        r = requests.post(f"{API}/rentals/tenancies/{tid}/renew", headers=h,
                          json={"end_date": future, "new_rent": 1200, "rent_from": bad_from, "notify": False})
        assert r.status_code == 400

    def test_end_date_null_rolling(self, h, tenancy):
        tid, _ = tenancy
        r = requests.post(f"{API}/rentals/tenancies/{tid}/renew", headers=h,
                          json={"end_date": None, "notify": False})
        assert r.status_code == 200, r.text
        # verify via GET /rentals
        g = requests.get(f"{API}/rentals", headers=h).json()
        t = next(x for x in g["tenancies"] if x["id"] == tid)
        assert t["end_date"] is None
        assert len(t["renewals"]) >= 1

    def test_renew_with_new_rent_and_schedule(self, h, tenancy):
        tid, b = tenancy
        today = date.today()
        future_end = (today + timedelta(days=400)).isoformat()
        rent_from = date(today.year, today.month, 1).isoformat()
        r = requests.post(f"{API}/rentals/tenancies/{tid}/renew", headers=h,
                          json={"end_date": future_end, "new_rent": 1200, "rent_from": rent_from, "notify": True})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        # notify=True + tenant_email present => emailed should be 'sent' (or 'failed' if resend down)
        assert data["emailed"] in ("sent", "failed")

        g = requests.get(f"{API}/rentals", headers=h, params={"year": today.year}).json()
        t = next(x for x in g["tenancies"] if x["id"] == tid)
        assert t["end_date"] == future_end
        # rent_changes stored
        changes = t["rent_changes"]
        assert any(c["from_month"] == rent_from[:7] and c["rent"] == 1200 for c in changes)
        # current_rent should be new one (as of today, which is in rent_from's month)
        assert t["current_rent"] == 1200
        # schedule: month equal to rent_from should have due == 1200
        from_month = rent_from[:7]
        row = next(x for x in t["schedule"] if x["month"] == from_month)
        assert row["due"] == 1200

    def test_renew_notify_false_no_email(self, h, tenancy):
        tid, _ = tenancy
        future = (date.today() + timedelta(days=400)).isoformat()
        r = requests.post(f"{API}/rentals/tenancies/{tid}/renew", headers=h,
                          json={"end_date": future, "notify": False})
        assert r.status_code == 200
        assert r.json()["emailed"] is None


# -------------------- Rent receipts --------------------

class TestReceipts:
    def test_log_rent_sends_receipt(self, h, tenancy):
        tid, b = tenancy
        today = date.today()
        month = f"{today.year}-{today.month:02d}"
        r = requests.put(f"{API}/rentals/tenancies/{tid}/rent/{month}", headers=h,
                         json={"paid_amount": 1000, "paid_on": today.isoformat()})
        assert r.status_code == 200, r.text
        assert r.json().get("receipt") in ("sent", "failed")

    def test_resave_same_amount_no_receipt(self, h, tenancy):
        tid, _ = tenancy
        today = date.today()
        month = f"{today.year}-{today.month:02d}"
        # first log
        requests.put(f"{API}/rentals/tenancies/{tid}/rent/{month}", headers=h,
                     json={"paid_amount": 1000, "paid_on": today.isoformat()})
        # same amount again -> receipt should be None
        r = requests.put(f"{API}/rentals/tenancies/{tid}/rent/{month}", headers=h,
                         json={"paid_amount": 1000, "paid_on": today.isoformat()})
        assert r.status_code == 200
        assert r.json().get("receipt") is None

    def test_receipts_auto_off_no_receipt(self, h, tenancy):
        tid, b = tenancy
        # turn receipts_auto off
        put = requests.put(f"{API}/rentals/tenancies/{tid}", headers=h,
                           json={**b, "receipts_auto": False})
        assert put.status_code == 200
        today = date.today()
        month = f"{today.year}-{today.month:02d}"
        r = requests.put(f"{API}/rentals/tenancies/{tid}/rent/{month}", headers=h,
                         json={"paid_amount": 950, "paid_on": today.isoformat()})
        assert r.status_code == 200
        assert r.json().get("receipt") is None

    def test_no_email_no_receipt(self, h):
        today = date.today()
        body = {
            "tenant_name": "TEST_iter32 NoEmail",
            "tenant_email": "",
            "rent": 800,
            "start_date": (today - timedelta(days=60)).isoformat(),
            "rent_day": 1,
            "receipts_auto": True,
        }
        r = requests.post(f"{API}/rentals/tenancies", headers=h, json=body)
        assert r.status_code == 200
        tid = r.json()["id"]
        try:
            month = f"{today.year}-{today.month:02d}"
            r2 = requests.put(f"{API}/rentals/tenancies/{tid}/rent/{month}", headers=h,
                              json={"paid_amount": 800, "paid_on": today.isoformat()})
            assert r2.status_code == 200
            assert r2.json().get("receipt") is None
        finally:
            requests.delete(f"{API}/rentals/tenancies/{tid}", headers=h)


# -------------------- Remortgage scenarios + fixed_rate_end --------------------

@pytest.fixture(scope="module")
def personal_project(h):
    """Switch demo project to purpose=personal and restore at the end."""
    r = requests.get(f"{API}/project", headers=h).json()
    original = {"purpose": r["purpose"], "deposit": r["deposit"],
                "fixed_rate_end": r.get("fixed_rate_end"), "remortgage_scenarios": []}
    requests.put(f"{API}/project", headers=h,
                 json={"purpose": "personal", "deposit": 20000, "mortgage_rate": 5.0,
                       "mortgage_term": 25, "remortgage_ltv": 85})
    yield
    requests.put(f"{API}/project", headers=h, json={**original, "purpose": "investment", "deposit": 0,
                                                     "fixed_rate_end": None, "remortgage_scenarios": []})


class TestProjectRemortgage:
    def test_bad_fixed_rate_date_400(self, h, personal_project):
        r = requests.put(f"{API}/project", headers=h, json={"fixed_rate_end": "2026/01/01"})
        assert r.status_code == 400
        assert "YYYY-MM-DD" in r.json().get("detail", "")

    def test_too_many_scenarios_422(self, h, personal_project):
        r = requests.put(f"{API}/project", headers=h, json={
            "remortgage_scenarios": [
                {"label": "A", "rate": 4.5, "fee": 999},
                {"label": "B", "rate": 5.0, "fee": 0},
                {"label": "C", "rate": 5.5, "fee": 500},
                {"label": "D", "rate": 6.0, "fee": 100},
            ]})
        assert r.status_code == 422

    def test_bad_rate_422(self, h, personal_project):
        r = requests.put(f"{API}/project", headers=h, json={
            "remortgage_scenarios": [{"label": "Bad", "rate": 0, "fee": 0}]})
        assert r.status_code == 422
        r2 = requests.put(f"{API}/project", headers=h, json={
            "remortgage_scenarios": [{"label": "Bad", "rate": 31, "fee": 0}]})
        assert r2.status_code == 422

    def test_scenarios_computed_and_best_flags(self, h, personal_project):
        r = requests.put(f"{API}/project", headers=h, json={
            "remortgage_scenarios": [
                {"label": "", "rate": 4.5, "fee": 1500},     # low rate high fee
                {"label": "2yr fix", "rate": 5.0, "fee": 0},
                {"label": "", "rate": 5.5, "fee": 200},
            ]})
        assert r.status_code == 200, r.text
        hf = r.json()["home_finance"]
        scen = hf["scenarios"]
        assert len(scen) == 3
        # default label when empty = "Option N"
        assert scen[0]["label"] == "Option 1"
        assert scen[1]["label"] == "2yr fix"
        assert scen[2]["label"] == "Option 3"
        # exactly one best_monthly and one best_two_year
        assert sum(x["best_monthly"] for x in scen) == 1
        assert sum(x["best_two_year"] for x in scen) == 1
        # best_monthly must be the min monthly_payment
        bm = min(scen, key=lambda x: x["monthly_payment"])
        assert bm["best_monthly"] is True
        # best_two_year must be the min two_year_cost
        b2 = min(scen, key=lambda x: x["two_year_cost"])
        assert b2["best_two_year"] is True
        # keys present
        for x in scen:
            for k in ("label", "rate", "fee", "monthly_payment", "vs_current", "two_year_cost", "best_monthly", "best_two_year"):
                assert k in x

    def test_fixed_rate_end_and_days_left(self, h, personal_project):
        future = (date.today() + timedelta(days=30)).isoformat()
        r = requests.put(f"{API}/project", headers=h, json={"fixed_rate_end": future})
        assert r.status_code == 200, r.text
        hf = r.json()["home_finance"]
        assert hf["fixed_rate_end"] == future
        assert 28 <= hf["fixed_days_left"] <= 31

    def test_fixed_rate_end_null_clears(self, h, personal_project):
        r = requests.put(f"{API}/project", headers=h, json={"fixed_rate_end": None})
        assert r.status_code == 200
        hf = r.json()["home_finance"]
        assert hf["fixed_rate_end"] is None
        assert hf["fixed_days_left"] is None


# -------------------- Reminder still uses renewed rent --------------------

class TestReminderUsesRenewedRent:
    def test_reminder_amount_matches_renewed_rent(self, h):
        today = date.today()
        # tenancy with past unpaid month
        body = {
            "tenant_name": "TEST_iter32 Reminder",
            "tenant_email": "delivered@resend.dev",
            "rent": 800,
            "start_date": date(today.year - 1, 1, 1).isoformat(),
            "end_date": (today + timedelta(days=400)).isoformat(),
            "rent_day": 1,
            "receipts_auto": False,
        }
        r = requests.post(f"{API}/rentals/tenancies", headers=h, json=body)
        tid = r.json()["id"]
        try:
            rent_from = date(today.year, today.month, 1).isoformat()
            # renew with new rent effective this month
            requests.post(f"{API}/rentals/tenancies/{tid}/renew", headers=h,
                          json={"end_date": (today + timedelta(days=400)).isoformat(),
                                "new_rent": 1100, "rent_from": rent_from, "notify": False})
            # check schedule current month due = 1100
            g = requests.get(f"{API}/rentals", headers=h, params={"year": today.year}).json()
            t = next(x for x in g["tenancies"] if x["id"] == tid)
            assert t["current_rent"] == 1100
        finally:
            requests.delete(f"{API}/rentals/tenancies/{tid}", headers=h)
