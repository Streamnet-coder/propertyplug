"""Iteration 41 — Property report-link + team assign + job page.

Covers: /api/report-link (GET/POST/DELETE), public /api/r/{token} (HTML form + POST
submit + validation + revoked), /api/snag-assignees, /api/snags/{id}/assign (team/trade,
scoping, email, 404s), public /api/job/{token} (page + fix + photo), snag assignee
rename clears assigned_to, /api/inbox mine flag + sort + repair kind for report_link.
"""
import io
import os
import sys
import time
import uuid

import pytest
import requests
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://dev-budget-tracker-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"
MONGO = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

TAG = f"iter41_{uuid.uuid4().hex[:6]}"
RUN = {"users": [], "snags": [], "contacts": [], "co_owners": [], "report_links": [], "projects": []}
STATE: dict = {}


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def owner_sess():
    """Demo owner session (demo@mybuilder.app)."""
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": "demo@mybuilder.app", "password": "demo1234"})
    assert r.status_code == 200, r.text
    j = r.json()
    s.headers["Authorization"] = f"Bearer {j.get('access_token') or j.get('token')}"
    return s


@pytest.fixture(scope="module")
def manager_user(owner_sess, mongo):
    """Register a new user, invite as co-owner scoped to demo project (manager role)."""
    email = f"test_{TAG}_mgr@example.com"
    s = requests.Session()
    r = s.post(f"{API}/auth/register", json={"name": "ITER41 Mgr", "email": email, "password": "mgrpass123"})
    assert r.status_code == 200, r.text
    j = r.json()
    s.headers["Authorization"] = f"Bearer {j.get('access_token') or j.get('token')}"
    uid = j["user"]["id"]
    RUN["users"].append(uid)
    # Current active project for the demo owner
    me = owner_sess.get(f"{API}/auth/me").json()
    pid = me["user"]["active_project_id"]
    # Invite as manager (project-scoped)
    r = owner_sess.post(f"{API}/co-owners", json={"email": email, "project_ids": [pid]})
    assert r.status_code == 200, r.text
    return {"sess": s, "email": email, "uid": uid, "pid": pid}


@pytest.fixture(scope="module")
def demo_pid(owner_sess):
    return owner_sess.get(f"{API}/auth/me").json()["user"]["active_project_id"]


# ---------------- /api/report-link ----------------

class TestReportLink:
    def test_initial_get_no_link(self, owner_sess, mongo, demo_pid):
        # Ensure clean
        mongo.report_links.delete_many({"project_id": demo_pid})
        r = owner_sess.get(f"{API}/report-link")
        assert r.status_code == 200
        body = r.json()
        assert body["url"] is None
        assert isinstance(body["reports"], int)

    def test_create_report_link(self, owner_sess):
        r = owner_sess.post(f"{API}/report-link", json={"origin_url": BASE})
        assert r.status_code == 200, r.text
        url = r.json()["url"]
        assert url.startswith(BASE) and "/api/r/" in url
        # persist token for later use via module-scoped fixture
        STATE['report_url'] = url
        STATE['report_token'] = url.rsplit("/", 1)[-1]

    def test_get_shows_link(self, owner_sess):
        r = owner_sess.get(f"{API}/report-link")
        assert r.status_code == 200
        assert r.json()["url"] == STATE['report_url']

    def test_requires_auth(self):
        r = requests.get(f"{API}/report-link")
        assert r.status_code in (401, 403)


# ---------------- Public /api/r/{token} ----------------

class TestPublicReport:
    def test_report_page_renders(self):
        r = requests.get(f"{API}/r/{STATE['report_token']}")
        assert r.status_code == 200
        html = r.text
        for marker in ("report-name", "report-email", "report-phone", "report-room",
                       "report-description", "report-priority", "report-photo", "report-submit"):
            assert f"id='{marker}'" in html or f'id="{marker}"' in html, f"missing {marker}"

    def test_report_page_invalid_token(self):
        r = requests.get(f"{API}/r/zzz-no-such-token")
        # Returns an HTMLResponse "Link expired" (200), not 404
        assert r.status_code == 200
        assert "no longer active" in r.text.lower() or "expired" in r.text.lower()

    def test_submit_missing_fields_400(self):
        r = requests.post(f"{API}/r/{STATE['report_token']}", data={"name": "", "room": "", "description": ""})
        assert r.status_code == 400

    def test_submit_bad_email_400(self):
        r = requests.post(f"{API}/r/{STATE['report_token']}",
                          data={"name": "Alice", "room": "Kitchen", "description": "leaky tap",
                                "email": "not-an-email", "priority": "low"})
        assert r.status_code == 400

    def test_submit_success_303(self, mongo, demo_pid):
        r = requests.post(f"{API}/r/{STATE['report_token']}", data={
            "name": "TEST Reporter", "room": "Bathroom", "description": "iter41 broken shower",
            "email": "delivered@resend.dev", "phone": "07123456789", "priority": "high",
        }, allow_redirects=False)
        assert r.status_code == 303, r.text
        assert "?sent=1" in r.headers.get("location", "")
        # Verify in DB
        snag = mongo.snags.find_one({"description": "iter41 broken shower"})
        assert snag is not None
        assert snag["source"] == "report_link"
        assert snag["reported_by"] == "Tenant: TEST Reporter"
        assert snag["reporter_email"] == "delivered@resend.dev"
        assert snag["reporter_phone"] == "07123456789"
        assert snag["project_id"] == demo_pid
        STATE['snag_id'] = str(snag["_id"])
        RUN["snags"].append(snag["_id"])

    def test_page_sent_confirmation(self):
        r = requests.get(f"{API}/r/{STATE['report_token']}?sent=1")
        assert r.status_code == 200
        assert "report-sent-msg" in r.text

    def test_report_count_updated(self, owner_sess):
        r = owner_sess.get(f"{API}/report-link")
        assert r.json()["reports"] >= 1


# ---------------- /api/snag-assignees ----------------

class TestAssignees:
    def test_shape(self, owner_sess, manager_user):
        r = owner_sess.get(f"{API}/snag-assignees")
        assert r.status_code == 200
        d = r.json()
        assert "team" in d and "trades" in d
        emails = [t["email"] for t in d["team"]]
        assert manager_user["email"] in emails
        for t in d["team"]:
            assert t["kind"] == "team"
        for t in d["trades"]:
            assert t["kind"] == "trade"


# ---------------- /api/snags/{id}/assign ----------------

class TestAssign:
    def test_add_trade_contact(self, owner_sess, demo_pid):
        r = owner_sess.post(f"{API}/contacts", json={
            "name": f"TEST Trade {TAG}", "kind": "trade", "role": "Plumber",
            "email": "delivered@resend.dev", "phone": "07000000001",
        })
        assert r.status_code == 200, r.text
        STATE['trade_id'] = r.json()["id"]
        RUN["contacts"].append(STATE['trade_id'])

    def test_assign_trade_success(self, owner_sess):
        r = owner_sess.post(f"{API}/snags/{STATE['snag_id']}/assign",
                            json={"kind": "trade", "id": STATE['trade_id'], "origin_url": BASE})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["assignee"].startswith("TEST Trade")
        assert d["url"].startswith(BASE) and "/api/job/" in d["url"]
        assert d["emailed"] is True
        STATE['job_url'] = d["url"]
        STATE['job_token'] = d["url"].rsplit("/", 1)[-1]
        assert d["snag"]["assigned_to"]["kind"] == "trade"
        assert d["snag"]["assigned_to"]["id"] == STATE['trade_id']

    def test_assign_bad_snag_404(self, owner_sess):
        r = owner_sess.post(f"{API}/snags/000000000000000000000000/assign",
                            json={"kind": "trade", "id": STATE['trade_id'], "origin_url": BASE})
        assert r.status_code == 404

    def test_assign_bad_trade_404(self, owner_sess):
        r = owner_sess.post(f"{API}/snags/{STATE['snag_id']}/assign",
                            json={"kind": "trade", "id": "000000000000000000000000", "origin_url": BASE})
        assert r.status_code == 404

    def test_assign_manager_wrong_project(self, owner_sess, mongo, demo_pid):
        """A manager co-owner scoped to a different project cannot be assigned to a snag in the demo project."""
        # Create a dummy project for owner
        rp = owner_sess.post(f"{API}/projects", json={"name": f"TEST Other {TAG}", "address": "Nowhere"})
        assert rp.status_code == 200, rp.text
        other_pid = rp.json()["id"]
        RUN["projects"].append(other_pid)
        # Invite a different manager scoped only to other_pid
        bad_email = f"test_{TAG}_badmgr@example.com"
        br = requests.post(f"{API}/auth/register", json={"name": "Bad Mgr", "email": bad_email, "password": "pw12345678"})
        assert br.status_code == 200
        RUN["users"].append(br.json()["user"]["id"])
        inv = owner_sess.post(f"{API}/co-owners", json={"email": bad_email, "project_ids": [other_pid]})
        assert inv.status_code == 200
        # Find co_owner row for bad manager
        co = mongo.co_owners.find_one({"email": bad_email})
        assert co and co.get("project_ids") == [other_pid]
        RUN["co_owners"].append(co["_id"])
        r = owner_sess.post(f"{API}/snags/{STATE['snag_id']}/assign",
                            json={"kind": "team", "id": str(co["_id"]), "origin_url": BASE})
        assert r.status_code == 404


# ---------------- Public /api/job/{token} ----------------

class TestJobPage:
    def test_job_page(self):
        r = requests.get(f"{API}/job/{STATE['job_token']}")
        assert r.status_code == 200
        html = r.text
        assert "id='job-fix'" in html or 'id="job-fix"' in html
        assert "iter41 broken shower" in html

    def test_job_page_bad_token(self):
        r = requests.get(f"{API}/job/zzzz-no-token")
        assert r.status_code == 200
        assert "no longer active" in r.text.lower()

    def test_job_photo_no_photo_404(self):
        # Snag has no storage_path; expect 404 since no photo uploaded
        r = requests.get(f"{API}/job/{STATE['job_token']}/photo")
        assert r.status_code == 404

    def test_job_fix_marks_fixed(self, mongo):
        files = {"photo": ("fix.jpg", io.BytesIO(b"\xff\xd8\xff\xe0test-fix-photo"), "image/jpeg")}
        r = requests.post(f"{API}/job/{STATE['job_token']}/fix",
                          data={"note": "Replaced the shower head"}, files=files, allow_redirects=False)
        assert r.status_code == 303, r.text
        assert "?done=1" in r.headers.get("location", "")
        snag = mongo.snags.find_one({"_id": __import__("bson").ObjectId(STATE['snag_id'])})
        assert snag["status"] == "fixed"
        assert snag["fix_note"] == "Replaced the shower head"
        assert snag.get("fix_photo_path")
        assert snag["fixed_by"] == snag["assigned_to"]["name"]

    def test_fixed_photo_served(self):
        r = requests.get(f"{API}/job/{STATE['job_token']}/photo?kind=fix")
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/")

    def test_reporter_notified(self, mongo):
        # Check messages collection has a repair_fixed entry for the reporter email
        time.sleep(0.4)
        msg = mongo.messages.find_one({"kind": "repair_fixed", "email": "delivered@resend.dev"},
                                      sort=[("_id", -1)])
        assert msg is not None, "repair_fixed message not logged"


# ---------------- Rename assignee clears assigned_to ----------------

class TestRename:
    def test_put_different_name_clears_link(self, owner_sess, mongo, demo_pid):
        # Create a fresh snag then assign to the trade, then PUT with different assignee
        c = owner_sess.post(f"{API}/snags", json={"room": "Hall", "description": f"iter41 rename test {TAG}",
                                                   "priority": "low"})
        assert c.status_code == 200, c.text
        sid = c.json()["id"]
        RUN["snags"].append(__import__("bson").ObjectId(sid))
        a = owner_sess.post(f"{API}/snags/{sid}/assign",
                            json={"kind": "trade", "id": STATE['trade_id'], "origin_url": BASE})
        assert a.status_code == 200
        p = owner_sess.put(f"{API}/snags/{sid}", json={"assignee": "Someone Else Entirely"})
        assert p.status_code == 200
        after = mongo.snags.find_one({"_id": __import__("bson").ObjectId(sid)})
        assert after.get("assigned_to") is None
        assert after.get("assignee") == "Someone Else Entirely"


# ---------------- /api/inbox ----------------

class TestInbox:
    def test_demo_owner_inbox_has_repair(self, owner_sess, mongo, demo_pid):
        # Reopen a report_link snag to make it an open repair
        new_sid = mongo.snags.insert_one({
            "user_id": owner_sess.get(f"{API}/auth/me").json()["user"]["id"],
            "project_id": demo_pid,
            "room": "Kitchen", "description": f"iter41 inbox repair {TAG}",
            "priority": "medium", "status": "open", "assignee": "",
            "reported_by": "Tenant: TEST Alice", "reporter_name": "TEST Alice",
            "reporter_email": "", "reporter_phone": "", "source": "report_link",
            "created_at": "2026-01-15T10:00:00Z",
        }).inserted_id
        RUN["snags"].append(new_sid)
        r = owner_sess.get(f"{API}/inbox")
        assert r.status_code == 200
        d = r.json()
        kinds = [i["kind"] for i in d["items"] if str(new_sid) == i["id"]]
        assert kinds == ["repair"], f"expected report_link snag classified as repair, items={d['items'][:3]}"
        assert "mine" in d["counts"]

    def test_assign_to_manager_and_inbox_mine(self, owner_sess, manager_user, mongo, demo_pid):
        # Create a snag, assign to manager (team), verify mine=true in manager inbox and ASSIGNED first
        c = owner_sess.post(f"{API}/snags", json={"room": "Lounge",
                                                   "description": f"iter41 mgr job {TAG}", "priority": "high"})
        sid = c.json()["id"]
        RUN["snags"].append(__import__("bson").ObjectId(sid))
        co = mongo.co_owners.find_one({"email": manager_user["email"]})
        assert co is not None
        RUN["co_owners"].append(co["_id"])
        r = owner_sess.post(f"{API}/snags/{sid}/assign",
                            json={"kind": "team", "id": str(co["_id"]), "origin_url": BASE})
        assert r.status_code == 200, r.text
        # Manager inbox
        mi = manager_user["sess"].get(f"{API}/inbox")
        assert mi.status_code == 200
        d = mi.json()
        mine_items = [i for i in d["items"] if i["mine"]]
        assert any(i["id"] == sid for i in mine_items), f"manager inbox missing mine assignment; items={[(i['id'], i['mine']) for i in d['items']][:5]}"
        # First item should be mine (sort key puts mine first)
        assert d["items"][0]["mine"] is True
        assert d["counts"]["mine"] >= 1


# ---------------- DELETE /api/report-link ----------------

class TestRevoke:
    def test_delete(self, owner_sess, mongo, demo_pid):
        r = owner_sess.delete(f"{API}/report-link")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert mongo.report_links.find_one({"project_id": demo_pid}) is None

    def test_revoked_token_inactive_page(self):
        r = requests.get(f"{API}/r/{STATE['report_token']}")
        assert r.status_code == 200
        assert "no longer active" in r.text.lower() or "expired" in r.text.lower()

    def test_revoked_token_submit_404(self):
        r = requests.post(f"{API}/r/{STATE['report_token']}",
                          data={"name": "x", "room": "y", "description": "z"})
        assert r.status_code == 404


# ---------------- Cleanup ----------------

def test_zzz_cleanup(owner_sess, mongo):
    """Remove TEST-tagged data."""
    from bson import ObjectId
    for sid in RUN["snags"]:
        mongo.snags.delete_one({"_id": sid})
    for cid in RUN["contacts"]:
        try:
            owner_sess.delete(f"{API}/contacts/{cid}")
        except Exception:
            pass
    for co_id in RUN["co_owners"]:
        mongo.co_owners.delete_one({"_id": co_id})
    for pid in RUN["projects"]:
        try:
            mongo.projects.delete_one({"_id": ObjectId(pid)})
        except Exception:
            pass
    for uid in RUN["users"]:
        try:
            mongo.users.delete_one({"_id": ObjectId(uid)})
        except Exception:
            pass
    mongo.report_links.delete_many({"origin": {"$regex": TAG}})
    mongo.messages.delete_many({"summary": {"$regex": "iter41"}})
    assert True
