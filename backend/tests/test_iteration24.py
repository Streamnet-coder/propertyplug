"""Iteration 24 — Expiry Heads-Up for stakeholder portal.

Backend coverage:
- GET /api/portal-members/expiring (owner auth): lists members across ALL owner's projects whose
  expires_on is within the next 7 days (inclusive today) or ended within last 7 days.
  Fields: id,name,email,role,company,project_id,project_name,expires_on,expired,days_left.
  Sorted by expires_on ascending; members with no end date or >7 days out are excluded; other
  owners' members are excluded.
- POST /api/portal-members/{id}/extend {days:30 default, 1..366}: new end = max(today, cur) + days;
  expired member gets today+days and regains portal access; 404 for other owner's member.
"""
import os
import sys
import uuid
import pytest
import requests
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
sys.path.insert(0, "/app/backend")

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ["EXPO_BACKEND_URL"]).rstrip("/")
API = f"{BASE_URL}/api"

TODAY = date.today()


def _iso(delta_days: int) -> str:
    return (TODAY + timedelta(days=delta_days)).isoformat()


def _run(fn):
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    loop = asyncio.new_event_loop()
    try:
        async def _wrap():
            cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
            try:
                return await fn(cli[os.environ["DB_NAME"]])
            finally:
                cli.close()
        return loop.run_until_complete(_wrap())
    finally:
        loop.close()


def _set_expiry_direct(email, pid, expires_on):
    async def fn(db):
        await db.portal_members.update_one(
            {"email": email, "project_id": pid},
            {"$set": {"expires_on": expires_on}},
        )
    _run(fn)


def _cleanup_email(email):
    async def fn(db):
        await db.portal_accounts.delete_many({"email": email})
        await db.portal_handles.delete_many({"email": email})
        await db.portal_members.delete_many({"email": email})
        await db.portal_codes.delete_many({"email": email})
        await db.portal_activity.delete_many({"email": email})
        await db.portal_questions.delete_many({"email": email})
    _run(fn)


def _delete_user_by_email(email):
    async def fn(db):
        u = await db.users.find_one({"email": email}, {"_id": 1})
        if not u:
            return
        uid = str(u["_id"])
        await db.users.delete_one({"_id": u["_id"]})
        # best-effort: nuke anything they owned so leftover doesn't poison other tests
        for coll in ("projects", "portal_members", "portal_activity", "portal_questions",
                     "documents", "receipts", "line_items", "snags", "messages",
                     "notifications", "email_settings"):
            try:
                await db[coll].delete_many({"owner_id": uid})
            except Exception:
                pass
            try:
                await db[coll].delete_many({"user_id": uid})
            except Exception:
                pass
    _run(fn)


# ---------- Fixtures ----------
@pytest.fixture(scope="module")
def owner_ctx():
    """demo@mybuilder.app owner with their primary project."""
    r = requests.post(f"{API}/auth/login",
                      json={"email": "demo@mybuilder.app", "password": "demo1234"}, timeout=30)
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    projs = requests.get(f"{API}/projects", headers=headers, timeout=20).json()
    assert projs, "demo owner must have at least one project"
    pid = projs[0]["id"]
    requests.post(f"{API}/projects/{pid}/activate", headers=headers, timeout=20)
    return {"token": token, "headers": headers, "pid": pid, "project_name": projs[0]["name"]}


@pytest.fixture(scope="module")
def other_owner_ctx():
    """A separate owner used to prove cross-owner isolation."""
    em = f"test_otherowner_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/auth/register",
                      json={"name": "Other Owner", "email": em, "password": "demo1234"},
                      timeout=30)
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    projs = requests.get(f"{API}/projects", headers=headers, timeout=20).json()
    pid = projs[0]["id"]
    yield {"token": token, "headers": headers, "pid": pid, "email": em}
    _delete_user_by_email(em)


@pytest.fixture
def invited_emails():
    emails: list[str] = []
    yield emails
    for e in emails:
        _cleanup_email(e)


def _invite(ctx, email, name="Dave Heads", role="Investor", company="", expires_on=None):
    r = requests.post(f"{API}/portal-members", headers=ctx["headers"], json={
        "name": name, "email": email, "role": role, "company": company,
        "doc_ids": [], "digest": True, "origin_url": BASE_URL, "expires_on": expires_on,
    }, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


# =============================================================================
# 1. GET /portal-members/expiring — windowing & fields
# =============================================================================
class TestExpiringEndpoint:
    def test_within_window_includes_future_and_ended(self, owner_ctx, invited_emails):
        em_today = f"test_hu_today_{uuid.uuid4().hex[:8]}@example.com"
        em_3d = f"test_hu_3d_{uuid.uuid4().hex[:8]}@example.com"
        em_7d = f"test_hu_7d_{uuid.uuid4().hex[:8]}@example.com"
        em_ended3 = f"test_hu_ended3_{uuid.uuid4().hex[:8]}@example.com"
        em_far = f"test_hu_far_{uuid.uuid4().hex[:8]}@example.com"
        em_none = f"test_hu_none_{uuid.uuid4().hex[:8]}@example.com"
        em_ended15 = f"test_hu_ended15_{uuid.uuid4().hex[:8]}@example.com"
        for em in (em_today, em_3d, em_7d, em_ended3, em_far, em_none, em_ended15):
            invited_emails.append(em)

        _invite(owner_ctx, em_today, expires_on=_iso(0))
        _invite(owner_ctx, em_3d, expires_on=_iso(3))
        _invite(owner_ctx, em_7d, expires_on=_iso(7))
        _invite(owner_ctx, em_far, expires_on=_iso(30))
        _invite(owner_ctx, em_none, expires_on=None)
        # Ended-in-the-last-7-days & >7 days ago require direct db simulation
        _invite(owner_ctx, em_ended3, expires_on=_iso(30))
        _invite(owner_ctx, em_ended15, expires_on=_iso(30))
        _set_expiry_direct(em_ended3, owner_ctx["pid"], _iso(-3))
        _set_expiry_direct(em_ended15, owner_ctx["pid"], _iso(-15))

        r = requests.get(f"{API}/portal-members/expiring", headers=owner_ctx["headers"], timeout=20)
        assert r.status_code == 200, r.text
        rows = r.json()
        emails = {row["email"] for row in rows}
        assert em_today in emails
        assert em_3d in emails
        assert em_7d in emails
        assert em_ended3 in emails
        assert em_far not in emails
        assert em_none not in emails
        assert em_ended15 not in emails

    def test_fields_and_sort_order(self, owner_ctx, invited_emails):
        em1 = f"test_hu_sort1_{uuid.uuid4().hex[:8]}@example.com"
        em2 = f"test_hu_sort2_{uuid.uuid4().hex[:8]}@example.com"
        em3 = f"test_hu_sort3_{uuid.uuid4().hex[:8]}@example.com"
        for em in (em1, em2, em3):
            invited_emails.append(em)
        _invite(owner_ctx, em1, name="Alice Exp", role="Lender", company="North", expires_on=_iso(5))
        _invite(owner_ctx, em2, name="Bob Exp", role="Investor", company="", expires_on=_iso(1))
        _invite(owner_ctx, em3, expires_on=_iso(30))
        _set_expiry_direct(em3, owner_ctx["pid"], _iso(-2))

        r = requests.get(f"{API}/portal-members/expiring", headers=owner_ctx["headers"], timeout=20)
        assert r.status_code == 200
        rows = r.json()
        # Filter down to just our 3 to make the sort assertion stable
        ours = [row for row in rows if row["email"] in {em1, em2, em3}]
        assert len(ours) == 3
        # Sort order is by expires_on ascending: em3 (-2), em2 (+1), em1 (+5)
        assert [row["email"] for row in ours] == [em3, em2, em1]

        # Field shape
        row = ours[1]  # em2
        for k in ("id", "name", "email", "role", "company", "project_id", "project_name",
                  "expires_on", "expired", "days_left"):
            assert k in row, f"missing {k}"
        assert row["name"] == "Bob Exp"
        assert row["role"] == "Investor"
        assert row["company"] == ""
        assert row["project_id"] == owner_ctx["pid"]
        assert row["project_name"] == owner_ctx["project_name"]
        assert row["expired"] is False
        assert row["days_left"] == 1
        # Ended row
        ended = ours[0]
        assert ended["expired"] is True
        assert ended["days_left"] == -2

    def test_other_owners_members_excluded(self, owner_ctx, other_owner_ctx, invited_emails):
        em = f"test_hu_otherowner_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        _invite(other_owner_ctx, em, expires_on=_iso(2))
        # Demo owner should NOT see it
        r = requests.get(f"{API}/portal-members/expiring", headers=owner_ctx["headers"], timeout=20)
        emails = {row["email"] for row in r.json()}
        assert em not in emails
        # Other owner SHOULD see it
        r2 = requests.get(f"{API}/portal-members/expiring", headers=other_owner_ctx["headers"], timeout=20)
        emails2 = {row["email"] for row in r2.json()}
        assert em in emails2

    def test_requires_auth(self):
        r = requests.get(f"{API}/portal-members/expiring", timeout=20)
        assert r.status_code in (401, 403)


# =============================================================================
# 2. POST /portal-members/{id}/extend
# =============================================================================
class TestExtendMember:
    def test_extend_future_member_adds_days(self, owner_ctx, invited_emails):
        em = f"test_hu_ext_future_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        m = _invite(owner_ctx, em, expires_on=_iso(3))
        r = requests.post(f"{API}/portal-members/{m['id']}/extend",
                          headers=owner_ctx["headers"], json={"days": 30}, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        # new end = _iso(3) + 30 days = _iso(33)
        assert body["expires_on"] == _iso(33)
        # GET also reflects
        lst = requests.get(f"{API}/portal-members", headers=owner_ctx["headers"], timeout=20).json()
        row = next(x for x in lst if x["id"] == m["id"])
        assert row["expires_on"] == _iso(33)
        assert row["expired"] is False

    def test_extend_default_is_30_days(self, owner_ctx, invited_emails):
        em = f"test_hu_ext_default_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        m = _invite(owner_ctx, em, expires_on=_iso(5))
        r = requests.post(f"{API}/portal-members/{m['id']}/extend",
                          headers=owner_ctx["headers"], json={}, timeout=20)
        assert r.status_code == 200
        assert r.json()["expires_on"] == _iso(35)

    def test_extend_expired_uses_today_as_base_and_restores_access(self, owner_ctx, invited_emails):
        em = f"test_hu_ext_expired_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        m = _invite(owner_ctx, em, expires_on=_iso(30))
        _set_expiry_direct(em, owner_ctx["pid"], _iso(-5))
        # Verify expired first in listing
        lst = requests.get(f"{API}/portal-members", headers=owner_ctx["headers"], timeout=20).json()
        row = next(x for x in lst if x["id"] == m["id"])
        assert row["expired"] is True
        r = requests.post(f"{API}/portal-members/{m['id']}/extend",
                          headers=owner_ctx["headers"], json={"days": 30}, timeout=20)
        assert r.status_code == 200
        assert r.json()["expires_on"] == _iso(30)
        # Member regains active access
        lst2 = requests.get(f"{API}/portal-members", headers=owner_ctx["headers"], timeout=20).json()
        row2 = next(x for x in lst2 if x["id"] == m["id"])
        assert row2["expired"] is False
        assert row2["expires_on"] == _iso(30)

    def test_extend_rejects_out_of_range(self, owner_ctx, invited_emails):
        em = f"test_hu_ext_range_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        m = _invite(owner_ctx, em, expires_on=_iso(3))
        for bad in (0, -1, 367):
            r = requests.post(f"{API}/portal-members/{m['id']}/extend",
                              headers=owner_ctx["headers"], json={"days": bad}, timeout=20)
            assert r.status_code == 422, f"days={bad} -> {r.status_code} {r.text}"

    def test_extend_other_owners_member_404(self, owner_ctx, other_owner_ctx, invited_emails):
        em = f"test_hu_ext_crossowner_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        m = _invite(other_owner_ctx, em, expires_on=_iso(3))
        r = requests.post(f"{API}/portal-members/{m['id']}/extend",
                          headers=owner_ctx["headers"], json={"days": 30}, timeout=20)
        assert r.status_code == 404

    def test_extend_removes_row_from_expiring_once_beyond_7_days(self, owner_ctx, invited_emails):
        em = f"test_hu_ext_disappear_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        m = _invite(owner_ctx, em, expires_on=_iso(2))
        r = requests.get(f"{API}/portal-members/expiring", headers=owner_ctx["headers"], timeout=20)
        assert em in {row["email"] for row in r.json()}
        # Extend 30 days -> new end = +32, which is beyond the +7 window
        ex = requests.post(f"{API}/portal-members/{m['id']}/extend",
                           headers=owner_ctx["headers"], json={"days": 30}, timeout=20)
        assert ex.status_code == 200
        r2 = requests.get(f"{API}/portal-members/expiring", headers=owner_ctx["headers"], timeout=20)
        assert em not in {row["email"] for row in r2.json()}
