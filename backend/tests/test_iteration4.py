"""Iteration 4 backend tests: Branding, public brand block + trial CTA, /api/join signup, media milestone_id."""
import os
import io
import re
import uuid
import pytest
import requests
from tests.cleanup import delete_test_user

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://dev-budget-tracker-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
DEMO_EMAIL = "demo@mybuilder.app"
DEMO_PASSWORD = "demo1234"
PNG_1x1 = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4890000000A49444154789C6300010000000500010D0A2DB40000000049454E44AE426082"
)


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def demo_token():
    r = requests.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}, timeout=30)
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def demo_user_id(demo_token):
    r = requests.get(f"{API}/auth/me", headers=auth(demo_token), timeout=15)
    return r.json()["id"]


# ---------- Branding GET / PUT + logo validation ----------
class TestBranding:
    def test_get_branding_returns_object(self, demo_token):
        r = requests.get(f"{API}/branding", headers=auth(demo_token), timeout=15)
        assert r.status_code == 200
        b = r.json()
        for k in ("company_name", "contact_name", "phone", "email", "website", "tagline", "logo_path"):
            assert k in b

    def test_put_branding_rejects_bogus_logo_path(self, demo_token):
        r = requests.put(f"{API}/branding", headers=auth(demo_token), timeout=15,
                         json={"company_name": "Mapperley Property Co", "contact_name": "Mapperley", "phone": "",
                               "email": "", "website": "", "tagline": "", "logo_path": "not-a-real/path.jpg"})
        assert r.status_code == 400, f"Expected 400, got {r.status_code} {r.text}"

    def test_put_branding_accepts_uploaded_logo_and_round_trip(self, demo_token):
        # Save original branding first
        original = requests.get(f"{API}/branding", headers=auth(demo_token), timeout=15).json()
        # Upload a logo via /api/upload
        files = {"file": ("logo.png", io.BytesIO(PNG_1x1), "image/png")}
        up = requests.post(f"{API}/upload", files=files, headers=auth(demo_token), timeout=60)
        if up.status_code == 402:
            pytest.skip("Storage credits exhausted")
        assert up.status_code == 200
        path = up.json()["path"]
        try:
            body = {"company_name": "TEST BrandCo", "contact_name": "T Builder", "phone": "+447000000001",
                    "email": "owner@test.co", "website": "https://test.co", "tagline": "Builds things",
                    "logo_path": path}
            r = requests.put(f"{API}/branding", headers=auth(demo_token), json=body, timeout=15)
            assert r.status_code == 200
            out = r.json()
            assert out["company_name"] == "TEST BrandCo"
            assert out["logo_path"] == path
            # Verify round-trip
            r2 = requests.get(f"{API}/branding", headers=auth(demo_token), timeout=15).json()
            assert r2["company_name"] == "TEST BrandCo"
            assert r2["logo_path"] == path
        finally:
            # Restore demo branding (keep Mapperley Property Co, no logo per agent note)
            requests.put(f"{API}/branding", headers=auth(demo_token), json=original, timeout=15)


# ---------- Public brand block + trial CTA on /api/share and /api/q ----------
class TestPublicBranding:
    def _create_share(self, demo_token):
        r = requests.post(f"{API}/project/share", headers=auth(demo_token), timeout=15,
                          json={"origin_url": BASE_URL})
        assert r.status_code == 200
        url = r.json()["url"]
        return url, url.rsplit("/", 1)[-1]

    def test_share_has_brand_block_and_trial_cta(self, demo_token):
        # Ensure branding has company name
        original = requests.get(f"{API}/branding", headers=auth(demo_token), timeout=15).json()
        bb = dict(original)
        bb["company_name"] = bb.get("company_name") or "Mapperley Property Co"
        requests.put(f"{API}/branding", headers=auth(demo_token), json=bb, timeout=15)
        url, token = self._create_share(demo_token)
        try:
            html = requests.get(url, timeout=30).text
            assert 'id="brand-block"' in html or "id='brand-block'" in html
            assert bb["company_name"] in html
            assert 'id="trial-cta"' in html or "id='trial-cta'" in html
            assert "/api/join?ref=share" in html
            assert 'id="start-trial-link"' in html or "id='start-trial-link'" in html
        finally:
            requests.delete(f"{API}/project/share", headers=auth(demo_token), timeout=15)
            requests.put(f"{API}/branding", headers=auth(demo_token), json=original, timeout=15)

    def test_share_logo_served_when_logo_set(self, demo_token):
        original = requests.get(f"{API}/branding", headers=auth(demo_token), timeout=15).json()
        files = {"file": ("logo.png", io.BytesIO(PNG_1x1), "image/png")}
        up = requests.post(f"{API}/upload", files=files, headers=auth(demo_token), timeout=60)
        if up.status_code == 402:
            pytest.skip("Storage credits exhausted")
        path = up.json()["path"]
        body = {**original, "company_name": original.get("company_name") or "Mapperley Property Co", "logo_path": path}
        requests.put(f"{API}/branding", headers=auth(demo_token), json=body, timeout=15)
        url, token = self._create_share(demo_token)
        try:
            html = requests.get(url, timeout=30).text
            assert f"/api/share/{token}/logo" in html
            r = requests.get(f"{API}/share/{token}/logo", timeout=30)
            assert r.status_code == 200
            assert r.headers.get("Content-Type", "").startswith("image/")
        finally:
            requests.delete(f"{API}/project/share", headers=auth(demo_token), timeout=15)
            requests.put(f"{API}/branding", headers=auth(demo_token), json=original, timeout=15)

    def test_quote_page_has_brand_block_and_trial_cta_plus_logo(self, demo_token):
        original = requests.get(f"{API}/branding", headers=auth(demo_token), timeout=15).json()
        files = {"file": ("logo.png", io.BytesIO(PNG_1x1), "image/png")}
        up = requests.post(f"{API}/upload", files=files, headers=auth(demo_token), timeout=60)
        if up.status_code == 402:
            pytest.skip("Storage credits exhausted")
        logo_path = up.json()["path"]
        body = {**original, "company_name": original.get("company_name") or "Mapperley Property Co", "logo_path": logo_path}
        requests.put(f"{API}/branding", headers=auth(demo_token), json=body, timeout=15)
        trades = requests.get(f"{API}/contacts?kind=trade", headers=auth(demo_token), timeout=15).json()
        assert trades
        qc = requests.post(f"{API}/quotes", headers=auth(demo_token), timeout=15,
                           json={"title": "TEST Brand Quote", "description": "Brand test",
                                 "contact_ids": [trades[0]["id"]], "origin_url": BASE_URL, "trade": "plumber"})
        assert qc.status_code == 200
        q = qc.json()
        qid = q["id"]
        token = q["quotes"][0]["link"].rsplit("/", 1)[-1]
        try:
            html = requests.get(f"{BASE_URL}/api/q/{token}", timeout=15).text
            assert 'id="brand-block"' in html or "id='brand-block'" in html
            assert "Mapperley Property Co" in html or body["company_name"] in html
            assert f"/api/q/{token}/logo" in html
            assert "/api/join?ref=quote" in html
            # logo endpoint
            r = requests.get(f"{BASE_URL}/api/q/{token}/logo", timeout=30)
            assert r.status_code == 200
            assert r.headers.get("Content-Type", "").startswith("image/")
            # After public POST (submit), the response page should also have CTA with ref=quote
            resp = requests.post(f"{BASE_URL}/api/q/{token}", data={"amount": "1234", "days": "3", "notes": "n"}, timeout=15)
            assert resp.status_code == 200
            assert "/api/join?ref=quote" in resp.text
            assert 'id="trial-cta"' in resp.text or "id='trial-cta'" in resp.text
        finally:
            requests.delete(f"{API}/quotes/{qid}", headers=auth(demo_token), timeout=15)
            requests.put(f"{API}/branding", headers=auth(demo_token), json=original, timeout=15)


# ---------- Public trial signup via /api/join ----------
class TestJoin:
    def test_get_join_form(self):
        r = requests.get(f"{BASE_URL}/api/join?ref=share", timeout=15)
        assert r.status_code == 200
        assert 'id="join-form"' in r.text or "id='join-form'" in r.text
        assert 'value="share"' in r.text or "value='share'" in r.text

    def test_post_join_bad_email_shows_error(self):
        r = requests.post(f"{BASE_URL}/api/join", timeout=15,
                          data={"name": "T", "email": "notanemail", "password": "pass1234", "ref": "share"})
        assert r.status_code == 200
        assert 'id="join-error"' in r.text or "id='join-error'" in r.text

    def test_post_join_short_password_shows_error(self):
        email = f"TEST_short_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{BASE_URL}/api/join", timeout=15,
                          data={"name": "T", "email": email, "password": "123", "ref": "share"})
        assert r.status_code == 200
        assert 'id="join-error"' in r.text or "id='join-error'" in r.text

    def test_post_join_creates_user_success_and_login(self):
        email = f"TEST_join_{uuid.uuid4().hex[:8]}@example.com"
        password = "pass1234"
        r = requests.post(f"{BASE_URL}/api/join", timeout=60,
                          data={"name": "TEST Join User", "email": email, "password": password, "ref": "share"})
        assert r.status_code == 200
        assert 'id="join-success"' in r.text or "id='join-success'" in r.text
        assert email.lower() in r.text
        # Login should now work
        lr = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
        assert lr.status_code == 200
        tok = lr.json()["access_token"]
        # Confirm signup_source + seeded data
        me = requests.get(f"{API}/auth/me", headers=auth(tok), timeout=15).json()
        proj = requests.get(f"{API}/project", headers=auth(tok), timeout=15).json()
        assert proj["line_item_count"] >= 6
        # Cleanup: delete user doc + related data
        self._cleanup_user(me["id"])
        # Verify login no longer works
        lr2 = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
        assert lr2.status_code == 401

    def test_post_join_duplicate_email_error(self):
        r = requests.post(f"{BASE_URL}/api/join", timeout=15,
                          data={"name": "T", "email": DEMO_EMAIL, "password": "pass1234", "ref": "share"})
        assert r.status_code == 200
        assert 'id="join-error"' in r.text or "id='join-error'" in r.text
        assert "already registered" in r.text.lower()

    @staticmethod
    def _cleanup_user(uid):
        delete_test_user(uid)


# ---------- Media with milestone_id ----------
class TestMediaMilestone:
    def test_media_milestone_id_persists_and_renders_in_share(self, demo_token):
        # Grab the in_progress milestone
        ms = requests.get(f"{API}/milestones", headers=auth(demo_token), timeout=15).json()
        target = next((m for m in ms if m["status"] == "in_progress"), ms[0])
        mid = target["id"]
        # Create media with milestone_id
        r = requests.post(f"{API}/media", headers=auth(demo_token), timeout=15,
                          json={"title": "TEST Photo: " + target["name"], "phase": "before",
                                "url": "https://placehold.co/400x300/0f766e/ffffff.png?text=TestMS",
                                "milestone_id": mid, "date": "2026-07-01"})
        assert r.status_code == 200
        media_id = r.json()["id"]
        try:
            lst = requests.get(f"{API}/media", headers=auth(demo_token), timeout=15).json()
            found = next((x for x in lst if x["id"] == media_id), None)
            assert found and found.get("milestone_id") == mid
            # Build share and check that msph block includes photo under this milestone
            sr = requests.post(f"{API}/project/share", headers=auth(demo_token),
                               json={"origin_url": BASE_URL}, timeout=15).json()
            url = sr["url"]
            token = url.rsplit("/", 1)[-1]
            try:
                html = requests.get(url, timeout=30).text
                assert "msph" in html
                assert f"/api/share/{token}/photo/{media_id}" in html
            finally:
                requests.delete(f"{API}/project/share", headers=auth(demo_token), timeout=15)
        finally:
            requests.delete(f"{API}/media/{media_id}", headers=auth(demo_token), timeout=15)


# ---------- Regression: share, quotes, PDF button (route still OK) ----------
class TestRegression:
    def test_share_create_revoke(self, demo_token):
        r = requests.post(f"{API}/project/share", headers=auth(demo_token),
                          json={"origin_url": BASE_URL}, timeout=15)
        assert r.status_code == 200
        d = requests.delete(f"{API}/project/share", headers=auth(demo_token), timeout=15)
        assert d.status_code == 200
        assert d.json()["url"] is None

    def test_quotes_list_endpoint(self, demo_token):
        r = requests.get(f"{API}/quotes", headers=auth(demo_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
