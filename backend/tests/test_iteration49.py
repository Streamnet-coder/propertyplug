"""Iteration 49 – PropertyPlug: project cover, saved AI estimates, invited-user flow, co-owner privacy."""
import io
import os
import time
import uuid
import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://dev-budget-tracker-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"
DEMO_EMAIL = "demo@mybuilder.app"
DEMO_PASS = "demo1234"


def _reg(name=None, email=None, pw="pass1234", invited=False):
    email = email or f"TEST_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/auth/register", json={"name": name or "Tester", "email": email, "password": pw, "invited": invited}, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    return {"email": email, "pw": pw, "token": j["access_token"], "user": j["user"]}


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=20)
    assert r.status_code == 200, r.text
    j = r.json()
    return {"email": email, "token": j["access_token"], "user": j["user"]}


def _h(u):
    return {"Authorization": f"Bearer {u['token']}"}


# --- cleanup helpers (test co-owners/users remain cleaned up by not persisting) ---

@pytest.fixture(scope="module")
def owner():
    """Demo owner session."""
    return _login(DEMO_EMAIL, DEMO_PASS)


@pytest.fixture(scope="module")
def test_image_bytes():
    # 1x1 PNG
    return bytes.fromhex("89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4890000000D4944415478DA6364F8CF000000030001015B6E2F140000000049454E44AE426082")


# ============================= A. Project cover =============================

class TestProjectCover:
    def test_upload_and_set_cover_persists(self, owner, test_image_bytes):
        # upload
        files = {"file": ("cover.png", io.BytesIO(test_image_bytes), "image/png")}
        r = requests.post(f"{API}/upload", headers=_h(owner), files=files, timeout=30)
        assert r.status_code == 200, r.text
        path = r.json()["path"]
        assert path

        # set cover
        r = requests.put(f"{API}/project/cover", headers=_h(owner), json={"storage_path": path}, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["cover_path"] == path

        # GET /api/projects reflects cover_path
        r = requests.get(f"{API}/projects", headers=_h(owner), timeout=20)
        assert r.status_code == 200
        active = [p for p in r.json() if p.get("active")]
        assert active, "no active project"
        assert active[0].get("cover_path") == path, active[0]

    def test_clear_cover_with_null(self, owner):
        r = requests.put(f"{API}/project/cover", headers=_h(owner), json={"storage_path": None}, timeout=20)
        assert r.status_code == 200
        assert r.json()["cover_path"] is None
        r = requests.get(f"{API}/projects", headers=_h(owner), timeout=20)
        active = [p for p in r.json() if p.get("active")][0]
        assert active.get("cover_path") in (None,)

    def test_unknown_storage_path_404(self, owner):
        r = requests.put(f"{API}/project/cover", headers=_h(owner), json={"storage_path": "pp/uploads/does/not/exist.jpg"}, timeout=20)
        assert r.status_code == 404


# ============================= B. Saved AI estimates =============================

class TestAIEstimates:
    def test_list_estimates(self, owner):
        r = requests.get(f"{API}/ai/estimates", headers=_h(owner), timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # Expect demo seeded >= 1, user mentioned "13 saved estimates"
        assert len(data) >= 1, f"expected saved demo estimates, got {len(data)}"
        est = data[0]
        for k in ("id", "description", "created_at", "total_low", "total_high", "items"):
            assert k in est, est
        return est

    def test_get_rename_delete_estimate(self, owner):
        # pick an existing one
        r = requests.get(f"{API}/ai/estimates", headers=_h(owner), timeout=20)
        estimates = r.json()
        assert estimates
        eid = estimates[0]["id"]
        orig_title = estimates[0].get("title", "")

        # GET single
        r = requests.get(f"{API}/ai/estimates/{eid}", headers=_h(owner), timeout=20)
        assert r.status_code == 200
        assert r.json()["id"] == eid

        # PUT rename
        new_title = f"TEST_renamed_{uuid.uuid4().hex[:4]}"
        r = requests.put(f"{API}/ai/estimates/{eid}", headers=_h(owner), json={"title": new_title}, timeout=20)
        assert r.status_code == 200
        assert r.json()["title"] == new_title

        # revert
        requests.put(f"{API}/ai/estimates/{eid}", headers=_h(owner), json={"title": orig_title}, timeout=20)

        # DELETE on a non-existent id should be ok=true (no raise)
        fake_eid = "507f1f77bcf86cd799439011"
        r = requests.delete(f"{API}/ai/estimates/{fake_eid}", headers=_h(owner), timeout=20)
        assert r.status_code == 200

    def test_get_estimate_not_found(self, owner):
        r = requests.get(f"{API}/ai/estimates/507f1f77bcf86cd799439011", headers=_h(owner), timeout=20)
        assert r.status_code == 404


# ============================= C1. Register with invited=true =============================

class TestInvitedRegister:
    def test_invited_register_no_demo(self):
        u = _reg(invited=True, name="TEST Invited")
        r = requests.get(f"{API}/projects", headers=_h(u), timeout=20)
        assert r.status_code == 200
        assert r.json() == [], f"invited user shouldn't get a demo project, got {r.json()}"

        # GET /api/project should 400/404 (no active project)
        r = requests.get(f"{API}/project", headers=_h(u), timeout=20)
        assert r.status_code in (400, 404), r.status_code


# ============================= C1 (part 2). Join via link lands in shared =============================

class TestJoinLinkFlow:
    def test_full_invite_link_join(self, owner):
        # owner creates invite link (co-owner, all projects)
        r = requests.post(f"{API}/co-owner-links", headers=_h(owner),
                          json={"project_ids": None, "money_access": True, "role": "co_owner"}, timeout=20)
        assert r.status_code == 200, r.text
        link = r.json()
        token = link["token"]

        # public preview works
        r = requests.get(f"{API}/join/{token}", timeout=15)
        assert r.status_code == 200, r.text
        assert "owner_name" in r.json()

        # register fresh invited user
        u = _reg(invited=True, name="TEST Joiner")

        # projects before join = []
        assert requests.get(f"{API}/projects", headers=_h(u)).json() == []

        # accept
        r = requests.post(f"{API}/join/{token}", headers=_h(u), timeout=20)
        assert r.status_code == 200, r.text

        # projects list now has the shared project, marked active + shared
        r = requests.get(f"{API}/projects", headers=_h(u), timeout=20)
        assert r.status_code == 200
        plist = r.json()
        assert len(plist) >= 1, plist
        shared = [p for p in plist if p.get("shared")]
        assert shared, f"expected shared marker on project, got {plist}"
        assert any(p.get("active") for p in plist), plist

        # /api/project returns the shared project
        r = requests.get(f"{API}/project", headers=_h(u), timeout=20)
        assert r.status_code == 200
        assert r.json().get("name"), r.json()

        # cleanup: remove the co-owner from owner side
        try:
            requests.delete(f"{API}/co-owners/shared/{owner['user']['id']}", headers=_h(u), timeout=10)
        except Exception:
            pass


# ============================= C2. Email-invited user registers normally -> no demo, lands on shared =============================

class TestEmailInviteFlow:
    def test_email_invite_then_register_lands_on_shared(self, owner):
        invite_email = f"TEST_inv_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{API}/co-owners", headers=_h(owner),
                          json={"email": invite_email, "project_ids": None, "money_access": True, "role": "co_owner"},
                          timeout=20)
        assert r.status_code == 200, r.text
        co_id = r.json()["id"]

        # Register with invited=False (normal register) - should still land on shared because email was pre-invited
        u = _reg(email=invite_email, name="TEST Email Invitee", invited=False)

        # No demo project seeded (open_shared returned True because co_owners row existed)
        r = requests.get(f"{API}/projects", headers=_h(u), timeout=20)
        assert r.status_code == 200
        plist = r.json()
        shared = [p for p in plist if p.get("shared")]
        own = [p for p in plist if not p.get("shared")]
        assert shared, f"should have at least one shared project, got {plist}"
        assert not own, f"email-invited user should NOT have own demo project, got own={own}"

        # /api/project returns the shared one
        r = requests.get(f"{API}/project", headers=_h(u), timeout=20)
        assert r.status_code == 200

        # cleanup co-owner
        requests.delete(f"{API}/co-owners/{co_id}", headers=_h(owner), timeout=10)


# ============================= C4. Co-owner privacy on split/statements/payouts =============================

class TestCoOwnerPrivacy:
    @pytest.fixture(scope="class")
    def setup_shared(self, owner):
        emails = [f"TEST_co1_{uuid.uuid4().hex[:6]}@example.com", f"TEST_co2_{uuid.uuid4().hex[:6]}@example.com"]
        users = []
        co_ids = []
        for em in emails:
            r = requests.post(f"{API}/co-owners", headers=_h(owner),
                              json={"email": em, "project_ids": None, "money_access": True, "role": "co_owner"}, timeout=20)
            assert r.status_code == 200, r.text
            co_ids.append(r.json()["id"])
            users.append(_reg(email=em, name=f"TEST Co {em[:8]}", invited=False))

        # owner sets shares: co1=30%, co2=20%
        shares = {co_ids[0]: 30, co_ids[1]: 20}
        r = requests.put(f"{API}/project/split", headers=_h(owner), json={"shares": shares, "contributions": {co_ids[0]: 10000, co_ids[1]: 5000, "owner": 50000}}, timeout=20)
        assert r.status_code == 200, r.text

        yield {"owner": owner, "users": users, "co_ids": co_ids}

        # cleanup
        requests.put(f"{API}/project/split", headers=_h(owner), json={"shares": {}, "contributions": {}}, timeout=10)
        for cid in co_ids:
            requests.delete(f"{API}/co-owners/{cid}", headers=_h(owner), timeout=10)

    def test_owner_sees_full_split(self, setup_shared):
        owner = setup_shared["owner"]
        r = requests.get(f"{API}/project/split", headers=_h(owner), timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert data["can_edit"] is True
        # owner row + 2 co-owners
        assert len(data["rows"]) == 3, data["rows"]

    def test_co_owner_sees_only_own_row(self, setup_shared):
        u = setup_shared["users"][0]
        cid0 = setup_shared["co_ids"][0]
        r = requests.get(f"{API}/project/split", headers=_h(u), timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert data["can_edit"] is False
        assert len(data["rows"]) == 1, f"co-owner must only see their own row, got {data['rows']}"
        assert data["rows"][0]["co_owner_id"] == cid0
        assert data["rows"][0]["is_owner"] is False
        assert data["rows"][0]["pct"] == 30.0

    def test_co_owner_statements_forbidden(self, setup_shared):
        u = setup_shared["users"][0]
        r = requests.get(f"{API}/project/statements", headers=_h(u), timeout=20)
        assert r.status_code == 403, r.text

    def test_co_owner_payouts_only_self(self, setup_shared):
        u0 = setup_shared["users"][0]
        cid0 = setup_shared["co_ids"][0]
        r = requests.get(f"{API}/project/payouts", headers=_h(u0), timeout=20)
        assert r.status_code == 200
        data = r.json()
        for p in data["people"]:
            assert p["co_owner_id"] == cid0, f"co-owner should only see own payout row: {data}"


# ============================= C5. Co-owner creates own project (private) =============================

class TestCoOwnerPrivateProject:
    def test_co_owner_private_project_hidden_from_owner(self, owner):
        em = f"TEST_priv_{uuid.uuid4().hex[:6]}@example.com"
        r = requests.post(f"{API}/co-owners", headers=_h(owner),
                          json={"email": em, "project_ids": None, "money_access": True, "role": "co_owner"}, timeout=20)
        assert r.status_code == 200
        cid = r.json()["id"]
        co_user = _reg(email=em, name="TEST Priv Co", invited=False)

        # Co-owner creates own project
        r = requests.post(f"{API}/projects", headers=_h(co_user),
                          json={"name": "TEST Private Project"}, timeout=20)
        assert r.status_code == 200, r.text
        new_pid = r.json()["id"]

        # Owner's projects list should NOT contain this new project
        r = requests.get(f"{API}/projects", headers=_h(owner), timeout=20)
        ids = {p["id"] for p in r.json()}
        assert new_pid not in ids, "owner must NOT see co-owner's own private project"

        # Co-owner can see their own + shared
        r = requests.get(f"{API}/projects", headers=_h(co_user), timeout=20)
        plist = r.json()
        own = [p for p in plist if not p.get("shared")]
        shared = [p for p in plist if p.get("shared")]
        assert any(p["id"] == new_pid for p in own), f"co-owner should see own project: {own}"
        assert shared, "co-owner should also see shared project(s)"

        # cleanup
        requests.delete(f"{API}/projects/{new_pid}", headers=_h(co_user), timeout=10)
        requests.delete(f"{API}/co-owners/{cid}", headers=_h(owner), timeout=10)


# ============================= Regression: normal register still seeds demo =============================

class TestRegressionNormalRegister:
    def test_normal_register_gets_demo(self):
        u = _reg(invited=False, name="TEST NormalReg")
        r = requests.get(f"{API}/projects", headers=_h(u), timeout=20)
        assert r.status_code == 200
        plist = r.json()
        assert len(plist) == 1, plist
        assert not plist[0].get("shared")
        assert plist[0].get("name"), plist[0]
