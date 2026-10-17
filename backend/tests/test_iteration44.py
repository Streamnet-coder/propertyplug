"""Iteration 44 — Co-owner scoped project access.

Covers:
- POST /api/co-owners: role=co_owner with project_ids list -> role co_owner, project_names populated,
  money_access forced True; role=manager with project_ids=None -> 400; role=co_owner with empty list -> 400.
- Legacy behaviour: no role, project_ids=None -> co_owner (all); no role, project_ids=[pid] -> manager.
- PUT /api/co-owners/{id} switching co_owner all <-> co_owner chosen <-> manager.
- POST /api/co-owner-links role=co_owner + project_ids -> GET /api/join/{token} returns co_owner + project_names.
- Accepting link from another registered user creates a co_owner doc with project_ids and that user sees
  ONLY those owner's projects in GET /api/projects, with money access.
- GET /api/co-owners/shared-with-me returns correct role.
"""
import os
import sys
import uuid

import pytest
import requests
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://dev-budget-tracker-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"
MONGO = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

TAG = f"iter44_{uuid.uuid4().hex[:6]}"
RUN = {"co_owners": [], "links": [], "second_users": []}
STATE: dict = {}


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def owner():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": "demo@mybuilder.app", "password": "demo1234"})
    assert r.status_code == 200, r.text
    j = r.json()
    s.headers["Authorization"] = f"Bearer {j.get('access_token') or j.get('token')}"
    me = s.get(f"{API}/auth/me").json()
    STATE["owner_id"] = me["id"]
    STATE["owner_email"] = me["email"]
    return s


@pytest.fixture(scope="module")
def projects(owner):
    r = owner.get(f"{API}/projects")
    assert r.status_code == 200, r.text
    # Only our own projects, not shared ones
    pjs = [p for p in r.json() if not p.get("shared")]
    assert len(pjs) >= 1, "demo must have at least one project"
    STATE["pids"] = [p["id"] for p in pjs]
    STATE["pnames"] = {p["id"]: p["name"] for p in pjs}
    # Create a second project if only one exists, so we can validate scoping
    if len(pjs) < 2:
        r2 = owner.post(f"{API}/projects", json={"name": f"TEST ScopeProj {TAG}", "address": "1 Test Rd"})
        assert r2.status_code in (200, 201), r2.text
        p2 = r2.json()
        STATE["pids"].append(p2["id"])
        STATE["pnames"][p2["id"]] = p2["name"]
        STATE["created_pid"] = p2["id"]
    return STATE["pids"]


@pytest.fixture(scope="module")
def pre_cleanup(mongo, owner, projects):
    # Remove any lingering test co-owner/link entries from previous runs on this owner
    mongo.co_owners.delete_many({"owner_id": STATE["owner_id"], "email": {"$regex": "iter44.*@example.com"}})
    mongo.co_owner_links.delete_many({"owner_id": STATE["owner_id"]})
    yield


# ============ POST /api/co-owners validation ============

class TestInviteValidation:
    def test_co_owner_with_project_ids_scoped(self, owner, projects, pre_cleanup):
        pid = projects[0]
        email = f"iter44-co-a-{TAG}@example.com"
        r = owner.post(f"{API}/co-owners", json={"email": email, "role": "co_owner", "project_ids": [pid]})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["role"] == "co_owner"
        assert d["project_ids"] == [pid]
        assert d["project_names"] == [STATE["pnames"][pid]]
        assert d["money_access"] is True
        RUN["co_owners"].append(d["id"])
        STATE["co_a_id"] = d["id"]
        STATE["co_a_email"] = email

    def test_manager_without_project_ids_400(self, owner, projects):
        email = f"iter44-mgr-null-{TAG}@example.com"
        r = owner.post(f"{API}/co-owners", json={"email": email, "role": "manager", "project_ids": None})
        assert r.status_code == 400, r.text
        assert "project" in r.text.lower() or "pick" in r.text.lower()

    def test_co_owner_empty_list_400(self, owner, projects):
        email = f"iter44-co-empty-{TAG}@example.com"
        r = owner.post(f"{API}/co-owners", json={"email": email, "role": "co_owner", "project_ids": []})
        assert r.status_code == 400, r.text

    def test_legacy_no_role_null_pids_is_co_owner_all(self, owner, projects):
        email = f"iter44-legacy-co-{TAG}@example.com"
        r = owner.post(f"{API}/co-owners", json={"email": email, "project_ids": None})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["role"] == "co_owner"
        assert d["project_ids"] is None
        assert d["project_names"] is None
        assert d["money_access"] is True
        RUN["co_owners"].append(d["id"])
        STATE["legacy_co_id"] = d["id"]

    def test_legacy_no_role_with_pids_is_manager(self, owner, projects):
        email = f"iter44-legacy-mgr-{TAG}@example.com"
        pid = projects[0]
        r = owner.post(f"{API}/co-owners", json={"email": email, "project_ids": [pid], "money_access": False})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["role"] == "manager"
        assert d["project_ids"] == [pid]
        assert d["money_access"] is False
        RUN["co_owners"].append(d["id"])


# ============ PUT /api/co-owners/{id} switching ============

class TestScopeSwitching:
    def test_switch_co_owner_chosen_to_all(self, owner):
        cid = STATE["co_a_id"]
        r = owner.put(f"{API}/co-owners/{cid}", json={"role": "co_owner", "project_ids": None, "money_access": True})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["role"] == "co_owner"
        assert d["project_ids"] is None
        assert d["money_access"] is True

    def test_switch_to_manager(self, owner, projects):
        cid = STATE["co_a_id"]
        pid = projects[0]
        r = owner.put(f"{API}/co-owners/{cid}", json={"role": "manager", "project_ids": [pid], "money_access": False})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["role"] == "manager"
        assert d["project_ids"] == [pid]
        assert d["money_access"] is False

    def test_switch_back_to_co_owner_chosen(self, owner, projects):
        cid = STATE["co_a_id"]
        pid = projects[0]
        r = owner.put(f"{API}/co-owners/{cid}", json={"role": "co_owner", "project_ids": [pid], "money_access": False})
        # money_access must be forced True for co_owner
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["role"] == "co_owner"
        assert d["project_ids"] == [pid]
        assert d["money_access"] is True, "co_owner must always have money_access=True"


# ============ Invite link + accept flow (another registered user) ============

@pytest.fixture(scope="module")
def second_user(mongo):
    """Register a brand-new user to accept the invite link."""
    s = requests.Session()
    email = f"iter44-joiner-{TAG}@example.com"
    name = f"TEST Joiner {TAG}"
    r = s.post(f"{API}/auth/register", json={"name": name, "email": email, "password": "demo1234"})
    assert r.status_code == 200, r.text
    j = r.json()
    s.headers["Authorization"] = f"Bearer {j.get('access_token') or j.get('token')}"
    STATE["joiner_email"] = email
    RUN["second_users"].append(email)
    return s


class TestInviteLinkCoOwnerScoped:
    def test_create_link_co_owner_scoped(self, owner, projects):
        pid = projects[0]
        r = owner.post(f"{API}/co-owner-links", json={"role": "co_owner", "project_ids": [pid], "money_access": True})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["role"] == "co_owner"
        assert d["project_ids"] == [pid]
        assert d["project_names"] == [STATE["pnames"][pid]]
        STATE["link_token"] = d["token"]
        STATE["link_id"] = d["id"]
        RUN["links"].append(d["id"])

    def test_public_join_info(self):
        r = requests.get(f"{API}/join/{STATE['link_token']}")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["role"] == "co_owner"
        assert d["project_names"] == [STATE["pnames"][STATE["pids"][0]]]
        assert d["money_access"] is True
        assert "owner_name" in d

    def test_accept_link_creates_co_owner_doc(self, second_user, mongo):
        r = second_user.post(f"{API}/join/{STATE['link_token']}")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        # Validate DB
        doc = mongo.co_owners.find_one({"owner_id": STATE["owner_id"], "email": STATE["joiner_email"]})
        assert doc is not None, "co_owner doc missing after accept"
        assert doc["role"] == "co_owner"
        assert doc["project_ids"] == [STATE["pids"][0]]
        assert doc.get("money_access", True) is True

    def test_joiner_sees_only_scoped_projects(self, second_user, projects):
        r = second_user.get(f"{API}/projects")
        assert r.status_code == 200, r.text
        pjs = r.json()
        shared = [p for p in pjs if p.get("shared")]
        # Must see exactly the one scoped project from the demo owner (plus any own seeded projects of their own)
        shared_pids = {p["id"] for p in shared}
        assert projects[0] in shared_pids, f"scoped project {projects[0]} missing from joiner's /projects; got {shared_pids}"
        # Should NOT include the other owner's project if there are 2
        if len(projects) >= 2:
            assert projects[1] not in shared_pids, "joiner should not see owner projects outside the chosen scope"

    def test_shared_with_me_role(self, second_user):
        r = second_user.get(f"{API}/co-owners/shared-with-me")
        assert r.status_code == 200, r.text
        rows = r.json()
        row = next((x for x in rows if x["owner_id"] == STATE["owner_id"]), None)
        assert row is not None, "shared-with-me missing demo owner"
        assert row["role"] == "co_owner"
        assert row["money_access"] is True
        assert row["projects"] == 1, f"expected 1 shared project, got {row['projects']}"


# ============ Cleanup ============

def test_zzz_cleanup(mongo, owner):
    # Remove all co_owners we created
    mongo.co_owners.delete_many({"owner_id": STATE["owner_id"], "email": {"$regex": f".*{TAG}.*"}})
    mongo.co_owner_links.delete_many({"owner_id": STATE["owner_id"]})
    # Delete the second user and their data
    for em in RUN["second_users"]:
        u = mongo.users.find_one({"email": em})
        if u:
            uid = str(u["_id"])
            mongo.projects.delete_many({"user_id": uid})
            mongo.co_owners.delete_many({"email": em})
            mongo.users.delete_one({"_id": u["_id"]})
    # Clean the extra demo project if we created one
    if STATE.get("created_pid"):
        try:
            owner.delete(f"{API}/projects/{STATE['created_pid']}")
        except Exception:
            pass
    assert True
