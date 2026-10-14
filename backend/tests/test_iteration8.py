"""Iteration 8 backend tests.

Covers:
- DELETE /api/auth/account: 401 wrong password, 429 after 5 attempts, success deletes
  user + all owned data (projects/line_items/receipts/milestones/shopping_items/etc.),
  old token becomes invalid, login with same creds fails.
- GET /api/projects: batched summary fields, per-project totals correct (no cross-mixing)
  and consistent with GET /api/project for the active project.
- Digest share: GET/POST/DELETE /api/digest/share. Public GET /api/d/{token}?week=N renders
  the expected anchors; revoked token shows "no longer active"; /api/d/{token}/logo 404 when no logo.
- Shopping purchase: POST /api/shopping/{id}/purchase (idempotent, creates/updates receipt,
  increases project total_spent); PUT {checked:false} deletes receipt and clears actual_cost;
  amount<=0 -> 422.
- /health and /api/health return 200.
"""
import os
import time
import uuid
from typing import Dict, List, Optional

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
    """Register a fresh TEST_ user. Returns {token, user, email, password}."""
    pw = "testpass1234"
    email = f"test_{suffix or uuid.uuid4().hex[:10]}@example.com"
    r = requests.post(f"{API}/auth/register", json={"name": "TEST_ User", "email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    data = r.json()
    return {"token": data["access_token"], "user": data["user"], "email": email, "password": pw}


# -------------------- Health --------------------
class TestHealth:
    def test_api_health(self):
        r = requests.get(f"{API}/health", timeout=15)
        assert r.status_code == 200, r.text

    def test_root_health(self):
        # /health is served app-level (not through /api). Public ingress routes non-/api
        # to the frontend, so this test only guarantees server responds (not 500/404).
        r = requests.get(f"{BASE_URL}/health", timeout=15)
        assert r.status_code == 200


# -------------------- Account Deletion --------------------
class TestAccountDeletion:
    def test_wrong_password_401_and_data_untouched(self, mongo):
        u = register_test_user()
        tok = u["token"]
        # Add a shopping item to verify untouched after a failed delete
        it = requests.post(f"{API}/shopping", headers=auth(tok), json={"name": "TEST_untouched"}, timeout=15).json()
        r = requests.delete(f"{API}/auth/account", headers=auth(tok), json={"password": "wrongpass"}, timeout=15)
        assert r.status_code == 401, r.text
        # user still exists; shopping item still present
        me = requests.get(f"{API}/auth/me", headers=auth(tok), timeout=15)
        assert me.status_code == 200
        lst = requests.get(f"{API}/shopping", headers=auth(tok), timeout=15).json()
        assert any(x["id"] == it["id"] for x in lst)
        # cleanup
        requests.delete(f"{API}/auth/account", headers=auth(tok), json={"password": u["password"]}, timeout=15)

    def test_rate_limit_429_after_five_failed(self):
        u = register_test_user()
        tok = u["token"]
        codes: List[int] = []
        for _ in range(6):
            codes.append(requests.delete(f"{API}/auth/account", headers=auth(tok), json={"password": "wrongpass"}, timeout=15).status_code)
        # First 5 should be 401, 6th should be 429
        assert codes[:5] == [401] * 5, f"Expected first 5 401s, got {codes}"
        assert codes[5] == 429, f"Expected 429 after 5 fails, got {codes}"
        # Even correct password within window is rate-limited
        rl = requests.delete(f"{API}/auth/account", headers=auth(tok), json={"password": u["password"]}, timeout=15)
        assert rl.status_code == 429, f"expected 429, got {rl.status_code}"
        # Clean up: directly drop the test user from DB (ratelimit prevents API delete now)
        from pymongo import MongoClient
        from bson import ObjectId
        cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        db = cli[os.environ.get("DB_NAME", "test_database")]
        uid = u["user"]["id"]
        for coll in ("line_items", "contacts", "receipts", "media", "milestones", "quote_requests",
                     "stage_payments", "snags", "snag_links", "shopping_items", "estimates",
                     "payment_transactions", "projects"):
            db[coll].delete_many({"user_id": uid})
        db.files.delete_many({"owner_id": uid})
        db.referrals.delete_many({"$or": [{"referrer_id": uid}, {"new_user_id": uid}]})
        db.users.delete_one({"_id": ObjectId(uid)})
        cli.close()

    def test_success_wipes_all_owned_collections(self, mongo):
        u = register_test_user()
        tok = u["token"]
        uid = u["user"]["id"]
        # Seed should have created project, milestones, line_items. Verify counts > 0.
        pre_counts = {}
        for c in ("projects", "line_items", "milestones"):
            pre_counts[c] = mongo[c].count_documents({"user_id": uid})
            assert pre_counts[c] > 0, f"seed should have created {c} for TEST_ user"

        # add an extra receipt via shopping/purchase
        it = requests.post(f"{API}/shopping", headers=auth(tok), json={"name": "TEST_del_me", "est_cost": 10}, timeout=15).json()
        requests.post(f"{API}/shopping/{it['id']}/purchase", headers=auth(tok), json={"amount": 12.5}, timeout=15)
        assert mongo.receipts.count_documents({"user_id": uid}) >= 1
        assert mongo.shopping_items.count_documents({"user_id": uid}) >= 1

        # Delete
        r = requests.delete(f"{API}/auth/account", headers=auth(tok), json={"password": u["password"]}, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True}

        # All owned collections wiped
        for c in ("projects", "line_items", "milestones", "receipts", "shopping_items",
                  "contacts", "media", "quote_requests", "stage_payments", "snags",
                  "snag_links", "estimates", "payment_transactions"):
            n = mongo[c].count_documents({"user_id": uid})
            assert n == 0, f"{c} still has {n} docs for deleted user"
        assert mongo.files.count_documents({"owner_id": uid}) == 0
        assert mongo.referrals.count_documents({"$or": [{"referrer_id": uid}, {"new_user_id": uid}]}) == 0
        assert mongo.users.count_documents({"email": u["email"]}) == 0

        # Old token invalid
        me = requests.get(f"{API}/auth/me", headers=auth(tok), timeout=15)
        assert me.status_code == 401, f"old token should be invalid, got {me.status_code}"

        # Login fails
        login = requests.post(f"{API}/auth/login", json={"email": u["email"], "password": u["password"]}, timeout=15)
        assert login.status_code == 401


# -------------------- Projects list (batched summaries) --------------------
class TestProjectsList:
    def test_projects_list_shape_and_per_project_totals(self, demo_token, mongo):
        """Create a few TEST_ projects, each with distinct line_items/receipts, and
        verify GET /api/projects returns correct per-project totals (not mixed)."""
        # Register a dedicated TEST_ user so demo data is untouched
        u = register_test_user()
        tok = u["token"]
        uid = u["user"]["id"]
        try:
            # Create 2 extra projects (seed already created 1)
            p2 = requests.post(f"{API}/projects", headers=auth(tok),
                               json={"name": "TEST_proj_B", "address": "B", "purchase_price": 100000,
                                     "estimated_valuation": 150000, "monthly_rent": 900}, timeout=20).json()
            p3 = requests.post(f"{API}/projects", headers=auth(tok),
                               json={"name": "TEST_proj_C", "address": "C"}, timeout=20).json()
            # activate B; add line_item + receipt there
            requests.post(f"{API}/projects/{p2['id']}/activate", headers=auth(tok), timeout=15)
            li = requests.post(f"{API}/line-items", headers=auth(tok),
                               json={"name": "TEST_li_B", "category": "Hard Cost",
                                     "budgeted": 500, "actual": 123}, timeout=15).json()
            rc = requests.post(f"{API}/receipts", headers=auth(tok),
                               json={"title": "TEST_rc_B", "amount": 77.5, "date": "2026-01-05",
                                     "category": "Soft Cost"}, timeout=15).json()
            # Activate C; add line_item only
            requests.post(f"{API}/projects/{p3['id']}/activate", headers=auth(tok), timeout=15)
            requests.post(f"{API}/line-items", headers=auth(tok),
                          json={"name": "TEST_li_C", "category": "Hard Cost",
                                "budgeted": 200, "actual": 50}, timeout=15).json()

            # Now fetch /projects (any active OK)
            r = requests.get(f"{API}/projects", headers=auth(tok), timeout=20)
            assert r.status_code == 200, r.text
            arr = r.json()
            assert isinstance(arr, list)
            # Expected fields present on each summary
            required = {"id", "name", "spent", "total_budget", "total_spent", "line_item_count",
                        "receipt_count", "milestones_total", "milestones_done", "current_stage",
                        "rent_yield", "active"}
            for p in arr:
                missing = required - set(p.keys())
                assert not missing, f"missing fields on summary: {missing}"
                # No MongoDB _id leaked
                assert "_id" not in p
                # comparables shouldn't be returned on list
                assert "comparables" not in p

            # Exactly one active
            assert sum(1 for p in arr if p["active"]) == 1

            # Lookup each by id
            by_id = {p["id"]: p for p in arr}
            sb = by_id[p2["id"]]
            sc = by_id[p3["id"]]
            # Project B: 1 line_item (actual=123, Hard), 1 receipt (77.5, Soft)
            assert sb["line_item_count"] == 1
            assert sb["receipt_count"] == 1
            assert sb["spent"]["hard"] == 123
            assert sb["spent"]["soft"] == 77.5
            assert sb["total_spent"] == round(123 + 77.5, 2)
            # Project C: 1 line_item (actual=50, Hard), 0 receipts
            assert sc["line_item_count"] == 1
            assert sc["receipt_count"] == 0
            assert sc["spent"]["hard"] == 50
            assert sc["total_spent"] == 50

            # Consistency vs GET /api/project (active one). We activated C last.
            active_summary = requests.get(f"{API}/project", headers=auth(tok), timeout=15).json()
            assert active_summary["id"] == sc["id"]
            for k in ("total_budget", "total_spent", "line_item_count", "receipt_count",
                      "milestones_total", "milestones_done"):
                assert active_summary[k] == sc[k], f"mismatch on {k}"
        finally:
            # Delete the test user to clean everything up
            requests.delete(f"{API}/auth/account", headers=auth(tok),
                            json={"password": u["password"]}, timeout=20)


# -------------------- Digest Share --------------------
class TestDigestShare:
    def test_full_share_lifecycle(self, demo_token):
        tok = demo_token
        try:
            # Create share link
            r = requests.post(f"{API}/digest/share", headers=auth(tok),
                              json={"origin_url": BASE_URL}, timeout=15)
            assert r.status_code == 200, r.text
            url1 = r.json()["url"]
            assert url1 and "/api/d/" in url1
            # Idempotent token: second POST returns same token
            r2 = requests.post(f"{API}/digest/share", headers=auth(tok),
                               json={"origin_url": BASE_URL}, timeout=15)
            assert r2.json()["url"] == url1
            # GET returns the same
            g = requests.get(f"{API}/digest/share", headers=auth(tok), timeout=15)
            assert g.json()["url"] == url1

            # Public page renders expected anchors (HTML uses single quotes)
            html = requests.get(f"{url1}?week=1", timeout=20).text
            for anchor in ("id='digest-kpis'", "id='digest-milestones'", "id='digest-snags'"):
                assert anchor in html, f"missing {anchor} in public digest"
            # Prev/next links appear (week=1 has both prev and next)
            assert "id='digest-prev'" in html
            assert "id='digest-next'" in html
            # Trial / CTA footer should be present (shared pages append a sign-up CTA)
            assert "builder assist" in html.lower()

            # Week 0: no next link
            html0 = requests.get(url1, timeout=20).text
            assert "id='digest-prev'" in html0
            assert "id='digest-next'" not in html0

            # Logo endpoint returns 404 when no logo uploaded
            token = url1.rsplit("/", 1)[-1]
            lg = requests.get(f"{API}/d/{token}/logo", timeout=15)
            assert lg.status_code == 404

            # Revoke
            d = requests.delete(f"{API}/digest/share", headers=auth(tok), timeout=15)
            assert d.status_code == 200
            assert d.json()["url"] is None
            g2 = requests.get(f"{API}/digest/share", headers=auth(tok), timeout=15)
            assert g2.json()["url"] is None
            # Revoked token page shows 'no longer active'
            html_rev = requests.get(url1, timeout=20).text
            assert "no longer active" in html_rev.lower()
        finally:
            # Ensure demo link is revoked after tests
            requests.delete(f"{API}/digest/share", headers=auth(tok), timeout=15)


# -------------------- Shopping purchase --------------------
class TestShoppingPurchase:
    def test_purchase_creates_receipt_and_updates_total_spent(self, demo_token):
        # Use a dedicated TEST_ user so demo project totals stay clean
        u = register_test_user()
        tok = u["token"]
        try:
            # grab a demo-seeded line item to link so the receipt category comes from it
            lis = requests.get(f"{API}/line-items", headers=auth(tok), timeout=15).json()
            assert isinstance(lis, list) and lis, "seed should have line items"
            # Use a Soft Cost line item if available, else first
            soft = next((x for x in lis if x.get("category") == "Soft Cost"), lis[0])

            # Baseline total_spent
            p0 = requests.get(f"{API}/project", headers=auth(tok), timeout=15).json()
            base_spent = p0["total_spent"]

            # Add shopping item linked to that line item
            item = requests.post(f"{API}/shopping", headers=auth(tok),
                                 json={"name": "TEST_purch_1", "supplier": "Screwfix", "est_cost": 20}, timeout=15).json()
            # Manually attach line_item_id via internal mongo (route doesn't accept it); instead, use from-line-items
            from_r = requests.post(f"{API}/shopping/from-line-items", headers=auth(tok),
                                   json={"line_item_ids": [soft["id"]]}, timeout=15)
            assert from_r.status_code == 200
            all_items = requests.get(f"{API}/shopping", headers=auth(tok), timeout=15).json()
            linked = next((x for x in all_items if x.get("line_item_id") == soft["id"]), None)
            assert linked, "from-line-items should have created linked shopping item"

            # Amount<=0 => 422
            r_bad = requests.post(f"{API}/shopping/{linked['id']}/purchase", headers=auth(tok),
                                  json={"amount": 0}, timeout=15)
            assert r_bad.status_code == 422
            r_bad2 = requests.post(f"{API}/shopping/{linked['id']}/purchase", headers=auth(tok),
                                   json={"amount": -5}, timeout=15)
            assert r_bad2.status_code == 422

            # First purchase
            r1 = requests.post(f"{API}/shopping/{linked['id']}/purchase", headers=auth(tok),
                               json={"amount": 55.75, "date": "2026-01-10"}, timeout=15)
            assert r1.status_code == 200, r1.text
            after = r1.json()
            assert after["checked"] is True
            assert after["actual_cost"] == 55.75
            rid = after["receipt_id"]
            assert rid

            # Receipt appears in /api/receipts with correct title/supplier/category
            recs = requests.get(f"{API}/receipts", headers=auth(tok), timeout=15).json()
            match = next((r for r in recs if r["id"] == rid), None)
            assert match, "created receipt should appear in /receipts"
            assert match["title"] == linked["name"]
            assert match["amount"] == 55.75
            assert match["category"] == soft["category"]
            # supplier may be blank from line item seed, so check equal to shopping item's supplier
            assert match.get("supplier", "") == linked.get("supplier", "")

            # total_spent increased
            p1 = requests.get(f"{API}/project", headers=auth(tok), timeout=15).json()
            assert round(p1["total_spent"] - base_spent, 2) >= 55.75 - 0.01

            # Idempotent: calling again updates same receipt
            r2 = requests.post(f"{API}/shopping/{linked['id']}/purchase", headers=auth(tok),
                               json={"amount": 60.00}, timeout=15)
            assert r2.status_code == 200
            after2 = r2.json()
            assert after2["receipt_id"] == rid, "same receipt id expected"
            assert after2["actual_cost"] == 60.00
            recs2 = requests.get(f"{API}/receipts", headers=auth(tok), timeout=15).json()
            same = next((r for r in recs2 if r["id"] == rid), None)
            assert same and same["amount"] == 60.00
            # Only one receipt for this shopping item
            tied = [r for r in recs2 if r.get("shopping_item_id") == linked["id"]]
            assert len(tied) == 1

            # PUT {checked:false} deletes the receipt + clears actual_cost
            u1 = requests.put(f"{API}/shopping/{linked['id']}", headers=auth(tok),
                              json={"checked": False}, timeout=15)
            assert u1.status_code == 200
            assert u1.json()["checked"] is False
            assert u1.json()["actual_cost"] is None
            assert u1.json()["receipt_id"] is None
            recs3 = requests.get(f"{API}/receipts", headers=auth(tok), timeout=15).json()
            assert all(r["id"] != rid for r in recs3), "receipt should be deleted on un-tick"

            # cleanup custom (unused) shopping item
            requests.delete(f"{API}/shopping/{item['id']}", headers=auth(tok), timeout=15)
        finally:
            # Nuke the TEST_ user
            requests.delete(f"{API}/auth/account", headers=auth(tok),
                            json={"password": u["password"]}, timeout=20)

    def test_purchase_unlinked_defaults_hard_cost(self, demo_token):
        """Shopping item without line_item_id -> receipt category = Hard Cost."""
        u = register_test_user()
        tok = u["token"]
        try:
            item = requests.post(f"{API}/shopping", headers=auth(tok),
                                 json={"name": "TEST_unlinked", "supplier": "B&Q", "est_cost": 15}, timeout=15).json()
            r = requests.post(f"{API}/shopping/{item['id']}/purchase", headers=auth(tok),
                              json={"amount": 15.5}, timeout=15)
            assert r.status_code == 200
            rid = r.json()["receipt_id"]
            recs = requests.get(f"{API}/receipts", headers=auth(tok), timeout=15).json()
            match = next((x for x in recs if x["id"] == rid), None)
            assert match and match["category"] == "Hard Cost"
            assert match["supplier"] == "B&Q"
        finally:
            requests.delete(f"{API}/auth/account", headers=auth(tok),
                            json={"password": u["password"]}, timeout=20)
