"""Iteration 25 — Co-owners (shared full-access accounts) + three-tier Pro pricing (£19.99/mo, £199/yr, £499 lifetime).

Scope:
- Co-owner CRUD: invite (self/dup/max10 guards), list fields, remove.
- Shared-with-me + leave.
- Co-owner shared data flow: /projects shows owner's projects as shared=true, activate acts-as owner,
  /auth/me reflects acting_as, plan follows owner, data routes read/write owner's project, owner sees items.
- Restrictions: delete shared project 403, auth/plan + payments/* + delete-account operate on CO-OWNER's own account.
- Owner's active project unaffected by co-owner switching.
- Pricing: /payments/tiers content, /payments/checkout computes server-side amount (tx row), mark_paid math for
  monthly/yearly/lifetime, stacking on remaining time, and auto-downgrade for lapsed pro_until on next request.
"""
import os
import sys
import uuid
import asyncio
import pytest
import requests
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
sys.path.insert(0, "/app/backend")

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ["EXPO_BACKEND_URL"]).rstrip("/")
API = f"{BASE_URL}/api"


def _run(fn):
    from motor.motor_asyncio import AsyncIOMotorClient
    loop = asyncio.new_event_loop()
    try:
        async def _wrap():
            cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
            try:
                return await fn(cli[os.environ["DB_NAME"]])
            finally:
                cli.close()
        return loop.run_until_complete(_wrap())
    finally:
        loop.close()


def _delete_user_by_email(email):
    async def fn(db):
        u = await db.users.find_one({"email": email}, {"_id": 1})
        if not u:
            return
        uid = str(u["_id"])
        await db.users.delete_one({"_id": u["_id"]})
        for coll in ("projects", "line_items", "receipts", "snags", "snag_links", "documents",
                     "doc_folders", "milestones", "quote_requests", "stage_payments", "contacts",
                     "media", "shopping_items", "estimates", "payment_transactions", "planning_apps",
                     "messages", "trade_ratings", "snag_signoffs"):
            try:
                await db[coll].delete_many({"user_id": uid})
            except Exception:
                pass
        for coll in ("portal_members", "portal_activity", "portal_questions"):
            try:
                await db[coll].delete_many({"owner_id": uid})
            except Exception:
                pass
        await db.co_owners.delete_many({"$or": [{"owner_id": uid}, {"email": email}]})
    _run(fn)


def _reset_demo_actingas():
    async def fn(db):
        u = await db.users.find_one({"email": "demo@mybuilder.app"}, {"_id": 1})
        if u:
            await db.users.update_one({"_id": u["_id"]}, {"$set": {"acting_owner_id": None}})
    _run(fn)


def _set_demo_plan_basic():
    """Make sure demo ends up on basic plan, no lifetime pro, no pro_until lingering from a test."""
    async def fn(db):
        u = await db.users.find_one({"email": "demo@mybuilder.app"}, {"_id": 1})
        if u:
            await db.users.update_one({"_id": u["_id"]}, {"$set": {
                "plan": "basic", "pro_tier": None, "pro_until": None, "paid_pro": False,
            }})
            await db.payment_transactions.delete_many({"user_id": str(u["_id"])})
    _run(fn)


def _login(email, pwd):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _register(name, email, pwd):
    r = requests.post(f"{API}/auth/register", json={"name": name, "email": email, "password": pwd}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- Fixtures ----------
@pytest.fixture(scope="module")
def owner():
    tok = _login("demo@mybuilder.app", "demo1234")
    _reset_demo_actingas()
    _set_demo_plan_basic()
    # Clean any leftovers from previous test runs
    async def fn(db):
        u = await db.users.find_one({"email": "demo@mybuilder.app"}, {"_id": 1})
        if u:
            await db.co_owners.delete_many({"owner_id": str(u["_id"])})
    _run(fn)
    me = requests.get(f"{API}/auth/me", headers=_h(tok)).json()
    projs = requests.get(f"{API}/projects", headers=_h(tok)).json()
    # Pick Nottingham Victorian Refurb as active if present
    nv = next((p for p in projs if "Nottingham" in p.get("name", "")), projs[0])
    requests.post(f"{API}/projects/{nv['id']}/activate", headers=_h(tok))
    yield {"token": tok, "h": _h(tok), "id": me["id"], "email": me["email"], "name": me["name"],
           "project_id": nv["id"], "project_name": nv["name"]}
    # Teardown: reset demo
    _reset_demo_actingas()
    _set_demo_plan_basic()
    async def fn2(db):
        u = await db.users.find_one({"email": "demo@mybuilder.app"}, {"_id": 1})
        if u:
            await db.co_owners.delete_many({"owner_id": str(u["_id"])})
        # Re-activate Nottingham
    _run(fn2)
    projs2 = requests.get(f"{API}/projects", headers=_h(tok)).json()
    nv2 = next((p for p in projs2 if "Nottingham" in p.get("name", "")), None)
    if nv2:
        requests.post(f"{API}/projects/{nv2['id']}/activate", headers=_h(tok))


@pytest.fixture
def co_user():
    """A fresh co-owner account per test — teardown via /auth/account."""
    em = f"test_co_{uuid.uuid4().hex[:8]}@example.com"
    created = _register("Casey Co", em, "coowner1234")
    yield {"email": em, "token": created["access_token"], "h": _h(created["access_token"]),
           "id": created["user"]["id"], "name": "Casey Co"}
    _delete_user_by_email(em)


# =============================================================================
# 1. Co-owner CRUD (owner side)
# =============================================================================
class TestCoOwnerCRUD:
    def test_invite_self_rejected(self, owner):
        r = requests.post(f"{API}/co-owners", headers=owner["h"], json={"email": owner["email"]})
        assert r.status_code == 400
        assert "already own" in r.text.lower()

    def test_invite_and_list_fields(self, owner, co_user):
        r = requests.post(f"{API}/co-owners", headers=owner["h"], json={"email": co_user["email"]})
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["email"] == co_user["email"]
        assert b["has_account"] is True
        assert b["name"] == "Casey Co"
        assert "id" in b and "invited_at" in b and "email_sent" in b
        lst = requests.get(f"{API}/co-owners", headers=owner["h"]).json()
        row = next(x for x in lst if x["email"] == co_user["email"])
        assert row["has_account"] is True
        assert row["name"] == "Casey Co"
        # Cleanup
        requests.delete(f"{API}/co-owners/{row['id']}", headers=owner["h"])

    def test_invite_duplicate_rejected(self, owner, co_user):
        r1 = requests.post(f"{API}/co-owners", headers=owner["h"], json={"email": co_user["email"]})
        assert r1.status_code == 200
        r2 = requests.post(f"{API}/co-owners", headers=owner["h"], json={"email": co_user["email"]})
        assert r2.status_code == 400
        requests.delete(f"{API}/co-owners/{r1.json()['id']}", headers=owner["h"])

    def test_invite_without_account_has_account_false(self, owner):
        em = f"test_co_noacct_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{API}/co-owners", headers=owner["h"], json={"email": em})
        assert r.status_code == 200
        b = r.json()
        assert b["has_account"] is False
        assert b["name"] is None
        requests.delete(f"{API}/co-owners/{b['id']}", headers=owner["h"])

    def test_max_10_coowners(self, owner):
        ids = []
        for i in range(10):
            em = f"test_co_cap{i}_{uuid.uuid4().hex[:6]}@example.com"
            r = requests.post(f"{API}/co-owners", headers=owner["h"], json={"email": em})
            assert r.status_code == 200
            ids.append(r.json()["id"])
        em11 = f"test_co_cap11_{uuid.uuid4().hex[:6]}@example.com"
        r11 = requests.post(f"{API}/co-owners", headers=owner["h"], json={"email": em11})
        assert r11.status_code == 400
        assert "10 co-owners" in r11.text.lower() or "up to 10" in r11.text.lower()
        for i in ids:
            requests.delete(f"{API}/co-owners/{i}", headers=owner["h"])

    def test_delete_coowner(self, owner, co_user):
        r = requests.post(f"{API}/co-owners", headers=owner["h"], json={"email": co_user["email"]})
        cid = r.json()["id"]
        d = requests.delete(f"{API}/co-owners/{cid}", headers=owner["h"])
        assert d.status_code == 200
        # Second delete -> 404
        d2 = requests.delete(f"{API}/co-owners/{cid}", headers=owner["h"])
        assert d2.status_code == 404


# =============================================================================
# 2. Shared-with-me + full data flow
# =============================================================================
class TestSharedFlow:
    def test_shared_with_me_and_projects_listing(self, owner, co_user):
        # Owner invites
        inv = requests.post(f"{API}/co-owners", headers=owner["h"], json={"email": co_user["email"]})
        assert inv.status_code == 200
        # Co-user sees shared-with-me
        sw = requests.get(f"{API}/co-owners/shared-with-me", headers=co_user["h"]).json()
        assert any(o["owner_id"] == owner["id"] and o["owner_name"] == owner["name"] for o in sw)
        row = next(o for o in sw if o["owner_id"] == owner["id"])
        assert row["projects"] >= 1
        # Co-user /projects shows own + owner's (shared=true, owner_name)
        projs = requests.get(f"{API}/projects", headers=co_user["h"]).json()
        mine = [p for p in projs if not p["shared"]]
        shared = [p for p in projs if p["shared"]]
        assert mine, "co-user has their own seeded project"
        assert shared, "co-user sees owner's shared project"
        assert all(p["owner_name"] == owner["name"] for p in shared)
        assert any(p["id"] == owner["project_id"] for p in shared)
        requests.delete(f"{API}/co-owners/{inv.json()['id']}", headers=owner["h"])

    def test_activate_shared_switches_acting_as_and_plan(self, owner, co_user):
        # Set owner plan to pro so we can verify plan follows owner
        inv = requests.post(f"{API}/co-owners", headers=owner["h"], json={"email": co_user["email"]})
        assert inv.status_code == 200
        requests.post(f"{API}/auth/plan", headers=owner["h"], json={"plan": "pro"})
        # Co-user activates owner's shared project
        act = requests.post(f"{API}/projects/{owner['project_id']}/activate", headers=co_user["h"])
        assert act.status_code == 200
        me = requests.get(f"{API}/auth/me", headers=co_user["h"]).json()
        assert me["acting_as"] is not None
        assert me["acting_as"]["owner_id"] == owner["id"]
        assert me["acting_as"]["owner_name"] == owner["name"]
        assert me["plan"] == "pro"  # follows owner
        assert me["own_plan"] == "basic"  # their own
        # /project (singular) returns OWNER's project
        proj = requests.get(f"{API}/project", headers=co_user["h"]).json()
        assert proj["id"] == owner["project_id"]
        assert proj["name"] == owner["project_name"]
        # Data route read: line-items shows owner's data
        oli = requests.get(f"{API}/line-items", headers=owner["h"]).json()
        cli = requests.get(f"{API}/line-items", headers=co_user["h"]).json()
        assert isinstance(cli, list)
        assert {x["id"] for x in cli} == {x["id"] for x in oli}
        # Cleanup
        requests.post(f"{API}/auth/plan", headers=owner["h"], json={"plan": "basic"})
        requests.delete(f"{API}/co-owners/{inv.json()['id']}", headers=owner["h"])

    def test_coowner_edits_appear_for_owner(self, owner, co_user):
        inv = requests.post(f"{API}/co-owners", headers=owner["h"], json={"email": co_user["email"]})
        requests.post(f"{API}/projects/{owner['project_id']}/activate", headers=co_user["h"])
        # Create a snag as co-owner
        snag_body = {"title": f"TEST_snag_{uuid.uuid4().hex[:6]}", "description": "TEST_snag", "room": "Kitchen", "priority": "high"}
        r = requests.post(f"{API}/snags", headers=co_user["h"], json=snag_body)
        assert r.status_code == 200, r.text
        snag_id = r.json()["id"]
        # Owner sees it on their project
        owner_snags = requests.get(f"{API}/snags", headers=owner["h"]).json()
        assert any(s["id"] == snag_id for s in owner_snags)
        # Cleanup snag + co-owner link
        requests.delete(f"{API}/snags/{snag_id}", headers=owner["h"])
        requests.delete(f"{API}/co-owners/{inv.json()['id']}", headers=owner["h"])

    def test_delete_shared_project_forbidden(self, owner, co_user):
        inv = requests.post(f"{API}/co-owners", headers=owner["h"], json={"email": co_user["email"]})
        requests.post(f"{API}/projects/{owner['project_id']}/activate", headers=co_user["h"])
        r = requests.delete(f"{API}/projects/{owner['project_id']}", headers=co_user["h"])
        assert r.status_code == 403
        requests.delete(f"{API}/co-owners/{inv.json()['id']}", headers=owner["h"])

    def test_coowner_create_project_switches_back_to_own(self, owner, co_user):
        inv = requests.post(f"{API}/co-owners", headers=owner["h"], json={"email": co_user["email"]})
        requests.post(f"{API}/projects/{owner['project_id']}/activate", headers=co_user["h"])
        # Now acting_as owner. Create a project as co-owner.
        new = requests.post(f"{API}/projects", headers=co_user["h"], json={"name": "TEST_my_new_project"})
        assert new.status_code == 200
        new_pid = new.json()["id"]
        # /auth/me: acting_as cleared, active project = new one in own account
        me = requests.get(f"{API}/auth/me", headers=co_user["h"]).json()
        assert me["acting_as"] is None
        assert me["active_project_id"] == new_pid
        # Cleanup: switch to another project then delete the one we created
        # Need at least 2 projects to delete; the demo seeded one survives.
        projs = requests.get(f"{API}/projects", headers=co_user["h"]).json()
        others = [p for p in projs if not p["shared"] and p["id"] != new_pid]
        if others:
            requests.post(f"{API}/projects/{others[0]['id']}/activate", headers=co_user["h"])
            requests.delete(f"{API}/projects/{new_pid}", headers=co_user["h"])
        requests.delete(f"{API}/co-owners/{inv.json()['id']}", headers=owner["h"])

    def test_restricted_routes_operate_on_coowner_own_account(self, owner, co_user):
        inv = requests.post(f"{API}/co-owners", headers=owner["h"], json={"email": co_user["email"]})
        requests.post(f"{API}/projects/{owner['project_id']}/activate", headers=co_user["h"])
        # /auth/plan sets CO-OWNER's own plan, never owner's.
        before_owner = requests.get(f"{API}/auth/me", headers=owner["h"]).json()
        r = requests.post(f"{API}/auth/plan", headers=co_user["h"], json={"plan": "pro"})
        assert r.status_code == 200
        me = requests.get(f"{API}/auth/me", headers=co_user["h"]).json()
        assert me["own_plan"] == "pro"
        after_owner = requests.get(f"{API}/auth/me", headers=owner["h"]).json()
        assert after_owner["own_plan"] == before_owner["own_plan"], "owner's plan must not change"
        # Reset co-user own plan
        requests.post(f"{API}/auth/plan", headers=co_user["h"], json={"plan": "basic"})
        requests.delete(f"{API}/co-owners/{inv.json()['id']}", headers=owner["h"])

    def test_leave_shared_drops_acting_as(self, owner, co_user):
        inv = requests.post(f"{API}/co-owners", headers=owner["h"], json={"email": co_user["email"]})
        requests.post(f"{API}/projects/{owner['project_id']}/activate", headers=co_user["h"])
        me_before = requests.get(f"{API}/auth/me", headers=co_user["h"]).json()
        assert me_before["acting_as"] is not None
        # Leave
        r = requests.delete(f"{API}/co-owners/shared/{owner['id']}", headers=co_user["h"])
        assert r.status_code == 200
        me_after = requests.get(f"{API}/auth/me", headers=co_user["h"]).json()
        assert me_after["acting_as"] is None
        # /projects no longer shows the shared one
        projs = requests.get(f"{API}/projects", headers=co_user["h"]).json()
        assert not any(p["shared"] for p in projs)
        # inv record already removed by leave; owner's co-owner list is empty
        own_list = requests.get(f"{API}/co-owners", headers=owner["h"]).json()
        assert not any(c["email"] == co_user["email"] for c in own_list)

    def test_owner_remove_drops_coowner_access(self, owner, co_user):
        inv = requests.post(f"{API}/co-owners", headers=owner["h"], json={"email": co_user["email"]})
        requests.post(f"{API}/projects/{owner['project_id']}/activate", headers=co_user["h"])
        # Owner removes
        requests.delete(f"{API}/co-owners/{inv.json()['id']}", headers=owner["h"])
        me = requests.get(f"{API}/auth/me", headers=co_user["h"]).json()
        assert me["acting_as"] is None  # deps.effective() cleans up
        projs = requests.get(f"{API}/projects", headers=co_user["h"]).json()
        assert not any(p["shared"] for p in projs)

    def test_owner_active_project_unchanged_when_coowner_switches(self, owner, co_user):
        inv = requests.post(f"{API}/co-owners", headers=owner["h"], json={"email": co_user["email"]})
        # Owner currently has Nottingham active
        before = requests.get(f"{API}/auth/me", headers=owner["h"]).json()
        owner_active_before = before["active_project_id"]
        # Co-user activates a different owner project if available
        projs = requests.get(f"{API}/projects", headers=co_user["h"]).json()
        shared = [p for p in projs if p["shared"]]
        # If owner has only 1 project activating same pid is fine too — it tests isolation
        target = shared[-1]["id"]
        requests.post(f"{API}/projects/{target}/activate", headers=co_user["h"])
        after = requests.get(f"{API}/auth/me", headers=owner["h"]).json()
        assert after["active_project_id"] == owner_active_before, "owner's active project must not change"
        requests.delete(f"{API}/co-owners/{inv.json()['id']}", headers=owner["h"])


# =============================================================================
# 3. Pricing — tiers endpoint + checkout + mark_paid
# =============================================================================
class TestPricing:
    def test_tiers_content(self):
        r = requests.get(f"{API}/payments/tiers", timeout=20)
        assert r.status_code == 200
        tiers = r.json()
        by = {t["id"]: t for t in tiers}
        assert set(by.keys()) == {"monthly", "yearly", "lifetime"}
        assert by["monthly"]["price"] == 19.99
        assert by["monthly"]["days"] == 31
        assert by["yearly"]["price"] == 199.0
        assert by["yearly"]["days"] == 365
        assert by["lifetime"]["price"] == 499.0
        assert by["lifetime"]["days"] is None

    def test_checkout_amount_is_server_side(self, owner):
        for tier, want in [("monthly", 19.99), ("yearly", 199.0), ("lifetime", 499.0)]:
            r = requests.post(f"{API}/payments/checkout", headers=owner["h"],
                              json={"origin_url": BASE_URL, "tier": tier}, timeout=30)
            assert r.status_code == 200, r.text
            sid = r.json()["session_id"]
            # The server-side tx row must carry the server-authoritative amount for this tier
            async def fn(db, sid=sid):
                return await db.payment_transactions.find_one({"session_id": sid})
            tx = _run(fn)
            assert tx is not None
            assert tx["amount"] == want, f"{tier}: tx amount {tx['amount']} != {want}"
            assert tx["metadata"]["tier"] == tier
            assert tx["payment_status"] == "initiated"
        # Clean up any transactions we created
        async def cleanup(db, uid=owner["id"]):
            await db.payment_transactions.delete_many({"user_id": uid})
        _run(cleanup)

    def test_mark_paid_monthly_sets_pro_tier_and_31d(self, co_user):
        # Create a checkout for monthly then mark paid directly via helper
        r = requests.post(f"{API}/payments/checkout", headers=co_user["h"],
                          json={"origin_url": BASE_URL, "tier": "monthly"}, timeout=30)
        assert r.status_code == 200
        sid = r.json()["session_id"]

        async def do(db):
            from routes.payments import mark_paid
            await mark_paid(sid)
            return await db.users.find_one({"_id": ObjectId(co_user["id"])},
                                           {"plan": 1, "pro_tier": 1, "pro_until": 1, "paid_pro": 1})

        u = _run(do)
        assert u["plan"] == "pro"
        assert u["pro_tier"] == "monthly"
        assert u["paid_pro"] is True
        pu = datetime.fromisoformat(u["pro_until"])
        now = datetime.now(timezone.utc)
        delta = (pu - now).total_seconds() / 86400
        assert 30.9 < delta < 31.1, f"delta {delta} not ~31 days"

    def test_mark_paid_monthly_stacks_on_remaining(self, co_user):
        # First purchase
        r1 = requests.post(f"{API}/payments/checkout", headers=co_user["h"],
                           json={"origin_url": BASE_URL, "tier": "monthly"}, timeout=30)
        sid1 = r1.json()["session_id"]

        async def do1(db):
            from routes.payments import mark_paid
            await mark_paid(sid1)
            return (await db.users.find_one({"_id": ObjectId(co_user["id"])}, {"pro_until": 1}))["pro_until"]
        pu1 = _run(do1)

        # Second purchase (while still active)
        r2 = requests.post(f"{API}/payments/checkout", headers=co_user["h"],
                           json={"origin_url": BASE_URL, "tier": "monthly"}, timeout=30)
        sid2 = r2.json()["session_id"]

        async def do2(db):
            from routes.payments import mark_paid
            await mark_paid(sid2)
            return (await db.users.find_one({"_id": ObjectId(co_user["id"])}, {"pro_until": 1}))["pro_until"]
        pu2 = _run(do2)

        d1 = datetime.fromisoformat(pu1)
        d2 = datetime.fromisoformat(pu2)
        # Should extend by ~31 days from the previous end (not from now)
        delta = (d2 - d1).total_seconds() / 86400
        assert 30.9 < delta < 31.1, f"stack delta {delta} != 31 days"

    def test_mark_paid_lifetime_clears_pro_until(self, co_user):
        r = requests.post(f"{API}/payments/checkout", headers=co_user["h"],
                          json={"origin_url": BASE_URL, "tier": "lifetime"}, timeout=30)
        sid = r.json()["session_id"]

        async def do(db):
            from routes.payments import mark_paid
            await mark_paid(sid)
            return await db.users.find_one({"_id": ObjectId(co_user["id"])},
                                           {"plan": 1, "pro_tier": 1, "pro_until": 1})
        u = _run(do)
        assert u["plan"] == "pro"
        assert u["pro_tier"] == "lifetime"
        assert u["pro_until"] is None
        # Lifetime pro can't checkout again
        r2 = requests.post(f"{API}/payments/checkout", headers=co_user["h"],
                           json={"origin_url": BASE_URL, "tier": "monthly"}, timeout=30)
        assert r2.status_code == 400

    def test_expired_monthly_downgrades_on_next_request(self, co_user):
        # Set user to pro monthly with pro_until in the past
        past = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()

        async def do(db):
            await db.users.update_one({"_id": ObjectId(co_user["id"])}, {"$set": {
                "plan": "pro", "pro_tier": "monthly", "pro_until": past, "paid_pro": True,
            }})
        _run(do)
        me = requests.get(f"{API}/auth/me", headers=co_user["h"]).json()
        assert me["own_plan"] == "basic", "lapsed monthly pro should auto-downgrade"

    def test_expired_lifetime_does_not_downgrade(self, co_user):
        async def do(db):
            await db.users.update_one({"_id": ObjectId(co_user["id"])}, {"$set": {
                "plan": "pro", "pro_tier": "lifetime", "pro_until": None, "paid_pro": True,
            }})
        _run(do)
        me = requests.get(f"{API}/auth/me", headers=co_user["h"]).json()
        assert me["own_plan"] == "pro"
