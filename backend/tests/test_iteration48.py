"""Iteration 48 — Payout Tracker + Repeat Repair Flags + Statement PDFs
Backend endpoints under test:
  - GET /api/project/payouts
  - POST /api/project/payouts (owner-only; validations)
  - DELETE /api/project/payouts/{id}
  - GET /api/my-ownership (payout fields: earned/paid/balance/payouts, totals.paid/balance)
  - GET /api/repairs/history (repeats[] + items[].repeat flags)

Setup (per module): creates a fresh co-owner user, invites them, sets 30% share and
£5,000 contribution. Teardown removes everything created.
"""
import os
import uuid
from typing import Dict

import pytest
import requests

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or ""
).rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL or EXPO_BACKEND_URL must be set"

OWNER_EMAIL = "demo@mybuilder.app"
OWNER_PASS = "demo1234"


# ------------- helpers -------------
def _login(email: str, password: str) -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    j = r.json()
    return j.get("access_token") or j.get("token")


def _h(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ------------- module fixtures -------------
@pytest.fixture(scope="module")
def owner_token() -> str:
    return _login(OWNER_EMAIL, OWNER_PASS)


@pytest.fixture(scope="module")
def project_id(owner_token) -> str:
    r = requests.get(f"{BASE_URL}/api/project", headers=_h(owner_token), timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def coowner(owner_token, project_id):
    """Register a fresh co-owner user + invite them with a 30% share and £5,000 contribution."""
    tag = uuid.uuid4().hex[:8]
    email = f"iter48co{tag}@example.com"
    password = "pass12345"
    # register the user so they exist
    r = requests.post(f"{BASE_URL}/api/auth/register",
                      json={"name": "Iter48 CoOwner", "email": email, "password": password}, timeout=30)
    assert r.status_code in (200, 201), f"register: {r.status_code} {r.text}"
    # invite from owner
    inv = requests.post(f"{BASE_URL}/api/co-owners", headers=_h(owner_token),
                        json={"email": email, "project_ids": [project_id], "role": "co_owner"}, timeout=30)
    assert inv.status_code == 200, f"invite: {inv.status_code} {inv.text}"
    cid = inv.json()["id"]
    # set 30% share and £5,000 contribution
    sp = requests.put(f"{BASE_URL}/api/project/split", headers=_h(owner_token),
                      json={"shares": {cid: 30}, "contributions": {cid: 5000, "owner": 20000}}, timeout=30)
    assert sp.status_code == 200, f"split: {sp.status_code} {sp.text}"
    yield {"email": email, "password": password, "id": cid}
    # teardown
    _teardown_payouts(owner_token)
    requests.put(f"{BASE_URL}/api/project/split", headers=_h(owner_token),
                 json={"shares": {}, "contributions": {}}, timeout=30)
    requests.delete(f"{BASE_URL}/api/co-owners/{cid}", headers=_h(owner_token), timeout=30)
    _teardown_snags(owner_token)


def _teardown_payouts(owner_token):
    r = requests.get(f"{BASE_URL}/api/project/payouts", headers=_h(owner_token), timeout=30)
    if r.status_code != 200:
        return
    for p in r.json().get("people", []):
        for x in p.get("payouts", []):
            requests.delete(f"{BASE_URL}/api/project/payouts/{x['id']}", headers=_h(owner_token), timeout=30)


def _teardown_snags(owner_token):
    r = requests.get(f"{BASE_URL}/api/snags", headers=_h(owner_token), timeout=30)
    if r.status_code != 200:
        return
    for s in r.json():
        if s.get("description", "").startswith("ITER48_"):
            requests.delete(f"{BASE_URL}/api/snags/{s['id']}", headers=_h(owner_token), timeout=30)


# ========================================================================
# GET /api/project/payouts – ledger shape (people + income)
# ========================================================================
class TestPayoutsLedger:
    def test_payouts_shape(self, owner_token, coowner):
        r = requests.get(f"{BASE_URL}/api/project/payouts", headers=_h(owner_token), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        # income
        inc = d["income"]
        for k in ("rent_received", "expenses", "net"):
            assert k in inc, f"missing income.{k}"
            assert isinstance(inc[k], (int, float))
        assert round(inc["rent_received"] - inc["expenses"], 2) == round(inc["net"], 2)
        # people[]
        assert isinstance(d["people"], list)
        p = next((x for x in d["people"] if x["co_owner_id"] == coowner["id"]), None)
        assert p, f"co-owner {coowner['id']} not in people"
        for k in ("name", "pct", "earned", "paid", "balance", "payouts"):
            assert k in p, f"missing people[].{k}"
        assert p["pct"] == 30.0
        # earned ≈ net * pct / 100
        assert round(p["earned"], 2) == round(inc["net"] * 30 / 100, 2)
        # paid starts at 0, balance == earned
        assert p["paid"] == 0.0
        assert round(p["balance"], 2) == round(p["earned"], 2)
        assert p["payouts"] == []


# ========================================================================
# POST /api/project/payouts – create + validations
# ========================================================================
class TestPayoutCreate:
    def test_add_payout_updates_balance(self, owner_token, coowner):
        r = requests.post(f"{BASE_URL}/api/project/payouts", headers=_h(owner_token),
                          json={"co_owner_id": coowner["id"], "amount": 100.0, "date": "2025-10-01", "note": "ITER48 test"},
                          timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        p = next(x for x in d["people"] if x["co_owner_id"] == coowner["id"])
        assert p["paid"] == 100.0
        assert len(p["payouts"]) == 1
        assert p["payouts"][0]["amount"] == 100.0
        assert p["payouts"][0]["date"] == "2025-10-01"
        assert p["payouts"][0]["note"] == "ITER48 test"
        assert "id" in p["payouts"][0]
        # GET verifies persistence
        r2 = requests.get(f"{BASE_URL}/api/project/payouts", headers=_h(owner_token), timeout=30)
        p2 = next(x for x in r2.json()["people"] if x["co_owner_id"] == coowner["id"])
        assert p2["paid"] == 100.0

    def test_amount_must_be_positive(self, owner_token, coowner):
        r = requests.post(f"{BASE_URL}/api/project/payouts", headers=_h(owner_token),
                          json={"co_owner_id": coowner["id"], "amount": 0, "date": "2025-10-01"}, timeout=30)
        assert r.status_code == 422

    def test_unknown_coowner_returns_400(self, owner_token):
        r = requests.post(f"{BASE_URL}/api/project/payouts", headers=_h(owner_token),
                          json={"co_owner_id": "6ad39c08204308b85600dead", "amount": 10.0, "date": "2025-10-01"}, timeout=30)
        assert r.status_code == 400, r.text

    def test_bad_date_rejected(self, owner_token, coowner):
        r = requests.post(f"{BASE_URL}/api/project/payouts", headers=_h(owner_token),
                          json={"co_owner_id": coowner["id"], "amount": 10.0, "date": "01/10/2025"}, timeout=30)
        assert r.status_code in (400, 422), r.text

    def test_coowner_cannot_add_payout_403(self, coowner, project_id, owner_token):
        """Acting as the co-owner on the owner's project should return 403 ('owner-only')."""
        co_tok = _login(coowner["email"], coowner["password"])
        # Activate the shared project for the co-owner so active_pid resolves
        requests.post(f"{BASE_URL}/api/projects/{project_id}/activate", headers=_h(co_tok), timeout=30)
        r = requests.post(f"{BASE_URL}/api/project/payouts", headers=_h(co_tok),
                          json={"co_owner_id": coowner["id"], "amount": 50.0, "date": "2025-10-02"}, timeout=30)
        assert r.status_code == 403, f"expected 403 for co-owner acting on owner's project, got {r.status_code} {r.text}"


# ========================================================================
# DELETE /api/project/payouts/{id}
# ========================================================================
class TestPayoutDelete:
    def test_delete_payout(self, owner_token, coowner):
        add = requests.post(f"{BASE_URL}/api/project/payouts", headers=_h(owner_token),
                            json={"co_owner_id": coowner["id"], "amount": 25.0, "date": "2025-10-05", "note": "ITER48 del"},
                            timeout=30)
        assert add.status_code == 200
        pid = next(x["payouts"][-1]["id"] for x in add.json()["people"] if x["co_owner_id"] == coowner["id"])
        r = requests.delete(f"{BASE_URL}/api/project/payouts/{pid}", headers=_h(owner_token), timeout=30)
        assert r.status_code == 200
        p = next(x for x in r.json()["people"] if x["co_owner_id"] == coowner["id"])
        assert all(x["id"] != pid for x in p["payouts"]), "payout not removed"


# ========================================================================
# GET /api/my-ownership – includes earned/paid/balance/payouts + totals
# ========================================================================
class TestMyOwnershipPayouts:
    def test_coowner_sees_payouts(self, owner_token, coowner, project_id):
        # Ensure one payout exists
        requests.post(f"{BASE_URL}/api/project/payouts", headers=_h(owner_token),
                      json={"co_owner_id": coowner["id"], "amount": 75.0, "date": "2025-10-10", "note": "ITER48 myown"},
                      timeout=30)
        tok = _login(coowner["email"], coowner["password"])
        r = requests.get(f"{BASE_URL}/api/my-ownership", headers=_h(tok), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        proj = next((p for p in d["projects"] if p["project_id"] == project_id), None)
        assert proj, f"shared project {project_id} missing in /my-ownership"
        for k in ("earned", "paid", "balance", "payouts"):
            assert k in proj, f"missing project.{k}"
        assert proj["paid"] >= 75.0
        assert isinstance(proj["payouts"], list) and len(proj["payouts"]) >= 1
        # First payout record shape (no co_owner_id etc.)
        p0 = proj["payouts"][0]
        for k in ("id", "amount", "date", "note"):
            assert k in p0, f"payout missing {k}"
        # totals
        tot = d["totals"]
        for k in ("paid", "balance"):
            assert k in tot
        assert tot["paid"] >= 75.0


# ========================================================================
# GET /api/repairs/history – repeats detection
# ========================================================================
class TestRepairHistoryRepeats:
    def test_repeats_and_keywords(self, owner_token):
        _teardown_snags(owner_token)  # start clean
        s1 = requests.post(f"{BASE_URL}/api/snags", headers=_h(owner_token),
                           json={"room": "Bathroom", "description": "ITER48_Leak under sink", "priority": "medium"},
                           timeout=30)
        s2 = requests.post(f"{BASE_URL}/api/snags", headers=_h(owner_token),
                           json={"room": "Bathroom", "description": "ITER48_Leak behind toilet", "priority": "high"},
                           timeout=30)
        assert s1.status_code == 200 and s2.status_code == 200, f"{s1.status_code}/{s2.status_code}"
        sid1, sid2 = s1.json()["id"], s2.json()["id"]
        r = requests.get(f"{BASE_URL}/api/repairs/history", headers=_h(owner_token), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        bathroom = next((x for x in d["repeats"] if x["room"].lower() == "bathroom"), None)
        assert bathroom, f"Bathroom not flagged as repeat: {d['repeats']}"
        assert bathroom["count"] >= 2
        assert "leak" in [k.lower() for k in bathroom["keywords"]], f"keywords={bathroom['keywords']}"
        assert sid1 in bathroom["ids"] and sid2 in bathroom["ids"]
        # items[].repeat flag true for both
        flags = {i["id"]: i["repeat"] for i in d["items"] if i["id"] in (sid1, sid2)}
        assert flags.get(sid1) is True and flags.get(sid2) is True, f"items repeat flags: {flags}"
        # cleanup these two
        requests.delete(f"{BASE_URL}/api/snags/{sid1}", headers=_h(owner_token), timeout=30)
        requests.delete(f"{BASE_URL}/api/snags/{sid2}", headers=_h(owner_token), timeout=30)
