"""Iteration 40 — Co-owner shareable invite LINKS (one person, 7 days, cancellable).

Verifies:
  POST /api/co-owner-links (real user) {project_ids:null,money_access:true}
    -> {id, token, role:'co_owner', project_names:null, money_access:true, expires_at ~7d}
  GET  /api/co-owner-links lists only ACTIVE (unused, unexpired)
  DELETE /api/co-owner-links/{lid} cancels; subsequent GET /api/join/{token} -> 404
  GET  /api/join/{token} public (no auth) -> {owner_name, role, project_names, money_access, expires_at}
    - 404 for invalid token
    - 410 for USED
    - 410 for EXPIRED (expires_at tampered in mongo)
  POST /api/join/{token}
    - 400 when owner uses their own link
    - 200 for a new TEST user; appears in owner GET /api/co-owners with matching role / money_access;
      owner's projects visible in TEST user's GET /api/projects (shared=true)
    - 410 when a second user tries the already-used link
  Manager link limits to chosen projects (second user via a fresh manager link sees only those).
"""
import os
import time
import uuid

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") + "/api"
OWNER = {"email": "demo@mybuilder.app", "password": "demo1234"}
STAMP = str(int(time.time()))

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


# ---------- helpers ----------
def H(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _register(name, email, password):
    r = requests.post(f"{BASE}/auth/register", json={"name": name, "email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def owner_token():
    return _login(**OWNER)


@pytest.fixture(scope="module")
def owner_projects(owner_token):
    r = requests.get(f"{BASE}/projects", headers=H(owner_token), timeout=20)
    assert r.status_code == 200, r.text
    projects = [p for p in r.json() if not p.get("shared")]
    assert projects, "owner has no own projects"
    return projects


@pytest.fixture
def created_tokens():
    """Collect co_owner_link ids per test for cleanup."""
    ids = []
    yield ids
    # best-effort cleanup via mongo in finalizer below


@pytest.fixture(scope="module")
def cleanup_registry():
    """Collect test users / co_owner_links / co_owners rows to delete at end-of-module."""
    reg = {"users": set(), "links": [], "co_owners": []}
    yield reg
    import asyncio

    async def _cleanup():
        c = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
        if reg["links"]:
            await c.co_owner_links.delete_many({})  # safe: dev DB; filter stricter below if needed
        # Rebuild: only delete TEST co_owners rows
        await c.co_owners.delete_many({"email": {"$regex": "^test_iter40_"}})
        if reg["users"]:
            await c.users.delete_many({"email": {"$in": list(reg["users"])}})
        # Specifically also delete any lingering TEST links for the demo owner
        demo = await c.users.find_one({"email": OWNER["email"]}, {"_id": 1})
        if demo:
            await c.co_owner_links.delete_many({"owner_id": str(demo["_id"])})
    asyncio.get_event_loop().run_until_complete(_cleanup())


# ---------- POST /api/co-owner-links ----------
class TestCreateListLink:
    def test_create_co_owner_link_full_shape(self, owner_token, cleanup_registry):
        r = requests.post(f"{BASE}/co-owner-links", headers=H(owner_token),
                          json={"project_ids": None, "money_access": True}, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert set(["id", "token", "role", "project_ids", "project_names", "money_access", "expires_at", "created_at"]).issubset(d.keys())
        assert d["role"] == "co_owner"
        assert d["project_names"] is None
        assert d["money_access"] is True
        assert isinstance(d["token"], str) and len(d["token"]) >= 16
        # ~7 days from now
        from datetime import datetime, timezone
        exp = datetime.fromisoformat(d["expires_at"])
        delta_days = (exp - datetime.now(timezone.utc)).total_seconds() / 86400
        assert 6.5 < delta_days < 7.5, f"expires_at not ~7d: {delta_days}"
        cleanup_registry["links"].append(d["id"])

    def test_list_links_contains_active(self, owner_token):
        r = requests.get(f"{BASE}/co-owner-links", headers=H(owner_token), timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert any(x["role"] == "co_owner" for x in r.json())

    def test_create_manager_link_with_project(self, owner_token, owner_projects, cleanup_registry):
        pid = owner_projects[0]["id"]
        r = requests.post(f"{BASE}/co-owner-links", headers=H(owner_token),
                          json={"project_ids": [pid], "money_access": False}, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["role"] == "manager"
        assert d["project_ids"] == [pid]
        assert isinstance(d["project_names"], list) and len(d["project_names"]) == 1
        assert d["money_access"] is False
        cleanup_registry["links"].append(d["id"])

    def test_create_manager_link_rejects_empty_list(self, owner_token):
        r = requests.post(f"{BASE}/co-owner-links", headers=H(owner_token),
                          json={"project_ids": [], "money_access": True}, timeout=20)
        assert r.status_code == 400

    def test_create_requires_auth(self):
        r = requests.post(f"{BASE}/co-owner-links", json={"project_ids": None, "money_access": True}, timeout=20)
        assert r.status_code in (401, 403)


# ---------- DELETE / cancel ----------
class TestCancelLink:
    def test_cancel_hides_from_list_and_public(self, owner_token, cleanup_registry):
        # create a link
        r = requests.post(f"{BASE}/co-owner-links", headers=H(owner_token), json={"project_ids": None, "money_access": True}, timeout=20)
        assert r.status_code == 200
        link = r.json()
        lid, tok = link["id"], link["token"]
        # cancel
        r2 = requests.delete(f"{BASE}/co-owner-links/{lid}", headers=H(owner_token), timeout=20)
        assert r2.status_code == 200
        # list shouldn't include it
        lst = requests.get(f"{BASE}/co-owner-links", headers=H(owner_token), timeout=20).json()
        assert all(x["id"] != lid for x in lst)
        # public GET returns 404
        r3 = requests.get(f"{BASE}/join/{tok}", timeout=20)
        assert r3.status_code == 404, r3.text


# ---------- Public GET /api/join/{token} ----------
class TestJoinPublic:
    def test_public_preview_no_auth(self, owner_token, cleanup_registry):
        r = requests.post(f"{BASE}/co-owner-links", headers=H(owner_token), json={"project_ids": None, "money_access": True}, timeout=20)
        tok = r.json()["token"]
        cleanup_registry["links"].append(r.json()["id"])
        pub = requests.get(f"{BASE}/join/{tok}", timeout=20)
        assert pub.status_code == 200, pub.text
        b = pub.json()
        assert set(["owner_name", "role", "project_names", "money_access", "expires_at"]).issubset(b.keys())
        assert b["role"] == "co_owner"
        assert b["project_names"] is None
        assert b["money_access"] is True
        assert isinstance(b["owner_name"], str) and b["owner_name"]

    def test_public_invalid_404(self):
        r = requests.get(f"{BASE}/join/not-a-real-token-xyz-{STAMP}", timeout=20)
        assert r.status_code == 404

    def test_public_expired_410(self, owner_token, cleanup_registry):
        # create, then set expires_at to past in mongo
        r = requests.post(f"{BASE}/co-owner-links", headers=H(owner_token), json={"project_ids": None, "money_access": True}, timeout=20)
        tok = r.json()["token"]
        cleanup_registry["links"].append(r.json()["id"])
        import asyncio
        async def _expire():
            c = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
            res = await c.co_owner_links.update_one({"token": tok}, {"$set": {"expires_at": "2000-01-01T00:00:00+00:00"}})
            assert res.modified_count == 1
        asyncio.get_event_loop().run_until_complete(_expire())
        pub = requests.get(f"{BASE}/join/{tok}", timeout=20)
        assert pub.status_code == 410, pub.text


# ---------- POST /api/join/{token} ----------
class TestAcceptLink:
    def test_owner_using_own_link_400(self, owner_token, cleanup_registry):
        r = requests.post(f"{BASE}/co-owner-links", headers=H(owner_token), json={"project_ids": None, "money_access": True}, timeout=20)
        tok = r.json()["token"]
        cleanup_registry["links"].append(r.json()["id"])
        acc = requests.post(f"{BASE}/join/{tok}", headers=H(owner_token), timeout=20)
        assert acc.status_code == 400, acc.text

    def test_new_user_accepts_coowner_full_access(self, owner_token, cleanup_registry):
        # fresh link
        r = requests.post(f"{BASE}/co-owner-links", headers=H(owner_token), json={"project_ids": None, "money_access": True}, timeout=20)
        tok = r.json()["token"]
        cleanup_registry["links"].append(r.json()["id"])
        # register TEST user
        email = f"test_iter40_co_{uuid.uuid4().hex[:8]}@example.com"
        cleanup_registry["users"].add(email)
        tok_u = _register("TEST Iter40 CoOwner", email, "Pass12345!")
        acc = requests.post(f"{BASE}/join/{tok}", headers=H(tok_u), timeout=30)
        assert acc.status_code == 200, acc.text
        body = acc.json()
        assert body.get("ok") is True
        assert body.get("owner_name")

        # Owner's co-owners list contains this user with full access
        mine = requests.get(f"{BASE}/co-owners", headers=H(owner_token), timeout=20).json()
        found = [x for x in mine if x["email"] == email]
        assert found, f"user not in owner co-owners: {mine}"
        assert found[0]["role"] == "co_owner"
        assert found[0]["money_access"] is True

        # TEST user's /projects includes owner's projects as shared
        projs = requests.get(f"{BASE}/projects", headers=H(tok_u), timeout=20).json()
        shared = [p for p in projs if p.get("shared")]
        assert shared, f"no shared projects visible to TEST user: {projs}"

        # Second user tries same link -> 410 used
        email2 = f"test_iter40_second_{uuid.uuid4().hex[:8]}@example.com"
        cleanup_registry["users"].add(email2)
        tok2 = _register("TEST Iter40 Second", email2, "Pass12345!")
        acc2 = requests.post(f"{BASE}/join/{tok}", headers=H(tok2), timeout=20)
        assert acc2.status_code == 410, acc2.text

        # The used link no longer appears in owner's /co-owner-links (only active)
        active = requests.get(f"{BASE}/co-owner-links", headers=H(owner_token), timeout=20).json()
        assert all(x["token"] != tok for x in active)

        # Public GET on used token -> 410
        pub = requests.get(f"{BASE}/join/{tok}", timeout=20)
        assert pub.status_code == 410

    def test_manager_link_limits_projects(self, owner_token, owner_projects, cleanup_registry):
        pid = owner_projects[0]["id"]
        r = requests.post(f"{BASE}/co-owner-links", headers=H(owner_token),
                          json={"project_ids": [pid], "money_access": False}, timeout=20)
        assert r.status_code == 200, r.text
        tok = r.json()["token"]
        cleanup_registry["links"].append(r.json()["id"])

        # Register fresh user and accept
        email = f"test_iter40_mgr_{uuid.uuid4().hex[:8]}@example.com"
        cleanup_registry["users"].add(email)
        tok_u = _register("TEST Iter40 Mgr", email, "Pass12345!")
        acc = requests.post(f"{BASE}/join/{tok}", headers=H(tok_u), timeout=30)
        assert acc.status_code == 200, acc.text

        # Owner side: role = manager with correct pids, money_access=False
        mine = requests.get(f"{BASE}/co-owners", headers=H(owner_token), timeout=20).json()
        found = [x for x in mine if x["email"] == email]
        assert found
        assert found[0]["role"] == "manager"
        assert found[0]["project_ids"] == [pid]
        assert found[0]["money_access"] is False

        # TEST user sees exactly 1 shared project (the chosen one) — if owner has >1 project
        projs = requests.get(f"{BASE}/projects", headers=H(tok_u), timeout=20).json()
        shared_ids = [p["id"] for p in projs if p.get("shared")]
        assert pid in shared_ids, f"chosen pid {pid} not shared: {shared_ids}"
        if len(owner_projects) > 1:
            # manager must NOT see the other owner project
            other_ids = {p["id"] for p in owner_projects if p["id"] != pid}
            assert not (set(shared_ids) & other_ids), f"manager sees unauthorized projects: {shared_ids}"
