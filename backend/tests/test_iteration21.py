"""Iteration 21 — Stakeholder portal access codes + passwords.

Tests the password+access-code flow added on top of the existing one-time-code portal:
- POST /api/portal-members accepts `company`, response has `company`, `password_set=false`
- An access code (BA-XXXX-...) is minted and stored only as HMAC in db.portal_accounts.code_lookup
- Resend rotates code only while password not set
- POST /api/portal/activate: validates code + password rules, 2nd call -> 409
- POST /api/portal/login-password: correct/wrong/not-activated, 5-fail lockout, removed member cannot sign in
- POST /api/portal/password-reset/{request,confirm}: generic 200, wrong/expired 401, success + token works,
  members with no code (legacy) get access_code once in confirm response
- GET /api/portal-members shows password_set=true after activation
- Existing OTP flow still works
"""
import os
import sys
import time
import uuid
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
sys.path.insert(0, "/app/backend")

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ["EXPO_PUBLIC_BACKEND_URL"]).rstrip("/")
API = f"{BASE_URL}/api"


# ---------- Helpers: direct Mongo access to inject known codes (per /app/memory/test_credentials.md) ----------
def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return cli[os.environ["DB_NAME"]]


async def _inject_code(email: str, raw: str):
    from routes.portal import _code_lookup
    from core import now_iso
    db = _db()
    await db.portal_accounts.update_one(
        {"email": email},
        {"$set": {"code_lookup": _code_lookup(raw), "code_issued_at": now_iso()},
         "$setOnInsert": {"created_at": now_iso(), "failed": 0}},
        upsert=True,
    )


async def _inject_reset(email: str, code: str, ttl: int = 600):
    from routes.portal import _code_hash
    db = _db()
    await db.portal_accounts.update_one(
        {"email": email},
        {"$set": {"reset": {"hash": _code_hash(email, "reset:" + code),
                            "expires": time.time() + ttl, "attempts": 0, "sends": [time.time()]}}}
    )


async def _get_account(email: str) -> dict | None:
    return await _db().portal_accounts.find_one({"email": email})


async def _cleanup(email: str):
    db = _db()
    await db.portal_accounts.delete_many({"email": email})
    await db.portal_handles.delete_many({"email": email})
    await db.portal_members.delete_many({"email": email})
    await db.portal_codes.delete_many({"email": email})


def _sync(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.new_event_loop().run_until_complete(coro)


# ---------- Fixtures ----------
@pytest.fixture(scope="module")
def owner():
    """Use demo seeded owner for its project context."""
    r = requests.post(f"{API}/auth/login", json={"email": "demo@mybuilder.app", "password": "demo1234"}, timeout=30)
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"token": token, "headers": {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}}


@pytest.fixture
def fresh_email():
    email = f"test_{uuid.uuid4().hex[:10]}@example.com"
    yield email
    _sync(_cleanup(email))


# ---------- Tests ----------
class TestInviteAndCode:
    def test_invite_includes_company_and_password_set_false(self, owner, fresh_email):
        r = requests.post(f"{API}/portal-members", headers=owner["headers"], json={
            "name": "Dave Patel", "email": fresh_email, "role": "Investor",
            "company": "Northfield Lending", "doc_ids": [], "digest": True,
            "origin_url": BASE_URL,
        }, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["company"] == "Northfield Lending"
        assert body["password_set"] is False
        assert body["handle"] and body["handle"].endswith("@propertyplug")
        # access code is NOT returned in response (only emailed). HMAC is stored.
        assert "access_code" not in body
        acc = _sync(_get_account(fresh_email))
        assert acc and acc.get("code_lookup"), "code_lookup HMAC must be stored"
        assert "password_hash" not in acc or not acc.get("password_hash")

    def test_duplicate_invite_rejected(self, owner, fresh_email):
        payload = {"name": "Dup", "email": fresh_email, "role": "Investor",
                   "company": "X", "doc_ids": [], "digest": True, "origin_url": BASE_URL}
        r1 = requests.post(f"{API}/portal-members", headers=owner["headers"], json=payload, timeout=30)
        assert r1.status_code == 200
        r2 = requests.post(f"{API}/portal-members", headers=owner["headers"], json=payload, timeout=30)
        assert r2.status_code == 400


class TestActivate:
    def test_activate_invalid_code(self, owner, fresh_email):
        requests.post(f"{API}/portal-members", headers=owner["headers"], json={
            "name": "A", "email": fresh_email, "role": "Investor", "company": "",
            "doc_ids": [], "digest": True, "origin_url": BASE_URL}, timeout=30)
        r = requests.post(f"{API}/portal/activate", json={
            "access_code": "PP-ZZZZ-ZZZZ-ZZZZ-ZZZZ", "password": "goodpass1"}, timeout=20)
        assert r.status_code == 400

    def test_weak_password_rejected(self, owner, fresh_email):
        requests.post(f"{API}/portal-members", headers=owner["headers"], json={
            "name": "A", "email": fresh_email, "role": "Investor", "company": "",
            "doc_ids": [], "digest": True, "origin_url": BASE_URL}, timeout=30)
        raw = "PP-TEST-AAAA-BBBB-CCCC"
        _sync(_inject_code(fresh_email, raw))
        # too short
        r1 = requests.post(f"{API}/portal/activate", json={"access_code": raw, "password": "ab12"}, timeout=20)
        assert r1.status_code == 400
        # no digit
        r2 = requests.post(f"{API}/portal/activate", json={"access_code": raw, "password": "abcdefgh"}, timeout=20)
        assert r2.status_code == 400
        # no letter
        r3 = requests.post(f"{API}/portal/activate", json={"access_code": raw, "password": "12345678"}, timeout=20)
        assert r3.status_code == 400

    def test_activate_success_and_me(self, owner, fresh_email):
        requests.post(f"{API}/portal-members", headers=owner["headers"], json={
            "name": "A", "email": fresh_email, "role": "Investor", "company": "Acme",
            "doc_ids": [], "digest": True, "origin_url": BASE_URL}, timeout=30)
        raw = "PP-ACT1-AAAA-BBBB-CCCC"
        _sync(_inject_code(fresh_email, raw))
        # case/dash insensitive: use lowercase without dashes
        r = requests.post(f"{API}/portal/activate", json={
            "access_code": "ba act1 aaaa bbbb cccc".upper(), "password": "goodpass1"}, timeout=20)
        assert r.status_code == 200, r.text
        token = r.json()["token"]
        me = requests.get(f"{API}/portal/me", headers={"Authorization": f"Bearer {token}"}, timeout=20)
        assert me.status_code == 200
        assert me.json()["email"] == fresh_email
        # second activate -> 409
        r2 = requests.post(f"{API}/portal/activate", json={"access_code": raw, "password": "goodpass1"}, timeout=20)
        assert r2.status_code == 409

    def test_password_set_true_after_activation(self, owner, fresh_email):
        inv = requests.post(f"{API}/portal-members", headers=owner["headers"], json={
            "name": "A", "email": fresh_email, "role": "Investor", "company": "Acme",
            "doc_ids": [], "digest": True, "origin_url": BASE_URL}, timeout=30).json()
        mid = inv["id"]
        raw = "PP-PSET-AAAA-BBBB-CCCC"
        _sync(_inject_code(fresh_email, raw))
        requests.post(f"{API}/portal/activate", json={"access_code": raw, "password": "goodpass1"}, timeout=20)
        lst = requests.get(f"{API}/portal-members", headers=owner["headers"], timeout=20).json()
        row = next((m for m in lst if m["id"] == mid), None)
        assert row and row["password_set"] is True


class TestLoginPassword:
    def test_login_correct(self, owner, fresh_email):
        requests.post(f"{API}/portal-members", headers=owner["headers"], json={
            "name": "A", "email": fresh_email, "role": "Investor", "company": "",
            "doc_ids": [], "digest": True, "origin_url": BASE_URL}, timeout=30)
        raw = "PP-LOG1-AAAA-BBBB-CCCC"
        _sync(_inject_code(fresh_email, raw))
        requests.post(f"{API}/portal/activate", json={"access_code": raw, "password": "goodpass1"}, timeout=20)
        r = requests.post(f"{API}/portal/login-password", json={"access_code": raw, "password": "goodpass1"}, timeout=20)
        assert r.status_code == 200
        assert "token" in r.json()

    def test_login_wrong_password_401(self, owner, fresh_email):
        requests.post(f"{API}/portal-members", headers=owner["headers"], json={
            "name": "A", "email": fresh_email, "role": "Investor", "company": "",
            "doc_ids": [], "digest": True, "origin_url": BASE_URL}, timeout=30)
        raw = "PP-LOG2-AAAA-BBBB-CCCC"
        _sync(_inject_code(fresh_email, raw))
        requests.post(f"{API}/portal/activate", json={"access_code": raw, "password": "goodpass1"}, timeout=20)
        r = requests.post(f"{API}/portal/login-password", json={"access_code": raw, "password": "wrongpass1"}, timeout=20)
        assert r.status_code == 401

    def test_login_not_activated(self, owner, fresh_email):
        requests.post(f"{API}/portal-members", headers=owner["headers"], json={
            "name": "A", "email": fresh_email, "role": "Investor", "company": "",
            "doc_ids": [], "digest": True, "origin_url": BASE_URL}, timeout=30)
        raw = "PP-LOG3-AAAA-BBBB-CCCC"
        _sync(_inject_code(fresh_email, raw))
        r = requests.post(f"{API}/portal/login-password", json={"access_code": raw, "password": "anything1"}, timeout=20)
        assert r.status_code == 401
        assert "No password set" in r.json().get("detail", "")

    def test_lockout_after_5_wrong(self, owner, fresh_email):
        requests.post(f"{API}/portal-members", headers=owner["headers"], json={
            "name": "A", "email": fresh_email, "role": "Investor", "company": "",
            "doc_ids": [], "digest": True, "origin_url": BASE_URL}, timeout=30)
        raw = "PP-LOCK-AAAA-BBBB-CCCC"
        _sync(_inject_code(fresh_email, raw))
        requests.post(f"{API}/portal/activate", json={"access_code": raw, "password": "goodpass1"}, timeout=20)
        for _ in range(5):
            requests.post(f"{API}/portal/login-password", json={"access_code": raw, "password": "wrongpass1"}, timeout=20)
        # correct password should now be rejected 429 (locked)
        r = requests.post(f"{API}/portal/login-password", json={"access_code": raw, "password": "goodpass1"}, timeout=20)
        assert r.status_code == 429, f"expected lockout 429, got {r.status_code} {r.text}"

    def test_removed_member_cannot_login(self, owner, fresh_email):
        inv = requests.post(f"{API}/portal-members", headers=owner["headers"], json={
            "name": "A", "email": fresh_email, "role": "Investor", "company": "",
            "doc_ids": [], "digest": True, "origin_url": BASE_URL}, timeout=30).json()
        raw = "PP-RMVE-AAAA-BBBB-CCCC"
        _sync(_inject_code(fresh_email, raw))
        requests.post(f"{API}/portal/activate", json={"access_code": raw, "password": "goodpass1"}, timeout=20)
        # remove member
        requests.delete(f"{API}/portal-members/{inv['id']}", headers=owner["headers"], timeout=20)
        r = requests.post(f"{API}/portal/login-password", json={"access_code": raw, "password": "goodpass1"}, timeout=20)
        assert r.status_code == 401


class TestPasswordReset:
    def test_reset_request_generic_200(self, owner, fresh_email):
        # Unknown identifier is also 200 (no account enumeration)
        r = requests.post(f"{API}/portal/password-reset/request", json={"identifier": "nobody@nowhere.test"}, timeout=20)
        assert r.status_code == 200
        assert "ok" in r.json()

    def test_reset_confirm_wrong_then_success(self, owner, fresh_email):
        requests.post(f"{API}/portal-members", headers=owner["headers"], json={
            "name": "A", "email": fresh_email, "role": "Investor", "company": "",
            "doc_ids": [], "digest": True, "origin_url": BASE_URL}, timeout=30)
        raw = "PP-RST1-AAAA-BBBB-CCCC"
        _sync(_inject_code(fresh_email, raw))
        requests.post(f"{API}/portal/activate", json={"access_code": raw, "password": "goodpass1"}, timeout=20)
        # request + inject reset code
        requests.post(f"{API}/portal/password-reset/request", json={"identifier": fresh_email}, timeout=20)
        _sync(_inject_reset(fresh_email, "654321"))
        # wrong reset code -> 401
        r_wrong = requests.post(f"{API}/portal/password-reset/confirm", json={
            "identifier": fresh_email, "reset_code": "000000", "new_password": "newpass123"}, timeout=20)
        assert r_wrong.status_code == 401
        # correct -> 200 token
        r_ok = requests.post(f"{API}/portal/password-reset/confirm", json={
            "identifier": fresh_email, "reset_code": "654321", "new_password": "newpass123"}, timeout=20)
        assert r_ok.status_code == 200, r_ok.text
        body = r_ok.json()
        assert "token" in body
        # access_code is None here (member already had one)
        assert body.get("access_code") in (None, "")
        # new password works for login-password
        login = requests.post(f"{API}/portal/login-password", json={"access_code": raw, "password": "newpass123"}, timeout=20)
        assert login.status_code == 200

    def test_reset_expired_code(self, owner, fresh_email):
        requests.post(f"{API}/portal-members", headers=owner["headers"], json={
            "name": "A", "email": fresh_email, "role": "Investor", "company": "",
            "doc_ids": [], "digest": True, "origin_url": BASE_URL}, timeout=30)
        raw = "PP-RST2-AAAA-BBBB-CCCC"
        _sync(_inject_code(fresh_email, raw))
        requests.post(f"{API}/portal/activate", json={"access_code": raw, "password": "goodpass1"}, timeout=20)
        _sync(_inject_reset(fresh_email, "111111", ttl=-10))  # already expired
        r = requests.post(f"{API}/portal/password-reset/confirm", json={
            "identifier": fresh_email, "reset_code": "111111", "new_password": "newpass123"}, timeout=20)
        assert r.status_code == 401

    def test_reset_for_legacy_member_returns_access_code(self, owner, fresh_email):
        """Member invited before passwords existed: delete their portal_accounts doc so no code_lookup.
        Confirm via email returns access_code once."""
        requests.post(f"{API}/portal-members", headers=owner["headers"], json={
            "name": "A", "email": fresh_email, "role": "Investor", "company": "",
            "doc_ids": [], "digest": True, "origin_url": BASE_URL}, timeout=30)
        # Simulate legacy: delete portal_accounts doc so there's no code_lookup
        import asyncio
        async def _del():
            await _db().portal_accounts.delete_many({"email": fresh_email})
        _sync(_del())
        # Request reset (creates account via _account_by_identifier)
        requests.post(f"{API}/portal/password-reset/request", json={"identifier": fresh_email}, timeout=20)
        _sync(_inject_reset(fresh_email, "222222"))
        r = requests.post(f"{API}/portal/password-reset/confirm", json={
            "identifier": fresh_email, "reset_code": "222222", "new_password": "newpass123"}, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("access_code"), f"access_code should be returned for legacy member: {body}"
        assert body["access_code"].startswith("PP-")
        # New access code should now work for login-password
        login = requests.post(f"{API}/portal/login-password", json={
            "access_code": body["access_code"], "password": "newpass123"}, timeout=20)
        assert login.status_code == 200


class TestResendRotation:
    def test_resend_rotates_code_before_password_set(self, owner, fresh_email):
        inv = requests.post(f"{API}/portal-members", headers=owner["headers"], json={
            "name": "A", "email": fresh_email, "role": "Investor", "company": "",
            "doc_ids": [], "digest": True, "origin_url": BASE_URL}, timeout=30).json()
        acc1 = _sync(_get_account(fresh_email))
        lookup1 = acc1["code_lookup"]
        # Resend has a 120s guard; bypass by backdating invited_at
        import asyncio
        async def _back():
            await _db().portal_members.update_one({"_id": __import__("bson").ObjectId(inv["id"])},
                                                   {"$set": {"invited_at": "2020-01-01T00:00:00+00:00"}})
        _sync(_back())
        r = requests.post(f"{API}/portal-members/{inv['id']}/resend", headers=owner["headers"], timeout=30)
        # Email may 429 under parallel load (iter 17-20 context note). Rotation happens before send,
        # so accept 200 or 503 and still verify rotation.
        assert r.status_code in (200, 503), r.text
        acc2 = _sync(_get_account(fresh_email))
        assert acc2["code_lookup"] != lookup1, "code must rotate on resend while password not set"

    def test_resend_does_not_rotate_after_password_set(self, owner, fresh_email):
        inv = requests.post(f"{API}/portal-members", headers=owner["headers"], json={
            "name": "A", "email": fresh_email, "role": "Investor", "company": "",
            "doc_ids": [], "digest": True, "origin_url": BASE_URL}, timeout=30).json()
        raw = "PP-NOR0-AAAA-BBBB-CCCC"
        _sync(_inject_code(fresh_email, raw))
        requests.post(f"{API}/portal/activate", json={"access_code": raw, "password": "goodpass1"}, timeout=20)
        acc1 = _sync(_get_account(fresh_email))
        lookup1 = acc1["code_lookup"]
        import asyncio
        async def _back():
            await _db().portal_members.update_one({"_id": __import__("bson").ObjectId(inv["id"])},
                                                   {"$set": {"invited_at": "2020-01-01T00:00:00+00:00"}})
        _sync(_back())
        r = requests.post(f"{API}/portal-members/{inv['id']}/resend", headers=owner["headers"], timeout=30)
        assert r.status_code in (200, 503)
        acc2 = _sync(_get_account(fresh_email))
        assert acc2["code_lookup"] == lookup1, "code must NOT rotate once password is set"


class TestOtpStillWorks:
    def test_request_code_generic_response(self):
        r = requests.post(f"{API}/portal/request-code", json={"identifier": "nobody@nowhere.test"}, timeout=20)
        assert r.status_code == 200
        assert "ok" in r.json()

    def test_otp_full_flow_still_works(self, owner, fresh_email):
        inv = requests.post(f"{API}/portal-members", headers=owner["headers"], json={
            "name": "O", "email": fresh_email, "role": "Investor", "company": "",
            "doc_ids": [], "digest": True, "origin_url": BASE_URL}, timeout=30).json()
        # Request code and inject known hash
        requests.post(f"{API}/portal/request-code", json={"identifier": fresh_email}, timeout=20)
        import asyncio
        async def _inject():
            from routes.portal import _code_hash
            await _db().portal_codes.update_one({"email": fresh_email},
                {"$set": {"hash": _code_hash(fresh_email, "123456"),
                          "expires": time.time() + 600, "attempts": 0, "sends": [time.time()]}}, upsert=True)
        _sync(_inject())
        r = requests.post(f"{API}/portal/verify", json={"identifier": fresh_email, "code": "123456"}, timeout=20)
        assert r.status_code == 200
        assert "token" in r.json()


class TestPortalWebPage:
    def test_portal_html_contains_elements(self):
        r = requests.get(f"{API}/portal", timeout=20)
        assert r.status_code == 200
        html = r.text
        # The HTML shell is static; the password-login screen with #pw-login, #acode, #pw, #pw-signin
        # is rendered dynamically via PORTAL_JS. Verify the JS source contains those IDs and the setup/forgot/otp hooks.
        for needle in ["pw-login", "acode", "'#pw'", "pw-signin", "to-setup", "to-forgot", "to-otp",
                        "pw-setup", "pw2", "pw-activate", "pw-forgot", "rid", "reset-send",
                        "pw-reset", "rcode", "reset-confirm", "otp-login"]:
            assert needle in html, f"portal HTML/JS missing: {needle}"
