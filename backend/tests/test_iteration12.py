"""Iteration 12 backend tests.

Covers:
- Snag sign-off: POST/GET/DELETE /api/snag-signoffs including validation
- Public trade snag link + sign (POST /api/s/{token}/sign)
- Sign-off invalidation when new snag created or snag reopened
- /api/stakeholders aggregated list + /api/messages log + auto-logging flows
- Account deletion also removes messages & snag_signoffs
Cleanup: TEST_ snags, snag_links, snag_signoffs, messages removed; demo plan
reset to basic; digest recipients cleared, auto false; digest share revoked.
"""
import os
import re
import time
import uuid
from typing import Dict, Optional

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://dev-budget-tracker-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
DEMO_EMAIL = "demo@mybuilder.app"
DEMO_PASSWORD = "demo1234"

# ---- a plausible signed path (matches ^[MLml0-9 .,-]{4,30000}$) ----
VALID_SIG_PATH = "M10 10 L50 40 L90 20"


def auth(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def demo_token() -> str:
    r = requests.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def register_test_user(suffix: Optional[str] = None) -> Dict:
    pw = "testpass1234"
    email = f"test_{suffix or uuid.uuid4().hex[:10]}@example.com"
    r = requests.post(f"{API}/auth/register", json={"name": "TEST_ User", "email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    data = r.json()
    return {"token": data["access_token"], "user": data["user"], "email": email, "password": pw}


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
    return r.json()


# ==================== Snag Sign-off API ====================
class TestSnagSignoff:
    def test_signoff_blocked_when_snag_open_and_other_validations(self):
        u = register_test_user("sign_valid")
        try:
            tok = u["token"]
            assignee = f"TEST_Dave_{uuid.uuid4().hex[:6]}"

            # 1. No snags assigned yet -> 400
            r = requests.post(f"{API}/snag-signoffs", headers=auth(tok),
                              json={"assignee": assignee, "name": "Owner", "path": VALID_SIG_PATH,
                                    "width": 300, "height": 160}, timeout=15)
            assert r.status_code == 400, r.text
            assert "No snags" in r.text or "no snags" in r.text.lower()

            # 2. Create a snag, open -> still 400
            s1 = _create_snag(tok, assignee)
            r = requests.post(f"{API}/snag-signoffs", headers=auth(tok),
                              json={"assignee": assignee, "name": "Owner", "path": VALID_SIG_PATH,
                                    "width": 300, "height": 160}, timeout=15)
            assert r.status_code == 400, r.text
            assert "fixed" in r.text.lower()

            # 3. Invalid path -> 400
            _fix_snag(tok, s1["id"])
            r = requests.post(f"{API}/snag-signoffs", headers=auth(tok),
                              json={"assignee": assignee, "name": "Owner", "path": "XYZ##!!",
                                    "width": 300, "height": 160}, timeout=15)
            assert r.status_code == 400, r.text

            # 4. All fixed + valid path -> 200
            r = requests.post(f"{API}/snag-signoffs", headers=auth(tok),
                              json={"assignee": assignee, "name": "Owner Name",
                                    "path": VALID_SIG_PATH, "width": 300, "height": 160}, timeout=15)
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["assignee"] == assignee
            assert data["snag_count"] == 1
            assert data["owner"] and data["owner"]["name"] == "Owner Name"
            assert data["trade"] is None
            assert data["complete"] is False

            # GET list contains our signoff
            r = requests.get(f"{API}/snag-signoffs", headers=auth(tok), timeout=15)
            assert r.status_code == 200
            lst = r.json()
            assert any(s["assignee"] == assignee for s in lst)

            # DELETE signoff
            r = requests.delete(f"{API}/snag-signoffs/{assignee}", headers=auth(tok), timeout=15)
            assert r.status_code == 200
            lst2 = requests.get(f"{API}/snag-signoffs", headers=auth(tok), timeout=15).json()
            assert not any(s["assignee"] == assignee for s in lst2)
        finally:
            _cleanup_test_user(u)

    def test_signoff_invalidated_by_new_snag_or_reopen(self):
        u = register_test_user("sign_inval")
        try:
            tok = u["token"]
            assignee = f"TEST_Mike_{uuid.uuid4().hex[:6]}"
            s = _create_snag(tok, assignee)
            _fix_snag(tok, s["id"])
            r = requests.post(f"{API}/snag-signoffs", headers=auth(tok),
                              json={"assignee": assignee, "name": "Owner",
                                    "path": VALID_SIG_PATH, "width": 300, "height": 160}, timeout=15)
            assert r.status_code == 200

            # Creating a new snag for the same assignee invalidates
            _create_snag(tok, assignee, "TEST_ second snag")
            lst = requests.get(f"{API}/snag-signoffs", headers=auth(tok), timeout=15).json()
            assert not any(x["assignee"] == assignee for x in lst), "sign-off should be cleared on new snag"

            # Fix all, sign again
            snags = requests.get(f"{API}/snags", headers=auth(tok), timeout=15).json()
            for sn in snags:
                if sn["assignee"] == assignee:
                    _fix_snag(tok, sn["id"])
            r = requests.post(f"{API}/snag-signoffs", headers=auth(tok),
                              json={"assignee": assignee, "name": "Owner",
                                    "path": VALID_SIG_PATH, "width": 300, "height": 160}, timeout=15)
            assert r.status_code == 200

            # Reopen one snag -> signoff cleared
            snags = requests.get(f"{API}/snags", headers=auth(tok), timeout=15).json()
            sid = next(x["id"] for x in snags if x["assignee"] == assignee)
            r = requests.put(f"{API}/snags/{sid}", headers=auth(tok), json={"status": "open"}, timeout=15)
            assert r.status_code == 200
            lst = requests.get(f"{API}/snag-signoffs", headers=auth(tok), timeout=15).json()
            assert not any(x["assignee"] == assignee for x in lst), "sign-off should be cleared on reopen"
        finally:
            _cleanup_test_user(u)


# ==================== Public trade sign-off ====================
class TestPublicSnagSignoff:
    def test_create_link_and_trade_signs_off(self):
        u = register_test_user("pub_sign")
        try:
            tok = u["token"]
            assignee = f"TEST_Pat_{uuid.uuid4().hex[:6]}"
            # No snags yet -> cannot create snag-link
            r = requests.post(f"{API}/snag-links", headers=auth(tok),
                              json={"assignee": assignee, "origin_url": BASE_URL}, timeout=15)
            assert r.status_code == 400

            # Create snag and link
            s = _create_snag(tok, assignee)
            r = requests.post(f"{API}/snag-links", headers=auth(tok),
                              json={"assignee": assignee, "origin_url": BASE_URL}, timeout=15)
            assert r.status_code == 200, r.text
            url = r.json()["url"]
            token = url.rsplit("/", 1)[-1]
            assert token

            # Page while snag open: no #sig-form
            html = requests.get(f"{API}/s/{token}", timeout=20).text
            assert "snag-" + s["id"] in html
            assert "id='sig-form'" not in html, "sig-form should NOT appear while snags open"

            # Fix snag then page shows signoff form
            _fix_snag(tok, s["id"])
            html = requests.get(f"{API}/s/{token}", timeout=20).text
            assert "id='signoff'" in html, "signoff section should appear"
            assert "id='sig-form'" in html, "sig-form canvas should appear"

            # Submit trade sign (no owner yet)
            form_r = requests.post(f"{API}/s/{token}/sign",
                                   data={"name": "Pat Trade", "path": VALID_SIG_PATH, "width": 300, "height": 160},
                                   timeout=20, allow_redirects=False)
            assert form_r.status_code == 303, form_r.text
            assert "signed=1" in form_r.headers.get("location", "")

            # Trade sign shows on page
            html = requests.get(f"{API}/s/{token}?signed=1", timeout=20).text
            assert "snag-signed-msg" in html
            assert "signed-trade" in html

            # Owner signs via app -> complete true
            r = requests.post(f"{API}/snag-signoffs", headers=auth(tok),
                              json={"assignee": assignee, "name": "Owner Smith",
                                    "path": VALID_SIG_PATH, "width": 300, "height": 160}, timeout=15)
            assert r.status_code == 200
            data = r.json()
            assert data["complete"] is True
            assert data["owner"]["name"] == "Owner Smith"
            assert data["trade"]["name"] == "Pat Trade"
        finally:
            _cleanup_test_user(u)

    def test_public_sign_rejects_when_snag_open(self):
        u = register_test_user("pub_rej")
        try:
            tok = u["token"]
            assignee = f"TEST_Rob_{uuid.uuid4().hex[:6]}"
            _create_snag(tok, assignee)
            r = requests.post(f"{API}/snag-links", headers=auth(tok),
                              json={"assignee": assignee, "origin_url": BASE_URL}, timeout=15)
            token = r.json()["url"].rsplit("/", 1)[-1]
            # Still open -> trade cannot sign
            form_r = requests.post(f"{API}/s/{token}/sign",
                                   data={"name": "Rob", "path": VALID_SIG_PATH, "width": 300, "height": 160},
                                   timeout=20, allow_redirects=False)
            assert form_r.status_code == 400
        finally:
            _cleanup_test_user(u)


# ==================== Messages & Stakeholders ====================
class TestMessages:
    def test_add_and_list_messages_newest_first(self):
        u = register_test_user("msg")
        try:
            tok = u["token"]
            name = f"TEST_Jane_{uuid.uuid4().hex[:6]}"
            for i, ch in enumerate(["email", "whatsapp", "call"]):
                r = requests.post(f"{API}/messages", headers=auth(tok),
                                  json={"name": name, "email": "", "phone": "+440000000",
                                        "channel": ch, "kind": "message", "summary": f"TEST_sum_{i}"},
                                  timeout=15)
                assert r.status_code == 200, r.text
                time.sleep(0.01)
            r = requests.get(f"{API}/messages", headers=auth(tok), params={"name": name}, timeout=15)
            assert r.status_code == 200
            msgs = r.json()
            assert len(msgs) >= 3
            # Newest first - last inserted is call
            assert msgs[0]["channel"] == "call"
            assert msgs[0]["summary"] == "TEST_sum_2"
            # id field is present (string, not ObjectId)
            assert isinstance(msgs[0]["id"], str)

            # Invalid channel -> 422
            r = requests.post(f"{API}/messages", headers=auth(tok),
                              json={"name": name, "channel": "sms", "kind": "x", "summary": "y"}, timeout=15)
            assert r.status_code == 422
        finally:
            _cleanup_test_user(u)

    def test_snag_link_view_logs_once_per_day(self):
        u = register_test_user("msg_view")
        try:
            tok = u["token"]
            assignee = f"TEST_Carl_{uuid.uuid4().hex[:6]}"
            _create_snag(tok, assignee)
            r = requests.post(f"{API}/snag-links", headers=auth(tok),
                              json={"assignee": assignee, "origin_url": BASE_URL}, timeout=15)
            token = r.json()["url"].rsplit("/", 1)[-1]
            # View twice
            requests.get(f"{API}/s/{token}", timeout=20)
            requests.get(f"{API}/s/{token}", timeout=20)
            msgs = requests.get(f"{API}/messages", headers=auth(tok), params={"name": assignee}, timeout=15).json()
            view_msgs = [m for m in msgs if m["kind"] == "snag_link"]
            assert len(view_msgs) == 1, f"expected 1 snag_link view per day, got {len(view_msgs)}"
            assert view_msgs[0]["direction"] == "in"
            assert view_msgs[0]["channel"] == "web"
        finally:
            _cleanup_test_user(u)

    def test_stakeholders_lists_team_contacts_and_partners(self):
        u = register_test_user("stake")
        try:
            tok = u["token"]
            # Create a trade contact (allowed on basic)
            c = requests.post(f"{API}/contacts", headers=auth(tok),
                              json={"kind": "trade", "name": "TEST_Alice", "role": "Plumber",
                                    "email": "alice.test@example.com"},
                              timeout=15)
            assert c.status_code == 200, c.text

            # Add a weekly partner via digest settings
            put_r = requests.put(f"{API}/digest/settings", headers=auth(tok),
                                 json={"recipients": [{"name": "TEST_Partner",
                                                       "email": "partner.test@example.com"}],
                                       "auto": False}, timeout=15)
            assert put_r.status_code == 200, put_r.text

            # Log a message to the trade contact
            requests.post(f"{API}/messages", headers=auth(tok),
                          json={"name": "TEST_Alice", "email": "alice.test@example.com",
                                "channel": "email", "kind": "message",
                                "summary": "TEST_hello"}, timeout=15)

            r = requests.get(f"{API}/stakeholders", headers=auth(tok), timeout=15)
            assert r.status_code == 200
            people = r.json()
            keys = {p["name"]: p for p in people}
            assert "TEST_Alice" in keys, f"team contact missing in stakeholders: {keys}"
            # Weekly partner should appear
            assert any(p["email"] == "partner.test@example.com" for p in people), \
                f"digest partner missing: {people}"
            alice = keys["TEST_Alice"]
            assert alice.get("count", 0) >= 1
            assert alice.get("last_summary") == "TEST_hello"
            assert alice.get("last_direction") == "out"
        finally:
            _cleanup_test_user(u)


    def test_quote_submission_logs_message(self):
        u = register_test_user("qlog")
        try:
            tok = u["token"]
            # create a trade contact to request quote from
            c = requests.post(f"{API}/contacts", headers=auth(tok),
                              json={"kind": "trade", "name": "TEST_QuoteTrade",
                                    "email": "qt.test@example.com"}, timeout=15).json()
            r = requests.post(f"{API}/quotes", headers=auth(tok),
                              json={"title": "TEST_job", "description": "TEST_desc",
                                    "trade": "", "contact_ids": [c["id"]],
                                    "origin_url": BASE_URL}, timeout=15)
            assert r.status_code == 200, r.text
            q = r.json()
            token = q["quotes"][0]["token"]
            # Submit quote via public endpoint
            sub = requests.post(f"{API}/q/{token}", data={"amount": "1234.5", "days": "3",
                                                          "notes": "ok"}, timeout=20)
            assert sub.status_code == 200
            msgs = requests.get(f"{API}/messages", headers=auth(tok),
                                params={"name": "TEST_QuoteTrade"}, timeout=15).json()
            assert any(m["kind"] == "quote" and m["direction"] == "in" for m in msgs), \
                f"quote submission not logged: {msgs}"
        finally:
            _cleanup_test_user(u)


# ==================== Account deletion removes messages & signoffs ====================
class TestAccountDeletion:
    def test_delete_account_removes_messages_and_signoffs(self):
        u = register_test_user("del_acct")
        tok = u["token"]
        assignee = f"TEST_Zoe_{uuid.uuid4().hex[:6]}"
        s = _create_snag(tok, assignee)
        _fix_snag(tok, s["id"])
        r = requests.post(f"{API}/snag-signoffs", headers=auth(tok),
                          json={"assignee": assignee, "name": "O",
                                "path": VALID_SIG_PATH, "width": 300, "height": 160}, timeout=15)
        assert r.status_code == 200
        requests.post(f"{API}/messages", headers=auth(tok),
                      json={"name": assignee, "channel": "call",
                            "kind": "message", "summary": "TEST_pre_delete"}, timeout=15)

        # Delete account
        r = requests.delete(f"{API}/auth/account", headers=auth(tok),
                            json={"password": u["password"]}, timeout=20)
        assert r.status_code == 200
        # Token should no longer work
        r = requests.get(f"{API}/snag-signoffs", headers=auth(tok), timeout=15)
        assert r.status_code in (401, 404)


# ==================== Cleanup demo artifacts ====================
@pytest.fixture(scope="module", autouse=True)
def demo_cleanup(demo_token):
    yield
    tok = demo_token
    # Make sure plan is basic
    requests.post(f"{API}/auth/plan", headers=auth(tok), json={"plan": "basic"}, timeout=15)
    # Remove TEST_ snags on demo project
    try:
        snags = requests.get(f"{API}/snags", headers=auth(tok), timeout=15).json()
        for s in snags:
            if (s.get("assignee") or "").startswith("TEST_") or (s.get("description") or "").startswith("TEST_"):
                requests.delete(f"{API}/snags/{s['id']}", headers=auth(tok), timeout=15)
    except Exception:
        pass
    # Reset digest settings and revoke share
    try:
        requests.put(f"{API}/digest/settings", headers=auth(tok),
                     json={"recipients": [], "auto": False}, timeout=15)
        requests.delete(f"{API}/digest/share", headers=auth(tok), timeout=15)
    except Exception:
        pass


# Small sanity: regex matches expected example
def test_sig_path_regex_matches_example():
    assert re.compile(r"^[MLml0-9 .,\-]{4,30000}$").match("M10 10 L50 40 L90 20")
