"""Iteration 34 backend tests:
- Repair-fixed notification to tenant (owner PUT /api/snags/{id} status=fixed AND trade public link)
- Tenant document sharing via PUT /api/rentals/tenancies/{tid}/documents + portal rendering + /api/t/{token}/doc/{did}
- Portfolio rent roll: GET /api/portfolio/rent-roll?year= aggregation
"""
import io
import os
import re
from datetime import date, timedelta

import pytest
import requests
from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
HTTPS_ORIGIN = "https://example.com"
TENANT_EMAIL = "delivered@resend.dev"

_cli = MongoClient(os.environ["MONGO_URL"])
_db = _cli[os.environ["DB_NAME"]]


def _snag_db(sid):
    return _db.snags.find_one({"_id": ObjectId(sid)}) or {}


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login", json={"email": "demo@mybuilder.app", "password": "demo1234"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def active_project_id(h):
    """Ensure demo project is active and return its id."""
    r = requests.get(f"{API}/projects", headers=h)
    assert r.status_code == 200, r.text
    projs = r.json()
    # pick first non-land project (demo seed Nottingham)
    p = next((p for p in projs if p.get("property_type") != "land"), projs[0])
    pid = p["id"]
    requests.post(f"{API}/projects/{pid}/activate", headers=h)
    return pid


@pytest.fixture(scope="module")
def tenancy(h, active_project_id):
    today = date.today()
    body = {
        "tenant_name": "TEST_iter34 Alice",
        "tenant_email": TENANT_EMAIL,
        "rent": 1200,
        "deposit": 1200,
        "deposit_protected": True,
        "deposit_scheme": "DPS",
        "start_date": (today - timedelta(days=120)).isoformat(),
        "end_date": (today + timedelta(days=200)).isoformat(),
        "rent_day": 1,
        "notes": "TEST_iter34",
    }
    r = requests.post(f"{API}/rentals/tenancies", headers=h, json=body)
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    # Create portal (HTTPS origin required)
    pr = requests.post(f"{API}/rentals/tenancies/{tid}/portal", headers=h, json={"origin_url": HTTPS_ORIGIN})
    assert pr.status_code == 200, pr.text
    url = pr.json()["url"]
    m = re.search(r"/api/t/([^/?#]+)", url)
    assert m, url
    token = m.group(1)
    yield {"id": tid, "token": token, "project_id": active_project_id}
    # cleanup
    requests.delete(f"{API}/rentals/tenancies/{tid}", headers=h)


# -----------------------------------------------------------------------------
# 1. Repair updates / tenant notified
# -----------------------------------------------------------------------------
class TestRepairFixed:
    def test_owner_marks_snag_fixed_notifies_tenant(self, h, tenancy):
        # Tenant reports repair via portal
        rep = requests.post(f"{API}/t/{tenancy['token']}/repair",
                            data={"room": "TEST_iter34 Bathroom", "description": "TEST_iter34 Dripping tap", "priority": "high"},
                            allow_redirects=False)
        assert rep.status_code == 303, rep.text

        # Find snag owner-side
        snags = requests.get(f"{API}/snags", headers=h).json()
        snag = next((s for s in snags if s.get("description") == "TEST_iter34 Dripping tap"), None)
        assert snag is not None, "snag not created from tenant report"
        sid = snag.get("id") or snag.get("_id")
        # tenancy_id is persisted in Mongo even if not in Snag.out()
        assert _snag_db(sid).get("tenancy_id") == tenancy["id"]

        # Owner marks fixed via PUT /api/snags/{id} status fixed
        upd = requests.put(f"{API}/snags/{sid}", headers=h, json={"status": "fixed"})
        assert upd.status_code == 200, upd.text
        out = upd.json()
        assert out["status"] == "fixed"
        assert out.get("fixed_at")

        # DB side: snag has tenant_notified_at
        assert _snag_db(sid).get("tenant_notified_at"), "tenant_notified_at missing on snag doc"

        # Messages includes repair_fixed (filter by tenant email)
        msgs = requests.get(f"{API}/messages", headers=h, params={"email": TENANT_EMAIL}).json()
        kinds = [m.get("kind") for m in msgs]
        assert "repair_fixed" in kinds, f"repair_fixed kind missing; got {kinds[:10]}"

        # Portal HTML shows repair-list with FIXED
        portal_html = requests.get(f"{API}/t/{tenancy['token']}").text
        assert 'id="repair-list"' in portal_html or "id='repair-list'" in portal_html, "repair-list missing"
        assert "FIXED" in portal_html, "FIXED tag missing in portal"

        # Cleanup snag
        requests.delete(f"{API}/snags/{sid}", headers=h)

    def test_non_tenant_snag_marked_fixed_does_not_error(self, h):
        # Create a snag with no tenancy_id (plain snag)
        r = requests.post(f"{API}/snags", headers=h, json={
            "room": "TEST_iter34 Garden", "description": "TEST_iter34 Fence lean", "priority": "low", "assignee": "TEST_iter34_Trade"
        })
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        upd = requests.put(f"{API}/snags/{sid}", headers=h, json={"status": "fixed"})
        assert upd.status_code == 200, upd.text
        assert upd.json()["status"] == "fixed"
        # cleanup
        requests.delete(f"{API}/snags/{sid}", headers=h)

    def test_trade_fix_via_public_snag_link_notifies_tenant(self, h, tenancy):
        # Create a tenant-sourced snag with assignee
        rep = requests.post(f"{API}/t/{tenancy['token']}/repair",
                            data={"room": "TEST_iter34 Boiler", "description": "TEST_iter34 No heat", "priority": "high"},
                            allow_redirects=False)
        assert rep.status_code == 303

        snags = requests.get(f"{API}/snags", headers=h).json()
        snag = next((s for s in snags if s.get("description") == "TEST_iter34 No heat"), None)
        assert snag is not None
        sid = snag["id"]
        # Assign a trade name
        upd = requests.put(f"{API}/snags/{sid}", headers=h, json={"assignee": "TEST_iter34_Boiler_Co"})
        assert upd.status_code == 200

        # Create snag link
        link = requests.post(f"{API}/snag-links", headers=h,
                             json={"assignee": "TEST_iter34_Boiler_Co", "origin_url": HTTPS_ORIGIN}).json()
        m = re.search(r"/api/s/([^/?#]+)", link["url"])
        token = m.group(1)

        # Trade marks fixed via public link
        fx = requests.post(f"{API}/s/{token}/fix/{sid}", data={"note": "TEST_iter34 Replaced valve"},
                           allow_redirects=False)
        assert fx.status_code == 303, fx.text

        # Verify snag got tenant_notified_at + repair_fixed message
        assert _snag_db(sid).get("tenant_notified_at"), "tenant_notified_at missing after trade fix"
        msgs = requests.get(f"{API}/messages", headers=h, params={"email": TENANT_EMAIL}).json()
        kinds = [m.get("kind") for m in msgs]
        assert kinds.count("repair_fixed") >= 1

        # Cleanup
        requests.delete(f"{API}/snags/{sid}", headers=h)


# -----------------------------------------------------------------------------
# 2. Tenant document sharing
# -----------------------------------------------------------------------------
MINI_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 100 100]>>endobj\n"
            b"xref\n0 4\n0000000000 65535 f \n0000000010 00000 n \n0000000053 00000 n \n0000000100 00000 n \n"
            b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n160\n%%EOF\n")


@pytest.fixture(scope="module")
def test_doc(token, active_project_id):
    files = {"file": ("test_iter34.pdf", io.BytesIO(MINI_PDF), "application/pdf")}
    data = {"title": "TEST_iter34 Gas Safety",
            "doc_type": "Gas certificate",
            "expires_on": (date.today() + timedelta(days=30)).isoformat()}
    r = requests.post(f"{API}/documents",
                      headers={"Authorization": f"Bearer {token}"}, files=files, data=data)
    assert r.status_code in (200, 201), r.text
    body = r.json()
    did = body.get("id") or body.get("_id")
    assert did, body
    yield did
    requests.delete(f"{API}/documents/{did}",
                    headers={"Authorization": f"Bearer {token}"})


class TestTenantDocs:
    def test_share_docs_ok(self, h, tenancy, test_doc):
        r = requests.put(f"{API}/rentals/tenancies/{tenancy['id']}/documents",
                         headers=h, json={"doc_ids": [test_doc]})
        assert r.status_code == 200, r.text
        assert r.json()["shared_doc_ids"] == [test_doc]

    def test_share_docs_unknown_404(self, h, tenancy):
        r = requests.put(f"{API}/rentals/tenancies/{tenancy['id']}/documents",
                         headers=h, json={"doc_ids": ["000000000000000000000000"]})
        assert r.status_code == 404, r.text

    def test_portal_shows_tenant_docs(self, tenancy, test_doc):
        html = requests.get(f"{API}/t/{tenancy['token']}").text
        assert 'id="tenant-docs"' in html or "id='tenant-docs'" in html, "tenant-docs section missing"
        assert f"tdoc-{test_doc}" in html, "doc testID link missing"
        assert "VALID UNTIL" in html, "expiry tag missing"

    def test_tenant_doc_download_200(self, tenancy, test_doc):
        r = requests.get(f"{API}/t/{tenancy['token']}/doc/{test_doc}")
        assert r.status_code == 200, r.text
        assert r.content.startswith(b"%PDF")

    def test_tenant_doc_download_not_shared_404(self, h, tenancy, test_doc, token, active_project_id):
        # Create a second doc, do not share
        files = {"file": ("extra.pdf", io.BytesIO(MINI_PDF), "application/pdf")}
        data = {"title": "TEST_iter34 Extra", "doc_type": "Other"}
        r = requests.post(f"{API}/documents", headers={"Authorization": f"Bearer {token}"},
                          files=files, data=data)
        assert r.status_code in (200, 201)
        extra = r.json().get("id") or r.json().get("_id")
        try:
            gr = requests.get(f"{API}/t/{tenancy['token']}/doc/{extra}")
            assert gr.status_code == 404
        finally:
            requests.delete(f"{API}/documents/{extra}",
                            headers={"Authorization": f"Bearer {token}"})

    def test_rentals_includes_shared_doc_ids(self, h, tenancy, test_doc):
        r = requests.get(f"{API}/rentals", headers=h).json()
        t = next((x for x in r["tenancies"] if x["id"] == tenancy["id"]), None)
        assert t is not None
        assert test_doc in (t.get("shared_doc_ids") or [])


# -----------------------------------------------------------------------------
# 3. Portfolio rent roll
# -----------------------------------------------------------------------------
class TestRentRoll:
    def test_shape_and_filtering(self, h, tenancy, active_project_id):
        r = requests.get(f"{API}/portfolio/rent-roll", headers=h)
        assert r.status_code == 200, r.text
        d = r.json()
        for key in ("year", "home_currency", "rate_date", "properties", "totals", "counts"):
            assert key in d, f"missing {key}"
        for key in ("rent_due", "received", "arrears", "expenses", "net", "active_rent"):
            assert key in d["totals"], f"totals.{key} missing"
        for key in ("properties", "tenancies", "active", "in_arrears"):
            assert key in d["counts"], f"counts.{key} missing"
        # must include our active project since it has a tenancy
        row = next((p for p in d["properties"] if p["id"] == active_project_id), None)
        assert row is not None, f"active project missing in rent roll: {[p['id'] for p in d['properties']]}"
        for key in ("id", "name", "currency", "received", "arrears", "net", "expenses", "rent_due", "active_rent", "home", "tenants", "late_months"):
            assert key in row, f"property row missing {key}"
        for key in ("rent_due", "received", "arrears", "expenses", "net", "active_rent"):
            assert key in row["home"], f"home.{key} missing"
        assert isinstance(row["tenants"], list)

    def test_land_excluded(self, h, token):
        # Create a land project and verify not in rent roll
        pr = requests.post(f"{API}/projects", headers=h,
                           json={"name": "TEST_iter34 Land", "property_type": "land", "address": "nowhere", "currency": "GBP"})
        assert pr.status_code == 200, pr.text
        land_pid = pr.json()["id"]
        try:
            rr = requests.get(f"{API}/portfolio/rent-roll", headers=h).json()
            assert all(p["id"] != land_pid for p in rr["properties"]), "land must be excluded"
        finally:
            requests.delete(f"{API}/projects/{land_pid}", headers=h)

    def test_year_switch(self, h):
        y = date.today().year
        r1 = requests.get(f"{API}/portfolio/rent-roll?year={y}", headers=h).json()
        r2 = requests.get(f"{API}/portfolio/rent-roll?year={y - 5}", headers=h).json()
        assert r1["year"] == y
        assert r2["year"] == y - 5
