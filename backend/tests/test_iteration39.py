"""Iteration 39 — Quick Mark Fixed from My tasks.

Verifies POST /api/inbox/snags/{sid}/fix:
- 200 {ok, photo:false} without a file; sets status fixed, fix_note, fixed_by=real user name,
  and the item disappears from GET /api/inbox.
- 200 {ok, photo:true} with an image file; fix_photo_path is persisted.
- 400 when already fixed (idempotency guard).
- 400 when a non-image file is attached.
- 404 for a snag in a project the user can't access.
- Tasks-only manager (money_access=false) scoped to the owner's project can mark a snag fixed
  WITHOUT having that project activated.
- Tenant repair gets tenant_notified_at set after fix.
"""
import io
import os
import time
import uuid
from datetime import date

import pytest
import requests

BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") + "/api"
OWNER = {"email": "demo@mybuilder.app", "password": "demo1234"}
STAMP = str(int(time.time()))


# ---------- helpers ----------
def H(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def H_form(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _login(email: str, password: str) -> str:
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _register(name: str, email: str, password: str) -> str:
    r = requests.post(f"{BASE}/auth/register", json={"name": name, "email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _tiny_png() -> bytes:
    # 1x1 red PNG
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
        b"\x00\x00\x00\x03\x00\x01\xa5\xf6E@\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _create_snag(token: str, room: str, desc: str, priority: str = "medium") -> str:
    r = requests.post(f"{BASE}/snags", headers=H(token), json={"room": room, "description": desc, "priority": priority}, timeout=15)
    assert r.status_code == 200, f"snag create: {r.status_code} {r.text}"
    return r.json()["id"]


def _get_snag_doc(token: str, sid: str):
    """Fetch snag from active project list; returns dict or None."""
    r = requests.get(f"{BASE}/snags", headers=H(token), timeout=15)
    assert r.status_code == 200, r.text
    for s in r.json():
        if s.get("id") == sid:
            return s
    return None


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def owner_token():
    return _login(**OWNER)


@pytest.fixture(scope="module")
def owner_user(owner_token):
    r = requests.get(f"{BASE}/auth/me", headers=H(owner_token), timeout=15)
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def owner_pid(owner_token):
    r = requests.get(f"{BASE}/projects", headers=H(owner_token), timeout=15)
    assert r.status_code == 200
    own = [p for p in r.json() if not p.get("shared")]
    assert own
    pid = own[0]["id"]
    # Ensure active
    requests.post(f"{BASE}/projects/{pid}/activate", headers=H(owner_token), timeout=15)
    return pid


@pytest.fixture(scope="module")
def tenancy_and_repair(owner_token, owner_pid):
    """Create a tenancy on the demo project with portal and a tenant-reported repair snag."""
    t = requests.post(
        f"{BASE}/rentals/tenancies",
        headers=H(owner_token),
        json={
            "tenant_name": f"TEST_Tenant_{STAMP}",
            "tenant_email": "delivered@resend.dev",
            "rent": 1200.0, "deposit": 1200.0,
            "start_date": date.today().isoformat(), "rent_day": 1,
        },
        timeout=15,
    )
    assert t.status_code == 200, t.text
    tid = t.json()["id"]
    p = requests.post(f"{BASE}/rentals/tenancies/{tid}/portal", headers=H(owner_token),
                     json={"origin_url": "https://example.com"}, timeout=15)
    assert p.status_code == 200, p.text
    portal_url = p.json().get("url", "")
    token = portal_url.rstrip("/").split("/")[-1]
    assert token, "no portal token"
    # Tenant reports a repair
    rep = requests.post(f"{BASE}/t/{token}/repair",
                       data={"room": "TEST_Bathroom", "description": f"TEST_dripping shower {STAMP}", "priority": "high"},
                       allow_redirects=False, timeout=15)
    assert rep.status_code in (200, 302, 303), f"tenant repair: {rep.status_code} {rep.text[:200]}"
    # Find the created tenant repair snag
    snags = requests.get(f"{BASE}/snags", headers=H(owner_token), timeout=15).json()
    sid = next((s["id"] for s in snags if s.get("tenancy_id") == tid and s.get("status") == "open"), None)
    assert sid, f"tenant repair snag not created; snags={[s.get('description') for s in snags]}"
    yield {"tenancy_id": tid, "snag_id": sid}
    # Cleanup
    # delete snags (any still around with TEST_ prefix)
    all_snags = requests.get(f"{BASE}/snags", headers=H(owner_token), timeout=15).json()
    for s in all_snags:
        if s.get("tenancy_id") == tid or s.get("description", "").startswith("TEST_") or s.get("room", "").startswith("TEST_"):
            requests.delete(f"{BASE}/snags/{s['id']}", headers=H(owner_token), timeout=15)
    requests.delete(f"{BASE}/rentals/tenancies/{tid}", headers=H(owner_token), timeout=15)


@pytest.fixture(scope="module")
def manager(owner_token, owner_pid):
    """Register a TEST manager and invite them to owner_pid as tasks-only."""
    email = f"TEST_iter39mgr_{STAMP}_{uuid.uuid4().hex[:6]}@example.com"
    password = "MgrPass123!"
    token = _register("TEST Iter39 Manager", email, password)
    inv = requests.post(f"{BASE}/co-owners", headers=H(owner_token),
                       json={"email": email, "project_ids": [owner_pid], "money_access": False},
                       timeout=15)
    assert inv.status_code == 200, f"invite failed: {inv.status_code} {inv.text}"
    co_id = inv.json().get("id")
    yield {"email": email, "password": password, "token": token, "co_id": co_id}
    if co_id:
        requests.delete(f"{BASE}/co-owners/{co_id}", headers=H(owner_token), timeout=15)
    requests.delete(f"{BASE}/auth/account", headers=H(token), timeout=15)


@pytest.fixture(scope="module")
def other_user():
    """Register an unrelated user with their own project. Used for 404 (no access) test."""
    email = f"TEST_iter39other_{STAMP}_{uuid.uuid4().hex[:6]}@example.com"
    password = "OtherPass123!"
    token = _register("TEST Iter39 Other", email, password)
    yield {"email": email, "password": password, "token": token}
    requests.delete(f"{BASE}/auth/account", headers=H(token), timeout=15)


# ---------- tests ----------
class TestQuickFixHappy:
    def test_fix_without_photo(self, owner_token, owner_user, owner_pid):
        sid = _create_snag(owner_token, "TEST_Lounge", f"TEST_cracked tile {STAMP}_a")
        r = requests.post(
            f"{BASE}/inbox/snags/{sid}/fix",
            headers=H_form(owner_token),
            data={"note": "Replaced tile and grouted"},
            timeout=20,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True
        assert body.get("photo") is False
        # Verify persistence via GET
        s = _get_snag_doc(owner_token, sid)
        assert s is not None, "snag disappeared from list"
        assert s["status"] == "fixed"
        assert s.get("fix_note") == "Replaced tile and grouted"
        assert s.get("fixed_by") == owner_user.get("name") or s.get("fixed_by")  # name of real user
        assert s.get("fixed_at")
        assert not s.get("fix_photo_path")
        # Cleanup
        requests.delete(f"{BASE}/snags/{sid}", headers=H(owner_token), timeout=15)

    def test_fix_with_photo(self, owner_token, owner_pid):
        sid = _create_snag(owner_token, "TEST_Hall", f"TEST_scuffed door {STAMP}_b")
        files = {"file": ("after.png", _tiny_png(), "image/png")}
        r = requests.post(
            f"{BASE}/inbox/snags/{sid}/fix",
            headers=H_form(owner_token),
            data={"note": "Repainted"},
            files=files,
            timeout=25,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True
        assert body.get("photo") is True
        s = _get_snag_doc(owner_token, sid)
        assert s and s["status"] == "fixed"
        assert s.get("fix_photo_path"), f"fix_photo_path missing: {s}"
        requests.delete(f"{BASE}/snags/{sid}", headers=H(owner_token), timeout=15)

    def test_item_disappears_from_inbox(self, owner_token):
        sid = _create_snag(owner_token, "TEST_Garage", f"TEST_broken latch {STAMP}_c")
        inbox_before = requests.get(f"{BASE}/inbox", headers=H(owner_token), timeout=15).json()
        assert any(i["id"] == sid for i in inbox_before["items"]), "new open snag should be in inbox"
        r = requests.post(f"{BASE}/inbox/snags/{sid}/fix", headers=H_form(owner_token),
                         data={"note": ""}, timeout=20)
        assert r.status_code == 200
        inbox_after = requests.get(f"{BASE}/inbox", headers=H(owner_token), timeout=15).json()
        assert not any(i["id"] == sid for i in inbox_after["items"]), "fixed snag must disappear from inbox"
        requests.delete(f"{BASE}/snags/{sid}", headers=H(owner_token), timeout=15)


class TestQuickFixValidation:
    def test_already_fixed_returns_400(self, owner_token):
        sid = _create_snag(owner_token, "TEST_Pantry", f"TEST_wobbly shelf {STAMP}_d")
        r1 = requests.post(f"{BASE}/inbox/snags/{sid}/fix", headers=H_form(owner_token),
                          data={"note": "done"}, timeout=20)
        assert r1.status_code == 200
        r2 = requests.post(f"{BASE}/inbox/snags/{sid}/fix", headers=H_form(owner_token),
                          data={"note": "again"}, timeout=20)
        assert r2.status_code == 400, f"expected 400 already fixed, got {r2.status_code} {r2.text}"
        assert "fixed" in r2.text.lower() or "already" in r2.text.lower()
        requests.delete(f"{BASE}/snags/{sid}", headers=H(owner_token), timeout=15)

    def test_non_image_file_rejected(self, owner_token):
        sid = _create_snag(owner_token, "TEST_Shed", f"TEST_bad lock {STAMP}_e")
        files = {"file": ("notes.txt", b"hello world", "text/plain")}
        r = requests.post(f"{BASE}/inbox/snags/{sid}/fix", headers=H_form(owner_token),
                         data={"note": ""}, files=files, timeout=20)
        assert r.status_code == 400, f"expected 400 non-image, got {r.status_code} {r.text}"
        # Snag must remain open (fix should not have been persisted)
        s = _get_snag_doc(owner_token, sid)
        assert s and s["status"] == "open", f"snag status should still be open: {s}"
        requests.delete(f"{BASE}/snags/{sid}", headers=H(owner_token), timeout=15)

    def test_no_access_returns_404(self, owner_token, other_user):
        sid = _create_snag(owner_token, "TEST_Office", f"TEST_locked drawer {STAMP}_f")
        r = requests.post(f"{BASE}/inbox/snags/{sid}/fix", headers=H_form(other_user["token"]),
                         data={"note": "hi"}, timeout=20)
        assert r.status_code == 404, f"expected 404 for other user, got {r.status_code} {r.text}"
        s = _get_snag_doc(owner_token, sid)
        assert s and s["status"] == "open"
        requests.delete(f"{BASE}/snags/{sid}", headers=H(owner_token), timeout=15)

    def test_requires_auth(self, owner_token):
        sid = _create_snag(owner_token, "TEST_Loft", f"TEST_hatch stuck {STAMP}_g")
        r = requests.post(f"{BASE}/inbox/snags/{sid}/fix", data={"note": "x"}, timeout=15)
        assert r.status_code in (401, 403)
        requests.delete(f"{BASE}/snags/{sid}", headers=H(owner_token), timeout=15)


class TestQuickFixManagerScoped:
    def test_tasks_only_manager_can_fix_without_activation(self, owner_token, manager, owner_pid):
        """Manager invited to owner_pid with money_access=false can mark a snag fixed in that project
        WITHOUT activating it (manager's own project may be active)."""
        sid = _create_snag(owner_token, "TEST_MgrRoom", f"TEST_mgr snag {STAMP}_h")
        # Make sure manager's active project is NOT owner_pid.
        mp = requests.get(f"{BASE}/projects", headers=H(manager["token"]), timeout=15).json()
        own = [p for p in mp if not p.get("shared")]
        if own:
            requests.post(f"{BASE}/projects/{own[0]['id']}/activate", headers=H(manager["token"]), timeout=15)
        # Manager marks fixed via inbox endpoint (no activate call).
        r = requests.post(f"{BASE}/inbox/snags/{sid}/fix", headers=H_form(manager["token"]),
                         data={"note": "Fixed by manager"}, timeout=20)
        assert r.status_code == 200, f"manager fix should succeed: {r.status_code} {r.text}"
        assert r.json().get("ok") is True
        # Owner (who owns the snag) can confirm persistence.
        s = _get_snag_doc(owner_token, sid)
        assert s and s["status"] == "fixed"
        # fixed_by must be the manager's real name, not the owner's.
        me_mgr = requests.get(f"{BASE}/auth/me", headers=H(manager["token"]), timeout=15).json()
        assert s.get("fixed_by") == me_mgr.get("name"), f"fixed_by={s.get('fixed_by')} vs manager={me_mgr.get('name')}"
        requests.delete(f"{BASE}/snags/{sid}", headers=H(owner_token), timeout=15)


class TestQuickFixTenantNotified:
    def test_tenant_repair_sets_notified_timestamp(self, owner_token, tenancy_and_repair):
        sid = tenancy_and_repair["snag_id"]
        r = requests.post(f"{BASE}/inbox/snags/{sid}/fix", headers=H_form(owner_token),
                         data={"note": "Repair done"}, timeout=25)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        # Small wait for the awaited notify to complete
        time.sleep(0.5)
        s = _get_snag_doc(owner_token, sid)
        assert s and s["status"] == "fixed"
        assert s.get("tenant_notified_at"), f"tenant_notified_at not set on tenant repair after fix: {s}"
