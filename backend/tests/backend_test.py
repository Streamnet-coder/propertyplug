"""Backend API tests for Builder Assist."""
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


# ---------- Milestones (Iteration 3) ----------
class TestMilestones:
    def test_demo_has_seeded_milestones(self, demo_token):
        r = requests.get(f"{API}/milestones", headers=auth(demo_token), timeout=15)
        assert r.status_code == 200
        ms = r.json()
        assert len(ms) == 10, f"Expected 10 default milestones, got {len(ms)}"
        done = [m for m in ms if m["status"] == "done"]
        inprog = [m for m in ms if m["status"] == "in_progress"]
        assert len(done) == 3, f"Expected first 3 done, got {len(done)}"
        assert len(inprog) == 1, f"Expected 1 in_progress, got {len(inprog)}"
        assert inprog[0]["name"] == "First fix (electrics & plumbing)"

    def test_project_summary_includes_milestone_counts(self, demo_token):
        p = requests.get(f"{API}/project", headers=auth(demo_token), timeout=15).json()
        assert p.get("milestones_total") == 10
        assert p.get("milestones_done") == 3
        assert p.get("current_stage") == "First fix (electrics & plumbing)"

    def test_milestone_create_update_status_cycle_delete(self, demo_token):
        # Create
        r = requests.post(f"{API}/milestones", json={"name": "TEST Stage", "target_date": "2026-07-01"},
                          headers=auth(demo_token), timeout=15)
        assert r.status_code == 200
        m = r.json()
        mid = m["id"]
        assert m["name"] == "TEST Stage"
        assert m["status"] == "todo"
        try:
            # Cycle status: todo -> in_progress
            r2 = requests.put(f"{API}/milestones/{mid}", json={"status": "in_progress"},
                              headers=auth(demo_token), timeout=15)
            assert r2.status_code == 200 and r2.json()["status"] == "in_progress"
            assert r2.json().get("completed_at") is None
            # -> done sets completed_at
            r3 = requests.put(f"{API}/milestones/{mid}", json={"status": "done"},
                              headers=auth(demo_token), timeout=15)
            assert r3.status_code == 200 and r3.json()["status"] == "done"
            assert r3.json().get("completed_at")
            # -> back to todo clears completed_at
            r4 = requests.put(f"{API}/milestones/{mid}", json={"status": "todo", "notes": "note"},
                              headers=auth(demo_token), timeout=15)
            assert r4.status_code == 200
            assert r4.json()["status"] == "todo"
            assert r4.json().get("completed_at") is None
            assert r4.json()["notes"] == "note"
        finally:
            d = requests.delete(f"{API}/milestones/{mid}", headers=auth(demo_token), timeout=15)
            assert d.status_code == 200
        lst = requests.get(f"{API}/milestones", headers=auth(demo_token), timeout=15).json()
        assert not any(x["id"] == mid for x in lst)

    def test_milestone_blank_name_400(self, demo_token):
        r = requests.post(f"{API}/milestones", json={"name": "   "}, headers=auth(demo_token), timeout=15)
        assert r.status_code == 400


# ---------- Share link (Iteration 3) ----------
class TestShare:
    def test_share_create_fetch_revoke(self, demo_token):
        origin = BASE_URL
        # Initially get -> may be None
        g0 = requests.get(f"{API}/project/share", headers=auth(demo_token), timeout=15)
        assert g0.status_code == 200
        # Create
        r = requests.post(f"{API}/project/share", json={"origin_url": origin},
                          headers=auth(demo_token), timeout=15)
        assert r.status_code == 200
        url = r.json()["url"]
        assert url and "/api/share/" in url
        token = url.rsplit("/", 1)[-1]
        # Verify get returns it
        g1 = requests.get(f"{API}/project/share", headers=auth(demo_token), timeout=15)
        assert g1.json()["url"] == url
        # Public page returns HTML, no auth required
        html = requests.get(url, timeout=30)
        assert html.status_code == 200
        assert "text/html" in html.headers.get("Content-Type", "")
        body = html.text
        # Content must include milestones, budget, project header
        assert "Milestones" in body
        assert "Nottingham" in body or "LIVE PROJECT REPORT" in body
        assert "£" in body  # money rendered
        # photo endpoint should resolve to an image (either direct bytes or redirect)
        import re
        m = re.search(r"/api/share/" + re.escape(token) + r"/photo/([a-f0-9]+)", body)
        if m:
            mid = m.group(1)
            p_resp = requests.get(f"{BASE_URL}/api/share/{token}/photo/{mid}", timeout=30,
                                  allow_redirects=True)
            assert p_resp.status_code == 200
            assert p_resp.headers.get("Content-Type", "").startswith("image/")
        # Revoke
        d = requests.delete(f"{API}/project/share", headers=auth(demo_token), timeout=15)
        assert d.status_code == 200
        assert d.json()["url"] is None
        # After revoke, visiting old URL should show "no longer active"
        html2 = requests.get(url, timeout=30)
        assert html2.status_code == 200
        assert "no longer active" in html2.text.lower()


# ---------- Quote requests (Iteration 3) ----------
class TestQuotes:
    @pytest.fixture
    def trade_ids(self, demo_token):
        trades = requests.get(f"{API}/contacts?kind=trade", headers=auth(demo_token), timeout=15).json()
        assert len(trades) >= 2, "Need at least 2 trades on demo"
        return [t["id"] for t in trades[:2]]

    def test_quote_full_flow(self, demo_token, trade_ids):
        origin = BASE_URL
        # Create
        payload = {"title": "TEST Kitchen fit", "description": "Install replacement kitchen units and worktops.",
                   "contact_ids": trade_ids, "origin_url": origin, "trade": "carpenter"}
        c = requests.post(f"{API}/quotes", json=payload, headers=auth(demo_token), timeout=15)
        assert c.status_code == 200
        q = c.json()
        qid = q["id"]
        try:
            assert len(q["quotes"]) == len(trade_ids)
            # Every entry has a link
            for e in q["quotes"]:
                assert e["link"].startswith(origin) and "/api/q/" in e["link"]
                assert e["status"] == "requested"
                assert e["amount"] is None
            # List endpoint
            lst = requests.get(f"{API}/quotes", headers=auth(demo_token), timeout=15).json()
            assert any(x["id"] == qid for x in lst)
            # Get
            g = requests.get(f"{API}/quotes/{qid}", headers=auth(demo_token), timeout=15).json()
            assert g["title"] == payload["title"]

            # Owner PUT first entry with amount -> status becomes received
            e1 = q["quotes"][0]
            u1 = requests.put(f"{API}/quotes/{qid}/entries/{e1['id']}",
                              json={"amount": 5000, "days": 7, "notes": "incl materials", "sent": True},
                              headers=auth(demo_token), timeout=15)
            assert u1.status_code == 200
            e1b = next(x for x in u1.json()["quotes"] if x["id"] == e1["id"])
            assert e1b["amount"] == 5000
            assert e1b["status"] == "received"
            assert e1b["sent"] is True
            assert e1b["days"] == 7

            # Public GET of 2nd entry's token returns form HTML
            e2 = q["quotes"][1]
            token2 = e2["link"].rsplit("/", 1)[-1]
            html = requests.get(f"{BASE_URL}/api/q/{token2}", timeout=15)
            assert html.status_code == 200
            assert "text/html" in html.headers.get("Content-Type", "")
            assert "Submit your quote" in html.text or "Update your quote" in html.text

            # Public POST form-encoded sets amount, status received
            resp = requests.post(f"{BASE_URL}/api/q/{token2}",
                                 data={"amount": "4500.50", "days": "10", "notes": "ready next month"},
                                 timeout=15)
            assert resp.status_code == 200
            assert "4,500" in resp.text or "Quote sent" in resp.text
            gq = requests.get(f"{API}/quotes/{qid}", headers=auth(demo_token), timeout=15).json()
            e2b = next(x for x in gq["quotes"] if x["id"] == e2["id"])
            assert e2b["amount"] == 4500.50
            assert e2b["status"] == "received"
            assert e2b["days"] == 10

            # Accept e1 -> creates a line item, others declined
            a1 = requests.post(f"{API}/quotes/{qid}/entries/{e1['id']}/accept",
                               json={"add_to_budget": True}, headers=auth(demo_token), timeout=15)
            assert a1.status_code == 200
            qa = a1.json()
            accepted = [x for x in qa["quotes"] if x["status"] == "accepted"]
            declined = [x for x in qa["quotes"] if x["status"] == "declined"]
            assert len(accepted) == 1 and accepted[0]["id"] == e1["id"]
            assert len(declined) == len(trade_ids) - 1
            assert qa.get("added_line_item_id")
            line_id_1 = qa["added_line_item_id"]
            # Verify line item created in budget with amount
            lis = requests.get(f"{API}/line-items", headers=auth(demo_token), timeout=15).json()
            matched = [x for x in lis if x["id"] == line_id_1]
            assert matched and matched[0]["budgeted"] == 5000

            # Public GET of accepted entry's token should now be "closed" / "awarded"
            tokenA = e1["link"].rsplit("/", 1)[-1]
            closedh = requests.get(f"{BASE_URL}/api/q/{tokenA}", timeout=15)
            assert "awarded" in closedh.text.lower() or "closed" in closedh.text.lower()

            # Re-accept e2 -> replaces line item
            a2 = requests.post(f"{API}/quotes/{qid}/entries/{e2['id']}/accept",
                               json={"add_to_budget": True}, headers=auth(demo_token), timeout=15)
            assert a2.status_code == 200
            qa2 = a2.json()
            line_id_2 = qa2.get("added_line_item_id")
            assert line_id_2 and line_id_2 != line_id_1
            lis2 = requests.get(f"{API}/line-items", headers=auth(demo_token), timeout=15).json()
            assert not any(x["id"] == line_id_1 for x in lis2), "Old line item should be replaced"
            matched2 = [x for x in lis2 if x["id"] == line_id_2]
            assert matched2 and matched2[0]["budgeted"] == 4500.50
        finally:
            # Clean up: delete quote (which may leave line item orphaned if not cleaned by DELETE)
            # Delete the created line item first if present
            try:
                gfin = requests.get(f"{API}/quotes/{qid}", headers=auth(demo_token), timeout=15).json()
                lid = gfin.get("added_line_item_id")
                if lid:
                    requests.delete(f"{API}/line-items/{lid}", headers=auth(demo_token), timeout=15)
            except Exception:
                pass
            d = requests.delete(f"{API}/quotes/{qid}", headers=auth(demo_token), timeout=15)
            assert d.status_code == 200
        lst2 = requests.get(f"{API}/quotes", headers=auth(demo_token), timeout=15).json()
        assert not any(x["id"] == qid for x in lst2)

    def test_quote_empty_title_400(self, demo_token, trade_ids):
        r = requests.post(f"{API}/quotes",
                          json={"title": " ", "description": "x", "contact_ids": trade_ids, "origin_url": BASE_URL},
                          headers=auth(demo_token), timeout=15)
        assert r.status_code == 400

    def test_quote_no_contacts_400(self, demo_token):
        r = requests.post(f"{API}/quotes",
                          json={"title": "x", "description": "x", "contact_ids": [], "origin_url": BASE_URL},
                          headers=auth(demo_token), timeout=15)
        assert r.status_code in (400, 422)

    def test_public_q_token_not_found(self):
        r = requests.get(f"{BASE_URL}/api/q/notarealtoken_xxx", timeout=15)
        assert r.status_code == 200
        assert "no longer active" in r.text.lower()
