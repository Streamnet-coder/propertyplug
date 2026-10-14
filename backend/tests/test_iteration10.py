"""Iteration 10 backend tests.

Covers:
- GET /api/export (ZIP of CSVs per data type; auth required; data scoped to caller)
- GET /api/line-items variance fields (linked_spend, spent, alert over/near/null)
- POST /api/shopping/{id}/purchase returns alert when linked line_item crosses 90%/100%
- GET/PUT /api/digest/settings (recipients cap/dedup/validate, auto flag)
- POST /api/digest/send-now error paths + success + 2-min cooldown
- run_weekly_digests gating (unit-level logic: Monday after 08:00 UK, once per ISO week)

Cleanup: all TEST_ users deleted via DELETE /api/auth/account; demo digest
settings reset (recipients [], auto False) and digest share revoked.
"""
import io
import os
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from zoneinfo import ZoneInfo

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://dev-budget-tracker-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
DEMO_EMAIL = "demo@mybuilder.app"
DEMO_PASSWORD = "demo1234"


def auth(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def mongo():
    cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    yield cli[os.environ.get("DB_NAME", "test_database")]
    cli.close()


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


def delete_user(u):
    try:
        requests.delete(f"{API}/auth/account", headers=auth(u["token"]), json={"password": u["password"]}, timeout=20)
    except Exception:
        pass


# ==================== Export ====================
EXPECTED_CSVS = {"account.csv", "projects.csv", "line_items.csv", "receipts.csv", "contacts.csv",
                 "milestones.csv", "snags.csv", "shopping_items.csv", "stage_payments.csv",
                 "quote_requests.csv", "media.csv", "README.txt"}


class TestExport:
    def test_export_requires_auth(self):
        r = requests.get(f"{API}/export", timeout=20)
        assert r.status_code == 401

    def test_export_returns_zip_with_all_csvs_scoped_to_user(self):
        u = register_test_user()
        try:
            tok = u["token"]
            # Add distinct TEST_ shopping item + purchase to populate a receipt
            s = requests.post(f"{API}/shopping", headers=auth(tok),
                              json={"name": "TEST_export_item", "supplier": "ExpSup", "est_cost": 9},
                              timeout=15).json()
            requests.post(f"{API}/shopping/{s['id']}/purchase", headers=auth(tok),
                          json={"amount": 12.34}, timeout=15)
            r = requests.get(f"{API}/export", headers=auth(tok), timeout=30)
            assert r.status_code == 200, r.text
            assert r.headers.get("content-type", "").startswith("application/zip")
            cd = r.headers.get("content-disposition", "")
            assert "builder-assist-export-" in cd and ".zip" in cd

            z = zipfile.ZipFile(io.BytesIO(r.content))
            names = set(z.namelist())
            missing = EXPECTED_CSVS - names
            assert not missing, f"missing files in export zip: {missing}"

            # account.csv contains the user's email
            acc = z.read("account.csv").decode("utf-8").lstrip("\ufeff")
            assert u["email"] in acc, "account.csv should contain user email"
            assert "name,email,plan,created_at" in acc

            # projects.csv has header + at least 1 row (seed project)
            proj = z.read("projects.csv").decode("utf-8").lstrip("\ufeff").strip().splitlines()
            assert len(proj) >= 2
            assert proj[0].startswith("id,name,address")

            # shopping_items.csv contains the test item name
            si = z.read("shopping_items.csv").decode("utf-8").lstrip("\ufeff")
            assert "TEST_export_item" in si

            # receipts.csv has the purchase (12.34) with no cross-user data
            rec = z.read("receipts.csv").decode("utf-8").lstrip("\ufeff")
            assert "12.34" in rec

            # README non-empty
            assert z.read("README.txt").decode("utf-8").strip()
        finally:
            delete_user(u)

    def test_export_isolates_other_user_data(self):
        """Two independent TEST_ users; neither sees the other's data in the ZIP."""
        a = register_test_user()
        b = register_test_user()
        try:
            # user A: unique project name
            name_a = f"TEST_A_{uuid.uuid4().hex[:6]}"
            requests.post(f"{API}/projects", headers=auth(a["token"]),
                          json={"name": name_a, "address": "A"}, timeout=15)
            # user B: unique project name
            name_b = f"TEST_B_{uuid.uuid4().hex[:6]}"
            requests.post(f"{API}/projects", headers=auth(b["token"]),
                          json={"name": name_b, "address": "B"}, timeout=15)
            za = zipfile.ZipFile(io.BytesIO(requests.get(f"{API}/export", headers=auth(a["token"]), timeout=30).content))
            projs_a = za.read("projects.csv").decode("utf-8")
            assert name_a in projs_a
            assert name_b not in projs_a, "User A's export must not contain User B's project"
        finally:
            delete_user(a)
            delete_user(b)


# ==================== Line-items variance ====================
class TestLineItemsVariance:
    def test_variance_fields_null_near_over(self):
        u = register_test_user()
        tok = u["token"]
        try:
            # Fresh user has seeded line items; create our own 3 with known numbers
            null_item = requests.post(f"{API}/line-items", headers=auth(tok),
                                      json={"name": "TEST_null_budget", "category": "Hard Cost",
                                            "budgeted": 0, "actual": 50}, timeout=15).json()
            near_item = requests.post(f"{API}/line-items", headers=auth(tok),
                                      json={"name": "TEST_near", "category": "Hard Cost",
                                            "budgeted": 100, "actual": 92}, timeout=15).json()
            over_item = requests.post(f"{API}/line-items", headers=auth(tok),
                                      json={"name": "TEST_over", "category": "Hard Cost",
                                            "budgeted": 100, "actual": 150}, timeout=15).json()
            ok_item = requests.post(f"{API}/line-items", headers=auth(tok),
                                    json={"name": "TEST_ok", "category": "Hard Cost",
                                          "budgeted": 100, "actual": 50}, timeout=15).json()

            items = requests.get(f"{API}/line-items", headers=auth(tok), timeout=15).json()
            by_id = {x["id"]: x for x in items}
            # Required fields
            for it in (null_item, near_item, over_item, ok_item):
                m = by_id[it["id"]]
                assert "linked_spend" in m and "spent" in m and "alert" in m
                assert m["linked_spend"] == 0  # no receipts yet
                assert m["spent"] == m["actual"]
            assert by_id[null_item["id"]]["alert"] is None  # budgeted<=0 -> null
            assert by_id[near_item["id"]]["alert"] == "near"
            assert by_id[over_item["id"]]["alert"] == "over"
            assert by_id[ok_item["id"]]["alert"] is None

            # Add a receipt linked to near_item to push to 'over' via linked_spend
            # Receipts route doesn't accept line_item_id -> use shopping/from-line-items + purchase
            requests.post(f"{API}/shopping/from-line-items", headers=auth(tok),
                          json={"line_item_ids": [near_item["id"]]}, timeout=15)
            all_sh = requests.get(f"{API}/shopping", headers=auth(tok), timeout=15).json()
            linked_sh = next(x for x in all_sh if x.get("line_item_id") == near_item["id"])
            r = requests.post(f"{API}/shopping/{linked_sh['id']}/purchase", headers=auth(tok),
                              json={"amount": 20}, timeout=15)
            assert r.status_code == 200
            # alert should fire on this purchase (near_item spent now 92+20=112 > 100 -> over)
            alert = r.json().get("alert")
            assert alert is not None
            assert alert["level"] == "over"
            assert alert["item"] == near_item["name"]
            assert alert["spent"] == 112.0
            assert alert["budgeted"] == 100.0

            # Verify line-items reflects linked_spend
            items2 = requests.get(f"{API}/line-items", headers=auth(tok), timeout=15).json()
            m2 = next(x for x in items2 if x["id"] == near_item["id"])
            assert m2["linked_spend"] == 20
            assert m2["spent"] == 112
            assert m2["alert"] == "over"
        finally:
            delete_user(u)

    def test_shopping_purchase_no_alert_when_under_90(self):
        u = register_test_user()
        tok = u["token"]
        try:
            li = requests.post(f"{API}/line-items", headers=auth(tok),
                               json={"name": "TEST_safe", "category": "Hard Cost",
                                     "budgeted": 1000, "actual": 0}, timeout=15).json()
            requests.post(f"{API}/shopping/from-line-items", headers=auth(tok),
                          json={"line_item_ids": [li["id"]]}, timeout=15)
            sh = next(x for x in requests.get(f"{API}/shopping", headers=auth(tok), timeout=15).json()
                      if x.get("line_item_id") == li["id"])
            r = requests.post(f"{API}/shopping/{sh['id']}/purchase", headers=auth(tok),
                              json={"amount": 50}, timeout=15)
            assert r.status_code == 200
            assert r.json().get("alert") is None
        finally:
            delete_user(u)


# ==================== Digest settings + send-now ====================
class TestDigestSettings:
    def test_get_default_settings(self, demo_token):
        r = requests.get(f"{API}/digest/settings", headers=auth(demo_token), timeout=15)
        assert r.status_code == 200
        body = r.json()
        for k in ("recipients", "auto", "last_sent_at", "url"):
            assert k in body

    def test_recipients_dedup_lowercase_and_cap(self, demo_token):
        tok = demo_token
        try:
            payload = {
                "recipients": [
                    {"name": "A", "email": "Delivered@Resend.dev"},
                    {"name": "A2", "email": "delivered@resend.dev"},  # dup, lower
                    {"name": "B", "email": "someone@example.com"},
                ],
                "auto": False,
            }
            r = requests.put(f"{API}/digest/settings", headers=auth(tok), json=payload, timeout=15)
            assert r.status_code == 200, r.text
            data = r.json()
            emails = [x["email"] for x in data["recipients"]]
            assert emails == ["delivered@resend.dev", "someone@example.com"]
            assert all(e == e.lower() for e in emails)

            # Over 10 -> 422
            many = {"recipients": [{"name": "x", "email": f"u{i}@ex.com"} for i in range(11)], "auto": False}
            r2 = requests.put(f"{API}/digest/settings", headers=auth(tok), json=many, timeout=15)
            assert r2.status_code == 422, r2.text

            # Invalid email -> 422
            bad = {"recipients": [{"name": "x", "email": "not-an-email"}], "auto": False}
            r3 = requests.put(f"{API}/digest/settings", headers=auth(tok), json=bad, timeout=15)
            assert r3.status_code == 422, r3.text
        finally:
            # Reset to empty
            requests.put(f"{API}/digest/settings", headers=auth(tok),
                         json={"recipients": [], "auto": False}, timeout=15)


class TestDigestSendNow:
    def test_errors_without_link_or_recipients_and_success_cooldown(self, demo_token):
        tok = demo_token
        try:
            # Ensure no link
            requests.delete(f"{API}/digest/share", headers=auth(tok), timeout=15)
            # Ensure no recipients
            requests.put(f"{API}/digest/settings", headers=auth(tok),
                         json={"recipients": [], "auto": False}, timeout=15)
            # No link -> 400
            r = requests.post(f"{API}/digest/send-now", headers=auth(tok), timeout=15)
            assert r.status_code == 400, r.text
            assert "link" in r.json().get("detail", "").lower()

            # Create https link using the public BASE_URL (must be https)
            assert BASE_URL.startswith("https://"), "test requires https EXPO_PUBLIC_BACKEND_URL"
            s = requests.post(f"{API}/digest/share", headers=auth(tok),
                              json={"origin_url": BASE_URL}, timeout=15)
            assert s.status_code == 200
            # Still no recipients -> 400
            r2 = requests.post(f"{API}/digest/send-now", headers=auth(tok), timeout=15)
            assert r2.status_code == 400
            assert "recipient" in r2.json().get("detail", "").lower()

            # Add delivered@resend.dev as recipient
            requests.put(f"{API}/digest/settings", headers=auth(tok),
                         json={"recipients": [{"name": "QA", "email": "delivered@resend.dev"}],
                               "auto": False}, timeout=15)

            # Reset digest_last_sent_at so cooldown is clean (previous iteration may have left value)
            cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
            db = cli[os.environ.get("DB_NAME", "test_database")]
            db.projects.update_many(
                {"digest_recipients.email": "delivered@resend.dev"},
                {"$set": {"digest_last_sent_at": None, "digest_last_sent_week": None}},
            )
            cli.close()

            # First send -> 200 sent:1
            r3 = requests.post(f"{API}/digest/send-now", headers=auth(tok), timeout=60)
            assert r3.status_code == 200, r3.text
            body = r3.json()
            assert body.get("sent") == 1, body
            assert body.get("last_sent_at")

            # Immediate second call -> 429 cooldown
            r4 = requests.post(f"{API}/digest/send-now", headers=auth(tok), timeout=20)
            assert r4.status_code == 429, r4.text
        finally:
            # Clean up: revoke link, empty recipients, auto off
            requests.put(f"{API}/digest/settings", headers=auth(tok),
                         json={"recipients": [], "auto": False}, timeout=15)
            requests.delete(f"{API}/digest/share", headers=auth(tok), timeout=15)


# ==================== Weekly scheduler logic ====================
class TestWeeklySchedulerGating:
    """Unit-level test of run_weekly_digests gating: only runs on Monday >= 08:00 UK."""

    def test_gating_logic(self, monkeypatch):
        import asyncio

        from routes import digest as digest_module

        calls = []

        async def fake_find(_q):
            # Should only be called when gating passes
            calls.append("find_called")
            if False:
                yield  # make this an async generator

        class FakeCursor:
            def __init__(self):
                self._q = None

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        def fake_projects_find(q):
            calls.append(q)
            return FakeCursor()

        monkeypatch.setattr(digest_module.db, "projects", type("P", (), {"find": staticmethod(fake_projects_find)})())

        # 1) Tuesday 10:00 UK -> no call
        class FakeDTuesday(datetime):
            @classmethod
            def now(cls, tz=None):
                # Tuesday 2024-01-02 10:00 UK
                return datetime(2024, 1, 2, 10, 0, tzinfo=tz or ZoneInfo("Europe/London"))

        monkeypatch.setattr(digest_module, "datetime", FakeDTuesday)
        asyncio.get_event_loop().run_until_complete(digest_module.run_weekly_digests())
        assert not calls, "scheduler should not run on Tuesday"

        # 2) Monday 07:00 UK -> no call
        class FakeDMondayEarly(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2024, 1, 1, 7, 0, tzinfo=tz or ZoneInfo("Europe/London"))

        monkeypatch.setattr(digest_module, "datetime", FakeDMondayEarly)
        asyncio.get_event_loop().run_until_complete(digest_module.run_weekly_digests())
        assert not calls, "scheduler should not run on Monday before 08:00"

        # 3) Monday 09:00 UK -> should call .find once
        class FakeDMondayLate(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2024, 1, 1, 9, 0, tzinfo=tz or ZoneInfo("Europe/London"))

        monkeypatch.setattr(digest_module, "datetime", FakeDMondayLate)
        asyncio.get_event_loop().run_until_complete(digest_module.run_weekly_digests())
        assert len(calls) == 1, f"expected 1 find call, got {calls}"
        q = calls[0]
        assert q.get("digest_auto") is True
        assert q.get("digest_token", {}).get("$ne") is None
        assert "digest_last_sent_week" in q  # ensures once-per-week guard


# Final cleanup: ensure demo digest is reset even if a test above failed early.
def test_zz_final_cleanup(demo_token):
    tok = demo_token
    requests.put(f"{API}/digest/settings", headers=auth(tok),
                 json={"recipients": [], "auto": False}, timeout=15)
    requests.delete(f"{API}/digest/share", headers=auth(tok), timeout=15)
    # Delete any TEST_ receipts/shopping on demo (defensive)
    r = requests.get(f"{API}/shopping", headers=auth(tok), timeout=15).json()
    for item in r:
        if item.get("name", "").startswith("TEST_"):
            requests.delete(f"{API}/shopping/{item['id']}", headers=auth(tok), timeout=15)
    recs = requests.get(f"{API}/receipts", headers=auth(tok), timeout=15).json()
    for rec in recs:
        if rec.get("title", "").startswith("TEST_"):
            requests.delete(f"{API}/receipts/{rec['id']}", headers=auth(tok), timeout=15)
