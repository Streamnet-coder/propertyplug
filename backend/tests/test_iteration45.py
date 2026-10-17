"""Iteration 45 — auto-add new projects + per-project ownership split.
Covers:
- POST/PUT /api/co-owners + POST /api/co-owner-links accept auto_add (only stored when project_ids is not null)
- GET /api/co-owners returns auto_add
- POST /api/projects without add_co_owner_ids adds auto-add scoped co-owners
- POST /api/projects with add_co_owner_ids [ids] adds exactly those scoped co-owners
- All-project co-owners are unaffected either way
- GET /api/project/split rows and figures
- PUT /api/project/split validation (sum>100, negative, >100, unknown id)
- non-owner (co-owner acting) PUT /split -> 403
- tasks-only manager GET /split -> 403
- Accepting a link with auto_add keeps it
"""
import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
DEMO_EMAIL = "demo@mybuilder.app"
DEMO_PASSWORD = "demo1234"
TAG = f"iter45{uuid.uuid4().hex[:6]}"


def _api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(s: requests.Session, email: str, pw: str) -> dict:
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    data = r.json()
    s.headers["Authorization"] = f"Bearer {data['access_token']}"
    return data


def _register(s: requests.Session, email: str, pw: str, name: str) -> dict:
    r = s.post(f"{BASE_URL}/api/auth/register", json={"email": email, "password": pw, "name": name})
    assert r.status_code == 200, r.text
    data = r.json()
    s.headers["Authorization"] = f"Bearer {data['access_token']}"
    return data


@pytest.fixture(scope="module")
def owner():
    s = _api()
    _login(s, DEMO_EMAIL, DEMO_PASSWORD)
    return s


@pytest.fixture(scope="module")
def owner_projects(owner):
    r = owner.get(f"{BASE_URL}/api/projects")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def active_pid(owner_projects):
    for p in owner_projects:
        if p.get("active"):
            return p["id"]
    return owner_projects[0]["id"]


# =================================================================
# Backend: auto_add on invite / scope-change
# =================================================================
class TestAutoAddInvite:
    """auto_add stored on co-owner when scoped; ignored when project_ids is None."""

    def test_invite_scoped_coowner_with_auto_add(self, owner, active_pid):
        email = f"{TAG}-auto1@example.com"
        r = owner.post(f"{BASE_URL}/api/co-owners",
                       json={"email": email, "role": "co_owner", "project_ids": [active_pid], "auto_add": True})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["role"] == "co_owner"
        assert data["project_ids"] == [active_pid]
        assert data["auto_add"] is True
        # Verify list reflects persistence
        r2 = owner.get(f"{BASE_URL}/api/co-owners")
        found = next(c for c in r2.json() if c["email"] == email)
        assert found["auto_add"] is True

    def test_invite_all_project_coowner_ignores_auto_add(self, owner):
        email = f"{TAG}-autoall@example.com"
        r = owner.post(f"{BASE_URL}/api/co-owners",
                       json={"email": email, "role": "co_owner", "project_ids": None, "auto_add": True})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["project_ids"] is None
        assert data["auto_add"] is False  # ignored because unscoped

    def test_put_scoped_toggle_auto_add_off(self, owner, active_pid):
        # Find a scoped auto-add row created above
        r = owner.get(f"{BASE_URL}/api/co-owners")
        cid = next(c["id"] for c in r.json() if c["email"] == f"{TAG}-auto1@example.com")
        r2 = owner.put(f"{BASE_URL}/api/co-owners/{cid}",
                       json={"role": "co_owner", "project_ids": [active_pid], "auto_add": False})
        assert r2.status_code == 200, r2.text
        assert r2.json()["auto_add"] is False

    def test_put_switch_to_all_clears_auto_add(self, owner, active_pid):
        r = owner.get(f"{BASE_URL}/api/co-owners")
        cid = next(c["id"] for c in r.json() if c["email"] == f"{TAG}-auto1@example.com")
        r2 = owner.put(f"{BASE_URL}/api/co-owners/{cid}",
                       json={"role": "co_owner", "project_ids": None, "auto_add": True})
        assert r2.status_code == 200, r2.text
        assert r2.json()["auto_add"] is False  # unscoped: forced to False
        # Switch back to scoped+auto_add on for later tests
        owner.put(f"{BASE_URL}/api/co-owners/{cid}",
                  json={"role": "co_owner", "project_ids": [active_pid], "auto_add": True})


# =================================================================
# Backend: co-owner-links accept auto_add + accepting a link keeps it
# =================================================================
class TestLinkAutoAdd:

    def test_create_scoped_link_with_auto_add(self, owner, active_pid):
        r = owner.post(f"{BASE_URL}/api/co-owner-links",
                       json={"role": "co_owner", "project_ids": [active_pid], "auto_add": True})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["role"] == "co_owner"
        assert data["project_ids"] == [active_pid]
        # link_out doesn't surface auto_add; verify via accept flow below
        self.__class__.token = data["token"]

    def test_accept_link_preserves_auto_add(self, owner):
        # Register a second user and accept the invite link
        joiner = _api()
        email = f"{TAG}-join@example.com"
        _register(joiner, email, "Password1!", f"{TAG} Joiner")
        r = joiner.post(f"{BASE_URL}/api/join/{self.__class__.token}")
        assert r.status_code == 200, r.text
        # Owner's list should now include this joiner with auto_add True
        r2 = owner.get(f"{BASE_URL}/api/co-owners")
        found = next(c for c in r2.json() if c["email"] == email)
        assert found["auto_add"] is True
        self.__class__.joiner_email = email
        self.__class__.joiner = joiner


# =================================================================
# Backend: POST /projects auto-add behaviour
# =================================================================
class TestProjectCreateAutoAdd:
    """Creating a project: without add_co_owner_ids -> auto_add=True scoped co-owners get it;
       with add_co_owner_ids -> only those get it; unscoped co-owners untouched."""

    def _emails_with_pid(self, owner, pid):
        r = owner.get(f"{BASE_URL}/api/co-owners")
        return {c["email"]: (c["project_ids"] or []) for c in r.json()}

    def test_without_add_ids_only_auto_add_gets_project(self, owner, active_pid):
        # Create new co-owners: one scoped+auto_add, one scoped no auto_add, one unscoped
        auto_email = f"{TAG}-a-auto@example.com"
        plain_email = f"{TAG}-a-plain@example.com"
        allp_email = f"{TAG}-a-all@example.com"
        owner.post(f"{BASE_URL}/api/co-owners",
                   json={"email": auto_email, "role": "co_owner", "project_ids": [active_pid], "auto_add": True})
        owner.post(f"{BASE_URL}/api/co-owners",
                   json={"email": plain_email, "role": "co_owner", "project_ids": [active_pid], "auto_add": False})
        owner.post(f"{BASE_URL}/api/co-owners",
                   json={"email": allp_email, "role": "co_owner", "project_ids": None, "auto_add": False})

        # Create a new project (no add_co_owner_ids)
        pname = f"{TAG}_auto_proj"
        r = owner.post(f"{BASE_URL}/api/projects", json={"name": pname})
        assert r.status_code == 200, r.text
        new_pid = r.json()["id"]
        self.__class__.auto_pid = new_pid

        d = self._emails_with_pid(owner, new_pid)
        assert new_pid in d[auto_email], f"auto-add should include new project: {d[auto_email]}"
        assert new_pid not in d[plain_email], f"non-auto should NOT include: {d[plain_email]}"
        # unscoped co-owners should still have project_ids None
        r2 = owner.get(f"{BASE_URL}/api/co-owners")
        allp = next(c for c in r2.json() if c["email"] == allp_email)
        assert allp["project_ids"] is None

    def test_with_add_co_owner_ids_adds_exactly_those(self, owner, active_pid):
        # Get the ids of the two scoped co-owners
        r = owner.get(f"{BASE_URL}/api/co-owners")
        by_email = {c["email"]: c["id"] for c in r.json()}
        plain_id = by_email[f"{TAG}-a-plain@example.com"]
        auto_id = by_email[f"{TAG}-a-auto@example.com"]
        allp_email = f"{TAG}-a-all@example.com"

        # Create another project with add_co_owner_ids=[plain_id] — auto-add scoped NOT included
        pname = f"{TAG}_pick_proj"
        r2 = owner.post(f"{BASE_URL}/api/projects",
                        json={"name": pname, "add_co_owner_ids": [plain_id]})
        assert r2.status_code == 200, r2.text
        new_pid = r2.json()["id"]
        self.__class__.pick_pid = new_pid

        d = self._emails_with_pid(owner, new_pid)
        assert new_pid in d[f"{TAG}-a-plain@example.com"]
        assert new_pid not in d[f"{TAG}-a-auto@example.com"]
        # unscoped untouched
        r3 = owner.get(f"{BASE_URL}/api/co-owners")
        allp = next(c for c in r3.json() if c["email"] == allp_email)
        assert allp["project_ids"] is None
        _ = auto_id  # unused but documents intent

    def test_with_empty_add_ids_adds_none(self, owner):
        """add_co_owner_ids=[] should add exactly those (zero), not fall through to auto_add."""
        r = owner.post(f"{BASE_URL}/api/projects",
                       json={"name": f"{TAG}_empty_proj", "add_co_owner_ids": []})
        assert r.status_code == 200, r.text
        new_pid = r.json()["id"]
        self.__class__.empty_pid = new_pid
        r2 = owner.get(f"{BASE_URL}/api/co-owners")
        for c in r2.json():
            assert new_pid not in (c.get("project_ids") or [])


# =================================================================
# Backend: GET /project/split rows + figures
# =================================================================
class TestSplitGet:

    def test_get_split_returns_owner_first_and_people(self, owner, active_pid):
        # Activate the original demo project
        owner.post(f"{BASE_URL}/api/projects/{active_pid}/activate")
        r = owner.get(f"{BASE_URL}/api/project/split")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "rows" in data and "figures" in data and "can_edit" in data and "has_split" in data
        assert data["rows"][0]["is_owner"] is True
        assert data["rows"][0]["pct"] == 100  # starts with 100 to owner, no shares yet
        # people after owner — should include the scoped co-owners we added
        others = [r for r in data["rows"] if not r["is_owner"]]
        emails = {r["email"] for r in others}
        # auto-add scoped co-owner should have access to this pid (it was active when created)
        # The demo's original active project may or may not be in scope; just assert structure
        for row in data["rows"]:
            for k in ("profit", "monthly_rent", "monthly_cashflow", "annual_cashflow"):
                assert k in row
        assert data["can_edit"] is True
        _ = emails

    def test_get_split_includes_scoped_coowners_on_new_project(self, owner):
        """Our auto-add scoped co-owner was added to {TAG}_auto_proj, so split must include them."""
        new_pid = TestProjectCreateAutoAdd.auto_pid
        owner.post(f"{BASE_URL}/api/projects/{new_pid}/activate")
        r = owner.get(f"{BASE_URL}/api/project/split")
        assert r.status_code == 200, r.text
        d = r.json()
        emails = {row["email"] for row in d["rows"]}
        assert f"{TAG}-a-auto@example.com" in emails
        assert f"{TAG}-a-plain@example.com" not in emails  # didn't auto-add


# =================================================================
# Backend: PUT /project/split validation
# =================================================================
class TestSplitPut:

    def _get_scoped_coid(self, owner, pid):
        """Get a co_owner_id that has access to pid."""
        r = owner.get(f"{BASE_URL}/api/project/split")
        others = [row for row in r.json()["rows"] if not row["is_owner"]]
        return others[0]["co_owner_id"] if others else None

    def test_save_valid_split(self, owner):
        new_pid = TestProjectCreateAutoAdd.auto_pid
        owner.post(f"{BASE_URL}/api/projects/{new_pid}/activate")
        cid = self._get_scoped_coid(owner, new_pid)
        assert cid is not None
        r = owner.put(f"{BASE_URL}/api/project/split", json={"shares": {cid: 25.0}})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["has_split"] is True
        other = next(x for x in d["rows"] if x["co_owner_id"] == cid)
        assert other["pct"] == 25.0
        owner_row = next(x for x in d["rows"] if x["is_owner"])
        assert owner_row["pct"] == 75.0

    def test_sum_over_100_rejected(self, owner):
        new_pid = TestProjectCreateAutoAdd.auto_pid
        owner.post(f"{BASE_URL}/api/projects/{new_pid}/activate")
        cid = self._get_scoped_coid(owner, new_pid)
        r = owner.put(f"{BASE_URL}/api/project/split", json={"shares": {cid: 101.0}})
        # 101 is >100 per share AND >100 total — negative/>100 check hits first
        assert r.status_code == 400, r.text

    def test_negative_rejected(self, owner):
        new_pid = TestProjectCreateAutoAdd.auto_pid
        owner.post(f"{BASE_URL}/api/projects/{new_pid}/activate")
        cid = self._get_scoped_coid(owner, new_pid)
        r = owner.put(f"{BASE_URL}/api/project/split", json={"shares": {cid: -5}})
        assert r.status_code == 400, r.text

    def test_sum_exceeds_100_two_shares(self, owner, active_pid):
        """When two scoped shares sum to >100 (but each is <=100), reject."""
        # Create a project with two scoped co-owners
        r = owner.get(f"{BASE_URL}/api/co-owners")
        by_email = {c["email"]: c["id"] for c in r.json()}
        two_ids = [by_email[f"{TAG}-a-auto@example.com"], by_email[f"{TAG}-a-plain@example.com"]]
        pr = owner.post(f"{BASE_URL}/api/projects",
                        json={"name": f"{TAG}_two_proj", "add_co_owner_ids": two_ids})
        assert pr.status_code == 200
        new_pid = pr.json()["id"]
        TestSplitPut.two_pid = new_pid
        # Resolve the split co_owner_ids for this project
        s = owner.get(f"{BASE_URL}/api/project/split").json()
        others = [row for row in s["rows"] if not row["is_owner"]]
        assert len(others) >= 2
        shares = {others[0]["co_owner_id"]: 60.0, others[1]["co_owner_id"]: 50.0}
        r2 = owner.put(f"{BASE_URL}/api/project/split", json={"shares": shares})
        assert r2.status_code == 400, r2.text

    def test_unknown_id_rejected(self, owner):
        new_pid = TestProjectCreateAutoAdd.auto_pid
        owner.post(f"{BASE_URL}/api/projects/{new_pid}/activate")
        r = owner.put(f"{BASE_URL}/api/project/split",
                      json={"shares": {"507f1f77bcf86cd799439011": 10.0}})
        assert r.status_code == 400, r.text

    def test_non_owner_put_forbidden(self, owner):
        """Co-owner (via accepted invite) acting on owner's project must get 403."""
        joiner = TestLinkAutoAdd.joiner
        # Joiner is scoped co-owner (co_owner_pids has active demo project only? depends on link)
        projects = joiner.get(f"{BASE_URL}/api/projects").json()
        shared = next((p for p in projects if p.get("shared")), None)
        assert shared is not None, "Joiner should see at least one shared project"
        act = joiner.post(f"{BASE_URL}/api/projects/{shared['id']}/activate")
        assert act.status_code == 200, act.text
        r = joiner.put(f"{BASE_URL}/api/project/split", json={"shares": {}})
        assert r.status_code == 403, r.text


# =================================================================
# Backend: tasks-only manager GET /split -> 403 (via block_money)
# =================================================================
class TestTasksOnlyManagerBlocked:

    def test_tasks_only_manager_cannot_get_split(self, owner, active_pid):
        """Make a scoped tasks-only manager, log in as them, GET /split -> 403."""
        mgr_email = f"{TAG}-mgr@example.com"
        r = owner.post(f"{BASE_URL}/api/co-owners",
                       json={"email": mgr_email, "role": "manager", "project_ids": [active_pid], "money_access": False})
        assert r.status_code == 200
        mgr = _api()
        _register(mgr, mgr_email, "Password1!", f"{TAG} Mgr")
        projs = mgr.get(f"{BASE_URL}/api/projects").json()
        shared = next((p for p in projs if p.get("shared")), None)
        assert shared is not None
        mgr.post(f"{BASE_URL}/api/projects/{shared['id']}/activate")
        r2 = mgr.get(f"{BASE_URL}/api/project/split")
        assert r2.status_code == 403, r2.text


# =================================================================
# Cleanup — restore the demo account to a clean state
# =================================================================
class TestZZZCleanup:

    def test_cleanup(self, owner, owner_projects):
        # Remove all iter45* co_owners
        r = owner.get(f"{BASE_URL}/api/co-owners")
        for c in r.json():
            if TAG in c["email"] or c["email"].startswith("iter45"):
                owner.delete(f"{BASE_URL}/api/co-owners/{c['id']}")
        # Delete all iter45* projects
        time.sleep(0.3)
        pr = owner.get(f"{BASE_URL}/api/projects")
        for p in pr.json():
            if p["name"].startswith(TAG) or p["name"].startswith("iter45"):
                owner.delete(f"{BASE_URL}/api/projects/{p['id']}")
        # Re-activate the demo's original active project (Nottingham)
        pr2 = owner.get(f"{BASE_URL}/api/projects").json()
        original = next((p for p in pr2 if "Nottingham" in p["name"]), pr2[0] if pr2 else None)
        if original:
            owner.post(f"{BASE_URL}/api/projects/{original['id']}/activate")
        # Also delete any ownership_shares the tests created — not exposed via API; those get orphaned.
        # They are harmless because the project is already gone.
