"""Iteration 35 backend tests – Co-owners & managers scoped access.

NOTE: Must be run sequentially (not xdist). State flows across test classes.
    pytest backend/tests/test_iteration35.py -v -o "addopts=" --tb=short

Covers:
1. POST /api/co-owners validation: empty list -> 400, bad pid -> 404, roles returned, email_sent.
2. PUT /api/co-owners/{id} scope changes (null = co-owner), GET /api/co-owners returns
   role/project_names, GET /api/co-owners/shared-with-me returns role and correct project count.
3. Manager access control: TEST invitee can only see / activate / edit the picked project,
   portfolio endpoints exclude non-allowed, scope change auto-switches, removal falls back.
"""
import os
import uuid
import time
from typing import Any, Dict, List, Optional

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


# ----------------------- shared fixtures -----------------------
@pytest.fixture(scope="module")
def owner_tok() -> str:
    return _login(OWNER_EMAIL, OWNER_PASS)


@pytest.fixture(scope="module")
def owner_projects(owner_tok) -> Dict[str, Any]:
    """Make sure the owner has exactly two projects for scope testing.
    Returns {A: pid, B: pid, created_B: bool} with the original project left active at the end."""
    pr = requests.get(f"{API}/projects", headers=_h(owner_tok)).json()
    own = [p for p in pr if not p.get("shared")]
    assert own, "owner must have at least one project"
    a_pid = own[0]["id"]
    created_b = False
    if len(own) >= 2:
        b_pid = own[1]["id"]
    else:
        r = requests.post(f"{API}/projects", headers=_h(owner_tok),
                          json={"name": f"TEST_iter35_Scope_{uuid.uuid4().hex[:6]}", "address": "9 Test Lane"})
        assert r.status_code == 200, r.text
        b_pid = r.json()["id"]
        created_b = True
    # Re-activate A so demo project remains the one the owner is working on
    requests.post(f"{API}/projects/{a_pid}/activate", headers=_h(owner_tok))
    yield {"A": a_pid, "B": b_pid, "created_B": created_b}
    # Teardown: activate A, delete B if we created it
    requests.post(f"{API}/projects/{a_pid}/activate", headers=_h(owner_tok))
    if created_b:
        requests.delete(f"{API}/projects/{b_pid}", headers=_h(owner_tok))


@pytest.fixture(scope="module")
def invitee() -> Dict[str, str]:
    email = f"test_iter35_{uuid.uuid4().hex[:8]}@example.com"
    password = "TestPass123!"
    name = "TEST_iter35 Invitee"
    tok = _register(email, password, name)
    yield {"email": email, "password": password, "name": name, "token": tok}
    # cleanup user + any co_owner docs
    u = _db.users.find_one({"email": email})
    if u:
        uid = str(u["_id"])
        # own data cleanup across common collections
        for coll in ("projects", "line_items", "contacts", "receipts", "milestones", "snags",
                     "shopping_items", "documents", "doc_folders", "quote_requests", "stage_payments",
                     "snag_links", "tenancies", "rent_payments", "rental_expenses", "rent_statements",
                     "compare_links", "portal_members", "project_activity", "co_owners"):
            try:
                _db[coll].delete_many({"user_id": uid})
            except Exception:
                pass
        _db.co_owners.delete_many({"email": email})
        _db.users.delete_one({"_id": u["_id"]})


# ===== 1. Invite / PUT scope / list / shared-with-me =====
class TestInviteAndScope:
    def test_invite_empty_list_400(self, owner_tok, invitee):
        r = requests.post(f"{API}/co-owners", headers=_h(owner_tok),
                          json={"email": invitee["email"], "project_ids": []})
        assert r.status_code == 400, r.text
        assert "at least one project" in r.text.lower()

    def test_invite_bad_project_404(self, owner_tok, invitee):
        r = requests.post(f"{API}/co-owners", headers=_h(owner_tok),
                          json={"email": invitee["email"], "project_ids": ["000000000000000000000000"]})
        assert r.status_code == 404, r.text

    def test_invite_project_not_owned_404(self, owner_tok, invitee):
        # Create a TEST owner with a project; try to invite scoped to that project from demo owner.
        other_email = f"test_iter35_other_{uuid.uuid4().hex[:6]}@example.com"
        other_tok = _register(other_email, "OtherPass123!", "TEST_iter35 Other Owner")
        try:
            others = requests.get(f"{API}/projects", headers=_h(other_tok)).json()
            other_pid = others[0]["id"]
            r = requests.post(f"{API}/co-owners", headers=_h(owner_tok),
                              json={"email": invitee["email"], "project_ids": [other_pid]})
            assert r.status_code == 404, r.text
        finally:
            u = _db.users.find_one({"email": other_email})
            if u:
                oid = str(u["_id"])
                for coll in ("projects", "line_items", "milestones", "co_owners"):
                    try:
                        _db[coll].delete_many({"user_id": oid})
                    except Exception:
                        pass
                _db.co_owners.delete_many({"email": other_email})
                _db.users.delete_one({"_id": u["_id"]})

    def test_invite_as_manager_single_project_ok(self, owner_tok, invitee, owner_projects):
        pid_a = owner_projects["A"]
        r = requests.post(f"{API}/co-owners", headers=_h(owner_tok),
                          json={"email": invitee["email"], "project_ids": [pid_a]})
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["role"] == "manager"
        assert b["project_ids"] == [pid_a]
        assert isinstance(b["project_names"], list) and len(b["project_names"]) == 1
        assert "email_sent" in b
        # Persisted
        got = requests.get(f"{API}/co-owners", headers=_h(owner_tok)).json()
        row = next((x for x in got if x["email"] == invitee["email"]), None)
        assert row and row["role"] == "manager"
        assert row["project_ids"] == [pid_a]
        assert row["project_names"]

    def test_invitee_shared_with_me_role_and_count(self, invitee, owner_projects):
        tok = _login(invitee["email"], invitee["password"])
        r = requests.get(f"{API}/co-owners/shared-with-me", headers=_h(tok)).json()
        assert len(r) == 1
        row = r[0]
        assert row["role"] == "manager"
        assert row["projects"] == 1  # only A

    def test_duplicate_invite_400(self, owner_tok, invitee, owner_projects):
        r = requests.post(f"{API}/co-owners", headers=_h(owner_tok),
                          json={"email": invitee["email"], "project_ids": [owner_projects["A"]]})
        assert r.status_code == 400, r.text

    def test_put_scope_change_to_B_then_upgrade_full(self, owner_tok, invitee, owner_projects):
        got = requests.get(f"{API}/co-owners", headers=_h(owner_tok)).json()
        row = next(x for x in got if x["email"] == invitee["email"])
        cid = row["id"]
        pid_b = owner_projects["B"]
        # scope to B
        r = requests.put(f"{API}/co-owners/{cid}", headers=_h(owner_tok), json={"project_ids": [pid_b]})
        assert r.status_code == 200, r.text
        assert r.json()["project_ids"] == [pid_b]
        assert r.json()["role"] == "manager"

        # shared-with-me reflects count=1 and still manager
        inv_tok = _login(invitee["email"], invitee["password"])
        s = requests.get(f"{API}/co-owners/shared-with-me", headers=_h(inv_tok)).json()
        assert s[0]["projects"] == 1 and s[0]["role"] == "manager"

        # upgrade to full co-owner (null)
        r = requests.put(f"{API}/co-owners/{cid}", headers=_h(owner_tok), json={"project_ids": None})
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "co_owner"
        assert r.json()["project_ids"] is None

        s = requests.get(f"{API}/co-owners/shared-with-me", headers=_h(inv_tok)).json()
        assert s[0]["role"] == "co_owner"
        assert s[0]["projects"] == 2  # both A and B

        # revert to manager-A for later tests
        r = requests.put(f"{API}/co-owners/{cid}", headers=_h(owner_tok),
                         json={"project_ids": [owner_projects["A"]]})
        assert r.status_code == 200


# ===== 2. Manager access control on data routes =====
class TestManagerAccess:
    def _inv_tok(self, invitee):
        return _login(invitee["email"], invitee["password"])

    def test_projects_list_shows_only_A_as_shared(self, invitee, owner_projects):
        tok = self._inv_tok(invitee)
        projs = requests.get(f"{API}/projects", headers=_h(tok)).json()
        shared = [p for p in projs if p.get("shared")]
        assert len(shared) == 1, [p["name"] for p in shared]
        assert shared[0]["id"] == owner_projects["A"]
        # Also includes invitee's own project(s)
        assert any(not p.get("shared") for p in projs)

    def test_cannot_activate_B(self, invitee, owner_projects):
        tok = self._inv_tok(invitee)
        r = requests.post(f"{API}/projects/{owner_projects['B']}/activate", headers=_h(tok))
        assert r.status_code == 404, r.text

    def test_activate_A_and_data_routes(self, invitee, owner_projects):
        tok = self._inv_tok(invitee)
        pid_a = owner_projects["A"]
        r = requests.post(f"{API}/projects/{pid_a}/activate", headers=_h(tok))
        assert r.status_code == 200, r.text
        assert r.json()["id"] == pid_a

        # /api/project reflects A
        pr = requests.get(f"{API}/project", headers=_h(tok))
        assert pr.status_code == 200
        assert pr.json()["id"] == pid_a

        # Data routes work on A
        li = requests.get(f"{API}/line-items", headers=_h(tok))
        assert li.status_code == 200, li.text
        assert isinstance(li.json(), list)

        rt = requests.get(f"{API}/rentals", headers=_h(tok))
        assert rt.status_code == 200, rt.text

    def test_portfolio_map_and_rent_roll_scoped(self, invitee, owner_projects, owner_tok):
        tok = self._inv_tok(invitee)
        pid_a, pid_b = owner_projects["A"], owner_projects["B"]
        m = requests.get(f"{API}/portfolio/map", headers=_h(tok)).json()
        shared_ids = [x["id"] for x in m if x["id"] in (pid_a, pid_b)]
        assert pid_a in shared_ids
        assert pid_b not in shared_ids, "manager should not see B in portfolio map"

        rr = requests.get(f"{API}/portfolio/rent-roll", headers=_h(tok)).json()
        rr_ids = [p["id"] for p in rr["properties"]]
        assert pid_b not in rr_ids

    def test_scope_change_auto_switches_active(self, owner_tok, invitee, owner_projects):
        tok = self._inv_tok(invitee)
        # Invitee is active on A right now. Change scope to B-only.
        got = requests.get(f"{API}/co-owners", headers=_h(owner_tok)).json()
        row = next(x for x in got if x["email"] == invitee["email"])
        cid = row["id"]
        pid_b = owner_projects["B"]
        r = requests.put(f"{API}/co-owners/{cid}", headers=_h(owner_tok), json={"project_ids": [pid_b]})
        assert r.status_code == 200

        # GET /api/project must now be B
        pr = requests.get(f"{API}/project", headers=_h(tok))
        assert pr.status_code == 200, pr.text
        assert pr.json()["id"] == pid_b, pr.json()

        # Projects list: only B as shared
        projs = requests.get(f"{API}/projects", headers=_h(tok)).json()
        shared = [p for p in projs if p.get("shared")]
        assert len(shared) == 1
        assert shared[0]["id"] == pid_b

    def test_removal_falls_back_to_own_projects(self, owner_tok, invitee):
        tok = self._inv_tok(invitee)
        got = requests.get(f"{API}/co-owners", headers=_h(owner_tok)).json()
        row = next((x for x in got if x["email"] == invitee["email"]), None)
        assert row
        r = requests.delete(f"{API}/co-owners/{row['id']}", headers=_h(owner_tok))
        assert r.status_code == 200

        # /api/project now returns invitee's own project
        pr = requests.get(f"{API}/project", headers=_h(tok))
        assert pr.status_code == 200, pr.text
        own = requests.get(f"{API}/projects", headers=_h(tok)).json()
        assert not any(p.get("shared") for p in own)
        assert pr.json()["id"] in [p["id"] for p in own if not p.get("shared")]


# ===== 3. Full co-owner (null) still sees all owner projects =====
class TestFullCoOwner:
    def test_full_co_owner_sees_all(self, owner_tok, invitee, owner_projects):
        # Invite again as full co-owner (null)
        r = requests.post(f"{API}/co-owners", headers=_h(owner_tok),
                          json={"email": invitee["email"], "project_ids": None})
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "co_owner"
        tok = _login(invitee["email"], invitee["password"])
        projs = requests.get(f"{API}/projects", headers=_h(tok)).json()
        shared = [p for p in projs if p.get("shared")]
        shared_ids = [p["id"] for p in shared]
        assert owner_projects["A"] in shared_ids
        assert owner_projects["B"] in shared_ids

        # shared-with-me reports project count = 2
        s = requests.get(f"{API}/co-owners/shared-with-me", headers=_h(tok)).json()
        assert s[0]["role"] == "co_owner"
        assert s[0]["projects"] >= 2

        # Cleanup: owner removes
        got = requests.get(f"{API}/co-owners", headers=_h(owner_tok)).json()
        row = next(x for x in got if x["email"] == invitee["email"])
        requests.delete(f"{API}/co-owners/{row['id']}", headers=_h(owner_tok))


# ===== Final teardown safety =====
def test_zz_cleanup_demo_active(owner_tok):
    """Make sure demo owner's original project is active at the end."""
    pr = requests.get(f"{API}/projects", headers=_h(owner_tok)).json()
    own = [p for p in pr if not p.get("shared")]
    # pick the first (non-TEST_) if possible
    original = next((p for p in own if not p["name"].startswith("TEST_")), own[0])
    r = requests.post(f"{API}/projects/{original['id']}/activate", headers=_h(owner_tok))
    assert r.status_code == 200
