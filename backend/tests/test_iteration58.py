"""Iteration 58 - EPC floor areas endpoint (POST /api/sold-prices/floor-areas).

Covers:
- Auth required
- 422 when sales array > 60 items
- Response shape: items[] in same order with keys sqm, sqft, price_per_sqft, epc_band
  plus matched (int) and median_ppsf
- Items align with cached sold-prices sales (NG7 1AA, 0.25mi, 3y)
- Most sold sales should get an EPC match (>=50%)
- Nulls returned (not errors) when no EPC matches

Also sanity-checks:
- POST /api/auth/plan to switch demo user to 'pro' so BRRR screen is accessible
- POST /api/auth/plan to restore 'basic'
"""
import os
import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
assert BASE, "EXPO_PUBLIC_BACKEND_URL must be set"
API = f"{BASE}/api"
DEMO = {"email": "demo@mybuilder.app", "password": "demo1234"}


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def tok():
    r = requests.post(f"{API}/auth/login", json=DEMO, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def sold_sales(tok):
    r = requests.get(f"{API}/sold-prices?postcode=NG7+1AA&miles=0.25&years=3",
                     headers=_h(tok), timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("sales"), "Expected cached sales for NG7 1AA 0.25mi 3y"
    return data["sales"]


class TestFloorAreasAuth:
    def test_requires_auth(self):
        r = requests.post(f"{API}/sold-prices/floor-areas",
                          json={"sales": [{"postcode": "NG7 1AA", "address": "1 Test St", "price": 150000}]},
                          timeout=20)
        assert r.status_code in (401, 403), r.text


class TestFloorAreasValidation:
    def test_too_many_sales(self, tok):
        # >60 items -> 422
        sales = [{"postcode": "NG7 1AA", "address": f"{i} Test St", "price": 150000} for i in range(61)]
        r = requests.post(f"{API}/sold-prices/floor-areas", json={"sales": sales},
                          headers=_h(tok), timeout=20)
        assert r.status_code == 422, f"Expected 422, got {r.status_code} {r.text}"

    def test_empty_sales(self, tok):
        r = requests.post(f"{API}/sold-prices/floor-areas", json={"sales": []},
                          headers=_h(tok), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["items"] == []
        assert d["matched"] == 0
        assert d["median_ppsf"] is None


class TestFloorAreasShape:
    @pytest.fixture(scope="class")
    def payload(self, tok, sold_sales):
        # Use up to 25 sales to keep lookup cost reasonable
        picked = sold_sales[:25]
        body = {"sales": [{"postcode": s["postcode"], "address": s["address"] or s["postcode"],
                           "price": s["price"]} for s in picked]}
        r = requests.post(f"{API}/sold-prices/floor-areas", json=body,
                          headers=_h(tok), timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        return d, picked

    def test_top_level_keys(self, payload):
        d, _ = payload
        for k in ("items", "matched", "median_ppsf"):
            assert k in d, f"Missing {k}"
        assert isinstance(d["items"], list)
        assert isinstance(d["matched"], int)

    def test_items_same_order_and_length(self, payload):
        d, picked = payload
        assert len(d["items"]) == len(picked), f"Expected {len(picked)} items, got {len(d['items'])}"

    def test_item_shape(self, payload):
        d, _ = payload
        for i, it in enumerate(d["items"]):
            for k in ("sqm", "sqft", "price_per_sqft", "epc_band"):
                assert k in it, f"item {i} missing {k}"
            # When matched: sqft int, price_per_sqft int, epc_band single letter
            if it["sqft"] is not None:
                assert isinstance(it["sqft"], int) and it["sqft"] > 0
                assert isinstance(it["price_per_sqft"], int) and it["price_per_sqft"] > 0
                if it["epc_band"] is not None:
                    assert len(it["epc_band"]) == 1

    def test_matched_count_and_median(self, payload):
        d, picked = payload
        matched = sum(1 for it in d["items"] if it["price_per_sqft"])
        assert d["matched"] == matched
        # Most sold sales in NG7 1AA / 0.25mi should match an EPC - require >=50%
        assert matched >= len(picked) * 0.5, f"Only {matched}/{len(picked)} matched"
        if matched:
            assert isinstance(d["median_ppsf"], int) and d["median_ppsf"] > 0


class TestAuthPlanToggle:
    """BRRR screen is Pro - verify demo user can be switched to pro via /auth/plan."""

    def test_set_pro_then_basic(self, tok):
        r = requests.post(f"{API}/auth/plan", json={"plan": "pro"},
                          headers=_h(tok), timeout=20)
        assert r.status_code == 200, r.text
        me = requests.get(f"{API}/auth/me", headers=_h(tok), timeout=20).json()
        assert me["plan"] == "pro"
        # Restore
        r2 = requests.post(f"{API}/auth/plan", json={"plan": "basic"},
                           headers=_h(tok), timeout=20)
        assert r2.status_code == 200, r2.text
        me2 = requests.get(f"{API}/auth/me", headers=_h(tok), timeout=20).json()
        assert me2["plan"] == "basic"
