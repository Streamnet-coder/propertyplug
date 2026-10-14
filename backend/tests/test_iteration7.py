"""Iteration 7 backend tests: Rent Yield + Weekly Digest + Shopping List.

Covers:
- GET /api/project includes refinance_ltv/refinance_rate + rent_yield object
- PUT /api/project accepts refinance_ltv & refinance_rate and recalculates rent_yield
- /api/share/{token} HTML includes #rent-yield when monthly_rent>0
- GET /api/digest?week=0,1 shape + validation (0..52)
- Shopping CRUD: GET/POST, from-line-items dedupe, PUT checked_at, DELETE /checked, DELETE /{id}
"""
import os
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient
from bson import ObjectId

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://dev-budget-tracker-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
DEMO_EMAIL = "demo@mybuilder.app"
DEMO_PASSWORD = "demo1234"


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def mongo():
    cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    yield cli[os.environ.get("DB_NAME", "test_database")]
    cli.close()


@pytest.fixture(scope="module")
def demo_token():
    r = requests.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def project(demo_token):
    r = requests.get(f"{API}/project", headers=auth(demo_token), timeout=15)
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module", autouse=True)
def restore_demo_project(demo_token, project):
    """Restore demo project settings after this module runs."""
    yield
    requests.put(
        f"{API}/project",
        headers=auth(demo_token),
        json={"refinance_ltv": 75, "refinance_rate": 5.5, "monthly_rent": 1350},
        timeout=15,
    )
    # cleanup any TEST_ shopping items we created
    tok_hdr = auth(demo_token)
    items = requests.get(f"{API}/shopping", headers=tok_hdr, timeout=15).json()
    for it in items:
        if it.get("name", "").startswith("TEST_"):
            requests.delete(f"{API}/shopping/{it['id']}", headers=tok_hdr, timeout=15)


# -------------------- Rent Yield --------------------
class TestRentYield:
    def test_project_has_refinance_fields(self, project):
        assert "refinance_ltv" in project
        assert "refinance_rate" in project
        assert "rent_yield" in project
        ry = project["rent_yield"]
        for k in ("gross_yield", "yield_on_cost", "invested", "refinance_amount",
                  "cash_left_in", "monthly_mortgage", "monthly_cashflow"):
            assert k in ry, f"Missing rent_yield.{k}"

    def test_rent_yield_math(self, project):
        ry = project["rent_yield"]
        # invested = purchase + total_budget
        expected_invested = round(project["purchase_price"] + project["total_budget"], 2)
        assert ry["invested"] == expected_invested
        # refinance = valuation * ltv / 100
        expected_refi = round(project["estimated_valuation"] * project["refinance_ltv"] / 100, 2)
        assert ry["refinance_amount"] == expected_refi
        # cash_left_in = invested - refi
        assert ry["cash_left_in"] == round(expected_invested - expected_refi, 2)
        # monthly mortgage = refi * rate / 100 / 12
        expected_mort = round(expected_refi * project["refinance_rate"] / 100 / 12, 2)
        assert ry["monthly_mortgage"] == expected_mort

    def test_put_project_updates_ltv_and_recalculates(self, demo_token):
        # change LTV to 80 and verify rent_yield recomputes
        r = requests.put(f"{API}/project", headers=auth(demo_token),
                         json={"refinance_ltv": 80}, timeout=15)
        assert r.status_code == 200
        p = r.json()
        assert p["refinance_ltv"] == 80
        expected_refi = round(p["estimated_valuation"] * 80 / 100, 2)
        assert p["rent_yield"]["refinance_amount"] == expected_refi
        # restore to 75 for other tests
        requests.put(f"{API}/project", headers=auth(demo_token),
                     json={"refinance_ltv": 75}, timeout=15)

    def test_put_project_updates_rate(self, demo_token):
        r = requests.put(f"{API}/project", headers=auth(demo_token),
                         json={"refinance_rate": 6.0}, timeout=15)
        assert r.status_code == 200
        p = r.json()
        assert p["refinance_rate"] == 6.0
        expected_mort = round(p["rent_yield"]["refinance_amount"] * 6.0 / 100 / 12, 2)
        assert p["rent_yield"]["monthly_mortgage"] == expected_mort
        requests.put(f"{API}/project", headers=auth(demo_token),
                     json={"refinance_rate": 5.5}, timeout=15)


# -------------------- Share Report --------------------
class TestShareReport:
    def test_share_includes_rent_yield_card(self, demo_token):
        # ensure monthly_rent>0
        requests.put(f"{API}/project", headers=auth(demo_token),
                     json={"monthly_rent": 1350}, timeout=15)
        # create/get share
        r = requests.post(f"{API}/project/share", headers=auth(demo_token),
                          json={"origin_url": BASE_URL}, timeout=15)
        assert r.status_code == 200
        url = r.json()["url"]
        # fetch public share
        html = requests.get(url, timeout=15).text
        assert 'id="rent-yield"' in html or "id='rent-yield'" in html, "rent-yield card missing"
        assert "Rent &amp; refinance" in html or "Rent & refinance" in html

    def test_share_hides_rent_yield_when_rent_zero(self, demo_token):
        # Ensure share link exists first
        requests.post(f"{API}/project/share", headers=auth(demo_token),
                      json={"origin_url": BASE_URL}, timeout=15)
        requests.put(f"{API}/project", headers=auth(demo_token),
                     json={"monthly_rent": 0}, timeout=15)
        r = requests.get(f"{API}/project/share", headers=auth(demo_token), timeout=15)
        url = r.json()["url"]
        assert url, "share url missing"
        html = requests.get(url, timeout=15).text
        assert 'id="rent-yield"' not in html and "id='rent-yield'" not in html
        # restore
        requests.put(f"{API}/project", headers=auth(demo_token),
                     json={"monthly_rent": 1350}, timeout=15)


# -------------------- Digest --------------------
class TestDigest:
    def test_digest_week_zero(self, demo_token):
        r = requests.get(f"{API}/digest?week=0", headers=auth(demo_token), timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["week"] == 0
        for k in ("week_start", "week_end", "spend", "prev_spend",
                  "snags_fixed", "snags_opened", "snags_open_now",
                  "milestones_done", "next_milestone"):
            assert k in d, f"missing {k}"
        # week_start is Monday (weekday 0)
        start = datetime.fromisoformat(d["week_start"]).date()
        assert start.weekday() == 0
        end = datetime.fromisoformat(d["week_end"]).date()
        assert (end - start).days == 6
        # spend shape
        for k in ("total", "receipts_total", "receipts_count",
                  "payments_total", "payments_count", "top"):
            assert k in d["spend"]

    def test_digest_week_one_is_last_week(self, demo_token):
        r0 = requests.get(f"{API}/digest?week=0", headers=auth(demo_token), timeout=15).json()
        r1 = requests.get(f"{API}/digest?week=1", headers=auth(demo_token), timeout=15).json()
        s0 = datetime.fromisoformat(r0["week_start"]).date()
        s1 = datetime.fromisoformat(r1["week_start"]).date()
        assert (s0 - s1).days == 7

    def test_digest_validation(self, demo_token):
        r = requests.get(f"{API}/digest?week=-1", headers=auth(demo_token), timeout=15)
        assert r.status_code == 422
        r = requests.get(f"{API}/digest?week=53", headers=auth(demo_token), timeout=15)
        assert r.status_code == 422
        r = requests.get(f"{API}/digest?week=52", headers=auth(demo_token), timeout=15)
        assert r.status_code == 200

    def test_digest_auth_required(self):
        r = requests.get(f"{API}/digest?week=0", timeout=15)
        assert r.status_code in (401, 403)

    def test_digest_counts_paid_stage_payment(self, demo_token, mongo, project):
        """Insert a paid stage payment within this week and confirm it shows in spend.payments_total."""
        pid = project["id"]
        me = requests.get(f"{API}/auth/me", headers=auth(demo_token), timeout=15).json()
        uid = me["id"]
        today = datetime.now(timezone.utc).date()
        iso = (today - timedelta(days=today.weekday())).isoformat()  # Monday
        payment = {
            "user_id": uid,
            "project_id": pid,
            "stage": "TEST_iter7_payment",
            "amount": 1234.56,
            "status": "paid",
            "paid_at": iso,
            "created_at": iso,
        }
        res = mongo.stage_payments.insert_one(payment)
        try:
            r = requests.get(f"{API}/digest?week=0", headers=auth(demo_token), timeout=15).json()
            assert r["spend"]["payments_count"] >= 1
            assert r["spend"]["payments_total"] >= 1234.56
            assert r["spend"]["total"] >= 1234.56
        finally:
            mongo.stage_payments.delete_one({"_id": res.inserted_id})


# -------------------- Shopping --------------------
class TestShopping:
    def test_auth_required(self):
        r = requests.get(f"{API}/shopping", timeout=15)
        assert r.status_code in (401, 403)

    def test_list_empty_initially(self, demo_token):
        r = requests.get(f"{API}/shopping", headers=auth(demo_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_add_custom_item(self, demo_token):
        r = requests.post(f"{API}/shopping", headers=auth(demo_token),
                          json={"name": "TEST_plaster", "supplier": "Screwfix",
                                "qty": "4 bags", "est_cost": 42.5}, timeout=15)
        assert r.status_code == 200, r.text
        it = r.json()
        assert it["name"] == "TEST_plaster"
        assert it["supplier"] == "Screwfix"
        assert it["checked"] is False
        assert it["checked_at"] is None
        # GET verifies persistence
        items = requests.get(f"{API}/shopping", headers=auth(demo_token), timeout=15).json()
        assert any(x["id"] == it["id"] for x in items)
        # cleanup
        requests.delete(f"{API}/shopping/{it['id']}", headers=auth(demo_token), timeout=15)

    def test_add_blank_name_400(self, demo_token):
        r = requests.post(f"{API}/shopping", headers=auth(demo_token),
                          json={"name": "   "}, timeout=15)
        assert r.status_code == 400

    def test_from_line_items_dedupe(self, demo_token):
        # fetch budget items from active project
        items = requests.get(f"{API}/line-items", headers=auth(demo_token), timeout=15).json()
        assert isinstance(items, list) and len(items) >= 2, "demo project should have budget line items"
        ids = [items[0]["id"], items[1]["id"]]
        # ensure fresh - delete any existing shopping entries pointing to these line_item_ids
        existing = requests.get(f"{API}/shopping", headers=auth(demo_token), timeout=15).json()
        for s in existing:
            if s.get("line_item_id") in ids:
                requests.delete(f"{API}/shopping/{s['id']}", headers=auth(demo_token), timeout=15)
        # first call -> added=2 skipped=0
        r1 = requests.post(f"{API}/shopping/from-line-items", headers=auth(demo_token),
                          json={"line_item_ids": ids}, timeout=15)
        assert r1.status_code == 200, r1.text
        assert r1.json() == {"added": 2, "skipped": 0}
        # second call -> added=0 skipped=2 (dedupe)
        r2 = requests.post(f"{API}/shopping/from-line-items", headers=auth(demo_token),
                          json={"line_item_ids": ids}, timeout=15)
        assert r2.json() == {"added": 0, "skipped": 2}
        # cleanup
        shop = requests.get(f"{API}/shopping", headers=auth(demo_token), timeout=15).json()
        for s in shop:
            if s.get("line_item_id") in ids:
                requests.delete(f"{API}/shopping/{s['id']}", headers=auth(demo_token), timeout=15)

    def test_from_line_items_empty_400(self, demo_token):
        r = requests.post(f"{API}/shopping/from-line-items", headers=auth(demo_token),
                          json={"line_item_ids": []}, timeout=15)
        assert r.status_code == 400

    def test_check_sets_checked_at(self, demo_token):
        r = requests.post(f"{API}/shopping", headers=auth(demo_token),
                          json={"name": "TEST_tick_me"}, timeout=15)
        sid = r.json()["id"]
        try:
            r2 = requests.put(f"{API}/shopping/{sid}", headers=auth(demo_token),
                              json={"checked": True}, timeout=15)
            assert r2.status_code == 200
            assert r2.json()["checked"] is True
            assert r2.json()["checked_at"] is not None
            # uncheck -> checked_at should be None
            r3 = requests.put(f"{API}/shopping/{sid}", headers=auth(demo_token),
                              json={"checked": False}, timeout=15)
            assert r3.json()["checked"] is False
            assert r3.json()["checked_at"] is None
        finally:
            requests.delete(f"{API}/shopping/{sid}", headers=auth(demo_token), timeout=15)

    def test_delete_checked_only(self, demo_token):
        a = requests.post(f"{API}/shopping", headers=auth(demo_token),
                          json={"name": "TEST_keep_me"}, timeout=15).json()
        b = requests.post(f"{API}/shopping", headers=auth(demo_token),
                          json={"name": "TEST_delete_me"}, timeout=15).json()
        try:
            requests.put(f"{API}/shopping/{b['id']}", headers=auth(demo_token),
                         json={"checked": True}, timeout=15)
            r = requests.delete(f"{API}/shopping/checked", headers=auth(demo_token), timeout=15)
            assert r.status_code == 200
            assert r.json()["deleted"] >= 1
            # verify: 'keep_me' still exists, 'delete_me' is gone
            lst = requests.get(f"{API}/shopping", headers=auth(demo_token), timeout=15).json()
            ids = [x["id"] for x in lst]
            assert a["id"] in ids
            assert b["id"] not in ids
        finally:
            requests.delete(f"{API}/shopping/{a['id']}", headers=auth(demo_token), timeout=15)

    def test_delete_single(self, demo_token):
        r = requests.post(f"{API}/shopping", headers=auth(demo_token),
                          json={"name": "TEST_byebye"}, timeout=15)
        sid = r.json()["id"]
        d = requests.delete(f"{API}/shopping/{sid}", headers=auth(demo_token), timeout=15)
        assert d.status_code == 200
        lst = requests.get(f"{API}/shopping", headers=auth(demo_token), timeout=15).json()
        assert all(x["id"] != sid for x in lst)

    def test_shopping_scoped_to_active_project(self, demo_token, mongo, project):
        """Items created in active project should not appear if we switch active project."""
        # create a second project
        r = requests.post(f"{API}/projects", headers=auth(demo_token),
                          json={"name": "TEST_iter7_proj2", "address": ""}, timeout=20)
        assert r.status_code == 200, r.text
        proj2_id = r.json()["id"]
        try:
            # new project is now active - shopping should be empty
            lst = requests.get(f"{API}/shopping", headers=auth(demo_token), timeout=15).json()
            assert lst == []
            # add an item in proj2
            it = requests.post(f"{API}/shopping", headers=auth(demo_token),
                               json={"name": "TEST_proj2_item"}, timeout=15).json()
            # switch back to original project
            requests.post(f"{API}/projects/{project['id']}/activate",
                          headers=auth(demo_token), timeout=15)
            lst = requests.get(f"{API}/shopping", headers=auth(demo_token), timeout=15).json()
            assert all(x["id"] != it["id"] for x in lst), "proj2 item leaked to original project"
        finally:
            # ensure active project is restored, then delete proj2
            requests.post(f"{API}/projects/{project['id']}/activate",
                          headers=auth(demo_token), timeout=15)
            requests.delete(f"{API}/projects/{proj2_id}", headers=auth(demo_token), timeout=15)
