"""Iteration 56 - Remove co-owners + apply ownership share across projects.

Covers:
- POST /api/co-owners/{cid}/apply-share: sets % on all accessible projects; pct=0 clears; 400 when other co-owners'
  shares + new pct > 100 on any project (nothing changed); 404 for unknown cid; 422 for pct>100 or <0.
- GET /api/co-owners now returns 'shares' map per person.
- DELETE /api/co-owners/{cid} clears that person's shares AND contributions from ownership_shares.
- After apply-share, GET /api/project/split per project shows the person's pct and owner = 100 - sum.
"""
import os
import sys
import uuid

import pytest
import requests

sys.path.insert(0, "/app/backend")

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
assert BASE, "EXPO_PUBLIC_BACKEND_URL env var must be set"
API = f"{BASE}/api"

import pymongo

_MONGO = pymongo.MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
_DB = _MONGO[os.environ.get("DB_NAME", "test_database")]

DEMO_EMAIL = "demo@mybuilder.app"
DEMO_PASS = "demo1234"


# -- helpers -----------------------------------------------------------------

def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=20)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _rand_email():
    return f"test_i56_{uuid.uuid4().hex[:10]}@example.com"


def _cleanup_cos(tok, keep=None):
    keep = keep or set()
    r = requests.get(f"{API}/co-owners", headers=_h(tok), timeout=20)
    if r.status_code != 200:
        return
    for c in r.json():
        if c["id"] in keep:
            continue
        if c["email"].startswith("test_i56_"):
            requests.delete(f"{API}/co-owners/{c['id']}", headers=_h(tok), timeout=20)


def _list_projects(tok):
    r = requests.get(f"{API}/projects", headers=_h(tok), timeout=20)
    assert r.status_code == 200, r.text
    return [p for p in r.json() if not p.get("shared")]


def _set_active(tok, pid):
    r = requests.post(f"{API}/projects/{pid}/activate", headers=_h(tok), timeout=20)
    assert r.status_code == 200, r.text


def _split(tok, pid):
    _set_active(tok, pid)
    r = requests.get(f"{API}/project/split", headers=_h(tok), timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def tok():
    t = _login(DEMO_EMAIL, DEMO_PASS)
    _cleanup_cos(t)
    yield t
    _cleanup_cos(t)


_CREATED_PIDS = []


@pytest.fixture(scope="module")
def projects(tok):
    pr = _list_projects(tok)
    while len(pr) < 2:
        r = requests.post(f"{API}/projects", headers=_h(tok),
                          json={"name": f"TEST_i56_{uuid.uuid4().hex[:6]}", "property_type": "residential", "purpose": "investment"},
                          timeout=20)
        assert r.status_code == 200, r.text
        _CREATED_PIDS.append(r.json()["id"])
        pr = _list_projects(tok)
    yield pr
    for pid in _CREATED_PIDS:
        requests.delete(f"{API}/projects/{pid}", headers=_h(tok), timeout=20)


# -- tests -------------------------------------------------------------------

class TestApplyShare:
    """POST /api/co-owners/{cid}/apply-share flows."""

    def test_shares_field_on_list_and_apply_sets_pct(self, tok, projects):
        email = _rand_email()
        r = requests.post(f"{API}/co-owners", headers=_h(tok),
                          json={"email": email, "role": "co_owner", "project_ids": None}, timeout=20)
        assert r.status_code == 200, r.text
        cid = r.json()["id"]
        assert r.json().get("shares") == {}, "Fresh co-owner should have empty shares"

        # Apply 25% to all projects
        r = requests.post(f"{API}/co-owners/{cid}/apply-share", headers=_h(tok), json={"pct": 25}, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pct"] == 25
        assert body["count"] == len(projects)
        assert isinstance(body["projects"], list) and len(body["projects"]) == len(projects)

        # GET /co-owners now shows shares per project
        r = requests.get(f"{API}/co-owners", headers=_h(tok), timeout=20)
        assert r.status_code == 200
        me = next(c for c in r.json() if c["id"] == cid)
        assert "shares" in me and isinstance(me["shares"], dict)
        for p in projects:
            assert me["shares"].get(p["id"]) == 25, f"Expected 25% on project {p['id']}, got {me['shares']}"

        # Each project split: owner share = 100 - 25 = 75, person has 25
        for p in projects:
            sp = _split(tok, p["id"])
            owner_row = next(r for r in sp["rows"] if r["is_owner"])
            co_row = next(r for r in sp["rows"] if r.get("co_owner_id") == cid)
            assert co_row["pct"] == 25
            assert owner_row["pct"] == 75

        requests.delete(f"{API}/co-owners/{cid}", headers=_h(tok), timeout=20)

    def test_pct_zero_clears_share(self, tok, projects):
        email = _rand_email()
        cid = requests.post(f"{API}/co-owners", headers=_h(tok),
                            json={"email": email, "role": "co_owner", "project_ids": None}, timeout=20).json()["id"]
        requests.post(f"{API}/co-owners/{cid}/apply-share", headers=_h(tok), json={"pct": 10}, timeout=20)

        r = requests.post(f"{API}/co-owners/{cid}/apply-share", headers=_h(tok), json={"pct": 0}, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["pct"] == 0

        r = requests.get(f"{API}/co-owners", headers=_h(tok), timeout=20)
        me = next(c for c in r.json() if c["id"] == cid)
        assert me["shares"] == {}, f"Expected shares cleared; got {me['shares']}"

        for p in projects:
            sp = _split(tok, p["id"])
            owner_row = next(r for r in sp["rows"] if r["is_owner"])
            assert owner_row["pct"] == 100

        requests.delete(f"{API}/co-owners/{cid}", headers=_h(tok), timeout=20)

    def test_blocked_when_other_coowners_exceed(self, tok, projects):
        # Co-owner A gets 70% everywhere
        emailA, emailB = _rand_email(), _rand_email()
        cidA = requests.post(f"{API}/co-owners", headers=_h(tok),
                             json={"email": emailA, "role": "co_owner", "project_ids": None}, timeout=20).json()["id"]
        cidB = requests.post(f"{API}/co-owners", headers=_h(tok),
                             json={"email": emailB, "role": "co_owner", "project_ids": None}, timeout=20).json()["id"]
        assert requests.post(f"{API}/co-owners/{cidA}/apply-share", headers=_h(tok), json={"pct": 70}, timeout=20).status_code == 200

        # Trying 40% for B -> 70+40=110% on every project. Should block (nothing changed).
        r = requests.post(f"{API}/co-owners/{cidB}/apply-share", headers=_h(tok), json={"pct": 40}, timeout=20)
        assert r.status_code == 400, f"Expected 400, got {r.status_code} {r.text}"
        # Error message should name a project
        msg = r.json().get("detail", "")
        assert any(p["name"] in msg for p in projects), f"Error should name at least one over project: {msg}"

        # Confirm nothing was partially applied for B
        me = next(c for c in requests.get(f"{API}/co-owners", headers=_h(tok), timeout=20).json() if c["id"] == cidB)
        assert me["shares"] == {}, f"B's share should be unchanged (empty); got {me['shares']}"

        # Also confirm A's 70% still intact
        meA = next(c for c in requests.get(f"{API}/co-owners", headers=_h(tok), timeout=20).json() if c["id"] == cidA)
        for p in projects:
            assert meA["shares"].get(p["id"]) == 70

        requests.delete(f"{API}/co-owners/{cidA}", headers=_h(tok), timeout=20)
        requests.delete(f"{API}/co-owners/{cidB}", headers=_h(tok), timeout=20)

    def test_404_for_unknown_cid(self, tok):
        r = requests.post(f"{API}/co-owners/507f1f77bcf86cd799439011/apply-share",
                          headers=_h(tok), json={"pct": 10}, timeout=20)
        assert r.status_code == 404, r.text

    def test_422_pct_out_of_range(self, tok, projects):
        email = _rand_email()
        cid = requests.post(f"{API}/co-owners", headers=_h(tok),
                            json={"email": email, "role": "co_owner", "project_ids": None}, timeout=20).json()["id"]
        r1 = requests.post(f"{API}/co-owners/{cid}/apply-share", headers=_h(tok), json={"pct": 101}, timeout=20)
        r2 = requests.post(f"{API}/co-owners/{cid}/apply-share", headers=_h(tok), json={"pct": -1}, timeout=20)
        assert r1.status_code == 422, f"pct>100 should be 422, got {r1.status_code}"
        assert r2.status_code == 422, f"pct<0 should be 422, got {r2.status_code}"
        requests.delete(f"{API}/co-owners/{cid}", headers=_h(tok), timeout=20)

    def test_scoped_to_project_ids(self, tok, projects):
        # Co-owner scoped to only project[0]
        email = _rand_email()
        only = projects[0]
        r = requests.post(f"{API}/co-owners", headers=_h(tok),
                          json={"email": email, "role": "manager", "project_ids": [only["id"]], "money_access": True},
                          timeout=20)
        assert r.status_code == 200, r.text
        cid = r.json()["id"]
        r = requests.post(f"{API}/co-owners/{cid}/apply-share", headers=_h(tok), json={"pct": 15}, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["count"] == 1
        assert r.json()["projects"] == [only["name"]]

        sp = _split(tok, only["id"])
        co_row = next(r for r in sp["rows"] if r.get("co_owner_id") == cid)
        assert co_row["pct"] == 15

        # Other project unaffected
        other = projects[1]
        sp2 = _split(tok, other["id"])
        assert not any(r.get("co_owner_id") == cid for r in sp2["rows"]), "Scoped co-owner should not appear on other project"
        requests.delete(f"{API}/co-owners/{cid}", headers=_h(tok), timeout=20)


class TestDeleteClearsShares:
    """DELETE /api/co-owners/{cid} clears shares & contributions from ownership_shares."""

    def test_delete_clears_shares_and_contributions(self, tok, projects):
        email = _rand_email()
        cid = requests.post(f"{API}/co-owners", headers=_h(tok),
                            json={"email": email, "role": "co_owner", "project_ids": None}, timeout=20).json()["id"]
        # Give them 20% on all projects
        assert requests.post(f"{API}/co-owners/{cid}/apply-share", headers=_h(tok), json={"pct": 20}, timeout=20).status_code == 200
        # And set a contribution on project[0] via /project/split
        p0 = projects[0]
        _set_active(tok, p0["id"])
        r = requests.put(f"{API}/project/split", headers=_h(tok),
                         json={"shares": {cid: 20}, "contributions": {cid: 1000, "owner": 2000}}, timeout=20)
        assert r.status_code == 200, r.text

        # DELETE co-owner
        r = requests.delete(f"{API}/co-owners/{cid}", headers=_h(tok), timeout=20)
        assert r.status_code == 200

        # Mongo check: no shares.{cid} and no contributions.{cid}
        for d in _DB.ownership_shares.find({"owner_id": _login_user_id(tok)}):
            assert cid not in (d.get("shares") or {}), f"shares still has {cid}: {d}"
            assert cid not in (d.get("contributions") or {}), f"contributions still has {cid}: {d}"

        # split no longer lists them
        for p in projects:
            sp = _split(tok, p["id"])
            assert not any(r.get("co_owner_id") == cid for r in sp["rows"])


def _login_user_id(tok):
    r = requests.get(f"{API}/auth/me", headers=_h(tok), timeout=20)
    assert r.status_code == 200
    return r.json()["id"]
