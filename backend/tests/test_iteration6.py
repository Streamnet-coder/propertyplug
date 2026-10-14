"""Iteration 6 backend tests: Snag share links for trades + Referral prompt.

Covers:
- POST /api/snag-links {assignee, origin_url} -> {assignee,url}
- 400 if no snags assigned to that name (case-insensitive match)
- Same assignee returns same token (idempotent)
- GET /api/snag-links lists active project links
- GET /api/s/{token} HTML with #snag-count, form posting to /api/s/{token}/fix/{sid},
  #trial-cta with ref=snag&by=<owner>, invalid token -> 'no longer active'
- POST /api/s/{token}/fix/{sid} -> 303 redirect, flips status, records fixed_by/fix_note/fix_photo_path
- Snag not assigned to that trade -> 404
- GET /api/s/{token}/photo/{sid}?kind=fix returns the uploaded fix image
"""
import io
import os
import re
import uuid
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://dev-budget-tracker-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
DEMO_EMAIL = "demo@mybuilder.app"
DEMO_PASSWORD = "demo1234"


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def db():
    cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    yield cli[os.environ.get("DB_NAME", "test_database")]
    cli.close()


@pytest.fixture(scope="module")
def demo_token():
    r = requests.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}, timeout=30)
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def demo_user_id(demo_token):
    r = requests.get(f"{API}/auth/me", headers=auth(demo_token), timeout=15)
    return r.json()["id"]


@pytest.fixture(scope="module")
def trade_name():
    return f"TEST_Trade_{uuid.uuid4().hex[:6]}"


@pytest.fixture(scope="module")
def created_snag(demo_token, trade_name):
    """Create a TEST_ snag assigned to a unique trade name; clean up after."""
    r = requests.post(f"{API}/snags", headers=auth(demo_token), json={
        "room": "Kitchen",
        "description": "TEST_snag_defect_" + uuid.uuid4().hex[:6],
        "priority": "high",
        "assignee": trade_name,
    }, timeout=15)
    assert r.status_code == 200, r.text
    snag = r.json()
    yield snag
    # cleanup snag
    try:
        requests.delete(f"{API}/snags/{snag['id']}", headers=auth(demo_token), timeout=10)
    except Exception:
        pass


@pytest.fixture(scope="module")
def created_link(demo_token, created_snag, trade_name, db, demo_user_id):
    r = requests.post(f"{API}/snag-links", headers=auth(demo_token), json={
        "assignee": trade_name,
        "origin_url": BASE_URL,
    }, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    token = data["url"].rstrip("/").split("/")[-1]
    yield {"data": data, "token": token}
    # cleanup snag_links doc
    try:
        db.snag_links.delete_one({"token": token, "assignee": {"$regex": "^TEST_", "$options": "i"}})
    except Exception:
        pass


# ---------------- /api/snag-links CRUD ----------------
class TestSnagLinksApi:
    def test_create_snag_link(self, created_link, trade_name):
        d = created_link["data"]
        assert d["assignee"] == trade_name
        assert d["url"].startswith(BASE_URL)
        assert "/api/s/" in d["url"]
        assert len(created_link["token"]) >= 10

    def test_create_snag_link_idempotent_same_token(self, demo_token, trade_name, created_link):
        r = requests.post(f"{API}/snag-links", headers=auth(demo_token), json={
            "assignee": trade_name,
            "origin_url": BASE_URL,
        }, timeout=15)
        assert r.status_code == 200
        assert r.json()["url"] == created_link["data"]["url"]

    def test_create_snag_link_case_insensitive_match(self, demo_token, trade_name, created_link):
        # Different case should map to the SAME existing link
        r = requests.post(f"{API}/snag-links", headers=auth(demo_token), json={
            "assignee": trade_name.upper(),
            "origin_url": BASE_URL,
        }, timeout=15)
        assert r.status_code == 200
        assert r.json()["url"] == created_link["data"]["url"]

    def test_create_snag_link_no_snags_assigned_returns_400(self, demo_token):
        r = requests.post(f"{API}/snag-links", headers=auth(demo_token), json={
            "assignee": f"NonExistent_{uuid.uuid4().hex[:8]}",
            "origin_url": BASE_URL,
        }, timeout=15)
        assert r.status_code == 400
        assert "No snags" in r.json().get("detail", "")

    def test_create_snag_link_empty_name_returns_400(self, demo_token):
        r = requests.post(f"{API}/snag-links", headers=auth(demo_token), json={
            "assignee": "   ",
            "origin_url": BASE_URL,
        }, timeout=15)
        assert r.status_code == 400

    def test_list_snag_links_contains_created(self, demo_token, created_link, trade_name):
        r = requests.get(f"{API}/snag-links", headers=auth(demo_token), timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert any(x["assignee"] == trade_name and x["url"] == created_link["data"]["url"] for x in rows)

    def test_list_requires_auth(self):
        r = requests.get(f"{API}/snag-links", timeout=15)
        assert r.status_code in (401, 403)


# ---------------- Public /api/s/{token} HTML ----------------
class TestPublicSnagPage:
    def test_html_contains_count_and_form_and_trial_cta(self, created_link, created_snag, demo_user_id, trade_name):
        token = created_link["token"]
        r = requests.get(f"{BASE_URL}/api/s/{token}", timeout=15)
        assert r.status_code == 200
        html = r.text
        # Only one open snag -> "1 open · 0 fixed"
        assert "id='snag-count'" in html or 'id="snag-count"' in html
        m = re.search(r"id=['\"]snag-count['\"][^>]*>([^<]+)<", html)
        assert m, "snag-count element missing"
        assert "1 open" in m.group(1)
        # Form posts to /fix/{sid}
        assert f"/api/s/{token}/fix/{created_snag['id']}" in html
        assert "enctype='multipart/form-data'" in html or 'enctype="multipart/form-data"' in html
        assert "name='photo'" in html or 'name="photo"' in html
        assert "name='note'" in html or 'name="note"' in html
        # trial-cta with ref=snag&by=<owner>
        assert "id='trial-cta'" in html or 'id="trial-cta"' in html
        assert "ref=snag" in html
        assert f"by={demo_user_id}" in html
        # Title shows the trade name
        assert trade_name in html

    def test_html_filters_to_assignee_only(self, created_link, created_snag, demo_token, trade_name):
        # Create another snag assigned to someone else - must NOT appear
        other_desc = "TEST_otherTrade_" + uuid.uuid4().hex[:6]
        r = requests.post(f"{API}/snags", headers=auth(demo_token), json={
            "room": "Bathroom", "description": other_desc, "priority": "low",
            "assignee": "SomeoneElse_" + uuid.uuid4().hex[:6],
        }, timeout=15)
        other = r.json()
        try:
            html = requests.get(f"{BASE_URL}/api/s/{created_link['token']}", timeout=15).text
            assert created_snag["description"] in html
            assert other_desc not in html
        finally:
            requests.delete(f"{API}/snags/{other['id']}", headers=auth(demo_token), timeout=10)

    def test_invalid_token_returns_inactive_message(self):
        r = requests.get(f"{BASE_URL}/api/s/not-a-real-token-xyz", timeout=15)
        # Returns a page (200) with the "no longer active" message
        assert r.status_code == 200
        assert "no longer active" in r.text.lower()


# ---------------- Public fix POST ----------------
class TestPublicFixSnag:
    def test_fix_wrong_snag_returns_404(self, created_link, demo_token):
        # Create snag assigned to a DIFFERENT trade in the same project
        r = requests.post(f"{API}/snags", headers=auth(demo_token), json={
            "room": "Bathroom", "description": "TEST_wrongassign_" + uuid.uuid4().hex[:6],
            "priority": "low", "assignee": "Different_" + uuid.uuid4().hex[:6],
        }, timeout=15)
        bad = r.json()
        try:
            resp = requests.post(f"{BASE_URL}/api/s/{created_link['token']}/fix/{bad['id']}",
                                 data={"note": "nope"}, allow_redirects=False, timeout=15)
            assert resp.status_code == 404
        finally:
            requests.delete(f"{API}/snags/{bad['id']}", headers=auth(demo_token), timeout=10)

    def test_fix_with_photo_persists_and_redirects(self, created_link, created_snag, demo_token, db):
        token = created_link["token"]
        sid = created_snag["id"]
        img_bytes = (b"\x89PNG\r\n\x1a\n" + b"0" * 128)  # minimal PNG-ish bytes
        files = {"photo": ("fix.png", io.BytesIO(img_bytes), "image/png")}
        data = {"note": "TEST_resealed_silicone"}
        resp = requests.post(f"{BASE_URL}/api/s/{token}/fix/{sid}", files=files, data=data,
                             allow_redirects=False, timeout=30)
        assert resp.status_code == 303, resp.text
        assert resp.headers.get("location", "").endswith(f"/api/s/{token}?done=1")

        # Verify server-side state via owner API
        snags = requests.get(f"{API}/snags", headers=auth(demo_token), timeout=15).json()
        s = next(x for x in snags if x["id"] == sid)
        assert s["status"] == "fixed"
        assert s["fixed_by"] == created_link["data"]["assignee"]
        assert s["fix_note"] == "TEST_resealed_silicone"
        assert s.get("fix_photo_path")

        # Public page shows the done message
        html = requests.get(f"{BASE_URL}/api/s/{token}?done=1", timeout=15).text
        assert "id='snag-fixed-msg'" in html or 'id="snag-fixed-msg"' in html
        # snag-count now shows 0 open / 1 fixed
        m = re.search(r"id=['\"]snag-count['\"][^>]*>([^<]+)<", html)
        assert "0 open" in m.group(1) and "1 fixed" in m.group(1)

    def test_fetch_fix_photo(self, created_link, created_snag):
        token = created_link["token"]
        sid = created_snag["id"]
        r = requests.get(f"{BASE_URL}/api/s/{token}/photo/{sid}?kind=fix", timeout=15)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/")
        assert len(r.content) > 0
