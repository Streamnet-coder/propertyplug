"""Iteration 42 — Assignee Reminders, Tenant Progress View (track_token), Urgent Call-Out Alert.

Covers:
- POST /api/r/{token} returns 303 to ?sent=1&track=<track_token>; snag has track_token;
  thank-you page shows #report-track-link; reporter confirmation email logged.
- GET /api/track/{token}: REPORTED initially, IN PROGRESS after assign (shows assignee),
  FIXED after /api/job/{token}/fix (shows #track-fix); invalid token page; /photo endpoint.
- Urgent: priority=high report triggers owner email with URGENT subject (checked via messages
  log of 'repair_fixed'-adjacent flow not possible here, so we assert no crash and that the
  code path runs by inspecting messages for the tenant_repair log); assign urgent returns
  {emailed: true, texted: false} because Twilio env is not set.
- Reminders: routes.report_links.run_assignee_reminders() respects schedule
  (normal 2d first then 3d, urgent 1d, max 3, skips fixed/no-email, reassign resets count).
- GET /api/report-link returns sms_enabled=false, alert_phone from branding.
"""
import asyncio
import io
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from bson import ObjectId
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://dev-budget-tracker-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"
MONGO = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

TAG = f"iter42_{uuid.uuid4().hex[:6]}"
RUN: dict = {"snags": [], "contacts": [], "report_links": []}
STATE: dict = {}


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def owner_sess():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": "demo@mybuilder.app", "password": "demo1234"})
    assert r.status_code == 200, r.text
    j = r.json()
    s.headers["Authorization"] = f"Bearer {j.get('access_token') or j.get('token')}"
    return s


@pytest.fixture(scope="module")
def demo_pid(owner_sess):
    return owner_sess.get(f"{API}/auth/me").json()["active_project_id"]


# ---------------- /api/report-link sms flags ----------------

class TestReportLinkFlags:
    def test_get_includes_sms_and_phone(self, owner_sess, mongo, demo_pid):
        # Ensure link exists on preview origin
        mongo.report_links.delete_many({"project_id": demo_pid})
        r = owner_sess.post(f"{API}/report-link", json={"origin_url": BASE})
        assert r.status_code == 200, r.text
        url = r.json()["url"]
        STATE["report_url"] = url
        STATE["report_token"] = url.rsplit("/", 1)[-1]
        g = owner_sess.get(f"{API}/report-link")
        assert g.status_code == 200
        d = g.json()
        assert d["sms_enabled"] is False, "Twilio env should not be set in this env"
        assert "alert_phone" in d  # may be '' if branding.phone not set, but key present
        assert isinstance(d["alert_phone"], str)


# ---------------- Public report submit → track_token in redirect ----------------

class TestReportTrack:
    def test_submit_urgent_returns_track_token(self, mongo):
        r = requests.post(f"{API}/r/{STATE['report_token']}", data={
            "name": f"TEST Reporter {TAG}",
            "room": "Bathroom",
            "description": f"iter42 urgent leak {TAG}",
            "email": "delivered@resend.dev",
            "phone": "07123456789",
            "priority": "high",
        }, allow_redirects=False)
        assert r.status_code == 303, r.text
        loc = r.headers.get("location", "")
        assert "?sent=1" in loc
        assert "track=" in loc, f"expected track_token in redirect, got {loc}"
        STATE["track_token"] = loc.split("track=")[-1]
        snag = mongo.snags.find_one({"description": f"iter42 urgent leak {TAG}"})
        assert snag is not None
        assert snag.get("track_token") == STATE["track_token"]
        assert snag.get("track_origin")
        assert snag["priority"] == "high"
        STATE["snag_id"] = str(snag["_id"])
        RUN["snags"].append(snag["_id"])

    def test_thank_you_page_shows_track_link(self):
        r = requests.get(f"{API}/r/{STATE['report_token']}?sent=1&track={STATE['track_token']}")
        assert r.status_code == 200
        assert "report-track-link" in r.text
        assert STATE["track_token"] in r.text

    def test_reporter_confirmation_email_logged(self, mongo):
        # Report receipt or tenant_repair log row exists
        row = mongo.messages.find_one({"email": "delivered@resend.dev", "summary": {"$regex": "iter42 urgent leak"}}, sort=[("_id", -1)])
        assert row is not None, "tenant_repair log row missing"
        assert row["kind"] in ("tenant_repair", "report_received")

    def test_urgent_owner_email_no_errors(self, mongo):
        # We can only indirectly verify: no exception occurred, snag was saved
        snag = mongo.snags.find_one({"_id": ObjectId(STATE["snag_id"])})
        assert snag["priority"] == "high"


# ---------------- Public /api/track/{token} progress stages ----------------

class TestTrackPage:
    def test_track_reported(self):
        r = requests.get(f"{API}/track/{STATE['track_token']}")
        assert r.status_code == 200
        html = r.text
        assert "track-status" in html
        assert "REPORTED" in html
        # Timeline step for reported marked as done
        assert "track-step-reported" in html
        # Issue card shows description
        assert f"iter42 urgent leak {TAG}" in html

    def test_track_photo_404_when_no_photo(self):
        r = requests.get(f"{API}/track/{STATE['track_token']}/photo")
        assert r.status_code == 404

    def test_track_invalid_token(self):
        r = requests.get(f"{API}/track/no-such-track-token")
        assert r.status_code == 200
        assert "no longer active" in r.text.lower()


# ---------------- Assign + urgent flags → IN PROGRESS ----------------

class TestAssignUrgent:
    def test_add_trade(self, owner_sess):
        r = owner_sess.post(f"{API}/contacts", json={
            "name": f"TEST Trade {TAG}", "kind": "trade", "role": "Plumber",
            "email": "delivered@resend.dev", "phone": "07000000001",
        })
        assert r.status_code == 200, r.text
        STATE["trade_id"] = r.json()["id"]
        RUN["contacts"].append(STATE["trade_id"])

    def test_assign_urgent_emailed_true_texted_false(self, owner_sess):
        r = owner_sess.post(
            f"{API}/snags/{STATE['snag_id']}/assign",
            json={"kind": "trade", "id": STATE["trade_id"], "origin_url": BASE},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["emailed"] is True, "assign email should be sent to delivered@resend.dev"
        assert d["texted"] is False, "no Twilio env -> SMS must be silently skipped"
        STATE["job_url"] = d["url"]
        STATE["job_token"] = d["url"].rsplit("/", 1)[-1]
        assert d["assignee"].startswith("TEST Trade")

    def test_track_in_progress_shows_assignee(self):
        r = requests.get(f"{API}/track/{STATE['track_token']}")
        assert r.status_code == 200
        html = r.text
        assert "IN PROGRESS" in html
        assert "track-step-assigned" in html
        assert "TEST Trade" in html, "assigned name should appear in #track-step-assigned"


# ---------------- Mark fixed → FIXED stage ----------------

class TestFixedStage:
    def test_mark_fixed(self, mongo):
        files = {"photo": ("fix.jpg", io.BytesIO(b"\xff\xd8\xff\xe0fix-photo-bytes"), "image/jpeg")}
        r = requests.post(
            f"{API}/job/{STATE['job_token']}/fix",
            data={"note": "Replaced the washer"},
            files=files,
            allow_redirects=False,
        )
        assert r.status_code == 303
        s = mongo.snags.find_one({"_id": ObjectId(STATE["snag_id"])})
        assert s["status"] == "fixed"
        assert s.get("fix_photo_path")

    def test_track_fixed_shows_fix(self):
        r = requests.get(f"{API}/track/{STATE['track_token']}")
        assert r.status_code == 200
        html = r.text
        assert "FIXED" in html
        assert "track-fix" in html
        assert "Replaced the washer" in html


# ---------------- Reminder logic ----------------

class TestReminderLogic:
    """Direct unit test of reminder_due + run_assignee_reminders by backdating mongo values."""

    def _make_snag(self, mongo, owner_sess, demo_pid, priority: str, reminders: int,
                    assigned_days_ago: float, last_reminded_days_ago: float = None,
                    with_email: bool = True, status: str = "open") -> ObjectId:
        now = datetime.now(timezone.utc)
        assigned_at = (now - timedelta(days=assigned_days_ago)).isoformat()
        last = (now - timedelta(days=last_reminded_days_ago)).isoformat() if last_reminded_days_ago is not None else assigned_at
        uid = owner_sess.get(f"{API}/auth/me").json()["id"]
        doc = {
            "user_id": uid,
            "project_id": demo_pid,
            "room": "Kitchen",
            "description": f"iter42 reminder {TAG} {uuid.uuid4().hex[:4]}",
            "priority": priority,
            "status": status,
            "assignee": "TEST Trade",
            "assigned_to": {
                "kind": "trade", "id": STATE["trade_id"], "name": "TEST Trade",
                "email": "delivered@resend.dev" if with_email else "",
                "phone": "", "user_id": None,
                "at": assigned_at,
                "reminders": reminders,
                "last_reminded_at": last,
            },
            "job_token": uuid.uuid4().hex,
            "job_origin": BASE,
            "created_at": assigned_at,
        }
        if status == "fixed":
            doc["fixed_at"] = now.isoformat()
        sid = mongo.snags.insert_one(doc).inserted_id
        RUN["snags"].append(sid)
        return sid

    def test_reminder_due_matrix(self):
        from routes.report_links import reminder_due
        now = datetime.now(timezone.utc)

        def mk(prio, reminders, days_since_last, email="x@x", at_days=None):
            at_days = at_days if at_days is not None else days_since_last
            return {
                "priority": prio,
                "assigned_to": {
                    "at": (now - timedelta(days=at_days)).isoformat(),
                    "last_reminded_at": (now - timedelta(days=days_since_last)).isoformat(),
                    "reminders": reminders,
                    "email": email,
                },
            }

        # Normal: first reminder after 2 days
        assert reminder_due(mk("medium", 0, 2.1), now) is True
        assert reminder_due(mk("medium", 0, 1.5), now) is False
        # Normal: subsequent after 3 days
        assert reminder_due(mk("medium", 1, 3.1), now) is True
        assert reminder_due(mk("medium", 1, 2.5), now) is False
        # Urgent: 1 day gap
        assert reminder_due(mk("high", 0, 1.1), now) is True
        assert reminder_due(mk("high", 2, 1.1), now) is True
        # Max 3 reminders -> stop
        assert reminder_due(mk("medium", 3, 10), now) is False
        # No email -> never
        assert reminder_due(mk("medium", 0, 10, email=""), now) is False
        # No assigned.at
        assert reminder_due({"priority": "medium", "assigned_to": {"email": "x@x"}}, now) is False

    def test_run_assignee_reminders_sends_and_increments(self, mongo, owner_sess, demo_pid):
        from routes import report_links as rl

        # Case A: normal snag assigned 3 days ago, 0 reminders -> should send, inc to 1
        sid_a = self._make_snag(mongo, owner_sess, demo_pid, "medium", 0, 3.0)
        # Case B: normal, 1 reminder sent 2 days ago -> NOT due yet (needs 3d)
        sid_b = self._make_snag(mongo, owner_sess, demo_pid, "medium", 1, 10.0, last_reminded_days_ago=2.0)
        # Case C: urgent, 1.2 days -> due
        sid_c = self._make_snag(mongo, owner_sess, demo_pid, "high", 0, 1.5)
        # Case D: fixed snag -> never due (status filter)
        sid_d = self._make_snag(mongo, owner_sess, demo_pid, "medium", 0, 10.0, status="fixed")
        # Case E: no-email assignee -> skipped
        sid_e = self._make_snag(mongo, owner_sess, demo_pid, "medium", 0, 10.0, with_email=False)
        # Case F: already at 3 reminders -> stop
        sid_f = self._make_snag(mongo, owner_sess, demo_pid, "medium", 3, 30.0)

        n = asyncio.get_event_loop().run_until_complete(rl.run_assignee_reminders()) \
            if False else asyncio.new_event_loop().run_until_complete(rl.run_assignee_reminders())
        # We only know n >= 2 (A, C). Other preview-env snags might also trigger; be lenient
        assert n >= 2

        a = mongo.snags.find_one({"_id": sid_a})
        assert a["assigned_to"]["reminders"] == 1
        assert a["assigned_to"].get("last_reminded_at")

        b = mongo.snags.find_one({"_id": sid_b})
        assert b["assigned_to"]["reminders"] == 1, "not due yet, should not increment"

        c = mongo.snags.find_one({"_id": sid_c})
        assert c["assigned_to"]["reminders"] == 1

        d = mongo.snags.find_one({"_id": sid_d})
        assert d["assigned_to"]["reminders"] == 0, "fixed snags are skipped"

        e = mongo.snags.find_one({"_id": sid_e})
        assert e["assigned_to"]["reminders"] == 0, "no-email assignees are skipped"

        f = mongo.snags.find_one({"_id": sid_f})
        assert f["assigned_to"]["reminders"] == 3, "cap at MAX_REMINDERS"

        # Job reminder messages logged for A and C
        msg_a = mongo.messages.find_one({"kind": "job_reminder", "summary": {"$regex": "Reminder 1/3"}, "email": "delivered@resend.dev"}, sort=[("_id", -1)])
        assert msg_a is not None, "job_reminder message not logged"

    def test_reassign_resets_counter(self, mongo, owner_sess, demo_pid):
        """Re-POST /snags/{id}/assign should replace assigned_to; reminders counter resets."""
        # Create and age a snag
        sid = self._make_snag(mongo, owner_sess, demo_pid, "medium", 2, 10.0)
        # Reassign to the trade (same but via API, replaces assigned_to)
        r = owner_sess.post(
            f"{API}/snags/{str(sid)}/assign",
            json={"kind": "trade", "id": STATE["trade_id"], "origin_url": BASE},
        )
        assert r.status_code == 200, r.text
        after = mongo.snags.find_one({"_id": sid})
        # New assigned_to dict - reminders key should be absent or 0
        reminders = after["assigned_to"].get("reminders", 0)
        assert reminders == 0, f"reassign should reset reminders, got {reminders}"


# ---------------- Cleanup ----------------

def test_zzz_cleanup(owner_sess, mongo):
    for sid in RUN["snags"]:
        mongo.snags.delete_one({"_id": sid})
    for cid in RUN["contacts"]:
        try:
            owner_sess.delete(f"{API}/contacts/{cid}")
        except Exception:
            pass
    mongo.messages.delete_many({"summary": {"$regex": "iter42"}})
    mongo.report_links.delete_many({"origin": {"$regex": TAG}})
    assert True
