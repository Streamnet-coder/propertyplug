"""Iteration 47 — Co-owner portfolio portal views
Tests:
 - GET /api/my-ownership (co-owner view)
 - GET /api/my-ownership/statement (per-year detail)
 - GET /api/ownership/portfolio (owner view)
"""
import os
import uuid
from typing import Any, Dict

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL / EXPO_BACKEND_URL must be set"

OWNER_EMAIL = "demo@mybuilder.app"
OWNER_PASS = "demo1234"
COOWNER_EMAIL = "own7b068e@example.com"
COOWNER_PASS = "pass12345"
COOWNER_ID = "6ad39c08204308b856c65c6d"  # co_owners doc _id
PID = "6acf7cf334e1da0ef6b14f50"  # Nottingham Victorian Refurb


def _login(email: str, password: str) -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.fixture(scope="module")
def owner_token() -> str:
    return _login(OWNER_EMAIL, OWNER_PASS)


@pytest.fixture(scope="module")
def coowner_token() -> str:
    return _login(COOWNER_EMAIL, COOWNER_PASS)


def _h(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# -------------------- GET /api/my-ownership --------------------
class TestMyOwnership:
    def test_coowner_sees_shared_project(self, coowner_token):
        r = requests.get(f"{BASE_URL}/api/my-ownership", headers=_h(coowner_token), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert isinstance(d.get("projects"), list)
        pids = [p["project_id"] for p in d["projects"]]
        assert PID in pids, f"shared project {PID} not in my-ownership: {pids}"
        p = next(x for x in d["projects"] if x["project_id"] == PID)
        for k in ("pct", "contribution", "profit", "monthly_cashflow", "annual_cashflow",
                  "cash_return_pct", "profit_return_pct", "statements", "owner_name", "project_name", "address"):
            assert k in p, f"missing key {k} in project row"
        assert p["pct"] == 25.0, f"expected 25% share, got {p['pct']}"
        assert p["contribution"] == 10000.0, f"expected £10,000, got {p['contribution']}"
        assert isinstance(p["statements"], list)
        # totals
        tot = d.get("totals") or {}
        assert tot.get("contribution") == 10000.0

    def test_statement_404_when_not_sent(self, coowner_token):
        """Pick an unlikely tax year to ensure no statement exists."""
        r = requests.get(f"{BASE_URL}/api/my-ownership/statement",
                         params={"project_id": PID, "tax_year": 2001},
                         headers=_h(coowner_token), timeout=30)
        assert r.status_code == 404

    def test_statement_404_for_unknown_project(self, coowner_token):
        r = requests.get(f"{BASE_URL}/api/my-ownership/statement",
                         params={"project_id": "6acffffffffffffffffffff0", "tax_year": 2025},
                         headers=_h(coowner_token), timeout=30)
        assert r.status_code == 404


# -------------------- Statement send & verify --------------------
class TestStatementSendAndRead:
    """Owner activates the project then sends statements; co-owner then reads the detail."""

    def _activate(self, owner_token: str):
        r = requests.post(f"{BASE_URL}/api/projects/{PID}/activate",
                          headers=_h(owner_token), timeout=30)
        assert r.status_code < 400, f"activate failed: {r.status_code} {r.text}"

    def test_owner_sends_then_coowner_reads(self, owner_token, coowner_token):
        self._activate(owner_token)
        send = requests.post(f"{BASE_URL}/api/project/statements",
                             json={"tax_year": 2025}, headers=_h(owner_token), timeout=60)
        # Resend may rate-limit; either way, the coowner_statements doc is inserted
        assert send.status_code == 200, f"send statements failed: {send.status_code} {send.text}"
        s = send.json()
        assert "label" in s
        # Now try to read the detail as co-owner — only works if co-owner was in `sent`
        if COOWNER_EMAIL in (s.get("sent") or []):
            r = requests.get(f"{BASE_URL}/api/my-ownership/statement",
                             params={"project_id": PID, "tax_year": 2025},
                             headers=_h(coowner_token), timeout=30)
            assert r.status_code == 200, f"detail should 200 after send: {r.status_code} {r.text}"
            d = r.json()
            assert "label" in d and "whole" in d and "mine" in d
            for k in ("rent_received", "expenses", "net"):
                assert k in d["whole"]
            for k in ("pct", "rent_received", "expenses", "net", "contribution"):
                assert k in d["mine"]
            assert d["mine"]["pct"] == 25.0
            assert d["mine"]["contribution"] == 10000.0
        else:
            # Resend rejected the email; inject into mongo to still exercise the read path
            from pymongo import MongoClient
            cli = MongoClient(os.environ["MONGO_URL"])
            dbn = cli[os.environ["DB_NAME"]]
            dbn.coowner_statements.update_one(
                {"project_id": PID, "tax_year": 2025, "sent": COOWNER_EMAIL},
                {"$setOnInsert": {"project_id": PID, "owner_id": None, "tax_year": 2025,
                                  "sent_at": "2026-01-01T00:00:00Z", "auto": False,
                                  "sent": [COOWNER_EMAIL], "failed": [], "_test": True}},
                upsert=True)
            r = requests.get(f"{BASE_URL}/api/my-ownership/statement",
                             params={"project_id": PID, "tax_year": 2025},
                             headers=_h(coowner_token), timeout=30)
            assert r.status_code == 200, f"detail should 200 after mongo insert: {r.status_code} {r.text}"
            d = r.json()
            assert d["mine"]["pct"] == 25.0

    def test_statement_now_in_my_ownership_list(self, coowner_token):
        r = requests.get(f"{BASE_URL}/api/my-ownership", headers=_h(coowner_token), timeout=30)
        assert r.status_code == 200
        d = r.json()
        p = next(x for x in d["projects"] if x["project_id"] == PID)
        years = [s["tax_year"] for s in p["statements"]]
        assert 2025 in years, f"2025 statement should be visible, got {years}"


# -------------------- GET /api/ownership/portfolio --------------------
class TestPortfolio:
    def test_owner_portfolio_includes_split(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/ownership/portfolio", headers=_h(owner_token), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "people" in d and "projects" in d
        # owner-first ordering
        assert d["people"][0]["is_owner"] is True
        # co-owner must appear with 25% + £10,000
        co = next((p for p in d["people"] if p.get("key") == COOWNER_ID), None)
        assert co is not None, f"co-owner key {COOWNER_ID} not in people: {[p['key'] for p in d['people']]}"
        assert co["contribution"] == 10000.0
        assert co["projects"] >= 1
        # projects row has 25% for the co-owner
        pr = next((x for x in d["projects"] if x["project_id"] == PID), None)
        assert pr is not None
        row = next((r for r in pr["rows"] if r["co_owner_id"] == COOWNER_ID), None)
        assert row and row["pct"] == 25.0
        assert row["contribution"] == 10000.0


# -------------------- Edge: fresh user with nothing shared --------------------
class TestEmptyUser:
    def test_fresh_user_empty_ownership(self):
        # register a fresh user
        email = f"iter47empty_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{BASE_URL}/api/auth/register",
                          json={"name": "Iter47 Empty", "email": email, "password": "pass12345"},
                          timeout=30)
        assert r.status_code in (200, 201), r.text
        tok = r.json().get("access_token") or r.json().get("token") or _login(email, "pass12345")
        g = requests.get(f"{BASE_URL}/api/my-ownership", headers=_h(tok), timeout=30)
        assert g.status_code == 200
        d = g.json()
        assert d["projects"] == []
        assert d["totals"]["contribution"] == 0


# -------------------- Edge: tasks-only manager hidden --------------------
class TestTasksOnlyManagerExcluded:
    """Create a tasks-only manager (money_access=False) tied to the demo project
    and verify /api/my-ownership returns empty for them."""

    def test_manager_without_money_sees_empty(self, owner_token):
        from pymongo import MongoClient
        from bson import ObjectId
        cli = MongoClient(os.environ["MONGO_URL"])
        dbn = cli[os.environ["DB_NAME"]]
        # register a new user we can log in as
        email = f"iter47mgr_{uuid.uuid4().hex[:8]}@example.com"
        rr = requests.post(f"{BASE_URL}/api/auth/register",
                           json={"name": "Iter47 Mgr", "email": email, "password": "pass12345"},
                           timeout=30)
        assert rr.status_code in (200, 201)
        tok = rr.json().get("access_token") or rr.json().get("token") or _login(email, "pass12345")

        # find demo owner id
        owner_doc = dbn.users.find_one({"email": OWNER_EMAIL}, {"_id": 1})
        assert owner_doc
        owner_id = str(owner_doc["_id"])

        # insert tasks-only manager co_owners doc, with share+contribution recorded (which should be ignored)
        co_id = ObjectId()
        dbn.co_owners.insert_one({
            "_id": co_id, "owner_id": owner_id, "email": email, "name": "Iter47 Mgr",
            "role": "manager", "project_ids": [PID], "money_access": False,
            "auto_add": False, "invited_at": "2026-01-01T00:00:00Z", "_test": True,
        })
        dbn.ownership_shares.update_one(
            {"project_id": PID},
            {"$set": {f"shares.{str(co_id)}": 5, f"contributions.{str(co_id)}": 500}},
            upsert=True)
        try:
            g = requests.get(f"{BASE_URL}/api/my-ownership", headers=_h(tok), timeout=30)
            assert g.status_code == 200
            d = g.json()
            assert d["projects"] == [], f"tasks-only manager should see no projects, got {d}"
        finally:
            # cleanup
            dbn.co_owners.delete_one({"_id": co_id})
            dbn.ownership_shares.update_one({"project_id": PID},
                                            {"$unset": {f"shares.{str(co_id)}": "",
                                                        f"contributions.{str(co_id)}": ""}})
            dbn.users.delete_one({"email": email})


# -------------------- Teardown-ish helper so pytest leaves nothing extra --------------------
def test_zz_cleanup_test_coowner_statements():
    """Remove any _test:true statement docs we inserted during this run.
    (Does NOT remove the main-agent-seeded co-owner — review request asks main
    agent cleanup to happen separately; we only touch our own test rows.)"""
    from pymongo import MongoClient
    cli = MongoClient(os.environ["MONGO_URL"])
    dbn = cli[os.environ["DB_NAME"]]
    dbn.coowner_statements.delete_many({"_test": True})
