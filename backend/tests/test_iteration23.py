"""Iteration 23 — Access expiry dates for portal stakeholders.

Backend coverage:
- POST /api/portal-members: accepts expires_on YYYY-MM-DD; rejects past date (400) and bad format (422);
  response + GET /api/portal-members includes expires_on and `expired` flag.
- PUT /api/portal-members/{id}: {expires_on:'YYYY-MM-DD'} sets, {expires_on:null} clears, past date -> 400.
- Resend invite for an EXPIRED member -> 400.
- Enforcement (end date inclusive): setting expires_on < today in db simulates expiry.
    * GET /api/portal/projects/{pid} -> 403 with message mentioning the expiry date.
    * GET /api/portal/me excludes the expired project.
    * /api/portal/request-code silently 200s with no code written when only membership is expired.
    * /api/portal/login-password and /api/portal/activate fail for stakeholder whose only membership is expired.
    * Extending the end date restores access immediately.
- POST /api/portal/projects/{pid}/team: teammates inherit the lead's expires_on.
"""
import os
import sys
import time
import uuid
import pytest
import requests
from dotenv import load_dotenv
from datetime import date, timedelta

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
sys.path.insert(0, "/app/backend")

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ["EXPO_BACKEND_URL"]).rstrip("/")
API = f"{BASE_URL}/api"

TODAY = date.today()
FUTURE_30 = (TODAY + timedelta(days=30)).isoformat()
FUTURE_90 = (TODAY + timedelta(days=90)).isoformat()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
PAST_FAR = (TODAY - timedelta(days=30)).isoformat()


def _run(fn):
    """Run an async callable in a fresh event loop with a fresh motor client bound to it."""
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


def _sync(coro):
    """Legacy: run an already-created coroutine (no DB)."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _mint_portal_token(email: str) -> str:
    import jwt
    from datetime import datetime, timedelta, timezone
    from routes.portal import PORTAL_SECRET
    n = datetime.now(timezone.utc)
    return jwt.encode({"sub": email, "typ": "portal", "iat": n, "exp": n + timedelta(hours=1)},
                      PORTAL_SECRET, algorithm="HS256")


async def _set_expiry_direct_fn(email: str, pid: str, expires_on):
    async def fn(db):
        await db.portal_members.update_one(
            {"email": email, "project_id": pid},
            {"$set": {"expires_on": expires_on}},
        )
    return fn


async def _plant_access_code_fn(email: str, code: str):
    from routes.portal import _code_lookup
    async def fn(db):
        await db.portal_accounts.update_one(
            {"email": email},
            {"$set": {"code_lookup": _code_lookup(code)}, "$setOnInsert": {"created_at": "now", "failed": 0}},
            upsert=True,
        )
    return fn


async def _set_password_fn(email: str, pw: str):
    import bcrypt
    h = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    async def fn(db):
        await db.portal_accounts.update_one({"email": email}, {"$set": {"password_hash": h, "failed": 0, "locked_until": 0}})
    return fn


def _set_expiry_direct(email, pid, expires_on):
    async def fn(db):
        await db.portal_members.update_one(
            {"email": email, "project_id": pid},
            {"$set": {"expires_on": expires_on}},
        )
    _run(fn)


def _plant_access_code(email, code):
    from routes.portal import _code_lookup
    async def fn(db):
        await db.portal_accounts.update_one(
            {"email": email},
            {"$set": {"code_lookup": _code_lookup(code)}, "$setOnInsert": {"created_at": "now", "failed": 0}},
            upsert=True,
        )
    _run(fn)


def _set_password(email, pw):
    import bcrypt
    h = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    async def fn(db):
        await db.portal_accounts.update_one({"email": email}, {"$set": {"password_hash": h, "failed": 0, "locked_until": 0}})
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


def _find_portal_code(email):
    async def fn(db):
        return await db.portal_codes.find_one({"email": email})
    return _run(fn)


def _reset_invited_at(mid, iso):
    from bson import ObjectId
    async def fn(db):
        await db.portal_members.update_one({"_id": ObjectId(mid)},
                                            {"$set": {"invited_at": iso}})
    _run(fn)


# ---------- Fixtures ----------
@pytest.fixture(scope="module")
def owner_ctx():
    r = requests.post(f"{API}/auth/login",
                      json={"email": "demo@mybuilder.app", "password": "demo1234"}, timeout=30)
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    projs = requests.get(f"{API}/projects", headers=headers, timeout=20).json()
    assert projs, "demo owner must have at least one project"
    pid = projs[0]["id"]
    requests.post(f"{API}/projects/{pid}/activate", headers=headers, timeout=20)
    return {"token": token, "headers": headers, "pid": pid}


@pytest.fixture
def invited_emails():
    emails: list[str] = []
    yield emails
    for e in emails:
        _cleanup_email(e)


def _invite(owner_ctx, email, name="Dave Expiry", role="Investor", company="", expires_on=None):
    r = requests.post(f"{API}/portal-members", headers=owner_ctx["headers"], json={
        "name": name, "email": email, "role": role, "company": company,
        "doc_ids": [], "digest": True, "origin_url": BASE_URL, "expires_on": expires_on,
    }, timeout=30)
    return r


# =============================================================================
# 1. POST /portal-members: validation of expires_on
# =============================================================================
class TestInviteExpiryValidation:
    def test_invite_with_valid_future_date_persists_and_appears(self, owner_ctx, invited_emails):
        em = f"test_exp_future_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        r = _invite(owner_ctx, em, expires_on=FUTURE_90)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["expires_on"] == FUTURE_90
        assert body["expired"] is False
        # GET also includes it
        lst = requests.get(f"{API}/portal-members", headers=owner_ctx["headers"], timeout=20).json()
        row = next((x for x in lst if x["email"] == em), None)
        assert row and row["expires_on"] == FUTURE_90 and row["expired"] is False

    def test_invite_without_expiry_has_null_and_not_expired(self, owner_ctx, invited_emails):
        em = f"test_exp_none_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        r = _invite(owner_ctx, em, expires_on=None)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("expires_on") in (None,)
        assert body["expired"] is False

    def test_invite_with_past_date_returns_400(self, owner_ctx, invited_emails):
        em = f"test_exp_past_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        r = _invite(owner_ctx, em, expires_on=YESTERDAY)
        assert r.status_code == 400, r.text
        assert "past" in r.text.lower() or "end date" in r.text.lower()

    def test_invite_with_bad_format_returns_422(self, owner_ctx, invited_emails):
        em = f"test_exp_bad_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        r = _invite(owner_ctx, em, expires_on="12/31/2026")
        assert r.status_code == 422, r.text


# =============================================================================
# 2. PUT /portal-members/{id}: set/clear/past
# =============================================================================
class TestUpdateExpiry:
    def test_put_sets_expiry(self, owner_ctx, invited_emails):
        em = f"test_setexp_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        m = _invite(owner_ctx, em).json()
        r = requests.put(f"{API}/portal-members/{m['id']}", headers=owner_ctx["headers"],
                         json={"expires_on": FUTURE_30}, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["expires_on"] == FUTURE_30
        assert r.json()["expired"] is False

    def test_put_clears_expiry_with_null(self, owner_ctx, invited_emails):
        em = f"test_clrexp_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        m = _invite(owner_ctx, em, expires_on=FUTURE_30).json()
        r = requests.put(f"{API}/portal-members/{m['id']}", headers=owner_ctx["headers"],
                         json={"expires_on": None}, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json().get("expires_on") is None
        assert r.json()["expired"] is False

    def test_put_past_returns_400(self, owner_ctx, invited_emails):
        em = f"test_pastexp_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        m = _invite(owner_ctx, em).json()
        r = requests.put(f"{API}/portal-members/{m['id']}", headers=owner_ctx["headers"],
                         json={"expires_on": YESTERDAY}, timeout=20)
        assert r.status_code == 400, r.text


# =============================================================================
# 3. Resend invite for an expired member -> 400
# =============================================================================
class TestResendExpired:
    def test_resend_expired_returns_400(self, owner_ctx, invited_emails):
        em = f"test_resendexp_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        m = _invite(owner_ctx, em).json()
        # Simulate expiry in DB (past PUT validation)
        _set_expiry_direct(em, owner_ctx["pid"], PAST_FAR)
        # Wait a moment to be past the 120s window would be too slow; instead reset invited_at far in past
        _sync(_mint_portal_token(em))  # noqa (no-op for backward compat)
        _reset_invited_at(m['id'], "2020-01-01T00:00:00+00:00")
        r = requests.post(f"{API}/portal-members/{m['id']}/resend", headers=owner_ctx["headers"], timeout=20)
        assert r.status_code == 400, r.text
        assert "ended" in r.text.lower() or "extend" in r.text.lower()


# =============================================================================
# 4. Enforcement across stakeholder endpoints
# =============================================================================
class TestExpiryEnforcement:
    def test_portal_project_returns_403_with_date_message(self, owner_ctx, invited_emails):
        em = f"test_enf_project_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        _invite(owner_ctx, em).json()
        _set_expiry_direct(em, owner_ctx["pid"], PAST_FAR)
        tok = _sync(_mint_portal_token(em))
        r = requests.get(f"{API}/portal/projects/{owner_ctx['pid']}",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=20)
        assert r.status_code == 403, r.text
        detail = r.json().get("detail", "")
        assert PAST_FAR in detail or "ended on" in detail.lower()

    def test_portal_me_excludes_expired_project(self, owner_ctx, invited_emails):
        em = f"test_enf_me_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        _invite(owner_ctx, em).json()
        _set_expiry_direct(em, owner_ctx["pid"], PAST_FAR)
        tok = _sync(_mint_portal_token(em))
        r = requests.get(f"{API}/portal/me", headers={"Authorization": f"Bearer {tok}"}, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json().get("projects") == []

    def test_request_code_silent_when_only_membership_expired(self, owner_ctx, invited_emails):
        em = f"test_enf_code_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        _invite(owner_ctx, em).json()
        _set_expiry_direct(em, owner_ctx["pid"], PAST_FAR)
        r = requests.post(f"{API}/portal/request-code", json={"identifier": em}, timeout=20)
        assert r.status_code == 200
        # No code row should be created for an expired-only stakeholder
        rec = _find_portal_code(em)
        assert rec is None

    def test_login_password_fails_when_only_membership_expired(self, owner_ctx, invited_emails):
        em = f"test_enf_login_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        _invite(owner_ctx, em).json()
        # Plant a known code + password; then expire the membership.
        code = "PP-ZZZZ-ZZZZ-ZZZZ-ZZZZ"
        _plant_access_code(em, code)
        _set_password(em, "Password12")
        _set_expiry_direct(em, owner_ctx["pid"], PAST_FAR)
        r = requests.post(f"{API}/portal/login-password",
                          json={"access_code": code, "password": "Password12"}, timeout=20)
        # _account_by_code returns None because active_q() filters out expired members → 401
        assert r.status_code == 401, r.text

    def test_activate_fails_when_only_membership_expired(self, owner_ctx, invited_emails):
        em = f"test_enf_act_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        _invite(owner_ctx, em).json()
        code = "PP-YYYY-YYYY-YYYY-YYYY"
        _plant_access_code(em, code)
        _set_expiry_direct(em, owner_ctx["pid"], PAST_FAR)
        r = requests.post(f"{API}/portal/activate",
                          json={"access_code": code, "password": "Password12"}, timeout=20)
        assert r.status_code == 400, r.text

    def test_extending_date_restores_access(self, owner_ctx, invited_emails):
        em = f"test_enf_restore_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        m = _invite(owner_ctx, em).json()
        _set_expiry_direct(em, owner_ctx["pid"], PAST_FAR)
        tok = _sync(_mint_portal_token(em))
        r1 = requests.get(f"{API}/portal/projects/{owner_ctx['pid']}",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=20)
        assert r1.status_code == 403
        # Owner extends via API
        r2 = requests.put(f"{API}/portal-members/{m['id']}", headers=owner_ctx["headers"],
                          json={"expires_on": FUTURE_30}, timeout=20)
        assert r2.status_code == 200, r2.text
        # Access immediately works again
        r3 = requests.get(f"{API}/portal/projects/{owner_ctx['pid']}",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=20)
        assert r3.status_code == 200, r3.text
        assert r3.json().get("expires_on") == FUTURE_30


# =============================================================================
# 5. Access-until (inclusive): today's date is still valid
# =============================================================================
class TestInclusiveEndDate:
    def test_today_is_still_accessible(self, owner_ctx, invited_emails):
        em = f"test_today_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.append(em)
        _invite(owner_ctx, em).json()
        _set_expiry_direct(em, owner_ctx["pid"], TODAY.isoformat())
        tok = _sync(_mint_portal_token(em))
        r = requests.get(f"{API}/portal/projects/{owner_ctx['pid']}",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json().get("expires_on") == TODAY.isoformat()


# =============================================================================
# 6. Team leads: teammates inherit the lead's expires_on
# =============================================================================
class TestTeamInheritExpiry:
    def test_teammate_inherits_lead_expiry(self, owner_ctx, invited_emails):
        lead = f"test_lead_exp_{uuid.uuid4().hex[:8]}@example.com"
        mate = f"test_mate_exp_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.extend([lead, mate])
        m = _invite(owner_ctx, lead, name="Pat Lead", company="Northfield Lending",
                    expires_on=FUTURE_90).json()
        r = requests.put(f"{API}/portal-members/{m['id']}", headers=owner_ctx["headers"],
                         json={"is_lead": True}, timeout=20)
        assert r.status_code == 200, r.text
        tok = _sync(_mint_portal_token(lead))
        r2 = requests.post(f"{API}/portal/projects/{owner_ctx['pid']}/team",
                           headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                           json={"name": "Priya Mate", "email": mate}, timeout=20)
        assert r2.status_code == 200, r2.text
        # Verify via owner GET /portal-members
        lst = requests.get(f"{API}/portal-members", headers=owner_ctx["headers"], timeout=20).json()
        row = next((x for x in lst if x["email"] == mate), None)
        assert row and row["expires_on"] == FUTURE_90
        assert row["expired"] is False

    def test_teammate_inherits_null_when_lead_no_expiry(self, owner_ctx, invited_emails):
        lead = f"test_lead_noexp_{uuid.uuid4().hex[:8]}@example.com"
        mate = f"test_mate_noexp_{uuid.uuid4().hex[:8]}@example.com"
        invited_emails.extend([lead, mate])
        m = _invite(owner_ctx, lead, name="Pat Lead2", company="Acme").json()
        requests.put(f"{API}/portal-members/{m['id']}", headers=owner_ctx["headers"],
                     json={"is_lead": True}, timeout=20)
        tok = _sync(_mint_portal_token(lead))
        r = requests.post(f"{API}/portal/projects/{owner_ctx['pid']}/team",
                         headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                         json={"name": "Mate2", "email": mate}, timeout=20)
        assert r.status_code == 200, r.text
        lst = requests.get(f"{API}/portal-members", headers=owner_ctx["headers"], timeout=20).json()
        row = next((x for x in lst if x["email"] == mate), None)
        assert row and row.get("expires_on") is None
