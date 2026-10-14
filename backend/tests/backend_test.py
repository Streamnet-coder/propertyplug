"""Backend API tests for My Builder App."""
import os
import io
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://dev-budget-tracker-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

DEMO_EMAIL = "demo@mybuilder.app"
DEMO_PASSWORD = "demo1234"


# ---------- fixtures ----------
@pytest.fixture(scope="session")
def demo_token():
    r = requests.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"Demo login failed: {r.status_code} {r.text}"
    tok = r.json()["access_token"]
    # Ensure plan is basic at start of session
    requests.post(f"{API}/auth/plan", json={"plan": "basic"}, headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    return tok


@pytest.fixture(scope="session")
def new_user():
    """Register a brand new user to validate seeding."""
    email = f"TEST_{uuid.uuid4().hex[:10]}@example.com"
    r = requests.post(f"{API}/auth/register", json={"name": "TEST User", "email": email, "password": "pass1234"}, timeout=60)
    assert r.status_code == 200, f"Register failed: {r.status_code} {r.text}"
    data = r.json()
    return {"token": data["access_token"], "user": data["user"], "email": email}


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------- Health ----------
def test_root():
    r = requests.get(f"{API}/", timeout=15)
    assert r.status_code == 200
    assert "message" in r.json()


# ---------- Auth ----------
class TestAuth:
    def test_login_demo(self, demo_token):
        assert isinstance(demo_token, str) and len(demo_token) > 20

    def test_me(self, demo_token):
        r = requests.get(f"{API}/auth/me", headers=auth(demo_token), timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["email"] == DEMO_EMAIL
        assert body["plan"] in ("basic", "pro")
        assert "trial_ends" in body

    def test_me_unauth(self):
        r = requests.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 401

    def test_login_wrong_password(self):
        r = requests.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": "wrong"}, timeout=15)
        assert r.status_code == 401

    def test_register_duplicate(self):
        r = requests.post(f"{API}/auth/register", json={"name": "x", "email": DEMO_EMAIL, "password": "pass1234"}, timeout=15)
        assert r.status_code == 409

    def test_register_short_password(self):
        r = requests.post(f"{API}/auth/register", json={"name": "x", "email": f"TEST_{uuid.uuid4().hex[:6]}@e.com", "password": "123"}, timeout=15)
        assert r.status_code == 400

    def test_new_user_seeded(self, new_user):
        tok = new_user["token"]
        proj = requests.get(f"{API}/project", headers=auth(tok), timeout=15).json()
        assert proj["line_item_count"] >= 6
        assert proj["receipt_count"] >= 3
        assert proj["total_budget"] == pytest.approx(48500.0)


# ---------- Project ----------
class TestProject:
    def test_get_project(self, demo_token):
        r = requests.get(f"{API}/project", headers=auth(demo_token), timeout=15)
        assert r.status_code == 200
        p = r.json()
        for k in ("name", "address", "spent", "total_budget", "total_spent", "line_item_count"):
            assert k in p, f"missing {k}"
        assert p["total_budget"] > 0
        # computed total_spent == sum(spent)
        assert round(sum(p["spent"].values()), 2) == pytest.approx(p["total_spent"], rel=1e-3)

    def test_update_project(self, demo_token):
        new_rent = 1399.0
        r = requests.put(f"{API}/project", headers=auth(demo_token), json={"monthly_rent": new_rent}, timeout=15)
        assert r.status_code == 200
        # Verify persisted
        r2 = requests.get(f"{API}/project", headers=auth(demo_token), timeout=15)
        assert r2.json()["monthly_rent"] == new_rent


# ---------- Line items ----------
class TestLineItems:
    def test_crud(self, demo_token):
        payload = {"category": "Hard Cost", "name": "TEST Insulation", "budgeted": 500, "actual": 450, "supplier": "Wickes", "status": "Planned"}
        r = requests.post(f"{API}/line-items", headers=auth(demo_token), json=payload, timeout=15)
        assert r.status_code == 200
        item = r.json()
        iid = item["id"]
        assert item["name"] == "TEST Insulation"

        # list
        lst = requests.get(f"{API}/line-items", headers=auth(demo_token), timeout=15).json()
        assert any(x["id"] == iid for x in lst)

        # update
        payload["actual"] = 475
        up = requests.put(f"{API}/line-items/{iid}", headers=auth(demo_token), json=payload, timeout=15)
        assert up.status_code == 200
        assert up.json()["actual"] == 475

        # delete
        d = requests.delete(f"{API}/line-items/{iid}", headers=auth(demo_token), timeout=15)
        assert d.status_code == 200

        lst2 = requests.get(f"{API}/line-items", headers=auth(demo_token), timeout=15).json()
        assert not any(x["id"] == iid for x in lst2)


# ---------- Contacts & Plan ----------
class TestContactsAndPlan:
    def test_basic_trade_ok(self, demo_token):
        # Ensure basic
        requests.post(f"{API}/auth/plan", json={"plan": "basic"}, headers=auth(demo_token), timeout=15)
        r = requests.get(f"{API}/contacts?kind=trade", headers=auth(demo_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_basic_subcontractor_403(self, demo_token):
        requests.post(f"{API}/auth/plan", json={"plan": "basic"}, headers=auth(demo_token), timeout=15)
        r = requests.get(f"{API}/contacts?kind=subcontractor", headers=auth(demo_token), timeout=15)
        assert r.status_code == 403

    def test_basic_stakeholder_403(self, demo_token):
        requests.post(f"{API}/auth/plan", json={"plan": "basic"}, headers=auth(demo_token), timeout=15)
        r = requests.get(f"{API}/contacts?kind=stakeholder", headers=auth(demo_token), timeout=15)
        assert r.status_code == 403

    def test_basic_comparables_403(self, demo_token):
        requests.post(f"{API}/auth/plan", json={"plan": "basic"}, headers=auth(demo_token), timeout=15)
        r = requests.get(f"{API}/project/comparables", headers=auth(demo_token), timeout=15)
        assert r.status_code == 403

    def test_pro_unlocks(self, demo_token):
        requests.post(f"{API}/auth/plan", json={"plan": "pro"}, headers=auth(demo_token), timeout=15)
        r1 = requests.get(f"{API}/contacts?kind=subcontractor", headers=auth(demo_token), timeout=15)
        r2 = requests.get(f"{API}/contacts?kind=stakeholder", headers=auth(demo_token), timeout=15)
        r3 = requests.get(f"{API}/project/comparables", headers=auth(demo_token), timeout=15)
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r3.status_code == 200
        assert len(r3.json()) >= 3
        # reset to basic
        requests.post(f"{API}/auth/plan", json={"plan": "basic"}, headers=auth(demo_token), timeout=15)

    def test_create_delete_contact(self, demo_token):
        payload = {"kind": "trade", "name": "TEST Trade", "role": "Painter", "phone": "+447000000000", "email": "t@t.co"}
        r = requests.post(f"{API}/contacts", json=payload, headers=auth(demo_token), timeout=15)
        assert r.status_code == 200
        cid = r.json()["id"]
        d = requests.delete(f"{API}/contacts/{cid}", headers=auth(demo_token), timeout=15)
        assert d.status_code == 200

    def test_basic_create_subcontractor_403(self, demo_token):
        requests.post(f"{API}/auth/plan", json={"plan": "basic"}, headers=auth(demo_token), timeout=15)
        r = requests.post(f"{API}/contacts", json={"kind": "subcontractor", "name": "X"}, headers=auth(demo_token), timeout=15)
        assert r.status_code == 403


# ---------- Receipts ----------
class TestReceipts:
    def test_crud(self, demo_token):
        r = requests.post(f"{API}/receipts", json={"title": "TEST Receipt", "amount": 12.5, "date": "2026-01-01", "supplier": "B&Q"},
                          headers=auth(demo_token), timeout=15)
        assert r.status_code == 200
        rid = r.json()["id"]
        lst = requests.get(f"{API}/receipts", headers=auth(demo_token), timeout=15).json()
        assert any(x["id"] == rid for x in lst)
        d = requests.delete(f"{API}/receipts/{rid}", headers=auth(demo_token), timeout=15)
        assert d.status_code == 200


# ---------- Media ----------
class TestMedia:
    def test_crud(self, demo_token):
        r = requests.post(f"{API}/media", json={"title": "TEST Media", "phase": "progress",
                                                "url": "https://placehold.co/600x400.png", "date": "2026-01-01"},
                          headers=auth(demo_token), timeout=15)
        assert r.status_code == 200
        mid = r.json()["id"]
        lst = requests.get(f"{API}/media", headers=auth(demo_token), timeout=15).json()
        assert any(x["id"] == mid for x in lst)
        d = requests.delete(f"{API}/media/{mid}", headers=auth(demo_token), timeout=15)
        assert d.status_code == 200


# ---------- Upload / Download ----------
class TestUploadDownload:
    def test_upload_and_download(self, demo_token):
        # Minimal 1x1 PNG
        png = bytes.fromhex("89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4890000000A49444154789C6300010000000500010D0A2DB40000000049454E44AE426082")
        files = {"file": ("tiny.png", io.BytesIO(png), "image/png")}
        r = requests.post(f"{API}/upload", files=files, headers=auth(demo_token), timeout=120)
        if r.status_code == 402:
            pytest.skip("Storage credits exhausted")
        assert r.status_code == 200, f"Upload failed: {r.status_code} {r.text}"
        path = r.json()["path"]
        assert path and APP_NAME_FRAG in path

        # Download via query token
        d = requests.get(f"{API}/files/{path}", params={"token": demo_token}, timeout=60)
        assert d.status_code == 200
        assert d.headers.get("Content-Type", "").startswith("image/")
        assert len(d.content) == len(png)

        # Download via bearer header
        d2 = requests.get(f"{API}/files/{path}", headers=auth(demo_token), timeout=60)
        assert d2.status_code == 200

        # Unauth should 401
        d3 = requests.get(f"{API}/files/{path}", timeout=60)
        assert d3.status_code == 401


APP_NAME_FRAG = "my-builder-app/uploads/"


# ---------- AI estimate ----------
class TestAIEstimate:
    def test_estimate(self, demo_token):
        r = requests.post(f"{API}/ai/estimate",
                          json={"description": "Replace a small bathroom suite including tiling and basic plumbing", "finish_type": "Medium Finish"},
                          headers=auth(demo_token), timeout=90)
        if r.status_code == 502:
            pytest.skip(f"AI service error: {r.text}")
        assert r.status_code == 200, f"AI failed: {r.status_code} {r.text}"
        data = r.json()
        assert "items" in data and isinstance(data["items"], list) and len(data["items"]) >= 1
        assert "total_low" in data and "total_high" in data
        assert float(data["total_low"]) <= float(data["total_high"])

    def test_estimate_empty(self, demo_token):
        r = requests.post(f"{API}/ai/estimate", json={"description": "", "finish_type": "Medium Finish"},
                          headers=auth(demo_token), timeout=20)
        assert r.status_code == 400


# ---------- Payments ----------
class TestPayments:
    def test_checkout_session(self, demo_token):
        origin = BASE_URL
        r = requests.post(f"{API}/payments/checkout", json={"origin_url": origin}, headers=auth(demo_token), timeout=30)
        assert r.status_code == 200, f"Checkout failed: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("session_id")
        assert body.get("url", "").startswith("http")

        # Status endpoint
        s = requests.get(f"{API}/payments/status/{body['session_id']}", headers=auth(demo_token), timeout=30)
        assert s.status_code == 200
        js = s.json()
        assert "status" in js and "payment_status" in js



# ---------- Projects (Iteration 2: multi-project) ----------
class TestProjects:
    def test_list_projects_has_active(self, demo_token):
        r = requests.get(f"{API}/projects", headers=auth(demo_token), timeout=15)
        assert r.status_code == 200
        projs = r.json()
        assert isinstance(projs, list) and len(projs) >= 1
        actives = [p for p in projs if p.get("active")]
        assert len(actives) == 1
        for k in ("id", "name", "total_budget", "total_spent", "line_item_count", "receipt_count", "active"):
            assert k in projs[0], f"missing {k} in list_projects result"

    def test_create_activate_isolation_delete(self, demo_token):
        # Snapshot original active project id (Nottingham)
        before = requests.get(f"{API}/project", headers=auth(demo_token), timeout=15).json()
        nottingham_id = before["id"]

        # Create a brand new project
        payload = {"name": "TEST Project Iso", "address": "1 Test Lane, London, EC1A 1BB",
                   "purchase_price": 100000, "estimated_valuation": 150000, "monthly_rent": 950,
                   "budget": {"hard": 10000, "soft": 2000, "contingency": 1000}}
        c = requests.post(f"{API}/projects", json=payload, headers=auth(demo_token), timeout=20)
        assert c.status_code == 200
        new_proj = c.json()
        new_id = new_proj["id"]
        assert new_proj["name"] == "TEST Project Iso"
        assert new_proj["total_budget"] == pytest.approx(13000.0)

        try:
            # New project should be active after creation
            me_proj = requests.get(f"{API}/project", headers=auth(demo_token), timeout=15).json()
            assert me_proj["id"] == new_id

            # Data isolation: new project should have zero line-items / receipts / media / trade contacts
            for ep in ("line-items", "receipts", "media"):
                lst = requests.get(f"{API}/{ep}", headers=auth(demo_token), timeout=15).json()
                assert lst == [], f"{ep} should be empty for new project, got {len(lst)}"
            trades = requests.get(f"{API}/contacts?kind=trade", headers=auth(demo_token), timeout=15).json()
            assert trades == [], "trade contacts should be empty for new project"

            # Switch back to Nottingham via activate
            a = requests.post(f"{API}/projects/{nottingham_id}/activate", headers=auth(demo_token), timeout=15)
            assert a.status_code == 200
            assert a.json()["id"] == nottingham_id

            # Seeded data visible again on Nottingham
            lis = requests.get(f"{API}/line-items", headers=auth(demo_token), timeout=15).json()
            recs = requests.get(f"{API}/receipts", headers=auth(demo_token), timeout=15).json()
            med = requests.get(f"{API}/media", headers=auth(demo_token), timeout=15).json()
            trs = requests.get(f"{API}/contacts?kind=trade", headers=auth(demo_token), timeout=15).json()
            assert len(lis) >= 6
            assert len(recs) >= 3
            assert len(med) >= 3
            assert len(trs) >= 3

            # /api/project reflects active (Nottingham)
            cur = requests.get(f"{API}/project", headers=auth(demo_token), timeout=15).json()
            assert cur["id"] == nottingham_id
        finally:
            # Clean up: delete the test project
            d = requests.delete(f"{API}/projects/{new_id}", headers=auth(demo_token), timeout=15)
            assert d.status_code in (200, 404)

        # Verify deletion returned ok and project no longer in list
        lst = requests.get(f"{API}/projects", headers=auth(demo_token), timeout=15).json()
        assert not any(p["id"] == new_id for p in lst)

    def test_delete_last_project_400(self, demo_token):
        # Must not allow deletion when only 1 project exists.
        # Confirm with demo (demo has 1 base project after any TEST cleanup)
        projs = requests.get(f"{API}/projects", headers=auth(demo_token), timeout=15).json()
        if len(projs) != 1:
            pytest.skip(f"Need exactly 1 project to test last-delete guard, have {len(projs)}")
        d = requests.delete(f"{API}/projects/{projs[0]['id']}", headers=auth(demo_token), timeout=15)
        assert d.status_code == 400

    def test_activate_nonexistent_404(self, demo_token):
        from bson import ObjectId
        fake = str(ObjectId())
        r = requests.post(f"{API}/projects/{fake}/activate", headers=auth(demo_token), timeout=15)
        assert r.status_code == 404

    def test_create_project_blank_name_400(self, demo_token):
        r = requests.post(f"{API}/projects", json={"name": "   "}, headers=auth(demo_token), timeout=15)
        assert r.status_code == 400


# ---------- Trades finder (Iteration 2) ----------
class TestTradesFinder:
    def test_invalid_postcode_400(self, demo_token):
        r = requests.get(f"{API}/trades/search", params={"postcode": "NOTAPC", "trade": "plumber"},
                         headers=auth(demo_token), timeout=15)
        assert r.status_code == 400

    def test_unknown_postcode_404(self, demo_token):
        r = requests.get(f"{API}/trades/search", params={"postcode": "ZZ9 9ZZ", "trade": "plumber"},
                         headers=auth(demo_token), timeout=20)
        assert r.status_code == 404

    def test_unknown_trade_400(self, demo_token):
        r = requests.get(f"{API}/trades/search", params={"postcode": "NG3 5AP", "trade": "wizard"},
                         headers=auth(demo_token), timeout=15)
        assert r.status_code == 400

    def test_search_success_and_cache(self, demo_token):
        r = requests.get(f"{API}/trades/search", params={"postcode": "NG3 5AP", "trade": "plumber"},
                         headers=auth(demo_token), timeout=60)
        if r.status_code == 503:
            pytest.skip(f"Trades upstream unavailable: {r.text}")
        assert r.status_code == 200, f"Trades search failed: {r.status_code} {r.text}"
        body = r.json()
        assert body["trade"] == "plumber"
        assert body["postcode"].replace(" ", "").upper() == "NG35AP"
        assert isinstance(body["results"], list)
        if body["results"]:
            item = body["results"][0]
            for k in ("name", "distance_km"):
                assert k in item
            assert isinstance(item["distance_km"], (int, float))

        # Second call should be served from cache quickly (<3s)
        import time as _t
        t0 = _t.time()
        r2 = requests.get(f"{API}/trades/search", params={"postcode": "NG3 5AP", "trade": "plumber"},
                          headers=auth(demo_token), timeout=15)
        elapsed = _t.time() - t0
        assert r2.status_code == 200
        assert r2.json()["results"] == body["results"]
        assert elapsed < 3.0, f"Second call not cached (took {elapsed:.2f}s)"
