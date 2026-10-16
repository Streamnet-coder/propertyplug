"""Iteration 26 — Project activity log + Lead document requests.

Scope:
- Activity log middleware: successful POST/PUT/DELETE on project data routes recorded, 4xx not logged,
  verbs translated ('added budget item'/'updated project details'/'deleted snag'), owner and co-owner
  share the same log for the same project, newest first.
- Lead doc requests: lead posts, non-lead 403, length validation, owner sees them (GET /portal-doc-requests),
  owner PUT fulfilled -> doc_ids added to all team members of same company, declined keeps docs intact.
- Owner portal activity shows kind=doc_request after a request.
"""
import os
import sys
import uuid
import asyncio
import pytest
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
sys.path.insert(0, "/app/backend")

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ["EXPO_BACKEND_URL"]).rstrip("/")
API = f"{BASE_URL}/api"


def _run(fn):
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


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _login(email, pwd):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _register(name, email, pwd):
    r = requests.post(f"{API}/auth/register", json={"name": name, "email": email, "password": pwd}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _delete_user_by_email(email):
    async def fn(db):
        u = await db.users.find_one({"email": email}, {"_id": 1})
        if not u:
            return
        uid = str(u["_id"])
        for coll in ("projects", "line_items", "receipts", "snags", "snag_links", "documents",
                     "doc_folders", "milestones", "quote_requests", "stage_payments", "contacts",
                     "media", "shopping_items", "estimates", "payment_transactions", "planning_apps",
                     "messages", "trade_ratings", "snag_signoffs", "project_activity",
                     "portal_members", "portal_activity", "portal_questions", "portal_doc_requests"):
            try:
                await db[coll].delete_many({"$or": [{"user_id": uid}, {"owner_id": uid}]})
            except Exception:
                pass
        await db.co_owners.delete_many({"$or": [{"owner_id": uid}, {"email": email}]})
        await db.users.delete_one({"_id": u["_id"]})
    _run(fn)


def _reset_demo():
    async def fn(db):
        u = await db.users.find_one({"email": "demo@mybuilder.app"}, {"_id": 1})
        if not u:
            return
        uid = str(u["_id"])
        await db.users.update_one({"_id": u["_id"]}, {"$set": {"acting_owner_id": None}})
        await db.co_owners.delete_many({"owner_id": uid})
        # Clear activity logs so each test gets a clean slate
        await db.project_activity.delete_many({"owner_id": uid})
        await db.portal_doc_requests.delete_many({"owner_id": uid})
        await db.portal_activity.delete_many({"owner_id": uid, "kind": "doc_request"})
    _run(fn)


# ---------- Fixtures ----------
@pytest.fixture(scope="module")
def owner():
    tok = _login("demo@mybuilder.app", "demo1234")
    _reset_demo()
    me = requests.get(f"{API}/auth/me", headers=_h(tok)).json()
    projs = requests.get(f"{API}/projects", headers=_h(tok)).json()
    nv = next((p for p in projs if "Nottingham" in p.get("name", "")), projs[0])
    requests.post(f"{API}/projects/{nv['id']}/activate", headers=_h(tok))
    yield {"token": tok, "h": _h(tok), "id": me["id"], "email": me["email"], "name": me["name"],
           "project_id": nv["id"], "project_name": nv["name"]}
    _reset_demo()


# =============================================================================
# A) Project activity log
# =============================================================================
class TestActivityLog:
    def test_project_details_update_logged_as_updated(self, owner):
        _reset_demo()
        pname = owner["project_name"]
        r = requests.put(f"{API}/project", headers=owner["h"], json={"name": pname})
        assert r.status_code == 200, r.text
        acts = requests.get(f"{API}/project-activity", headers=owner["h"]).json()
        assert len(acts) >= 1
        a0 = acts[0]
        assert a0["action"] == "updated project details"
        assert a0["is_owner"] is True
        assert a0["is_you"] is True
        assert a0["actor_name"] == owner["name"]
        assert "at" in a0

    def test_line_item_added_and_deleted_logged(self, owner):
        _reset_demo()
        # Add budget item
        r = requests.post(f"{API}/line-items", headers=owner["h"],
                          json={"category": "Hard Cost", "name": "TEST_item", "amount": 10.0, "kind": "budget"})
        assert r.status_code in (200, 201), r.text
        iid = r.json()["id"]
        # Delete it
        d = requests.delete(f"{API}/line-items/{iid}", headers=owner["h"])
        assert d.status_code == 200
        acts = requests.get(f"{API}/project-activity", headers=owner["h"]).json()
        actions = [a["action"] for a in acts]
        assert "added budget item" in actions
        assert "deleted budget item" in actions
        # Newest first
        assert acts[0]["action"] == "deleted budget item"

    def test_snag_add_logged(self, owner):
        _reset_demo()
        r = requests.post(f"{API}/snags", headers=owner["h"],
                          json={"room": "Kitchen", "description": "TEST_snag", "severity": "medium"})
        assert r.status_code in (200, 201), r.text
        sid = r.json()["id"]
        acts = requests.get(f"{API}/project-activity", headers=owner["h"]).json()
        assert any(a["action"] == "added snag" for a in acts)
        # Cleanup
        requests.delete(f"{API}/snags/{sid}", headers=owner["h"])

    def test_failed_4xx_not_logged(self, owner):
        _reset_demo()
        # 422/400: missing required
        r = requests.post(f"{API}/line-items", headers=owner["h"], json={})
        assert r.status_code >= 400
        acts = requests.get(f"{API}/project-activity", headers=owner["h"]).json()
        assert len(acts) == 0, f"Failed request should not be logged, got: {acts}"

    def test_activity_scoped_to_active_project(self, owner):
        _reset_demo()
        projs = requests.get(f"{API}/projects", headers=owner["h"]).json()
        if len(projs) < 2:
            pytest.skip("Need 2+ projects to test scoping")
        other = next(p for p in projs if p["id"] != owner["project_id"])
        # Switch, write, switch back
        requests.post(f"{API}/projects/{other['id']}/activate", headers=owner["h"])
        r = requests.put(f"{API}/project", headers=owner["h"], json={"name": other["name"]})
        assert r.status_code == 200
        # Back to Nottingham
        requests.post(f"{API}/projects/{owner['project_id']}/activate", headers=owner["h"])
        acts = requests.get(f"{API}/project-activity", headers=owner["h"]).json()
        # The 'updated project details' happened on *other* project, must not leak
        assert all("updated project details" not in a["action"] or a["action"] == "updated project details" for a in acts)
        # Specifically, no entries at all here (we just activated this project; no writes to it)
        assert len(acts) == 0


# =============================================================================
# B) Co-owner sees + writes to same log
# =============================================================================
class TestCoOwnerActivity:
    def test_coowner_sees_owner_log_and_contributes(self, owner):
        _reset_demo()
        em = f"test_co26_{uuid.uuid4().hex[:8]}@example.com"
        reg = _register("Casey Co26", em, "cowner1234")
        co_tok = reg["access_token"]
        co_id = reg["user"]["id"]
        co_h = _h(co_tok)
        try:
            # Invite
            r = requests.post(f"{API}/co-owners", headers=owner["h"], json={"email": em})
            assert r.status_code == 200, r.text
            # Owner writes something
            r2 = requests.put(f"{API}/project", headers=owner["h"], json={"name": owner["project_name"]})
            assert r2.status_code == 200
            # Co-owner activates the demo project
            r3 = requests.post(f"{API}/projects/{owner['project_id']}/activate", headers=co_h)
            assert r3.status_code == 200, r3.text
            # Co-owner writes something: add a snag
            r4 = requests.post(f"{API}/snags", headers=co_h,
                               json={"room": "Hall", "description": "TEST_cosnag", "severity": "low"})
            assert r4.status_code in (200, 201), r4.text
            sid = r4.json()["id"]

            # Owner view: should see both entries
            o_acts = requests.get(f"{API}/project-activity", headers=owner["h"]).json()
            actions_o = [a["action"] for a in o_acts]
            assert "updated project details" in actions_o
            assert "added snag" in actions_o
            # The snag entry attributed to co-owner, with is_you False and is_owner False
            snag_entry = next(a for a in o_acts if a["action"] == "added snag")
            assert snag_entry["is_owner"] is False
            assert snag_entry["is_you"] is False
            assert snag_entry["actor_name"] == "Casey Co26"

            # Co-owner view: same log; is_you flipped for the snag they added
            c_acts = requests.get(f"{API}/project-activity", headers=co_h).json()
            # Same length (same project log)
            assert len(c_acts) == len(o_acts)
            c_snag = next(a for a in c_acts if a["action"] == "added snag")
            assert c_snag["is_you"] is True
            assert c_snag["is_owner"] is False
            # Owner's update seen by co-owner as other actor
            c_upd = next(a for a in c_acts if a["action"] == "updated project details")
            assert c_upd["is_you"] is False
            assert c_upd["is_owner"] is True
            assert c_upd["actor_name"] == owner["name"]

            # Cleanup snag
            requests.delete(f"{API}/snags/{sid}", headers=co_h)
        finally:
            _delete_user_by_email(em)
            _reset_demo()


# =============================================================================
# C) Lead doc requests
# =============================================================================
def _get_or_make_lead_member(owner, email, name="Lead Pat", company="TEST_Northfield"):
    """Create portal member with company+is_lead=true for the active project."""
    # Create
    r = requests.post(f"{API}/portal-members", headers=owner["h"], json={
        "name": name, "email": email, "role": "Lender", "company": company,
        "doc_ids": [], "digest": True, "origin_url": BASE_URL,
    })
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    # Promote to lead
    r2 = requests.put(f"{API}/portal-members/{mid}", headers=owner["h"], json={"is_lead": True})
    assert r2.status_code == 200, r2.text
    assert r2.json()["is_lead"] is True
    return mid


def _portal_token(email):
    """Issue a portal JWT (bypasses email code)."""
    import jwt as pyjwt
    secret = os.environ["JWT_SECRET"] + "|portal"
    n = datetime.now(timezone.utc)
    return pyjwt.encode({"sub": email, "typ": "portal", "iat": n, "exp": n + timedelta(days=7)},
                        secret, algorithm="HS256")


def _mk_doc(owner, title="TEST_cert.pdf"):
    """Create a tiny document on the active project (owner side) and return its id."""
    files = {"file": (title, b"PDF-fake", "application/pdf")}
    data = {"title": title, "doc_type": "Building control"}
    h = {"Authorization": owner["h"]["Authorization"]}  # no Content-Type for multipart
    r = requests.post(f"{API}/documents", headers=h, data=data, files=files)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


class TestLeadDocRequests:
    def test_non_lead_cannot_post(self, owner):
        _reset_demo()
        em = f"test_nl_{uuid.uuid4().hex[:8]}@example.com"
        # Create member WITHOUT is_lead
        r = requests.post(f"{API}/portal-members", headers=owner["h"], json={
            "name": "Non Lead", "email": em, "role": "Lender", "company": "TEST_NL",
            "doc_ids": [], "digest": True, "origin_url": BASE_URL,
        })
        assert r.status_code == 200
        mid = r.json()["id"]
        tok = _portal_token(em)
        resp = requests.post(f"{API}/portal/projects/{owner['project_id']}/doc-requests",
                             headers=_h(tok), json={"title": "TEST_cert", "note": ""})
        assert resp.status_code == 403, resp.text
        # Cleanup
        requests.delete(f"{API}/portal-members/{mid}", headers=owner["h"])

    def test_title_length_validation(self, owner):
        _reset_demo()
        em = f"test_v_{uuid.uuid4().hex[:8]}@example.com"
        mid = _get_or_make_lead_member(owner, em, name="Val Lead", company="TEST_Val")
        try:
            tok = _portal_token(em)
            # Too short
            r1 = requests.post(f"{API}/portal/projects/{owner['project_id']}/doc-requests",
                               headers=_h(tok), json={"title": "a", "note": ""})
            assert r1.status_code in (400, 422), r1.text
            # Too long (>120)
            r2 = requests.post(f"{API}/portal/projects/{owner['project_id']}/doc-requests",
                               headers=_h(tok), json={"title": "x" * 121, "note": ""})
            assert r2.status_code in (400, 422), r2.text
        finally:
            requests.delete(f"{API}/portal-members/{mid}", headers=owner["h"])

    def test_full_fulfilled_flow_shares_with_whole_team(self, owner):
        _reset_demo()
        pid = owner["project_id"]
        em1 = f"test_lead_{uuid.uuid4().hex[:8]}@example.com"
        em2 = f"test_tm_{uuid.uuid4().hex[:8]}@example.com"
        # Make lead
        lead_id = _get_or_make_lead_member(owner, em1, name="Lead Pat", company="TEST_Co")
        # Add a teammate directly via owner invite (same company) — simpler than portal team invite
        r = requests.post(f"{API}/portal-members", headers=owner["h"], json={
            "name": "Team Mate", "email": em2, "role": "Lender", "company": "TEST_Co",
            "doc_ids": [], "digest": True, "origin_url": BASE_URL,
        })
        assert r.status_code == 200
        tm_id = r.json()["id"]
        # Owner uploads a doc on active project
        did = _mk_doc(owner, title="TEST_cert.pdf")
        try:
            tok = _portal_token(em1)
            # Lead creates request
            rq = requests.post(f"{API}/portal/projects/{pid}/doc-requests",
                               headers=_h(tok), json={"title": "Electrical certificate", "note": "latest version"})
            assert rq.status_code == 200, rq.text
            rid = rq.json()["id"]
            assert rq.json()["status"] == "open"

            # Lead GET lists their company's requests
            lst = requests.get(f"{API}/portal/projects/{pid}/doc-requests", headers=_h(tok)).json()
            assert any(x["id"] == rid for x in lst)

            # Owner GET
            o_lst = requests.get(f"{API}/portal-doc-requests", headers=owner["h"]).json()
            assert any(x["id"] == rid for x in o_lst)

            # Owner portal-activity shows kind doc_request
            pa = requests.get(f"{API}/portal-activity", headers=owner["h"]).json()
            assert any(x.get("kind") == "doc_request" for x in pa), f"portal_activity: {pa}"

            # Owner fulfilled
            ans = requests.put(f"{API}/portal-doc-requests/{rid}", headers=owner["h"],
                               json={"status": "fulfilled", "reply": "Here it is", "doc_ids": [did]})
            assert ans.status_code == 200, ans.text
            body = ans.json()
            assert body["status"] == "fulfilled"
            assert body["doc_titles"] == ["TEST_cert.pdf"]

            # Verify both members have doc_id now
            members = requests.get(f"{API}/portal-members", headers=owner["h"]).json()
            lead_m = next(m for m in members if m["id"] == lead_id)
            tm_m = next(m for m in members if m["id"] == tm_id)
            assert did in lead_m["doc_ids"], f"Lead doc_ids: {lead_m['doc_ids']}"
            assert did in tm_m["doc_ids"], f"Teammate doc_ids: {tm_m['doc_ids']}"
        finally:
            requests.delete(f"{API}/portal-members/{lead_id}", headers=owner["h"])
            requests.delete(f"{API}/portal-members/{tm_id}", headers=owner["h"])
            requests.delete(f"{API}/documents/{did}", headers=owner["h"])

    def test_declined_keeps_docs_unchanged(self, owner):
        _reset_demo()
        pid = owner["project_id"]
        em = f"test_lead2_{uuid.uuid4().hex[:8]}@example.com"
        lead_id = _get_or_make_lead_member(owner, em, name="Lead2", company="TEST_Co2")
        did = _mk_doc(owner, title="TEST_decline.pdf")
        try:
            tok = _portal_token(em)
            rq = requests.post(f"{API}/portal/projects/{pid}/doc-requests",
                               headers=_h(tok), json={"title": "Appraisal report", "note": ""})
            assert rq.status_code == 200
            rid = rq.json()["id"]
            # Snapshot doc_ids before
            m_before = next(m for m in requests.get(f"{API}/portal-members", headers=owner["h"]).json()
                            if m["id"] == lead_id)
            # Decline with doc_ids=[did] — must NOT share
            ans = requests.put(f"{API}/portal-doc-requests/{rid}", headers=owner["h"],
                               json={"status": "declined", "reply": "Not available", "doc_ids": [did]})
            assert ans.status_code == 200, ans.text
            assert ans.json()["status"] == "declined"
            m_after = next(m for m in requests.get(f"{API}/portal-members", headers=owner["h"]).json()
                           if m["id"] == lead_id)
            assert m_after["doc_ids"] == m_before["doc_ids"], \
                f"declined changed doc_ids: before={m_before['doc_ids']} after={m_after['doc_ids']}"
            assert did not in m_after["doc_ids"]
        finally:
            requests.delete(f"{API}/portal-members/{lead_id}", headers=owner["h"])
            requests.delete(f"{API}/documents/{did}", headers=owner["h"])


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
