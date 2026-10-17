"""Iteration 31 backend tests: rent reminders, compare share links, project purpose + home_finance."""
import os
import time
from datetime import date, timedelta

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://dev-budget-tracker-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
DEMO = {"email": "demo@mybuilder.app", "password": "demo1234"}


# -------- shared fixtures --------
@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json=DEMO, timeout=30)
    assert r.status_code == 200, r.text
    s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    return s


@pytest.fixture(scope="module")
def active_pid(session):
    r = session.get(f"{API}/projects", timeout=30)
    assert r.status_code == 200
    pid = next((p["id"] for p in r.json() if p.get("active")), None)
    assert pid, "No active project"
    return pid


# ============== Rent reminders ==============
class TestRentReminders:
    @pytest.fixture(scope="class")
    def tenancy_with_email(self, session):
        start = (date.today().replace(day=1) - timedelta(days=400)).isoformat()
        body = {
            "tenant_name": "TEST_iter31 Tenant A",
            "tenant_email": "delivered@resend.dev",
            "rent": 900.0, "deposit": 900.0,
            "start_date": start, "rent_day": 1,
        }
        r = session.post(f"{API}/rentals/tenancies", json=body, timeout=30)
        assert r.status_code == 200, r.text
        tid = r.json()["id"]
        yield tid
        session.delete(f"{API}/rentals/tenancies/{tid}", timeout=30)

    @pytest.fixture(scope="class")
    def tenancy_no_email(self, session):
        start = (date.today().replace(day=1) - timedelta(days=400)).isoformat()
        r = session.post(f"{API}/rentals/tenancies", json={
            "tenant_name": "TEST_iter31 Tenant NoEmail",
            "rent": 800.0, "start_date": start, "rent_day": 5,
        }, timeout=30)
        assert r.status_code == 200
        tid = r.json()["id"]
        yield tid
        session.delete(f"{API}/rentals/tenancies/{tid}", timeout=30)

    def _late_month(self):
        """A month in the past within the tenancy that is unpaid (will be 'late')."""
        t = date.today()
        y, m = t.year, t.month - 1
        if m == 0:
            y, m = y - 1, 12
        return f"{y}-{m:02d}"

    def _upcoming_month(self):
        """Future month in the next year (still within our 400-days-ago tenancy -> actually in next year won't match end=None rolling, OK)."""
        t = date.today()
        y, m = t.year, t.month + 1
        if m == 13:
            y, m = y + 1, 1
        return f"{y}-{m:02d}"

    def test_400_without_tenant_email(self, session, tenancy_no_email):
        r = session.post(f"{API}/rentals/tenancies/{tenancy_no_email}/remind", json={"month": self._late_month()}, timeout=30)
        assert r.status_code == 400
        assert "email" in r.json()["detail"].lower()

    def test_400_outside_tenancy_month(self, session, tenancy_with_email):
        # 10 years ago - well before start_date
        r = session.post(f"{API}/rentals/tenancies/{tenancy_with_email}/remind", json={"month": "2000-01"}, timeout=30)
        assert r.status_code == 400
        assert "no rent" in r.json()["detail"].lower()

    def test_400_bad_month_format(self, session, tenancy_with_email):
        r = session.post(f"{API}/rentals/tenancies/{tenancy_with_email}/remind", json={"month": "2026-13"}, timeout=30)
        assert r.status_code == 400

    def test_400_if_paid(self, session, tenancy_with_email):
        m = self._upcoming_month()
        # Log a payment >= rent for this month
        r = session.put(f"{API}/rentals/tenancies/{tenancy_with_email}/rent/{m}", json={"paid_amount": 900.0}, timeout=30)
        assert r.status_code == 200
        r = session.post(f"{API}/rentals/tenancies/{tenancy_with_email}/remind", json={"month": m}, timeout=30)
        assert r.status_code == 400
        assert "already paid" in r.json()["detail"].lower()
        # Clear it
        session.put(f"{API}/rentals/tenancies/{tenancy_with_email}/rent/{m}", json={"paid_amount": 0}, timeout=30)

    def test_send_reminder_late_kind_and_rate_limit(self, session, tenancy_with_email):
        m = self._late_month()
        r = session.post(f"{API}/rentals/tenancies/{tenancy_with_email}/remind", json={"month": m}, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["kind"] == "late"
        assert "sent_at" in body
        # 429 within 10 min
        r2 = session.post(f"{API}/rentals/tenancies/{tenancy_with_email}/remind", json={"month": m}, timeout=30)
        assert r2.status_code == 429
        assert "10 min" in r2.json()["detail"]

    def test_schedule_has_reminded_at_and_tenancy_fields(self, session, tenancy_with_email):
        year = int(self._late_month()[:4])
        r = session.get(f"{API}/rentals?year={year}", timeout=30)
        assert r.status_code == 200
        data = r.json()
        t = next((x for x in data["tenancies"] if x["id"] == tenancy_with_email), None)
        assert t is not None
        # tenancy-level new fields
        assert "deposit_protected" in t
        assert t["deposit_protected"] is False  # default
        assert "days_to_end" in t  # None since no end date
        assert t["days_to_end"] is None
        # schedule row has reminded_at populated for the late month
        row = next(r for r in t["schedule"] if r["month"] == self._late_month())
        assert row.get("reminded_at") is not None, "reminded_at should be set after sending reminder"

    def test_upcoming_kind_separate_tenancy(self, session):
        # Fresh tenancy to avoid the 10-min lockout on another month
        start = (date.today().replace(day=1) - timedelta(days=400)).isoformat()
        r = session.post(f"{API}/rentals/tenancies", json={
            "tenant_name": "TEST_iter31 Tenant Upcoming",
            "tenant_email": "delivered@resend.dev",
            "rent": 1000.0,
            "start_date": start,
            "rent_day": 28,  # late in month -> this current month may still be upcoming before 28th
        }, timeout=30)
        assert r.status_code == 200
        tid = r.json()["id"]
        try:
            today = date.today()
            # pick a month whose rent_day (28) is in the future
            if today.day < 28:
                m = f"{today.year}-{today.month:02d}"
            else:
                nm = today.month + 1
                ny = today.year + (1 if nm == 13 else 0)
                nm = 1 if nm == 13 else nm
                m = f"{ny}-{nm:02d}"
            r = session.post(f"{API}/rentals/tenancies/{tid}/remind", json={"month": m}, timeout=60)
            assert r.status_code == 200, r.text
            assert r.json()["kind"] == "upcoming"
        finally:
            session.delete(f"{API}/rentals/tenancies/{tid}", timeout=30)


# ============== Compare share links ==============
class TestCompareLinks:
    @pytest.fixture(scope="class")
    def photos(self, session, active_pid):
        r = session.get(f"{API}/media", timeout=30)
        assert r.status_code == 200
        items = r.json()
        before = next((m for m in items if m.get("phase") == "before"), None)
        after = next((m for m in items if m.get("phase") == "after"), None)
        assert before and after, f"Need at least one before & one after photo in seeded data; got {[m.get('phase') for m in items]}"
        return before["id"], after["id"]

    @pytest.fixture(scope="class")
    def link_id(self, session, photos):
        bid, aid = photos
        r = session.post(f"{API}/compare-links", json={
            "before_id": bid, "after_id": aid,
            "title": "TEST_iter31 Transformation",
            "origin_url": BASE_URL,
        }, timeout=30)
        assert r.status_code == 200, r.text
        lid = r.json()["id"]
        yield lid
        session.delete(f"{API}/compare-links/{lid}", timeout=30)

    def test_create_response_shape(self, session, photos):
        bid, aid = photos
        r = session.post(f"{API}/compare-links", json={
            "before_id": bid, "after_id": aid,
            "title": "TEST_iter31 Shape",
            "origin_url": BASE_URL,
        }, timeout=30)
        assert r.status_code == 200
        data = r.json()
        for k in ("id", "token", "url", "before_id", "after_id", "title", "created_at"):
            assert k in data
        assert data["url"].startswith(f"{BASE_URL}/api/c/")
        assert data["token"] in data["url"]
        session.delete(f"{API}/compare-links/{data['id']}", timeout=30)

    def test_404_bad_photo(self, session, photos):
        bid, _ = photos
        r = session.post(f"{API}/compare-links", json={
            "before_id": bid, "after_id": "68a0000000000000000000ff",
            "title": "TEST_iter31 Bad", "origin_url": BASE_URL,
        }, timeout=30)
        assert r.status_code == 404

    def test_same_pair_reuses_link(self, session, photos, link_id):
        bid, aid = photos
        # Fetch original token
        orig = next(x for x in session.get(f"{API}/compare-links", timeout=30).json() if x["id"] == link_id)
        # Re-create with same pair
        r = session.post(f"{API}/compare-links", json={
            "before_id": bid, "after_id": aid,
            "title": "TEST_iter31 Updated title",
            "origin_url": BASE_URL,
        }, timeout=30)
        assert r.status_code == 200
        again = r.json()
        assert again["id"] == link_id, "Same before/after pair should reuse the existing link"
        assert again["token"] == orig["token"]
        assert again["title"] == "TEST_iter31 Updated title"

    def test_list_links(self, session, link_id):
        r = session.get(f"{API}/compare-links", timeout=30)
        assert r.status_code == 200
        ids = [x["id"] for x in r.json()]
        assert link_id in ids

    def test_public_html_has_slider(self, session, link_id):
        link = next(x for x in session.get(f"{API}/compare-links").json() if x["id"] == link_id)
        token = link["token"]
        r = requests.get(f"{API}/c/{token}", timeout=30)
        assert r.status_code == 200
        html = r.text
        assert "id='ba'" in html or 'id="ba"' in html
        assert "trial" in html.lower() or "start" in html.lower() or "builder" in html.lower()
        # photo URLs referenced
        assert "/photo/before" in html and "/photo/after" in html

    def test_photo_endpoint(self, session, link_id):
        token = next(x["token"] for x in session.get(f"{API}/compare-links").json() if x["id"] == link_id)
        for which in ("before", "after"):
            r = requests.get(f"{API}/c/{token}/photo/{which}", timeout=30, allow_redirects=False)
            assert r.status_code in (200, 302, 307), f"{which}: {r.status_code}"

    def test_logo_endpoint(self, session, link_id):
        token = next(x["token"] for x in session.get(f"{API}/compare-links").json() if x["id"] == link_id)
        r = requests.get(f"{API}/c/{token}/logo", timeout=30, allow_redirects=False)
        assert r.status_code in (200, 302, 307, 404)

    def test_revoked_shows_expired(self, session, photos):
        bid, aid = photos
        r = session.post(f"{API}/compare-links", json={
            "before_id": bid, "after_id": aid,
            "title": "TEST_iter31 ToRevoke", "origin_url": BASE_URL,
        }, timeout=30)
        lid = r.json()["id"]
        token = r.json()["token"]
        del_r = session.delete(f"{API}/compare-links/{lid}", timeout=30)
        assert del_r.status_code == 200
        pub = requests.get(f"{API}/c/{token}", timeout=30)
        assert pub.status_code == 200
        assert "no longer active" in pub.text.lower() or "expired" in pub.text.lower()


# ============== Project purpose + home_finance ==============
class TestProjectPurpose:
    @pytest.fixture(scope="class", autouse=True)
    def _restore(self, session):
        """Capture state and restore at the end to 'investment' with deposit 0 per instructions."""
        orig = session.get(f"{API}/project", timeout=30).json()
        yield
        session.put(f"{API}/project", json={
            "purpose": "investment",
            "deposit": 0,
            "mortgage_rate": orig.get("mortgage_rate", 4.5),
            "mortgage_term": orig.get("mortgage_term", 25),
            "mortgage_type": orig.get("mortgage_type", "repayment"),
            "remortgage_ltv": orig.get("remortgage_ltv", 85),
        }, timeout=30)

    def test_switch_to_personal_sets_target(self, session):
        r = session.put(f"{API}/project", json={
            "purpose": "personal",
            "deposit": 50000,
            "mortgage_rate": 5.0,
            "mortgage_term": 25,
            "mortgage_type": "repayment",
            "remortgage_ltv": 85,
        }, timeout=30)
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["purpose"] == "personal"
        assert p["target_type"] == "Home Renovation"
        assert "home_finance" in p
        hf = p["home_finance"]
        # Validate shape
        for k in ("loan", "ltv_now", "ltv_after", "monthly_payment", "total_interest",
                 "equity_now", "equity_after", "value_added", "net_value_added", "remortgage"):
            assert k in hf, f"missing {k}"
        for k in ("max_loan", "headroom", "borrow_for_refurb", "covers_refurb",
                 "shortfall", "new_loan", "new_payment", "payment_increase", "new_ltv", "equity_after"):
            assert k in hf["remortgage"], f"missing remortgage.{k}"

    def test_amortization_math_repayment(self, session):
        # Set known values and verify monthly payment matches amortization formula
        put = {
            "purpose": "personal",
            "deposit": 50000,
            "mortgage_rate": 6.0,
            "mortgage_term": 25,
            "mortgage_type": "repayment",
            "remortgage_ltv": 85,
        }
        r = session.put(f"{API}/project", json=put, timeout=30)
        assert r.status_code == 200
        p = r.json()
        loan = max(0.0, p["purchase_price"] - 50000)
        r_m = 0.06 / 12
        n = 25 * 12
        expected = loan * r_m / (1 - (1 + r_m) ** -n) if r_m else loan / n
        assert abs(p["home_finance"]["monthly_payment"] - round(expected, 2)) < 0.5, \
            f"got {p['home_finance']['monthly_payment']} expected ~{expected}"
        # ltv_now = loan/purchase * 100
        if p["purchase_price"]:
            assert abs(p["home_finance"]["ltv_now"] - round(loan / p["purchase_price"] * 100, 2)) < 0.1

    def test_interest_only_math(self, session):
        put = {
            "purpose": "personal",
            "deposit": 20000,
            "mortgage_rate": 5.4,
            "mortgage_term": 20,
            "mortgage_type": "interest_only",
            "remortgage_ltv": 80,
        }
        r = session.put(f"{API}/project", json=put, timeout=30)
        assert r.status_code == 200
        p = r.json()
        loan = max(0.0, p["purchase_price"] - 20000)
        expected = round(loan * 0.054 / 12, 2)
        assert abs(p["home_finance"]["monthly_payment"] - expected) < 0.5

    def test_switch_back_to_investment(self, session):
        r = session.put(f"{API}/project", json={"purpose": "investment"}, timeout=30)
        assert r.status_code == 200
        assert r.json()["purpose"] == "investment"
        assert r.json()["target_type"] == "BRRR Refurbishment"

    def test_term_validation(self, session):
        r = session.put(f"{API}/project", json={"mortgage_term": 41}, timeout=30)
        assert r.status_code == 422
        r = session.put(f"{API}/project", json={"mortgage_term": 0}, timeout=30)
        assert r.status_code == 422

    def test_remortgage_ltv_validation(self, session):
        r = session.put(f"{API}/project", json={"remortgage_ltv": 101}, timeout=30)
        assert r.status_code == 422
        r = session.put(f"{API}/project", json={"remortgage_ltv": -1}, timeout=30)
        assert r.status_code == 422

    def test_post_project_personal_sets_target(self, session, active_pid):
        r = session.post(f"{API}/projects", json={
            "name": "TEST_iter31 Personal Home",
            "address": "1 Home Lane",
            "purpose": "personal",
            "purchase_price": 250000,
            "estimated_valuation": 320000,
            "deposit": 50000,
            "mortgage_rate": 5.25,
            "mortgage_term": 30,
            "remortgage_ltv": 80,
        }, timeout=30)
        assert r.status_code == 200, r.text
        p = r.json()
        try:
            assert p["purpose"] == "personal"
            assert p["target_type"] == "Home Renovation"
            assert p["home_finance"]["loan"] == 200000.0  # 250k - 50k
        finally:
            # Reactivate original project and delete the test one
            session.post(f"{API}/projects/{active_pid}/activate", timeout=30)
            session.delete(f"{API}/projects/{p['id']}", timeout=30)
