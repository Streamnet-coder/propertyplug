"""Iteration 46 - Co-owner statements, capital contributions, repair history.

Covers:
- PUT /api/project/split with contributions (validation + stays sticky)
- GET /api/project/split returns contribution/cash_return_pct/profit_return_pct/figures.total_contributed/has_contributions
- GET /api/project/statements?tax_year=YYYY label and figures
- POST /api/project/statements owner-only, 400 w/o shares, sends to co-owners (delivered@resend.dev), logs coowner_statement, last_sent_at updated
- run_auto_statements returns 0 when today is >60 days after 6 April; tax_year_now logic
- GET /api/repairs/history items/totals shape; tasks-only manager gets fix_cost=None
"""
import asyncio
import os
import time
from datetime import date

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"
DEMO = {"email": "demo@mybuilder.app", "password": "demo1234"}
CO_EMAIL = "delivered@resend.dev"


@pytest.fixture(scope="module")
def owner_token():
    r = requests.post(f"{API}/auth/login", json=DEMO, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    return j.get("token") or j.get("access_token")


def H(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def pid(owner_token):
    r = requests.get(f"{API}/projects", headers=H(owner_token), timeout=30)
    assert r.status_code == 200, r.text
    projs = r.json()
    nott = next((p for p in projs if "Nottingham" in p["name"]), None) or projs[0]
    requests.post(f"{API}/project/active", headers=H(owner_token), json={"project_id": nott["id"]}, timeout=30)
    return nott["id"]


@pytest.fixture(scope="module")
def coowner(owner_token, pid):
    """Invite delivered@resend.dev as a scoped co_owner on the active project."""
    requests.post(f"{API}/project/active", headers=H(owner_token), json={"project_id": pid}, timeout=30)
    # Find existing or create
    existing = requests.get(f"{API}/co-owners", headers=H(owner_token), timeout=30).json()
    for c in existing:
        if c["email"] == CO_EMAIL:
            # ensure it covers this project
            if c.get("project_ids") in (None,) or (c.get("project_ids") and pid in c["project_ids"]):
                return c["id"]
            requests.put(f"{API}/co-owners/{c['id']}", headers=H(owner_token),
                         json={"role": c["role"], "project_ids": None}, timeout=30)
            return c["id"]
    r = requests.post(f"{API}/co-owners", headers=H(owner_token),
                      json={"email": CO_EMAIL, "name": "Iter46 Co", "role": "co_owner", "project_ids": [pid]}, timeout=30)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


# ---------- Split + contributions ----------

class TestSplitContributions:
    def test_put_split_with_contributions_persists(self, owner_token, pid, coowner):
        body = {"shares": {coowner: 25}, "contributions": {"owner": 60000, coowner: 20000}}
        r = requests.put(f"{API}/project/split", headers=H(owner_token), json=body, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["has_contributions"] is True
        assert d["figures"]["total_contributed"] == 80000.0
        owner_row = next(x for x in d["rows"] if x["is_owner"])
        co_row = next(x for x in d["rows"] if x["co_owner_id"] == coowner)
        assert owner_row["contribution"] == 60000.0
        assert co_row["contribution"] == 20000.0
        assert co_row["pct"] == 25
        # cash_return_pct = annual_cashflow / contribution * 100
        if co_row["annual_cashflow"] and co_row["contribution"]:
            assert co_row["cash_return_pct"] == round(co_row["annual_cashflow"] / co_row["contribution"] * 100, 1)
        if co_row["profit"] is not None and co_row["contribution"]:
            assert co_row["profit_return_pct"] == round(co_row["profit"] / co_row["contribution"] * 100, 1)

    def test_get_split_returns_contributions(self, owner_token):
        r = requests.get(f"{API}/project/split", headers=H(owner_token), timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["has_contributions"] is True
        assert d["figures"]["total_contributed"] > 0
        for row in d["rows"]:
            assert "contribution" in row
            assert "cash_return_pct" in row
            assert "profit_return_pct" in row

    def test_omitting_contributions_keeps_existing(self, owner_token, pid, coowner):
        # Save split without contributions key
        r = requests.put(f"{API}/project/split", headers=H(owner_token),
                         json={"shares": {coowner: 30}}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["has_contributions"] is True, "existing contributions should remain when key omitted"
        assert d["figures"]["total_contributed"] == 80000.0

    def test_unknown_key_in_contributions_is_400(self, owner_token, pid, coowner):
        r = requests.put(f"{API}/project/split", headers=H(owner_token),
                         json={"shares": {coowner: 10}, "contributions": {"not-a-real-id": 1000}}, timeout=30)
        assert r.status_code == 400, r.text

    def test_negative_contribution_is_400(self, owner_token, coowner):
        r = requests.put(f"{API}/project/split", headers=H(owner_token),
                         json={"shares": {coowner: 10}, "contributions": {"owner": -5}}, timeout=30)
        assert r.status_code == 400, r.text


# ---------- Statements ----------

class TestStatements:
    def test_get_statements_label_and_rows(self, owner_token, pid, coowner):
        # Ensure split exists first
        requests.put(f"{API}/project/split", headers=H(owner_token),
                     json={"shares": {coowner: 25}, "contributions": {"owner": 60000, coowner: 20000}}, timeout=30)
        r = requests.get(f"{API}/project/statements?tax_year=2025", headers=H(owner_token), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["label"] == "6 Apr 2025 – 5 Apr 2026"
        assert d["tax_year"] == 2025
        assert "rent_received" in d and "expenses" in d and "net" in d
        assert d["has_split"] is True
        co_rows = [row for row in d["rows"] if not row["is_owner"]]
        assert any(row["co_owner_id"] == coowner for row in co_rows)
        for row in co_rows:
            if row["pct"]:
                # per-row shares scale proportionally
                assert abs(row["rent_received"] - round(d["rent_received"] * row["pct"] / 100, 2)) < 0.02
                assert abs(row["expenses"] - round(d["expenses"] * row["pct"] / 100, 2)) < 0.02
                assert abs(row["net"] - round(d["net"] * row["pct"] / 100, 2)) < 0.02

    def test_post_statements_sends_and_logs(self, owner_token, pid, coowner):
        # Ensure split is set
        requests.put(f"{API}/project/split", headers=H(owner_token),
                     json={"shares": {coowner: 25}}, timeout=30)
        r = requests.post(f"{API}/project/statements", headers=H(owner_token),
                          json={"tax_year": 2025}, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        # Resend may rate-limit the preview account, so accept either sent or failed - key is that
        # the co-owner was targeted and the statement run was recorded.
        assert CO_EMAIL in d["sent"] or CO_EMAIL in d["failed"], d
        assert d["label"] == "6 Apr 2025 – 5 Apr 2026"
        # last_sent_at reflected on next GET
        time.sleep(0.5)
        g = requests.get(f"{API}/project/statements?tax_year=2025", headers=H(owner_token), timeout=30)
        assert g.json()["last_sent_at"] is not None
        # messages log contains coowner_statement entry — query via /messages filtered by co-owner email
        ml = requests.get(f"{API}/messages?email={CO_EMAIL}", headers=H(owner_token), timeout=30).json()
        kinds = [m.get("kind") for m in (ml.get("items") if isinstance(ml, dict) else ml)]
        assert "coowner_statement" in kinds, kinds[:10]

    def test_post_statements_400_when_no_shares(self, owner_token, pid, coowner):
        # Clear shares
        requests.put(f"{API}/project/split", headers=H(owner_token), json={"shares": {}}, timeout=30)
        r = requests.post(f"{API}/project/statements", headers=H(owner_token),
                          json={"tax_year": 2025}, timeout=30)
        assert r.status_code == 400, r.text
        assert "shares" in r.text.lower()
        # restore
        requests.put(f"{API}/project/split", headers=H(owner_token),
                     json={"shares": {coowner: 25}}, timeout=30)

    def test_post_statements_403_for_coowner(self, owner_token, pid, coowner):
        """Acting as the co_owner on the owner's project must return 403."""
        # The invited co_owner needs an account to log in. Register them if not exists.
        reg = requests.post(f"{API}/auth/register", json={
            "name": "Iter46 Co", "email": CO_EMAIL, "password": "iter46pass"
        }, timeout=30)
        if reg.status_code in (200, 201):
            co_tok = reg.json().get("token") or reg.json().get("access_token")
            co_uid = reg.json()["user"]["id"]
        else:
            lo = requests.post(f"{API}/auth/login",
                               json={"email": CO_EMAIL, "password": "iter46pass"}, timeout=30)
            if lo.status_code != 200:
                pytest.skip("Cannot authenticate as co-owner for 403 test")
            co_tok = lo.json().get("token") or lo.json().get("access_token")
            co_uid = lo.json()["user"]["id"]
        # Make sure the demo owner has shares set so send_statements wouldn't 400 on this project
        requests.put(f"{API}/project/split", headers=H(owner_token),
                     json={"shares": {coowner: 25}}, timeout=30)
        # Wire acting_owner_id so the co-owner is seen as acting on owner's project
        async def _wire():
            mongo = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
            dbname = os.environ.get("DB_NAME") or "test_database"
            cli = AsyncIOMotorClient(mongo)
            dbh = cli[dbname]
            from bson import ObjectId
            owner_doc = await dbh.users.find_one({"email": DEMO["email"]}, {"_id": 1})
            await dbh.users.update_one({"_id": ObjectId(co_uid)},
                                       {"$set": {"acting_owner_id": str(owner_doc["_id"]), "active_project_id": pid}})
            cli.close()
        try:
            asyncio.get_event_loop().run_until_complete(_wire())
        except RuntimeError:
            asyncio.new_event_loop().run_until_complete(_wire())
        r = requests.post(f"{API}/project/statements", headers=H(co_tok),
                          json={"tax_year": 2025}, timeout=30)
        assert r.status_code == 403, r.text


# ---------- run_auto_statements logic ----------

class TestAutoStatements:
    def test_run_auto_statements_returns_0_past_window(self):
        """Container date is Oct 2026 which is >60 days after 6 Apr 2026."""
        import sys
        sys.path.insert(0, "/app/backend")
        from routes.ownership import run_auto_statements, tax_year_now
        # tax_year_now for Oct 2026 -> 2025
        assert tax_year_now(date(2026, 10, 17)) == 2025
        # before 6 Apr
        assert tax_year_now(date(2026, 4, 5)) == 2024
        # on 6 Apr
        assert tax_year_now(date(2026, 4, 6)) == 2025
        n = asyncio.get_event_loop().run_until_complete(run_auto_statements())
        assert n == 0


# ---------- Repair history ----------

class TestRepairHistory:
    def test_history_shape_and_totals(self, owner_token, pid):
        r = requests.get(f"{API}/repairs/history", headers=H(owner_token), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "items" in d and "totals" in d
        t = d["totals"]
        for k in ("count", "open", "fixed", "avg_days_to_fix", "total_cost", "tenant_reported"):
            assert k in t, k
        assert t["count"] == len(d["items"])
        assert t["open"] + t["fixed"] == t["count"]
        fixed = [i for i in d["items"] if i["status"] == "fixed"]
        assert t["fixed"] == len(fixed)
        tenant = [i for i in d["items"] if i["source"] == "tenant"]
        assert t["tenant_reported"] == len(tenant)
        for i in d["items"]:
            for k in ("id", "room", "description", "status", "source", "fixed_by", "fix_cost", "days"):
                assert k in i, k
            assert i["source"] in ("tenant", "snag")
            assert isinstance(i["days"], (int, float))

    def test_history_tasks_manager_has_no_cost(self, owner_token, pid):
        """A tasks-only manager must get fix_cost=None and total_cost=None."""
        mgr_email = "iter46mgr@example.com"
        # Register a user that will act as the owner's tasks-only manager
        reg = requests.post(f"{API}/auth/register", json={
            "name": "Iter46 Mgr", "email": mgr_email, "password": "iter46pass"
        }, timeout=30)
        if reg.status_code in (200, 201):
            tok = reg.json().get("token") or reg.json().get("access_token")
            mgr_uid = reg.json()["user"]["id"]
        else:
            lo = requests.post(f"{API}/auth/login",
                               json={"email": mgr_email, "password": "iter46pass"}, timeout=30)
            if lo.status_code != 200:
                pytest.skip("Cannot authenticate as manager")
            tok = lo.json().get("token") or lo.json().get("access_token")
            mgr_uid = lo.json()["user"]["id"]
        # Create co_owners doc with role=manager, scoped to this project, and set acting_owner_id on the manager user
        async def _wire():
            mongo = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
            dbname = os.environ.get("DB_NAME") or "test_database"
            cli = AsyncIOMotorClient(mongo)
            dbh = cli[dbname]
            owner_doc = await dbh.users.find_one({"email": DEMO["email"]}, {"_id": 1})
            from bson import ObjectId
            await dbh.co_owners.update_one(
                {"owner_id": str(owner_doc["_id"]), "email": mgr_email},
                {"$set": {"owner_id": str(owner_doc["_id"]), "email": mgr_email, "role": "manager",
                           "project_ids": [pid], "money_access": False,
                           "invited_at": "2026-10-17T00:00:00+00:00"}}, upsert=True)
            await dbh.users.update_one({"_id": ObjectId(mgr_uid)},
                                       {"$set": {"acting_owner_id": str(owner_doc["_id"]), "active_project_id": pid}})
            cli.close()
        try:
            asyncio.get_event_loop().run_until_complete(_wire())
        except RuntimeError:
            asyncio.new_event_loop().run_until_complete(_wire())
        r = requests.get(f"{API}/repairs/history", headers=H(tok), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["totals"]["total_cost"] is None, d["totals"]
        for i in d["items"]:
            assert i["fix_cost"] is None, i


# ---------- Cleanup ----------

@pytest.fixture(scope="module", autouse=True)
def _cleanup_at_end(owner_token, pid):
    yield
    # Remove invited co_owners iter46 + delivered@resend.dev, ownership_shares and coowner_statements for pid
    try:
        mongo = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
        dbname = os.environ.get("DB_NAME") or "test_database"
        async def _clean():
            client = AsyncIOMotorClient(mongo)
            db = client[dbname]
            await db.co_owners.delete_many({"email": {"$in": [CO_EMAIL, "iter46mgr@example.com"]}})
            await db.co_owner_links.delete_many({"email": {"$in": [CO_EMAIL, "iter46mgr@example.com"]}})
            await db.users.delete_many({"email": {"$in": [CO_EMAIL, "iter46mgr@example.com"]}})
            await db.ownership_shares.delete_many({"project_id": pid})
            await db.coowner_statements.delete_many({"project_id": pid})
            client.close()
        try:
            asyncio.get_event_loop().run_until_complete(_clean())
        except RuntimeError:
            asyncio.new_event_loop().run_until_complete(_clean())
    except Exception as e:
        print(f"cleanup error: {e}")
