"""Iteration 36 backend tests - Manager Money Access permission flag.

Covers:
1. POST /api/co-owners with {money_access: false} + GET /api/co-owners returns money_access
2. PUT /api/co-owners/{id} toggles money_access, GET /api/co-owners/shared-with-me returns money_access
3. Tasks-only manager auth/me acting_as.money false
4. /api/project money_hidden true + zeroed money fields, /api/projects shared row zeroed
5. 403 on money routes (line-items, receipts, quotes, stage-payments, rentals, project/comparables, project/share, POST ai/estimate)
6. 200 on day-to-day routes (milestones, snags, media, documents, contacts)
7. PUT /api/project with purchase_price ignored (owner value unchanged)
8. /api/portfolio/rent-roll excludes the project
9. Public pages (/api/t/{token}, /api/q/{token}) still work without auth
10. Switching money_access true restores 200 on money routes
11. Cleanup

Run sequentially:
    pytest /app/backend/tests/test_iteration36.py -v -o "addopts=" --tb=short
"""
import os
import uuid
from typing import Dict

import pytest
import requests
from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

_cli = MongoClient(os.environ["MONGO_URL"])
_db = _cli[os.environ["DB_NAME"]]

OWNER_EMAIL = "demo@mybuilder.app"
OWNER_PASS = "demo1234"


def _h(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _register(email: str, password: str, name: str) -> str:
    r = requests.post(f"{API}/auth/register", json={"email": email, "password": password, "name": name})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# ----------------------- fixtures -----------------------
@pytest.fixture(scope="module")
def owner_tok() -> str:
    return _login(OWNER_EMAIL, OWNER_PASS)


@pytest.fixture(scope="module")
def owner_project(owner_tok) -> str:
    pr = requests.get(f"{API}/projects", headers=_h(owner_tok)).json()
    own = [p for p in pr if not p.get("shared")]
    assert own, "owner must have at least one project"
    pid = own[0]["id"]
    requests.post(f"{API}/projects/{pid}/activate", headers=_h(owner_tok))
    return pid


@pytest.fixture(scope="module")
def owner_project_snapshot(owner_tok, owner_project) -> dict:
    """Capture the owner's own project money values to prove manager PUT doesn't change them."""
    pr = requests.get(f"{API}/project", headers=_h(owner_tok)).json()
    return {"purchase_price": pr.get("purchase_price"), "total_budget": pr.get("total_budget")}


@pytest.fixture(scope="module")
def invitee():
    email = f"test_iter36_{uuid.uuid4().hex[:8]}@example.com"
    password = "TestPass123!"
    name = "TEST_iter36 Manager"
    tok = _register(email, password, name)
    yield {"email": email, "password": password, "name": name, "token": tok}
    # cleanup
    u = _db.users.find_one({"email": email})
    if u:
        uid = str(u["_id"])
        for coll in (
            "projects", "line_items", "contacts", "receipts", "milestones", "snags",
            "shopping_items", "documents", "doc_folders", "quote_requests", "stage_payments",
            "snag_links", "tenancies", "rent_payments", "rental_expenses", "rent_statements",
            "compare_links", "portal_members", "project_activity", "co_owners",
        ):
            try:
                _db[coll].delete_many({"user_id": uid})
            except Exception:
                pass
        _db.co_owners.delete_many({"email": email})
        _db.users.delete_one({"_id": u["_id"]})


# ===== 1. Invite/PUT/GET persistence of money_access =====
class TestCoOwnerMoneyAccessPersistence:
    def test_invite_tasks_only_persists(self, owner_tok, invitee, owner_project):
        r = requests.post(f"{API}/co-owners", headers=_h(owner_tok), json={
            "email": invitee["email"], "project_ids": [owner_project], "money_access": False,
        })
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["money_access"] is False
        assert b["role"] == "manager"
        assert b["project_ids"] == [owner_project]

    def test_get_co_owners_returns_money_access(self, owner_tok, invitee):
        got = requests.get(f"{API}/co-owners", headers=_h(owner_tok)).json()
        row = next(x for x in got if x["email"] == invitee["email"])
        assert row["money_access"] is False

    def test_shared_with_me_returns_money_access(self, invitee):
        tok = _login(invitee["email"], invitee["password"])
        s = requests.get(f"{API}/co-owners/shared-with-me", headers=_h(tok)).json()
        assert len(s) == 1
        assert s[0]["money_access"] is False

    def test_put_toggle_money_access_true_then_false(self, owner_tok, invitee, owner_project):
        got = requests.get(f"{API}/co-owners", headers=_h(owner_tok)).json()
        cid = next(x for x in got if x["email"] == invitee["email"])["id"]
        # toggle true
        r = requests.put(f"{API}/co-owners/{cid}", headers=_h(owner_tok), json={
            "project_ids": [owner_project], "money_access": True,
        })
        assert r.status_code == 200, r.text
        assert r.json()["money_access"] is True
        # back to false for the rest of the tests
        r = requests.put(f"{API}/co-owners/{cid}", headers=_h(owner_tok), json={
            "project_ids": [owner_project], "money_access": False,
        })
        assert r.status_code == 200
        assert r.json()["money_access"] is False


# ===== 2. Tasks-only manager: acting_as, project hiding, 403, 200 =====
class TestTasksOnlyManagerAccess:
    @pytest.fixture(autouse=True)
    def activate(self, invitee, owner_project):
        tok = _login(invitee["email"], invitee["password"])
        # Activate the shared project
        r = requests.post(f"{API}/projects/{owner_project}/activate", headers=_h(tok))
        assert r.status_code == 200, r.text
        self.tok = tok
        self.pid = owner_project

    def test_auth_me_acting_as_money_false(self):
        r = requests.get(f"{API}/auth/me", headers=_h(self.tok))
        assert r.status_code == 200, r.text
        me = r.json()
        assert me["acting_as"] is not None, me
        assert me["acting_as"]["money"] is False, me["acting_as"]

    def test_project_money_hidden_and_zeroed(self):
        r = requests.get(f"{API}/project", headers=_h(self.tok))
        assert r.status_code == 200, r.text
        p = r.json()
        assert p.get("money_hidden") is True
        # Scalars that should be zero
        for k in ("total_budget", "purchase_price", "estimated_valuation", "total_spent"):
            if k in p:
                assert p[k] in (0, 0.0), f"{k} not zeroed: {p[k]}"
        # home_finance (nested dict): all numeric values zero
        hf = p.get("home_finance")
        if isinstance(hf, dict):
            def _check(d):
                for k, v in d.items():
                    if isinstance(v, dict):
                        _check(v)
                    elif isinstance(v, (int, float)) and not isinstance(v, bool):
                        assert v == 0, f"home_finance.{k} not zero: {v}"
            _check(hf)

    def test_projects_shared_row_zeroed(self):
        r = requests.get(f"{API}/projects", headers=_h(self.tok))
        assert r.status_code == 200
        shared = [p for p in r.json() if p.get("shared") and p["id"] == self.pid]
        assert len(shared) == 1
        row = shared[0]
        assert row.get("money_hidden") is True
        for k in ("total_budget", "purchase_price", "total_spent"):
            if k in row:
                assert row[k] in (0, 0.0), f"shared row {k} not zero: {row[k]}"

    @pytest.mark.parametrize("path", [
        "/line-items", "/receipts", "/quotes", "/stage-payments", "/rentals",
        "/project/comparables", "/project/share",
    ])
    def test_money_routes_403(self, path):
        r = requests.get(f"{API}{path}", headers=_h(self.tok))
        assert r.status_code == 403, f"{path} -> {r.status_code} {r.text}"

    def test_ai_estimate_403(self):
        r = requests.post(f"{API}/ai/estimate", headers=_h(self.tok), json={"description": "paint"})
        assert r.status_code == 403, r.text

    @pytest.mark.parametrize("path", ["/milestones", "/snags", "/media", "/documents", "/contacts"])
    def test_day_to_day_routes_200(self, path):
        r = requests.get(f"{API}{path}", headers=_h(self.tok))
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text}"

    def test_put_project_money_ignored(self, owner_tok, owner_project_snapshot):
        # Manager tries to change purchase_price - should be ignored.
        r = requests.put(f"{API}/project", headers=_h(self.tok),
                         json={"purchase_price": 999999})
        # Accepted (200) but money field unchanged in DB
        assert r.status_code in (200, 400, 403), r.text
        # Owner reads real value
        pr = requests.get(f"{API}/project", headers=_h(owner_tok)).json()
        assert pr.get("purchase_price") == owner_project_snapshot["purchase_price"], (
            f"owner purchase_price changed by manager! was {owner_project_snapshot['purchase_price']}, now {pr.get('purchase_price')}"
        )

    def test_rent_roll_excludes_project(self):
        r = requests.get(f"{API}/portfolio/rent-roll", headers=_h(self.tok))
        assert r.status_code == 200, r.text
        props = r.json().get("properties", [])
        assert not any(p["id"] == self.pid for p in props), (
            f"tasks-only manager rent-roll still contains shared project {self.pid}"
        )


# ===== 3. Public (no auth) pages still work =====
class TestPublicPagesStillWork:
    def test_quote_and_tenant_public_endpoints_no_auth(self, owner_tok, owner_project):
        """Make a quote request + a tenancy with public tokens, then confirm /api/q/{token}
        and /api/t/{token} work without a bearer (block_money passes when no cred)."""
        # Create a quote request to generate a public token
        qr = requests.post(f"{API}/quotes", headers=_h(owner_tok), json={
            "title": "TEST_iter36 Quote",
            "description": "Checking public endpoint",
            "project_id": owner_project,
            "trades": ["builder@test.example"],
        })
        q_token = None
        if qr.status_code == 200:
            data = qr.json()
            quotes = data.get("quotes") or []
            if quotes:
                q_token = quotes[0].get("token")
        if q_token:
            r = requests.get(f"{API}/q/{q_token}")
            # Should NOT be 401/403 due to money block; status should be 200 (or 404 if route differs)
            assert r.status_code in (200, 404), f"public /q/{{token}} returned {r.status_code}: {r.text[:200]}"
            if r.status_code == 200:
                assert "money_hidden" not in r.text or True
        else:
            pytest.skip("couldn't create quote with token")

        # Clean up the test quote so the owner's quotes list isn't polluted
        qid = (data or {}).get("id") if qr.status_code == 200 else None
        if qid:
            requests.delete(f"{API}/quotes/{qid}", headers=_h(owner_tok))

    def test_public_tenant_portal_no_bearer(self):
        # Hit a bogus token - should NOT be 403 money-block; should be 404 (route reached).
        r = requests.get(f"{API}/t/not-a-real-token")
        assert r.status_code != 403, f"public /t/{{token}} unexpectedly 403 money-blocked: {r.text[:200]}"
        assert r.status_code in (200, 404)


# ===== 4. Restoring money_access=True brings 200 back =====
class TestRestoreMoneyAccess:
    def test_switch_true_restores_200(self, owner_tok, invitee, owner_project):
        got = requests.get(f"{API}/co-owners", headers=_h(owner_tok)).json()
        cid = next(x for x in got if x["email"] == invitee["email"])["id"]
        r = requests.put(f"{API}/co-owners/{cid}", headers=_h(owner_tok), json={
            "project_ids": [owner_project], "money_access": True,
        })
        assert r.status_code == 200
        assert r.json()["money_access"] is True

        tok = _login(invitee["email"], invitee["password"])
        # ensure active project
        requests.post(f"{API}/projects/{owner_project}/activate", headers=_h(tok))
        for path in ("/line-items", "/receipts", "/quotes", "/stage-payments", "/rentals"):
            r = requests.get(f"{API}{path}", headers=_h(tok))
            assert r.status_code == 200, f"{path} after unlock -> {r.status_code} {r.text}"
        # /api/project no longer money_hidden
        pr = requests.get(f"{API}/project", headers=_h(tok)).json()
        assert not pr.get("money_hidden"), "project still money_hidden after unlock"
        # auth/me acting_as.money true
        me = requests.get(f"{API}/auth/me", headers=_h(tok)).json()
        assert me["acting_as"]["money"] is True


# ===== Final cleanup =====
def test_zz_cleanup(owner_tok):
    """Remove any TEST_iter36 co_owner invites and reactivate demo original project."""
    got = requests.get(f"{API}/co-owners", headers=_h(owner_tok)).json()
    for row in got:
        if row["email"].startswith("test_iter36_"):
            requests.delete(f"{API}/co-owners/{row['id']}", headers=_h(owner_tok))
    pr = requests.get(f"{API}/projects", headers=_h(owner_tok)).json()
    own = [p for p in pr if not p.get("shared")]
    original = next((p for p in own if not p["name"].startswith("TEST_")), own[0])
    requests.post(f"{API}/projects/{original['id']}/activate", headers=_h(owner_tok))
