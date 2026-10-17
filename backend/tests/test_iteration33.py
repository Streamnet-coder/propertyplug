"""Iteration 33 backend tests:
- Rent statements: per-tenancy + bulk + GET sent (routes/tenant_portal.py)
- Tenant portal: create/revoke, GET /api/t/{token}, receipt, repair submission
"""
import os
import re
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


def _make_tenancy(h, name_suffix, with_email=True, start_days_ago=800, end_days_ahead=165, rent=1000, log_months=None):
    today = date.today()
    body = {
        "tenant_name": f"TEST_iter33 {name_suffix}",
        "tenant_email": "delivered@resend.dev" if with_email else "",
        "rent": rent,
        "deposit": 500,
        "deposit_protected": True,
        "deposit_scheme": "DPS",
        "start_date": (today - timedelta(days=start_days_ago)).isoformat(),
        "end_date": (today + timedelta(days=end_days_ahead)).isoformat(),
        "rent_day": 1,
        "receipts_auto": False,
        "statements_auto": True,
    }
    r = requests.post(f"{API}/rentals/tenancies", headers=h, json=body)
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    # optionally log some rent payments
    for m in log_months or []:
        rp = requests.put(f"{API}/rentals/tenancies/{tid}/rent/{m}", headers=h,
                          json={"paid_amount": rent, "paid_on": f"{m}-05"})
        assert rp.status_code == 200
    return tid


@pytest.fixture
def tenancy_email(h):
    today = date.today()
    last_year = today.year - 1
    tid = _make_tenancy(h, "StmtEmail", log_months=[f"{last_year}-01", f"{last_year}-02", f"{last_year}-03"])
    yield tid
    requests.delete(f"{API}/rentals/tenancies/{tid}", headers=h)


@pytest.fixture
def tenancy_no_email(h):
    tid = _make_tenancy(h, "NoEmail", with_email=False)
    yield tid
    requests.delete(f"{API}/rentals/tenancies/{tid}", headers=h)


# -------------------- Statements --------------------

class TestStatements:
    def test_statement_no_email_400(self, h, tenancy_no_email):
        r = requests.post(f"{API}/rentals/tenancies/{tenancy_no_email}/statement",
                          headers=h, json={"year": date.today().year - 1})
        assert r.status_code == 400
        assert "email" in r.json().get("detail", "").lower()

    def test_statement_no_rent_due_400(self, h, tenancy_email):
        # year way before tenancy started -> no rent due that year
        r = requests.post(f"{API}/rentals/tenancies/{tenancy_email}/statement",
                          headers=h, json={"year": 2001})
        assert r.status_code == 400
        assert "no rent" in r.json().get("detail", "").lower()

    def test_statement_ok(self, h, tenancy_email):
        year = date.today().year - 1
        r = requests.post(f"{API}/rentals/tenancies/{tenancy_email}/statement",
                          headers=h, json={"year": year})
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        g = requests.get(f"{API}/rentals/statements", headers=h, params={"year": year})
        assert g.status_code == 200
        data = g.json()
        assert tenancy_email in data
        # ISO datetime string
        assert re.match(r"^\d{4}-\d{2}-\d{2}T", data[tenancy_email])

    def test_statement_all_counts(self, h, tenancy_email, tenancy_no_email):
        year = date.today().year - 1
        r = requests.post(f"{API}/rentals/statements", headers=h, json={"year": year})
        assert r.status_code == 200, r.text
        data = r.json()
        # schema
        for k in ("sent", "failed", "skipped", "no_email"):
            assert k in data
            assert isinstance(data[k], int)
        assert data["no_email"] >= 1  # tenancy_no_email counted
        # sent >= 1 OR failed/skipped >= 1 depending on Resend sandbox
        assert data["sent"] + data["failed"] + data["skipped"] >= 1


# -------------------- Portal: create / revoke / list excludes token --------------------

class TestPortal:
    def test_create_portal_idempotent(self, h, tenancy_email):
        r1 = requests.post(f"{API}/rentals/tenancies/{tenancy_email}/portal",
                           headers=h, json={"origin_url": BASE_URL})
        assert r1.status_code == 200, r1.text
        url1 = r1.json()["url"]
        assert "/api/t/" in url1

        r2 = requests.post(f"{API}/rentals/tenancies/{tenancy_email}/portal",
                           headers=h, json={"origin_url": BASE_URL})
        assert r2.status_code == 200
        assert r2.json()["url"] == url1  # same token

        # GET /api/rentals exposes portal_url but NOT portal_token
        g = requests.get(f"{API}/rentals", headers=h).json()
        t = next(x for x in g["tenancies"] if x["id"] == tenancy_email)
        assert t.get("portal_url") == url1
        assert "portal_token" not in t

    def test_revoke_portal(self, h, tenancy_email):
        requests.post(f"{API}/rentals/tenancies/{tenancy_email}/portal",
                      headers=h, json={"origin_url": BASE_URL})
        d = requests.delete(f"{API}/rentals/tenancies/{tenancy_email}/portal", headers=h)
        assert d.status_code == 200
        g = requests.get(f"{API}/rentals", headers=h).json()
        t = next(x for x in g["tenancies"] if x["id"] == tenancy_email)
        assert t.get("portal_url") is None


# -------------------- Public /api/t/{token} HTML page --------------------

@pytest.fixture
def portal_url(h, tenancy_email):
    r = requests.post(f"{API}/rentals/tenancies/{tenancy_email}/portal",
                      headers=h, json={"origin_url": BASE_URL})
    assert r.status_code == 200
    return r.json()["url"], tenancy_email


class TestPortalPage:
    def test_public_page_renders(self, portal_url):
        url, _tid = portal_url
        r = requests.get(url)
        assert r.status_code == 200
        html = r.text
        for anchor in ("tenancy-terms", "deposit-status", "rent-schedule",
                       "repair-form", "prev-year", "next-year"):
            assert anchor in html, f"missing anchor {anchor}"

    def test_year_nav(self, portal_url):
        url, _tid = portal_url
        year = date.today().year - 1
        r = requests.get(url, params={"year": year})
        assert r.status_code == 200
        # receipt-YYYY-MM anchor for a paid month (we logged 3 months last year)
        assert f"receipt-{year}-01" in r.text or f"receipt-{year}-02" in r.text

    def test_receipt_paid_month(self, portal_url):
        url, _tid = portal_url
        last_year = date.today().year - 1
        rec = requests.get(f"{url}/receipt/{last_year}-01")
        assert rec.status_code == 200
        assert "print-receipt" in rec.text

    def test_receipt_unpaid_404(self, portal_url):
        url, _tid = portal_url
        # month unlikely to have payment (far future same tenancy)
        future_m = f"{date.today().year + 10}-06"
        rec = requests.get(f"{url}/receipt/{future_m}")
        assert rec.status_code == 404

    def test_revoked_token_shows_gone(self, h, portal_url):
        url, tid = portal_url
        requests.delete(f"{API}/rentals/tenancies/{tid}/portal", headers=h)
        r = requests.get(url)
        assert r.status_code == 200
        assert "no longer active" in r.text


# -------------------- Repair submission --------------------

class TestRepair:
    def test_repair_creates_snag(self, h, portal_url):
        url, tid = portal_url
        r = requests.post(f"{url}/repair",
                          data={"room": "TEST_iter33 Kitchen", "description": "TEST_iter33 Leaky tap", "priority": "high"},
                          allow_redirects=False)
        assert r.status_code == 303
        assert "reported=1" in r.headers.get("location", "")

        # confirm 'repair-sent-msg' shown after redirect
        follow = requests.get(f"{url}?reported=1")
        assert follow.status_code == 200
        assert "repair-sent-msg" in follow.text

        # snag visible via owner's GET /api/snags with reported_by
        snags = requests.get(f"{API}/snags", headers=h).json()
        found = next((s for s in snags if s.get("description", "").startswith("TEST_iter33 Leaky tap")), None)
        assert found is not None, "snag not created"
        assert found["reported_by"].startswith("Tenant: TEST_iter33")
        assert found["room"] == "TEST_iter33 Kitchen"
        assert found["priority"] == "high"
        # cleanup snag
        sid = found.get("id") or found.get("_id")
        if sid:
            requests.delete(f"{API}/snags/{sid}", headers=h)

    def test_repair_rate_limit(self, h, portal_url):
        url, tid = portal_url
        created_ids = []
        try:
            # create 10 snags today for this tenancy via API (as owner) to simulate limit
            # faster path: insert via POST /api/snags? use repair endpoint 10 times
            for i in range(10):
                rr = requests.post(f"{url}/repair",
                                   data={"room": f"TEST_iter33 R{i}", "description": f"TEST_iter33 rate {i}", "priority": "low"},
                                   allow_redirects=False)
                # should succeed up to 10
                assert rr.status_code in (303, 429)
            # 11th should 429
            r = requests.post(f"{url}/repair",
                              data={"room": "TEST_iter33 R11", "description": "TEST_iter33 rate 11", "priority": "low"},
                              allow_redirects=False)
            assert r.status_code == 429
        finally:
            # clean up
            snags = requests.get(f"{API}/snags", headers=h).json()
            for s in snags:
                if s.get("description", "").startswith("TEST_iter33 rate"):
                    sid = s.get("id") or s.get("_id")
                    if sid:
                        requests.delete(f"{API}/snags/{sid}", headers=h)
