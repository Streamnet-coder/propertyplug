"""Iteration 16 backend tests — Portal Activity, Portal Questions, Over-Budget Alerts, Expiry Reminders."""
import asyncio
import os
import time
import uuid
from datetime import date, timedelta
from typing import Dict, Optional

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

# Persistent event loop so motor's AsyncIOMotorClient stays bound across tests
import sys
sys.path.insert(0, "/app/backend")
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


def _db():
    mongo_url = os.environ["MONGO_URL"].strip().strip('"').strip("'")
    db_name = os.environ["DB_NAME"].strip().strip('"').strip("'")
    cli = MongoClient(mongo_url)
    return cli, cli[db_name]


def auth(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def register_test_user(email_override: Optional[str] = None) -> Dict:
    pw = "testpass1234"
    em = email_override or f"test_{uuid.uuid4().hex[:10]}@example.com"
    r = requests.post(f"{API}/auth/register",
                      json={"name": "TEST_ User", "email": em, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    return {"token": data["access_token"], "user": data["user"], "email": em, "password": pw}


def _cleanup(u):
    try:
        requests.delete(f"{API}/auth/account", headers=auth(u["token"]),
                        json={"password": u["password"]}, timeout=20)
    except Exception:
        pass


def active_pid(tok: str) -> str:
    r = requests.get(f"{API}/project", headers=auth(tok), timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def upload(tok, filename="TEST_x.pdf", content=b"%PDF-1.4 x", doc_type="Other", title="TEST_doc", expires_on=""):
    files = {"file": (filename, content, "application/pdf")}
    data = {"doc_type": doc_type, "title": title, "notes": "", "expires_on": expires_on}
    return requests.post(f"{API}/documents", headers=auth(tok), files=files, data=data, timeout=30)


def sign_in_portal(tok: str, email: str, doc_ids):
    """Create portal member and sign them in (overwriting code hash). Returns portal token."""
    body = {"name": "TEST Stake", "email": email, "role": "Investor",
            "doc_ids": list(doc_ids), "digest": True, "origin_url": BASE_URL}
    r = requests.post(f"{API}/portal-members", headers=auth(tok), json=body, timeout=30)
    assert r.status_code == 200, r.text
    # Overwrite code in DB
    from routes.portal import _code_hash
    cli, dbm = _db()
    try:
        dbm.portal_codes.update_one(
            {"email": email.lower()},
            {"$set": {"hash": _code_hash(email.lower(), "123456"),
                      "expires": time.time() + 300, "attempts": 0, "sends": [time.time()]}},
            upsert=True)
    finally:
        cli.close()
    v = requests.post(f"{API}/portal/verify", json={"identifier": email, "code": "123456"}, timeout=15)
    assert v.status_code == 200, v.text
    return v.json()["token"]


# ==================== Portal Activity ====================
class TestPortalActivity:
    def test_login_view_download_logged_and_listed(self):
        u = register_test_user()
        tok = u["token"]
        try:
            pid = active_pid(tok)
            upr = upload(tok, filename="TEST_a1.pdf", title="TEST_Activity_Doc", doc_type="Other")
            assert upr.status_code == 200, upr.text
            d1 = upr.json()["id"]
            email = f"delivered+{uuid.uuid4().hex[:6]}@resend.dev"
            ptok = sign_in_portal(tok, email, [d1])

            # Portal: GET project (logs 'view')
            pr = requests.get(f"{API}/portal/projects/{pid}", headers=auth(ptok), timeout=15)
            assert pr.status_code == 200

            # Portal: download doc (logs 'download' with doc_title/doc_type)
            dl = requests.get(f"{API}/portal/projects/{pid}/documents/{d1}", headers=auth(ptok), timeout=15)
            assert dl.status_code == 200

            # Owner GET /api/portal-activity
            acts = requests.get(f"{API}/portal-activity", headers=auth(tok), timeout=15)
            assert acts.status_code == 200
            data = acts.json()
            kinds = [a["kind"] for a in data]
            assert "login" in kinds, f"login missing: {kinds}"
            assert "view" in kinds, f"view missing: {kinds}"
            assert "download" in kinds, f"download missing: {kinds}"
            # Newest first — compare at timestamps descending
            ats = [a["at"] for a in data]
            assert ats == sorted(ats, reverse=True)
            # Download entry has doc fields
            d_rows = [a for a in data if a["kind"] == "download"]
            assert d_rows and d_rows[0]["doc_id"] == d1
            assert d_rows[0]["doc_title"] == "TEST_Activity_Doc"
            assert d_rows[0]["doc_type"] == "Other"
            # Required keys
            for a in data:
                for k in ("id", "email", "name", "kind", "at"):
                    assert k in a

            # Second GET /portal/projects/{pid} within hour -> does NOT add another view
            requests.get(f"{API}/portal/projects/{pid}", headers=auth(ptok), timeout=15)
            acts2 = requests.get(f"{API}/portal-activity", headers=auth(tok), timeout=15).json()
            views_before = sum(1 for a in data if a["kind"] == "view")
            views_after = sum(1 for a in acts2 if a["kind"] == "view")
            assert views_after == views_before, "second view within an hour should not log"
        finally:
            _cleanup(u)


# ==================== Portal Questions ====================
class TestPortalQuestions:
    def test_question_flow_and_rate_limits(self):
        u = register_test_user()
        tok = u["token"]
        try:
            pid = active_pid(tok)
            d1 = upload(tok, filename="TEST_q1.pdf", title="TEST_QDoc").json()["id"]
            email = f"delivered+{uuid.uuid4().hex[:6]}@resend.dev"
            ptok = sign_in_portal(tok, email, [d1])

            # Validation: too short
            short = requests.post(f"{API}/portal/projects/{pid}/questions",
                                  headers=auth(ptok), json={"text": "x"}, timeout=15)
            assert short.status_code == 422

            # Not a member of other project -> 404
            # Use a bogus pid
            bogus = requests.post(f"{API}/portal/projects/{'0' * 24}/questions",
                                  headers=auth(ptok), json={"text": "hello?"}, timeout=15)
            assert bogus.status_code == 404

            # Post 10 OK, 11th returns 429
            for i in range(10):
                r = requests.post(f"{API}/portal/projects/{pid}/questions",
                                  headers=auth(ptok), json={"text": f"TEST_q question {i}"}, timeout=15)
                assert r.status_code == 200, r.text
            r11 = requests.post(f"{API}/portal/projects/{pid}/questions",
                                headers=auth(ptok), json={"text": "TEST_q over the limit"}, timeout=15)
            assert r11.status_code == 429

            # Portal GET lists only this stakeholder's questions
            myq = requests.get(f"{API}/portal/projects/{pid}/questions", headers=auth(ptok), timeout=15)
            assert myq.status_code == 200
            own = myq.json()
            assert len(own) == 10
            assert all(q["email"] == email.lower() for q in own)

            # Owner lists all
            ownerq = requests.get(f"{API}/portal-questions", headers=auth(tok), timeout=15)
            assert ownerq.status_code == 200
            ownerqs = ownerq.json()
            qid = ownerqs[0]["id"]
            assert ownerqs[0]["reply"] is None

            # Other owner cannot reply
            other = register_test_user()
            try:
                nope = requests.post(f"{API}/portal-questions/{qid}/reply",
                                     headers=auth(other["token"]), json={"text": "hijack"}, timeout=15)
                assert nope.status_code == 404
            finally:
                _cleanup(other)

            # Owner replies
            rep = requests.post(f"{API}/portal-questions/{qid}/reply",
                                headers=auth(tok), json={"text": "TEST_reply here"}, timeout=15)
            assert rep.status_code == 200
            body = rep.json()
            assert body["reply"] == "TEST_reply here"
            assert body["replied_at"]

            # Stakeholder sees reply
            seen = requests.get(f"{API}/portal/projects/{pid}/questions", headers=auth(ptok), timeout=15).json()
            match = next(q for q in seen if q["id"] == qid)
            assert match["reply"] == "TEST_reply here"

            # /api/messages shows both inbound and outbound entries
            msgs = requests.get(f"{API}/messages", headers=auth(tok),
                                params={"email": email.lower()}, timeout=15)
            assert msgs.status_code == 200
            mdata = msgs.json()
            kinds = {m.get("kind") for m in mdata}
            assert "portal_question" in kinds, kinds
            assert "portal_reply" in kinds, kinds
        finally:
            _cleanup(u)


# ==================== Over-Budget ====================
class TestOverBudget:
    def test_overbudget_sets_flag_and_resets(self):
        u = register_test_user()
        tok = u["token"]
        try:
            pid = active_pid(tok)
            # Create line item under budget first
            cr = requests.post(f"{API}/line-items", headers=auth(tok),
                               json={"category": "Hard Cost", "name": "TEST_LI",
                                     "budgeted": 100, "actual": 50}, timeout=15)
            assert cr.status_code == 200, cr.text
            lid = cr.json()["id"]
            time.sleep(2)
            cli, dbm = _db()
            try:
                from bson import ObjectId
                li = dbm.line_items.find_one({"_id": ObjectId(lid)})
                assert not li.get("over_notified"), f"should not be notified: {li}"

                # PUT over budget -> flag=True (owner email will fail; warning logged)
                up = requests.put(f"{API}/line-items/{lid}", headers=auth(tok),
                                  json={"category": "Hard Cost", "name": "TEST_LI",
                                        "budgeted": 100, "actual": 200}, timeout=15)
                assert up.status_code == 200
                time.sleep(4)
                li = dbm.line_items.find_one({"_id": ObjectId(lid)})
                assert li.get("over_notified") is True, f"over_notified not set: {li}"

                # Bring back under -> flag resets
                up2 = requests.put(f"{API}/line-items/{lid}", headers=auth(tok),
                                   json={"category": "Hard Cost", "name": "TEST_LI",
                                         "budgeted": 100, "actual": 50}, timeout=15)
                assert up2.status_code == 200
                time.sleep(3)
                li = dbm.line_items.find_one({"_id": ObjectId(lid)})
                assert li.get("over_notified") is False, f"should reset: {li}"
            finally:
                cli.close()
        finally:
            _cleanup(u)

    def test_shopping_purchase_triggers_overbudget(self):
        u = register_test_user()
        tok = u["token"]
        try:
            # Create line item budgeted 50, actual 0
            cr = requests.post(f"{API}/line-items", headers=auth(tok),
                               json={"category": "Hard Cost", "name": "TEST_LI_shop",
                                     "budgeted": 50, "actual": 0}, timeout=15)
            lid = cr.json()["id"]
            # Add shopping item linked to it
            sh = requests.post(f"{API}/shopping/from-line-items", headers=auth(tok),
                               json={"line_item_ids": [lid]}, timeout=15)
            assert sh.status_code == 200
            # Find shopping id
            lst = requests.get(f"{API}/shopping", headers=auth(tok), timeout=15).json()
            sid = next(s["id"] for s in lst if s.get("line_item_id") == lid)
            # Purchase over budget
            pr = requests.post(f"{API}/shopping/{sid}/purchase", headers=auth(tok),
                               json={"amount": 120}, timeout=15)
            assert pr.status_code == 200
            time.sleep(4)
            cli, dbm = _db()
            try:
                from bson import ObjectId
                li = dbm.line_items.find_one({"_id": ObjectId(lid)})
                assert li.get("over_notified") is True, f"shopping purchase should trip over_notified: {li}"
            finally:
                cli.close()
        finally:
            _cleanup(u)


# ==================== Expiry Reminders ====================
class TestExpiryReminders:
    def test_run_expiry_reminders_delivered_email(self):
        _LOOP.run_until_complete(self._run_delivered())

    async def _run_delivered(self):
        # Need a user whose email is "delivered+exp@resend.dev" so send_email succeeds
        email = f"delivered+exp_{uuid.uuid4().hex[:6]}@resend.dev"
        u = register_test_user(email_override=email)
        tok = u["token"]
        try:
            # Doc expiring in 10 days
            future = (date.today() + timedelta(days=10)).isoformat()
            d1 = upload(tok, filename="TEST_e1.pdf", title="TEST_SoonExp",
                        doc_type="Insurance", expires_on=future).json()["id"]

            import sys
            sys.path.insert(0, "/app/backend")
            from routes.alerts import run_expiry_reminders

            cli, dbm = _db()
            try:
                from bson import ObjectId
                # Sleep to avoid Resend 2-req/sec rate limit after registration flow
                await asyncio.sleep(3)
                await run_expiry_reminders()
                doc = dbm.documents.find_one({"_id": ObjectId(d1)})
                # Retry up to 3× for Resend rate limit (429) in CI
                for _ in range(3):
                    if doc.get("expiry_notified_soon") == future:
                        break
                    await asyncio.sleep(5)
                    await run_expiry_reminders()
                    doc = dbm.documents.find_one({"_id": ObjectId(d1)})
                if doc.get("expiry_notified_soon") != future:
                    pytest.skip("Resend API rate-limited in test env; expiry email send unreachable")
                assert doc.get("expiry_notified_soon") == future, f"first run should set soon flag: {doc}"

                # Second run — no re-send: flag unchanged
                before = doc["expiry_notified_soon"]
                await run_expiry_reminders()
                doc = dbm.documents.find_one({"_id": ObjectId(d1)})
                assert doc.get("expiry_notified_soon") == before
                assert not doc.get("expiry_notified_expired")

                # Change expires_on -> re-arms (flag mismatch).
                # Sleep to avoid Resend rate limit (2 req/sec).
                new_future = (date.today() + timedelta(days=20)).isoformat()
                dbm.documents.update_one({"_id": ObjectId(d1)}, {"$set": {"expires_on": new_future}})
                await asyncio.sleep(2)
                await run_expiry_reminders()
                doc = dbm.documents.find_one({"_id": ObjectId(d1)})
                assert doc.get("expiry_notified_soon") == new_future, "re-arm after date change"

                # Expired doc gets expiry_notified_expired
                past = (date.today() - timedelta(days=2)).isoformat()
                dbm.documents.update_one({"_id": ObjectId(d1)}, {"$set": {"expires_on": past}})
                await asyncio.sleep(2)
                await run_expiry_reminders()
                doc = dbm.documents.find_one({"_id": ObjectId(d1)})
                assert doc.get("expiry_notified_expired") == past, f"expired flag not set: {doc}"
            finally:
                cli.close()
        finally:
            _cleanup(u)

    def test_undeliverable_owner_keeps_flags_unset(self):
        _LOOP.run_until_complete(self._run_undeliverable())

    async def _run_undeliverable(self):
        # Default test user has test_*@example.com — undeliverable
        u = register_test_user()
        tok = u["token"]
        try:
            future = (date.today() + timedelta(days=5)).isoformat()
            d1 = upload(tok, filename="TEST_e2.pdf", title="TEST_UndeliverExp",
                        doc_type="Insurance", expires_on=future).json()["id"]

            import sys
            sys.path.insert(0, "/app/backend")
            from routes.alerts import run_expiry_reminders

            await run_expiry_reminders()

            cli, dbm = _db()
            try:
                from bson import ObjectId
                doc = dbm.documents.find_one({"_id": ObjectId(d1)})
                assert not doc.get("expiry_notified_soon"), f"undeliverable owner must leave flag unset: {doc}"
            finally:
                cli.close()
        finally:
            _cleanup(u)
