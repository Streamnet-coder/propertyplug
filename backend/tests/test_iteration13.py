"""Iteration 13 backend tests.

Covers:
- /api/email-settings GET/POST/DELETE: fields, origin https guard, 3/hour rate-limit, verification email use delivered@resend.dev
- public /api/verify-email/{token}: HTML #email-verified + verified flipping; invalid token -> expired page
- digest send-now still returns sent:1 when verified company email set (code review uses owner_reply_to)
- Sign-off notification: public /api/s/{token}/sign triggers notify_owner_signoff but still returns 303 even when email delivery fails
- Trade ratings: before signoff -> 400; after signoff -> 200; invalid stars -> 422; unknown tags filtered; upsert; GET filters; trusted-trades sorted best first; account deletion removes trade_ratings
"""
import os
import time
import uuid
from typing import Dict, Optional

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
DEMO_EMAIL = "demo@mybuilder.app"
DEMO_PASSWORD = "demo1234"
DELIVERED = "delivered@resend.dev"
VALID_SIG_PATH = "M10 10 L50 40 L90 20 L120 55"


def auth(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def demo_token() -> str:
    r = requests.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def register_test_user(suffix: Optional[str] = None, email: Optional[str] = None) -> Dict:
    pw = "testpass1234"
    em = email or f"test_{suffix or uuid.uuid4().hex[:10]}@example.com"
    r = requests.post(f"{API}/auth/register", json={"name": "TEST_ User", "email": em, "password": pw}, timeout=30)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    data = r.json()
    return {"token": data["access_token"], "user": data["user"], "email": em, "password": pw}


def _cleanup_test_user(u):
    try:
        requests.delete(f"{API}/auth/account", headers=auth(u["token"]),
                        json={"password": u["password"]}, timeout=20)
    except Exception:
        pass


def _create_snag(tok: str, assignee: str, desc: str = "TEST_ snag") -> dict:
    r = requests.post(f"{API}/snags", headers=auth(tok),
                      json={"room": "TEST_room", "description": desc, "priority": "medium", "assignee": assignee},
                      timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _fix_snag(tok: str, sid: str):
    r = requests.put(f"{API}/snags/{sid}", headers=auth(tok), json={"status": "fixed"}, timeout=15)
    assert r.status_code == 200, r.text


def _signoff(tok: str, assignee: str):
    r = requests.post(f"{API}/snag-signoffs", headers=auth(tok),
                      json={"assignee": assignee, "name": "Owner",
                            "path": VALID_SIG_PATH, "width": 300, "height": 160}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


# ==================== Email settings ====================
class TestEmailSettings:
    def test_initial_state_and_fields(self):
        u = register_test_user("em_init")
        try:
            r = requests.get(f"{API}/email-settings", headers=auth(u["token"]), timeout=15)
            assert r.status_code == 200, r.text
            d = r.json()
            for key in ("company_email", "verified", "sender_name", "company_name", "account_email"):
                assert key in d, f"missing field {key} in {d}"
            assert d["verified"] is False
            assert d["sender_name"] == "Builder Assist"
            assert d["account_email"] == u["email"]
            assert d["company_email"] in (None, "")
        finally:
            _cleanup_test_user(u)

    def test_post_rejects_http_origin(self):
        u = register_test_user("em_http")
        try:
            r = requests.post(f"{API}/email-settings", headers=auth(u["token"]),
                              json={"email": DELIVERED, "origin_url": "http://example.com"}, timeout=15)
            assert r.status_code == 400, r.text
            assert "https" in r.text.lower()
        finally:
            _cleanup_test_user(u)

    def test_post_sends_verification_and_rate_limits(self):
        u = register_test_user("em_rl")
        try:
            tok = u["token"]
            for i in range(3):
                r = requests.post(f"{API}/email-settings", headers=auth(tok),
                                  json={"email": DELIVERED, "origin_url": BASE_URL}, timeout=30)
                assert r.status_code == 200, f"attempt {i+1}: {r.status_code} {r.text}"
                d = r.json()
                assert d["company_email"] == DELIVERED
                assert d["verified"] is False
            # 4th within an hour -> 429
            r = requests.post(f"{API}/email-settings", headers=auth(tok),
                              json={"email": DELIVERED, "origin_url": BASE_URL}, timeout=30)
            assert r.status_code == 429, r.text
        finally:
            _cleanup_test_user(u)

    def test_verify_token_flips_verified_true(self):
        u = register_test_user("em_verify")
        try:
            tok = u["token"]
            r = requests.post(f"{API}/email-settings", headers=auth(tok),
                              json={"email": DELIVERED, "origin_url": BASE_URL}, timeout=30)
            assert r.status_code == 200, r.text
            # Fetch the token directly from Mongo via a helper endpoint? None exist; use test backdoor via driver.
            from motor.motor_asyncio import AsyncIOMotorClient
            import asyncio
            mongo_url = os.environ["MONGO_URL"]
            db_name = os.environ["DB_NAME"]

            async def fetch_token():
                cli = AsyncIOMotorClient(mongo_url)
                try:
                    doc = await cli[db_name].users.find_one({"email": u["email"]}, {"company_email_token": 1})
                    return doc.get("company_email_token") if doc else None
                finally:
                    cli.close()

            token = asyncio.new_event_loop().run_until_complete(fetch_token())
            assert token, "no company_email_token stored"

            # Hit verify
            vr = requests.get(f"{API}/verify-email/{token}", timeout=20)
            assert vr.status_code == 200
            assert "email-verified" in vr.text
            assert DELIVERED in vr.text

            # Verified flag should be true now
            r = requests.get(f"{API}/email-settings", headers=auth(tok), timeout=15)
            assert r.status_code == 200
            assert r.json()["verified"] is True

            # Invalid token -> expired page
            bad = requests.get(f"{API}/verify-email/not-a-real-token-xyz", timeout=15)
            assert bad.status_code == 200
            assert "expired" in bad.text.lower()
        finally:
            _cleanup_test_user(u)

    def test_delete_clears_company_email(self):
        u = register_test_user("em_del")
        try:
            tok = u["token"]
            requests.post(f"{API}/email-settings", headers=auth(tok),
                          json={"email": DELIVERED, "origin_url": BASE_URL}, timeout=30)
            r = requests.delete(f"{API}/email-settings", headers=auth(tok), timeout=15)
            assert r.status_code == 200
            d = r.json()
            assert d["company_email"] in (None, "")
            assert d["verified"] is False
        finally:
            _cleanup_test_user(u)


# ==================== Digest send-now uses reply_to ====================
class TestDigestSendNow:
    def test_send_now_returns_sent_one(self, demo_token):
        tok = demo_token
        # Ensure share exists
        r = requests.post(f"{API}/digest/share", headers=auth(tok), json={"origin_url": BASE_URL}, timeout=15)
        assert r.status_code == 200, r.text
        # Recipients: single delivered sandbox address
        put_r = requests.put(f"{API}/digest/settings", headers=auth(tok),
                             json={"recipients": [{"name": "TEST_Partner", "email": DELIVERED}],
                                   "auto": False}, timeout=15)
        assert put_r.status_code == 200, put_r.text
        # Call send-now (might be rate-limited if just sent)
        r = requests.post(f"{API}/digest/send-now?week=1", headers=auth(tok), timeout=60)
        if r.status_code == 429:
            # Wait a short while and try again or accept
            time.sleep(130)
            r = requests.post(f"{API}/digest/send-now?week=1", headers=auth(tok), timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["sent"] == 1, data
        assert data.get("failed", 0) == 0


# ==================== Sign-off notification (does not break 303) ====================
class TestSignoffNotification:
    def test_public_sign_still_303_even_if_email_fails(self):
        u = register_test_user("so_notif")
        try:
            tok = u["token"]
            assignee = f"TEST_Pat_{uuid.uuid4().hex[:6]}"
            s = _create_snag(tok, assignee)
            r = requests.post(f"{API}/snag-links", headers=auth(tok),
                              json={"assignee": assignee, "origin_url": BASE_URL}, timeout=15)
            token = r.json()["url"].rsplit("/", 1)[-1]
            _fix_snag(tok, s["id"])
            form_r = requests.post(f"{API}/s/{token}/sign",
                                   data={"name": "Pat Trade", "path": VALID_SIG_PATH, "width": 300, "height": 160},
                                   timeout=30, allow_redirects=False)
            assert form_r.status_code == 303, form_r.text
            assert "signed=1" in form_r.headers.get("location", "")
        finally:
            _cleanup_test_user(u)

    def test_signoff_notify_delivered_sandbox(self):
        """Register user with +signoff@resend.dev and verify sign still succeeds (email actually sends)."""
        em = "delivered+signoff@resend.dev"
        pw = "testpass1234"
        # Try register; if already exists (prev run), log in
        r = requests.post(f"{API}/auth/register", json={"name": "TEST_ User", "email": em, "password": pw}, timeout=30)
        if r.status_code != 200:
            r = requests.post(f"{API}/auth/login", json={"email": em, "password": pw}, timeout=30)
            assert r.status_code == 200, r.text
        tok = r.json()["access_token"]
        u = {"token": tok, "email": em, "password": pw}
        try:
            assignee = f"TEST_Jo_{uuid.uuid4().hex[:6]}"
            s = _create_snag(tok, assignee)
            r = requests.post(f"{API}/snag-links", headers=auth(tok),
                              json={"assignee": assignee, "origin_url": BASE_URL}, timeout=15)
            token = r.json()["url"].rsplit("/", 1)[-1]
            _fix_snag(tok, s["id"])
            form_r = requests.post(f"{API}/s/{token}/sign",
                                   data={"name": "Jo Trade", "path": VALID_SIG_PATH, "width": 300, "height": 160},
                                   timeout=30, allow_redirects=False)
            assert form_r.status_code == 303
        finally:
            _cleanup_test_user(u)


# ==================== Trade ratings ====================
class TestTradeRatings:
    def test_rate_blocked_before_owner_signoff(self):
        u = register_test_user("rat_block")
        try:
            tok = u["token"]
            assignee = f"TEST_Rate_{uuid.uuid4().hex[:6]}"
            _create_snag(tok, assignee)
            # before signoff -> 400
            r = requests.post(f"{API}/trade-ratings", headers=auth(tok),
                              json={"assignee": assignee, "stars": 5, "tags": ["Quality work"], "comment": "TEST_ok"},
                              timeout=15)
            assert r.status_code == 400, r.text
            assert "sign" in r.text.lower()
        finally:
            _cleanup_test_user(u)

    def test_rate_after_signoff_upsert_tag_filter(self):
        u = register_test_user("rat_ok")
        try:
            tok = u["token"]
            assignee = f"TEST_RateOK_{uuid.uuid4().hex[:6]}"
            s = _create_snag(tok, assignee)
            _fix_snag(tok, s["id"])
            _signoff(tok, assignee)

            r = requests.post(f"{API}/trade-ratings", headers=auth(tok),
                              json={"assignee": assignee, "stars": 4,
                                    "tags": ["Quality work", "Unknown Tag", "Tidy"],
                                    "comment": "TEST_good"}, timeout=15)
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["stars"] == 4
            assert d["assignee"] == assignee
            # Unknown tag filtered
            assert "Unknown Tag" not in d["tags"]
            assert set(d["tags"]).issubset({"Quality work", "On time", "Tidy", "Good value", "Communicative", "Would hire again"})
            assert "Quality work" in d["tags"] and "Tidy" in d["tags"]
            rating_id1 = d["id"]

            # Re-POST updates same doc (upsert)
            r2 = requests.post(f"{API}/trade-ratings", headers=auth(tok),
                               json={"assignee": assignee, "stars": 5,
                                     "tags": ["Would hire again"], "comment": "TEST_updated"}, timeout=15)
            assert r2.status_code == 200
            d2 = r2.json()
            assert d2["id"] == rating_id1, "upsert should keep same id"
            assert d2["stars"] == 5
            assert d2["tags"] == ["Would hire again"]
            assert d2["comment"] == "TEST_updated"

            # List endpoint returns it
            lst = requests.get(f"{API}/trade-ratings", headers=auth(tok), timeout=15)
            assert lst.status_code == 200
            assert any(x["assignee"] == assignee for x in lst.json())
            # ?project=active also works
            lst_active = requests.get(f"{API}/trade-ratings", headers=auth(tok), params={"project": "active"}, timeout=15)
            assert lst_active.status_code == 200
            assert any(x["assignee"] == assignee for x in lst_active.json())
        finally:
            _cleanup_test_user(u)

    def test_invalid_stars(self):
        u = register_test_user("rat_stars")
        try:
            tok = u["token"]
            assignee = f"TEST_Star_{uuid.uuid4().hex[:6]}"
            s = _create_snag(tok, assignee)
            _fix_snag(tok, s["id"])
            _signoff(tok, assignee)
            for bad in (0, 6):
                r = requests.post(f"{API}/trade-ratings", headers=auth(tok),
                                  json={"assignee": assignee, "stars": bad, "tags": [], "comment": ""},
                                  timeout=15)
                assert r.status_code == 422, f"stars={bad}: {r.status_code} {r.text}"
        finally:
            _cleanup_test_user(u)

    def test_trusted_trades_sorted_best_first_and_fields(self):
        u = register_test_user("rat_trust")
        try:
            tok = u["token"]
            # create 2 trades with different stars
            trades = [(f"TEST_Alpha_{uuid.uuid4().hex[:6]}", 5), (f"TEST_Beta_{uuid.uuid4().hex[:6]}", 3)]
            for name, stars in trades:
                s = _create_snag(tok, name)
                _fix_snag(tok, s["id"])
                _signoff(tok, name)
                r = requests.post(f"{API}/trade-ratings", headers=auth(tok),
                                  json={"assignee": name, "stars": stars,
                                        "tags": ["Quality work", "Tidy"], "comment": "TEST_"}, timeout=15)
                assert r.status_code == 200
            trusted = requests.get(f"{API}/trusted-trades", headers=auth(tok), timeout=15)
            assert trusted.status_code == 200
            data = trusted.json()
            names = [x["name"] for x in data]
            # Expect Alpha before Beta (higher avg first)
            alpha_name = trades[0][0]
            beta_name = trades[1][0]
            assert names.index(alpha_name) < names.index(beta_name), f"Expected {alpha_name} before {beta_name}: {names}"
            top = data[names.index(alpha_name)]
            # Fields present
            for k in ("name", "avg", "count", "top_tags", "contact_id"):
                assert k in top, f"missing {k}: {top}"
            assert top["avg"] == 5.0
            assert top["count"] == 1
        finally:
            _cleanup_test_user(u)

    def test_trusted_trades_contact_id_populated_when_contact_matches(self):
        u = register_test_user("rat_contact")
        try:
            tok = u["token"]
            # create a trade contact; use the exact same name as the assignee
            cname = f"TEST_ContactTrade_{uuid.uuid4().hex[:6]}"
            c = requests.post(f"{API}/contacts", headers=auth(tok),
                              json={"kind": "trade", "name": cname, "role": "Plumber"}, timeout=15)
            assert c.status_code == 200, c.text
            cid = c.json()["id"]
            s = _create_snag(tok, cname)
            _fix_snag(tok, s["id"])
            _signoff(tok, cname)
            r = requests.post(f"{API}/trade-ratings", headers=auth(tok),
                              json={"assignee": cname, "stars": 5,
                                    "tags": ["Quality work"], "comment": ""}, timeout=15)
            assert r.status_code == 200
            assert r.json().get("contact_id") == cid

            trusted = requests.get(f"{API}/trusted-trades", headers=auth(tok), timeout=15).json()
            match = next((x for x in trusted if x["name"] == cname), None)
            assert match is not None
            assert match["contact_id"] == cid
            assert match.get("role") == "Plumber"
        finally:
            _cleanup_test_user(u)

    def test_account_deletion_removes_trade_ratings(self):
        u = register_test_user("rat_del")
        tok = u["token"]
        assignee = f"TEST_DelRate_{uuid.uuid4().hex[:6]}"
        s = _create_snag(tok, assignee)
        _fix_snag(tok, s["id"])
        _signoff(tok, assignee)
        r = requests.post(f"{API}/trade-ratings", headers=auth(tok),
                          json={"assignee": assignee, "stars": 5,
                                "tags": [], "comment": ""}, timeout=15)
        assert r.status_code == 200
        # Delete account
        r = requests.delete(f"{API}/auth/account", headers=auth(tok),
                            json={"password": u["password"]}, timeout=20)
        assert r.status_code == 200
        # Try listing ratings -> unauthorised now
        r = requests.get(f"{API}/trade-ratings", headers=auth(tok), timeout=15)
        assert r.status_code in (401, 404)


# ==================== Cleanup demo artifacts ====================
@pytest.fixture(scope="module", autouse=True)
def demo_cleanup(demo_token):
    yield
    tok = demo_token
    try:
        requests.post(f"{API}/auth/plan", headers=auth(tok), json={"plan": "basic"}, timeout=15)
    except Exception:
        pass
    # Remove TEST_ snags on demo project
    try:
        snags = requests.get(f"{API}/snags", headers=auth(tok), timeout=15).json()
        for s in snags:
            if (s.get("assignee") or "").startswith("TEST_") or (s.get("description") or "").startswith("TEST_"):
                requests.delete(f"{API}/snags/{s['id']}", headers=auth(tok), timeout=15)
    except Exception:
        pass
    # Reset digest + email-settings
    try:
        requests.put(f"{API}/digest/settings", headers=auth(tok),
                     json={"recipients": [], "auto": False}, timeout=15)
        requests.delete(f"{API}/digest/share", headers=auth(tok), timeout=15)
        requests.delete(f"{API}/email-settings", headers=auth(tok), timeout=15)
    except Exception:
        pass
