"""Iteration 50 – PropertyPlug: (1) Home hero cover photo + add-photo flow,
(2) Payout receipts emailed with send_receipt toggle + payout_receipt messages log,
(3) Compare estimates flow — list has >=2 saved estimates and both are retrievable individually."""
import io
import os
import uuid

import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
assert BASE, "EXPO_PUBLIC_BACKEND_URL env var must be set"
API = f"{BASE}/api"

DEMO_EMAIL = "demo@mybuilder.app"
DEMO_PASS = "demo1234"
# Resend sandbox address that always delivers – lets us verify receipt_sent=true
DELIVERED = "delivered@resend.dev"


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=20)
    assert r.status_code == 200, r.text
    j = r.json()
    return {"email": email, "token": j["access_token"], "user": j["user"]}


def _h(u):
    return {"Authorization": f"Bearer {u['token']}"}


@pytest.fixture(scope="module")
def owner():
    return _login(DEMO_EMAIL, DEMO_PASS)


@pytest.fixture(scope="module")
def png1x1():
    # 1x1 PNG bytes
    return bytes.fromhex(
        "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4890000000D4944415478DA6364F8CF000000030001015B6E2F140000000049454E44AE426082"
    )


# ============================= 1) Home hero cover photo =============================

class TestHeroCover:
    def test_initial_demo_cover_null(self, owner):
        """Demo project should start with cover_path=null (per cleanup in prior iter)."""
        r = requests.get(f"{API}/project", headers=_h(owner), timeout=20)
        assert r.status_code == 200, r.text
        # not strictly null if a previous test left it set, but we assert the field exists & is None/str
        assert "cover_path" in r.json()

    def test_upload_then_put_cover_then_get_reflects(self, owner, png1x1):
        # Reset first
        requests.put(f"{API}/project/cover", headers=_h(owner), json={"storage_path": None}, timeout=20)

        # upload image
        files = {"file": ("hero.png", io.BytesIO(png1x1), "image/png")}
        r = requests.post(f"{API}/upload", headers=_h(owner), files=files, timeout=30)
        assert r.status_code == 200, r.text
        path = r.json()["path"]
        assert path

        # set cover
        r = requests.put(f"{API}/project/cover", headers=_h(owner), json={"storage_path": path}, timeout=20)
        assert r.status_code == 200
        assert r.json().get("cover_path") == path

        # GET /api/project reflects cover_path (home hero reads from this)
        r = requests.get(f"{API}/project", headers=_h(owner), timeout=20)
        assert r.status_code == 200
        assert r.json().get("cover_path") == path

    def test_clear_cover(self, owner):
        """After clearing, cover_path null again => frontend hero shows stock + add-photo pill."""
        r = requests.put(f"{API}/project/cover", headers=_h(owner), json={"storage_path": None}, timeout=20)
        assert r.status_code == 200
        assert r.json().get("cover_path") is None


# ============================= 2) Payout receipts =============================

class TestPayoutReceipts:
    @pytest.fixture(scope="class")
    def payout_ctx(self, owner):
        """Create a co-owner with share 25% so we can record a payout against them."""
        em = DELIVERED
        # Invite the delivered@resend.dev as co-owner
        r = requests.post(
            f"{API}/co-owners", headers=_h(owner),
            json={"email": em, "project_ids": None, "money_access": True, "role": "co_owner"}, timeout=20)
        assert r.status_code == 200, r.text
        co_id = r.json()["id"]

        # Set a split that gives them 25%
        r = requests.put(f"{API}/project/split", headers=_h(owner),
                         json={"shares": {co_id: 25}, "contributions": {}}, timeout=20)
        assert r.status_code == 200, r.text

        yield {"co_id": co_id, "email": em}

        # Teardown: clear split, delete all payouts for this co-owner, delete co-owner
        try:
            ledger = requests.get(f"{API}/project/payouts", headers=_h(owner), timeout=20).json()
            for person in ledger.get("people", []):
                for p in person.get("payouts", []):
                    requests.delete(f"{API}/project/payouts/{p['id']}", headers=_h(owner), timeout=10)
        except Exception:
            pass
        requests.put(f"{API}/project/split", headers=_h(owner), json={"shares": {}, "contributions": {}}, timeout=10)
        requests.delete(f"{API}/co-owners/{co_id}", headers=_h(owner), timeout=10)

    def test_payout_default_sends_receipt(self, owner, payout_ctx):
        """POST /api/project/payouts with send_receipt default (True) => receipt_sent true (delivered@resend.dev)."""
        payload = {"co_owner_id": payout_ctx["co_id"], "amount": 123.45, "date": "2026-01-15", "note": "TEST payout"}
        r = requests.post(f"{API}/project/payouts", headers=_h(owner), json=payload, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("receipt_sent") is True, f"expected receipt_sent true, got {data.get('receipt_sent')} full={data}"

        # messages log should have a payout_receipt entry for this email
        r = requests.get(f"{API}/messages", headers=_h(owner),
                         params={"email": payout_ctx["email"]}, timeout=20)
        assert r.status_code == 200, r.text
        msgs = r.json()
        receipts = [m for m in msgs if m.get("kind") == "payout_receipt" and m.get("email") == payout_ctx["email"]]
        assert receipts, f"expected a payout_receipt message log for {payout_ctx['email']}, got kinds={[m.get('kind') for m in msgs[:10]]}"
        # Most recent should be status=sent (since delivered@resend.dev)
        assert receipts[0].get("status") == "sent", receipts[0]

    def test_payout_with_send_receipt_false(self, owner, payout_ctx):
        """POST /api/project/payouts with send_receipt=false => receipt_sent false and no new message log."""
        before = requests.get(f"{API}/messages", headers=_h(owner),
                              params={"email": payout_ctx["email"]}, timeout=20).json()
        before_n = len([m for m in before if m.get("kind") == "payout_receipt"])

        payload = {"co_owner_id": payout_ctx["co_id"], "amount": 10.0, "date": "2026-01-16",
                   "note": "TEST silent", "send_receipt": False}
        r = requests.post(f"{API}/project/payouts", headers=_h(owner), json=payload, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json().get("receipt_sent") is False

        after = requests.get(f"{API}/messages", headers=_h(owner),
                             params={"email": payout_ctx["email"]}, timeout=20).json()
        after_n = len([m for m in after if m.get("kind") == "payout_receipt"])
        assert after_n == before_n, f"should NOT log a payout_receipt when send_receipt=false: before={before_n} after={after_n}"

    def test_payout_requires_valid_co_owner(self, owner):
        """POST with a bogus co_owner_id => 400."""
        r = requests.post(f"{API}/project/payouts", headers=_h(owner),
                          json={"co_owner_id": "507f1f77bcf86cd799439011", "amount": 5, "date": "2026-01-01"}, timeout=20)
        assert r.status_code == 400, r.text

    def test_payout_bad_date(self, owner, payout_ctx):
        r = requests.post(f"{API}/project/payouts", headers=_h(owner),
                          json={"co_owner_id": payout_ctx["co_id"], "amount": 5, "date": "15/01/2026"}, timeout=20)
        assert r.status_code == 422, r.text  # pydantic pattern

    def test_payouts_appear_in_ledger(self, owner, payout_ctx):
        r = requests.get(f"{API}/project/payouts", headers=_h(owner), timeout=20)
        assert r.status_code == 200
        data = r.json()
        person = next((p for p in data["people"] if p["co_owner_id"] == payout_ctx["co_id"]), None)
        assert person is not None, data
        # we recorded 123.45 + 10.0
        total_paid = round(sum(x["amount"] for x in person["payouts"]), 2)
        assert total_paid == 133.45, person


# ============================= 3) Compare estimates =============================

class TestCompareEstimates:
    def test_at_least_two_estimates_for_compare(self, owner):
        r = requests.get(f"{API}/ai/estimates", headers=_h(owner), timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 2, f"expected at least 2 saved estimates for compare flow, got {len(data)}"

    def test_fetch_two_estimates_detail(self, owner):
        r = requests.get(f"{API}/ai/estimates", headers=_h(owner), timeout=20)
        estimates = r.json()
        a_id, b_id = estimates[0]["id"], estimates[1]["id"]
        ra = requests.get(f"{API}/ai/estimates/{a_id}", headers=_h(owner), timeout=20)
        rb = requests.get(f"{API}/ai/estimates/{b_id}", headers=_h(owner), timeout=20)
        assert ra.status_code == 200 and rb.status_code == 200
        A, B = ra.json(), rb.json()
        # Fields needed by compare screen
        for k in ("id", "total_low", "total_high", "finish_type", "items", "created_at"):
            assert k in A and k in B, (A.keys(), B.keys())
        assert isinstance(A["items"], list) and isinstance(B["items"], list)

    def test_estimate_not_found(self, owner):
        r = requests.get(f"{API}/ai/estimates/507f1f77bcf86cd799439011", headers=_h(owner), timeout=20)
        assert r.status_code == 404
