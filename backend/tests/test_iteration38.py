"""Iteration 38 — Manager Task Inbox: GET /api/inbox and scoping tests.

Verifies:
- Items for open snags (fixed excluded), tenant snags with tenancy_id surfaced as kind "repair",
  non-done milestones within horizon flagged as kind "stage" (overdue if target_date < today).
- Response shape: items[], counts{repair,snag,stage,overdue,total}, projects (int).
- Sort order: overdue first, then high-priority tenant repairs, then by priority & date.
- Scoping: a TEST manager invited to only one project (via POST /api/co-owners with project_ids=[pid])
  sees only that project's items plus their own seeded project.
- Tasks-only (money_access=false) manager can still call /api/inbox successfully.
"""
import os
import time
import uuid
from datetime import date, timedelta

import pytest
import requests

BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") + "/api"
OWNER = {"email": "demo@mybuilder.app", "password": "demo1234"}
STAMP = str(int(time.time()))


# ---------- helpers ----------
def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _login(email: str, password: str) -> str:
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _register(name: str, email: str, password: str) -> str:
    r = requests.post(f"{BASE}/auth/register", json={"name": name, "email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def owner_token():
    return _login(**OWNER)


@pytest.fixture(scope="module")
def owner_pid(owner_token):
    r = requests.get(f"{BASE}/projects", headers=_auth_headers(owner_token), timeout=15)
    assert r.status_code == 200
    # Prefer the demo seeded project (owned by demo user, no "shared" flag).
    own = [p for p in r.json() if not p.get("shared")]
    assert own, "demo owner should have at least one own project"
    return own[0]["id"]


@pytest.fixture(scope="module")
def manager(owner_token, owner_pid):
    """Create a TEST manager, invited to only one of the owner's projects.
    Tasks-only (money_access=False) to also cover the scoping+money gate branch."""
    email = f"TEST_iter38mgr_{STAMP}_{uuid.uuid4().hex[:6]}@example.com"
    password = "ManagerPass123!"
    token = _register("TEST Iter38 Manager", email, password)
    # Owner invites manager scoped to a single project with money_access=false.
    inv = requests.post(
        f"{BASE}/co-owners",
        headers=_auth_headers(owner_token),
        json={"email": email, "project_ids": [owner_pid], "money_access": False},
        timeout=15,
    )
    assert inv.status_code == 200, f"invite failed: {inv.status_code} {inv.text}"
    co_id = inv.json().get("id")
    yield {"email": email, "password": password, "token": token, "co_id": co_id}
    # Cleanup co-owner row and manager user.
    if co_id:
        requests.delete(f"{BASE}/co-owners/{co_id}", headers=_auth_headers(owner_token), timeout=15)
    requests.delete(f"{BASE}/auth/account", headers=_auth_headers(token), timeout=15)


@pytest.fixture(scope="module")
def seeded_data(owner_token, owner_pid):
    """Seed: a TEST tenancy on the demo project + its portal + a tenant-reported repair snag
    + a non-tenant open snag + a fixed snag (should be excluded) + a milestone due in 3 days
    + an overdue milestone (date = yesterday)."""
    H = _auth_headers(owner_token)

    # Activate demo project to be safe.
    requests.post(f"{BASE}/projects/{owner_pid}/activate", headers=H, timeout=15)

    created = {"snag_ids": [], "milestone_ids": [], "tenancy_id": None, "repair_snag_ids": []}

    # 1) Create a tenancy on the active project.
    t = requests.post(
        f"{BASE}/rentals/tenancies",
        headers=H,
        json={
            "tenant_name": f"TEST_Tenant_{STAMP}",
            "tenant_email": "delivered@resend.dev",
            "rent": 1200.0,
            "deposit": 1200.0,
            "start_date": date.today().isoformat(),
            "rent_day": 1,
        },
        timeout=15,
    )
    assert t.status_code == 200, f"tenancy create: {t.status_code} {t.text}"
    tid = t.json()["id"]
    created["tenancy_id"] = tid

    # 2) Enable portal.
    p = requests.post(
        f"{BASE}/rentals/tenancies/{tid}/portal",
        headers=H,
        json={"origin_url": "https://example.com"},
        timeout=15,
    )
    assert p.status_code == 200, f"portal create: {p.status_code} {p.text}"
    pj = p.json()
    # Response is {"url": ".../api/t/<token>"}; token is the trailing path segment.
    portal_url = pj.get("url") or ""
    portal_token = pj.get("portal_token") or pj.get("token") or (portal_url.rstrip("/").split("/")[-1] if portal_url else "")
    assert portal_token, f"portal token missing after enabling portal: {pj}"

    # 3) Tenant reports a repair via public form -> creates snag with tenancy_id.
    rep = requests.post(
        f"{BASE}/t/{portal_token}/repair",
        data={"room": "TEST_Kitchen", f"description": f"TEST_leaking tap {STAMP}", "priority": "high"},
        allow_redirects=False,
        timeout=15,
    )
    assert rep.status_code in (303, 302, 200), f"tenant repair post: {rep.status_code} {rep.text[:200]}"

    # 4) Owner-created open snag (NOT tenant) -> kind should be "snag".
    s_open = requests.post(
        f"{BASE}/snags",
        headers=H,
        json={"room": "TEST_Hallway", "description": f"TEST_scuffed wall {STAMP}", "priority": "medium"},
        timeout=15,
    )
    assert s_open.status_code == 200, s_open.text
    created["snag_ids"].append(s_open.json()["id"])

    # 5) Owner-created fixed snag -> should be excluded from inbox.
    s_fix = requests.post(
        f"{BASE}/snags",
        headers=H,
        json={"room": "TEST_Attic", "description": f"TEST_already done {STAMP}", "priority": "low"},
        timeout=15,
    )
    assert s_fix.status_code == 200, s_fix.text
    sid_fixed = s_fix.json()["id"]
    created["snag_ids"].append(sid_fixed)
    fx = requests.put(
        f"{BASE}/snags/{sid_fixed}", headers=H, json={"status": "fixed"}, timeout=15
    )
    assert fx.status_code == 200, fx.text

    # 6) Future milestone (due in 3 days).
    future = (date.today() + timedelta(days=3)).isoformat()
    m_future = requests.post(
        f"{BASE}/milestones",
        headers=H,
        json={"name": f"TEST_Stage_future_{STAMP}", "target_date": future},
        timeout=15,
    )
    assert m_future.status_code == 200, m_future.text
    created["milestone_ids"].append(m_future.json()["id"])

    # 7) Overdue milestone (yesterday).
    past = (date.today() - timedelta(days=1)).isoformat()
    m_past = requests.post(
        f"{BASE}/milestones",
        headers=H,
        json={"name": f"TEST_Stage_overdue_{STAMP}", "target_date": past},
        timeout=15,
    )
    assert m_past.status_code == 200, m_past.text
    created["milestone_ids"].append(m_past.json()["id"])

    yield created

    # Cleanup
    for sid in created["snag_ids"]:
        requests.delete(f"{BASE}/snags/{sid}", headers=H, timeout=15)
    for mid in created["milestone_ids"]:
        requests.delete(f"{BASE}/milestones/{mid}", headers=H, timeout=15)
    # delete tenancy (also cleans rent_payments etc per route impl)
    if created["tenancy_id"]:
        requests.delete(f"{BASE}/rentals/tenancies/{created['tenancy_id']}", headers=H, timeout=15)
    # Remove any TEST_ snags created by tenant repair (tenancy_id scoped by desc prefix)
    snags = requests.get(f"{BASE}/snags", headers=H, timeout=15).json()
    for s in snags:
        if s.get("description", "").startswith("TEST_") or s.get("room", "").startswith("TEST_"):
            requests.delete(f"{BASE}/snags/{s['id']}", headers=H, timeout=15)


# ---------- tests ----------
class TestInboxShape:
    def test_requires_auth(self):
        r = requests.get(f"{BASE}/inbox", timeout=15)
        assert r.status_code in (401, 403), f"expected auth required, got {r.status_code}"

    def test_response_shape(self, owner_token, seeded_data):
        r = requests.get(f"{BASE}/inbox", headers=_auth_headers(owner_token), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body.get("items"), list)
        assert isinstance(body.get("counts"), dict)
        for k in ("repair", "snag", "stage", "overdue", "total"):
            assert k in body["counts"], f"counts missing {k}"
        assert isinstance(body.get("projects"), int)
        if body["items"]:
            it = body["items"][0]
            for k in ("id", "kind", "project_id", "project_name", "title", "detail", "priority", "date", "overdue"):
                assert k in it, f"item missing {k}: {it}"
            assert it["kind"] in ("repair", "snag", "stage")


class TestInboxContent:
    def test_tenant_repair_kind_is_repair(self, owner_token, seeded_data):
        r = requests.get(f"{BASE}/inbox", headers=_auth_headers(owner_token), timeout=15)
        assert r.status_code == 200
        body = r.json()
        # Our tenant repair has description "TEST_leaking tap <stamp>"
        repairs = [i for i in body["items"] if i["kind"] == "repair" and "TEST_leaking tap" in i["title"]]
        assert repairs, f"expected tenant repair snag to show as kind 'repair'; got items: {[i['title'] for i in body['items']]}"
        assert body["counts"]["repair"] >= 1

    def test_owner_snag_kind_is_snag(self, owner_token, seeded_data):
        r = requests.get(f"{BASE}/inbox", headers=_auth_headers(owner_token), timeout=15)
        assert r.status_code == 200
        body = r.json()
        owner_snags = [i for i in body["items"] if i["kind"] == "snag" and "TEST_scuffed wall" in i["title"]]
        assert owner_snags, "non-tenant open snag should surface as kind 'snag'"

    def test_fixed_snag_excluded(self, owner_token, seeded_data):
        r = requests.get(f"{BASE}/inbox", headers=_auth_headers(owner_token), timeout=15)
        assert r.status_code == 200
        titles = [i["title"] for i in r.json()["items"]]
        assert not any("TEST_already done" in t for t in titles), "fixed snag must be excluded"

    def test_milestones_included_and_overdue_flagged(self, owner_token, seeded_data):
        r = requests.get(f"{BASE}/inbox", headers=_auth_headers(owner_token), timeout=15)
        assert r.status_code == 200
        items = r.json()["items"]
        future = [i for i in items if i["kind"] == "stage" and "TEST_Stage_future_" in i["title"]]
        overdue = [i for i in items if i["kind"] == "stage" and "TEST_Stage_overdue_" in i["title"]]
        assert future, "future (<=30d) milestone must be included"
        assert future[0]["overdue"] is False
        assert overdue, "overdue milestone must be included"
        assert overdue[0]["overdue"] is True
        assert overdue[0]["priority"] == "high"

    def test_counts_match_items(self, owner_token, seeded_data):
        r = requests.get(f"{BASE}/inbox", headers=_auth_headers(owner_token), timeout=15)
        body = r.json()
        items = body["items"]
        c = body["counts"]
        assert c["repair"] == sum(1 for i in items if i["kind"] == "repair")
        assert c["snag"] == sum(1 for i in items if i["kind"] == "snag")
        assert c["stage"] == sum(1 for i in items if i["kind"] == "stage")
        assert c["overdue"] == sum(1 for i in items if i["overdue"])
        assert c["total"] == len(items)

    def test_sort_overdue_first(self, owner_token, seeded_data):
        r = requests.get(f"{BASE}/inbox", headers=_auth_headers(owner_token), timeout=15)
        items = r.json()["items"]
        # All overdue items should come before all non-overdue items.
        seen_non_overdue = False
        for i in items:
            if not i["overdue"]:
                seen_non_overdue = True
            elif seen_non_overdue:
                pytest.fail(f"overdue item {i['title']} appears after a non-overdue one in sort order")


class TestInboxScoping:
    def test_manager_login_ok(self, manager):
        assert manager["token"], "manager token should be present"

    def test_manager_can_call_inbox_tasks_only(self, manager, seeded_data):
        """Tasks-only (money_access=false) manager must still be able to GET /api/inbox."""
        r = requests.get(f"{BASE}/inbox", headers=_auth_headers(manager["token"]), timeout=15)
        assert r.status_code == 200, r.text

    def test_manager_sees_scoped_project_items(self, owner_token, owner_pid, manager, seeded_data):
        """Manager is invited only to owner_pid, so inbox for owner's projects should include only that project.
        Manager also has their own auto-seeded project — count includes it."""
        r = requests.get(f"{BASE}/inbox", headers=_auth_headers(manager["token"]), timeout=15)
        assert r.status_code == 200
        body = r.json()
        # Every item from the owner's side must be from owner_pid; manager's own project items are also fine.
        # Pull manager's own project ids.
        mp = requests.get(f"{BASE}/projects", headers=_auth_headers(manager["token"]), timeout=15).json()
        own_pids = {p["id"] for p in mp if not p.get("shared")}
        allowed = own_pids | {owner_pid}
        bad = [i for i in body["items"] if i["project_id"] not in allowed]
        assert not bad, f"manager saw items from unexpected projects: {[(i['project_id'], i['title']) for i in bad]}"
        # Scoping: should see the TEST_leaking tap repair we seeded on owner_pid.
        assert any("TEST_leaking tap" in i["title"] and i["project_id"] == owner_pid for i in body["items"]), (
            "manager should see tenant repair on scoped project"
        )

    def test_manager_does_not_see_other_owner_projects(self, owner_token, owner_pid, manager, seeded_data):
        """If owner has >1 project, manager must only see owner_pid, not the others.
        If owner has only 1 project (demo), this assertion still holds (vacuously)."""
        all_owner = requests.get(f"{BASE}/projects", headers=_auth_headers(owner_token), timeout=15).json()
        other_owner_pids = {p["id"] for p in all_owner if not p.get("shared") and p["id"] != owner_pid}
        if not other_owner_pids:
            pytest.skip("owner only has one project; scoping-exclusion case not applicable")
        r = requests.get(f"{BASE}/inbox", headers=_auth_headers(manager["token"]), timeout=15)
        body = r.json()
        leak = {i["project_id"] for i in body["items"]} & other_owner_pids
        assert not leak, f"manager leaked items from non-scoped owner projects: {leak}"
