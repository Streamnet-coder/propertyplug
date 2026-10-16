"""Iteration 17 backend tests — Spend Trend chart endpoint (GET /api/line-items/trend)."""
import os
import uuid
from typing import Dict, Optional

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


def auth(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def register_test_user(email_override: Optional[str] = None) -> Dict:
    pw = "testpass1234"
    em = email_override or f"test_trend_{uuid.uuid4().hex[:10]}@example.com"
    r = requests.post(
        f"{API}/auth/register",
        json={"name": "TEST_ Trend User", "email": em, "password": pw},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    return {"token": data["access_token"], "user": data["user"], "email": em, "password": pw}


def _cleanup(u):
    try:
        requests.delete(
            f"{API}/auth/account", headers=auth(u["token"]),
            json={"password": u["password"]}, timeout=20,
        )
    except Exception:
        pass


def _mongo():
    from pymongo import MongoClient
    mongo_url = os.environ["MONGO_URL"].strip().strip('"').strip("'")
    db_name = os.environ["DB_NAME"].strip().strip('"').strip("'")
    cli = MongoClient(mongo_url)
    return cli, cli[db_name]


def active_pid(tok: str) -> str:
    r = requests.get(f"{API}/project", headers=auth(tok), timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["id"]


class TestSpendTrendEndpoint:
    """GET /api/line-items/trend — contract & math."""

    def test_demo_trend_matches_line_items_spent_sum(self):
        """Demo user: budget == sum(budgeted), final cumulative spent == sum(spent) from list."""
        r = requests.post(
            f"{API}/auth/login",
            json={"email": "demo@mybuilder.app", "password": "demo1234"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        tok = r.json()["access_token"]

        items = requests.get(f"{API}/line-items", headers=auth(tok), timeout=15).json()
        trend = requests.get(f"{API}/line-items/trend", headers=auth(tok), timeout=15).json()

        assert set(trend.keys()) == {"budget", "points"}
        assert trend["budget"] == round(sum(i["budgeted"] for i in items), 2)
        if trend["points"]:
            last = trend["points"][-1]["spent"]
            assert last == round(sum(i["spent"] for i in items), 2), \
                f"final cumulative spent {last} != sum(spent) {sum(i['spent'] for i in items)}"
            # Sorted
            dates = [p["date"] for p in trend["points"]]
            assert dates == sorted(dates)
            # Shape
            for p in trend["points"]:
                assert set(p.keys()) == {"date", "spent"}
                assert len(p["date"]) == 10 and p["date"][4] == "-" and p["date"][7] == "-"

    def test_requires_auth(self):
        r = requests.get(f"{API}/line-items/trend", timeout=10)
        assert r.status_code in (401, 403)

    def test_new_user_no_actuals_empty_points(self):
        """A freshly registered user whose seeded line items may have zero actual — still returns empty points if no actuals."""
        u = register_test_user()
        try:
            tok = u["token"]
            # Zero-out all actuals in DB for this user to force empty points
            cli, dbm = _mongo()
            try:
                dbm.line_items.update_many(
                    {"user_id": u["user"]["id"]}, {"$set": {"actual": 0}}
                )
                # Also remove any receipts for this user to be safe
                dbm.receipts.delete_many({"user_id": u["user"]["id"]})
            finally:
                cli.close()

            trend = requests.get(f"{API}/line-items/trend", headers=auth(tok), timeout=15).json()
            assert trend["points"] == [], f"expected empty points, got {trend}"
            # Budget may still be >0 because budgeted is independent of actual
            assert isinstance(trend["budget"], (int, float))
        finally:
            _cleanup(u)

    def test_actuals_cumulative_over_created_at_dates(self):
        """Create 3 line items via DB on different dates — verify cumulative sorted points & final sum."""
        u = register_test_user()
        try:
            tok = u["token"]
            # Clear seed data for determinism
            cli, dbm = _mongo()
            try:
                uid = u["user"]["id"]
                dbm.line_items.delete_many({"user_id": uid})
                dbm.receipts.delete_many({"user_id": uid})
                pid = active_pid(tok)
                dbm.line_items.insert_many([
                    {"user_id": uid, "project_id": pid, "category": "Hard Cost",
                     "name": "TEST_A", "budgeted": 100, "actual": 50,
                     "supplier": "", "status": "Planned",
                     "created_at": "2026-01-01T10:00:00+00:00"},
                    {"user_id": uid, "project_id": pid, "category": "Soft Cost",
                     "name": "TEST_B", "budgeted": 200, "actual": 70,
                     "supplier": "", "status": "Planned",
                     "created_at": "2026-01-02T10:00:00+00:00"},
                    {"user_id": uid, "project_id": pid, "category": "Contingency",
                     "name": "TEST_C", "budgeted": 50, "actual": 30,
                     "supplier": "", "status": "Planned",
                     "created_at": "2026-01-03T10:00:00+00:00"},
                ])
            finally:
                cli.close()

            trend = requests.get(f"{API}/line-items/trend", headers=auth(tok), timeout=15).json()
            assert trend["budget"] == 350
            pts = trend["points"]
            assert [p["date"] for p in pts] == ["2026-01-01", "2026-01-02", "2026-01-03"]
            assert [p["spent"] for p in pts] == [50.0, 120.0, 150.0]
        finally:
            _cleanup(u)

    def test_unlinked_receipts_not_counted_linked_counted(self):
        """Receipts without line_item_id are IGNORED by trend; linked receipts are summed on receipt.date."""
        u = register_test_user()
        try:
            tok = u["token"]
            cli, dbm = _mongo()
            try:
                uid = u["user"]["id"]
                dbm.line_items.delete_many({"user_id": uid})
                dbm.receipts.delete_many({"user_id": uid})
                pid = active_pid(tok)
                # Create a line item (actual=0 => doesn't appear on its day)
                res = dbm.line_items.insert_one({
                    "user_id": uid, "project_id": pid, "category": "Hard Cost",
                    "name": "TEST_X", "budgeted": 500, "actual": 0,
                    "supplier": "", "status": "Planned",
                    "created_at": "2026-01-01T10:00:00+00:00",
                })
                lid = str(res.inserted_id)
                # Linked receipt on 2026-02-05 -> counted
                dbm.receipts.insert_one({
                    "user_id": uid, "project_id": pid,
                    "title": "TEST_linked", "amount": 80, "date": "2026-02-05",
                    "category": "Hard Cost", "supplier": "", "storage_path": None,
                    "line_item_id": lid, "created_at": "2026-02-05T10:00:00+00:00",
                })
                # Unlinked receipt -> NOT counted
                dbm.receipts.insert_one({
                    "user_id": uid, "project_id": pid,
                    "title": "TEST_unlinked", "amount": 999, "date": "2026-02-06",
                    "category": "Hard Cost", "supplier": "", "storage_path": None,
                    "line_item_id": None, "created_at": "2026-02-06T10:00:00+00:00",
                })
            finally:
                cli.close()

            trend = requests.get(f"{API}/line-items/trend", headers=auth(tok), timeout=15).json()
            assert trend["budget"] == 500
            # Only linked 80 on 2026-02-05
            assert trend["points"] == [{"date": "2026-02-05", "spent": 80.0}], trend

            # And final cumulative == sum of /line-items spent (which uses linked_spend)
            items = requests.get(f"{API}/line-items", headers=auth(tok), timeout=15).json()
            assert round(sum(i["spent"] for i in items), 2) == 80.0
        finally:
            _cleanup(u)

    def test_actual_plus_linked_receipt_same_day_combined(self):
        """Line item created_at day + linked receipt on same date → combined on that day."""
        u = register_test_user()
        try:
            tok = u["token"]
            cli, dbm = _mongo()
            try:
                uid = u["user"]["id"]
                dbm.line_items.delete_many({"user_id": uid})
                dbm.receipts.delete_many({"user_id": uid})
                pid = active_pid(tok)
                res = dbm.line_items.insert_one({
                    "user_id": uid, "project_id": pid, "category": "Hard Cost",
                    "name": "TEST_Y", "budgeted": 300, "actual": 40,
                    "supplier": "", "status": "Planned",
                    "created_at": "2026-03-10T10:00:00+00:00",
                })
                lid = str(res.inserted_id)
                dbm.receipts.insert_one({
                    "user_id": uid, "project_id": pid,
                    "title": "TEST_combo", "amount": 60, "date": "2026-03-10",
                    "category": "Hard Cost", "supplier": "", "storage_path": None,
                    "line_item_id": lid, "created_at": "2026-03-10T11:00:00+00:00",
                })
                dbm.receipts.insert_one({
                    "user_id": uid, "project_id": pid,
                    "title": "TEST_combo2", "amount": 25, "date": "2026-03-12",
                    "category": "Hard Cost", "supplier": "", "storage_path": None,
                    "line_item_id": lid, "created_at": "2026-03-12T10:00:00+00:00",
                })
            finally:
                cli.close()

            trend = requests.get(f"{API}/line-items/trend", headers=auth(tok), timeout=15).json()
            assert trend["points"] == [
                {"date": "2026-03-10", "spent": 100.0},
                {"date": "2026-03-12", "spent": 125.0},
            ], trend
            items = requests.get(f"{API}/line-items", headers=auth(tok), timeout=15).json()
            assert round(sum(i["spent"] for i in items), 2) == 125.0
        finally:
            _cleanup(u)

    def test_trend_scoped_per_active_project(self):
        """Switching active project yields a different trend."""
        u = register_test_user()
        try:
            tok = u["token"]
            # Capture original (seeded) active project
            pid1 = active_pid(tok)
            # Create a second project
            p2 = requests.post(
                f"{API}/projects", headers=auth(tok),
                json={"name": "TEST_SecondProj", "address": "1 Test Rd"},
                timeout=15,
            )
            assert p2.status_code == 200, p2.text
            pid2 = p2.json()["id"]

            # Activate project 2
            act = requests.post(f"{API}/projects/{pid2}/activate", headers=auth(tok), timeout=15)
            assert act.status_code == 200

            # On project 2: add line item with actual
            cr = requests.post(
                f"{API}/line-items", headers=auth(tok),
                json={"category": "Hard Cost", "name": "TEST_P2_LI",
                      "budgeted": 1000, "actual": 200}, timeout=15,
            )
            assert cr.status_code == 200, cr.text

            trend2 = requests.get(f"{API}/line-items/trend", headers=auth(tok), timeout=15).json()
            assert trend2["budget"] == 1000
            assert len(trend2["points"]) == 1
            assert trend2["points"][0]["spent"] == 200.0

            # Switch back to original project
            act1 = requests.post(f"{API}/projects/{pid1}/activate", headers=auth(tok), timeout=15)
            assert act1.status_code == 200
            trend1 = requests.get(f"{API}/line-items/trend", headers=auth(tok), timeout=15).json()
            # Different data: either different budget or different points
            assert trend1 != trend2
        finally:
            _cleanup(u)

    def test_shopping_purchase_appears_in_trend(self):
        """End-to-end: shopping/purchase inserts a line_item_id-linked receipt → shows in trend."""
        u = register_test_user()
        try:
            tok = u["token"]
            # Clear seed for determinism
            cli, dbm = _mongo()
            try:
                uid = u["user"]["id"]
                dbm.line_items.delete_many({"user_id": uid})
                dbm.receipts.delete_many({"user_id": uid})
            finally:
                cli.close()

            cr = requests.post(
                f"{API}/line-items", headers=auth(tok),
                json={"category": "Hard Cost", "name": "TEST_Shop_LI",
                      "budgeted": 500, "actual": 0}, timeout=15,
            )
            assert cr.status_code == 200, cr.text
            lid = cr.json()["id"]

            # Convert to shopping
            sh = requests.post(
                f"{API}/shopping/from-line-items", headers=auth(tok),
                json={"line_item_ids": [lid]}, timeout=15,
            )
            assert sh.status_code == 200
            lst = requests.get(f"{API}/shopping", headers=auth(tok), timeout=15).json()
            sid = next(s["id"] for s in lst if s.get("line_item_id") == lid)

            pr = requests.post(
                f"{API}/shopping/{sid}/purchase", headers=auth(tok),
                json={"amount": 75, "date": "2026-04-20"}, timeout=15,
            )
            assert pr.status_code == 200, pr.text

            trend = requests.get(f"{API}/line-items/trend", headers=auth(tok), timeout=15).json()
            # 2 points possible: line-item created_at (actual=0 so NOT a point) + receipt on 2026-04-20
            assert any(p["date"] == "2026-04-20" and p["spent"] == 75.0 for p in trend["points"]), trend

            items = requests.get(f"{API}/line-items", headers=auth(tok), timeout=15).json()
            assert round(sum(i["spent"] for i in items), 2) == trend["points"][-1]["spent"]
        finally:
            _cleanup(u)
