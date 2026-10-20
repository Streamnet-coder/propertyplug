"""Iteration 57 - Sold prices map backend endpoint.

Covers:
- GET /api/sold-prices requires auth (401/403 without token)
- Allowed for basic plan user (previously Pro only)
- Returns correct shape (postcode, lat, lon, radius_m, sales[], stats, source)
- radius_m scales with miles (0.25 -> ~402, 5 -> ~8047)
- sales[] items have required fields and distance_m <= radius_m
- stats.by_type keyed by friendly type names
- 400 for malformed postcode
- 404 for unknown postcode
- 400 for Scottish postcode (England & Wales only)
- 422 for invalid `miles` / `years` enum
- Cache-hit path: second identical request should return quickly
- /api/project/comparables now allowed for basic plan users

Reuses NG7 1AA / years=3 / miles in {0.25, 1} to minimise external calls.
"""
import os
import time

import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
assert BASE, "EXPO_PUBLIC_BACKEND_URL env var must be set"
API = f"{BASE}/api"

DEMO_EMAIL = "demo@mybuilder.app"
DEMO_PASS = "demo1234"
MILE_M = 1609.34


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=20)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def tok():
    return _login(DEMO_EMAIL, DEMO_PASS)


@pytest.fixture(scope="module")
def me(tok):
    r = requests.get(f"{API}/auth/me", headers=_h(tok), timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


class TestSoldPricesAuth:
    def test_requires_auth(self):
        r = requests.get(f"{API}/sold-prices?postcode=NG7+1AA", timeout=20)
        assert r.status_code in (401, 403), f"Expected auth error, got {r.status_code} {r.text}"

    def test_basic_plan_allowed(self, tok, me):
        # Demo user is basic plan by default - endpoint must be accessible
        assert me.get("plan") in ("basic", "pro"), f"Unexpected plan: {me}"
        r = requests.get(f"{API}/sold-prices?postcode=NG7+1AA&miles=0.25&years=3",
                         headers=_h(tok), timeout=60)
        assert r.status_code == 200, f"Basic plan user should access /sold-prices: {r.status_code} {r.text}"


class TestSoldPricesShape:
    @pytest.fixture(scope="class")
    def payload(self, tok):
        r = requests.get(f"{API}/sold-prices?postcode=NG7+1AA&miles=0.25&years=3",
                         headers=_h(tok), timeout=60)
        assert r.status_code == 200, r.text
        return r.json()

    def test_top_level_keys(self, payload):
        for k in ("postcode", "lat", "lon", "radius_m", "miles", "years", "since",
                  "sales", "truncated", "stats", "source"):
            assert k in payload, f"Missing key: {k}"

    def test_postcode_normalised(self, payload):
        assert payload["postcode"] == "NG7 1AA"

    def test_radius_matches_miles(self, payload):
        # miles=0.25 -> radius_m ~ 402
        assert payload["miles"] == 0.25
        assert payload["radius_m"] == round(0.25 * MILE_M), payload["radius_m"]

    def test_lat_lon_is_nottingham(self, payload):
        # NG7 1AA is central Nottingham
        assert 52.9 < payload["lat"] < 53.0, payload["lat"]
        assert -1.25 < payload["lon"] < -1.1, payload["lon"]

    def test_sales_shape_and_distance(self, payload):
        sales = payload["sales"]
        assert isinstance(sales, list)
        if not sales:
            pytest.skip("No sales returned (external data) - skipping shape assertion")
        s0 = sales[0]
        for k in ("price", "date", "type", "postcode", "address",
                  "tenure", "new_build", "lat", "lon", "distance_m"):
            assert k in s0, f"Missing sale key: {k}"
        assert isinstance(s0["price"], int) and s0["price"] > 0
        for s in sales:
            assert s["distance_m"] <= payload["radius_m"] + 1, \
                f"Sale distance {s['distance_m']} > radius {payload['radius_m']}"
        # Capped at 1500 for the map/list
        assert len(sales) <= 1500

    def test_stats_shape(self, payload):
        st = payload["stats"]
        for k in ("count", "median", "avg", "min", "max", "by_type"):
            assert k in st
        assert isinstance(st["by_type"], dict)
        # by_type should only use friendly labels
        allowed = {"Detached", "Semi-detached", "Terraced", "Flat", "Other"}
        for t, v in st["by_type"].items():
            assert t in allowed, f"Unexpected type: {t}"
            assert {"count", "median", "avg"} <= set(v.keys())

    def test_source_mentions_land_registry(self, payload):
        assert "Land Registry" in payload["source"]


class TestRadiusScaling:
    def test_five_miles_radius(self, tok):
        # NG7 1AA 5mi should be cached from earlier iterations
        r = requests.get(f"{API}/sold-prices?postcode=NG7+1AA&miles=5&years=3",
                         headers=_h(tok), timeout=120)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["radius_m"] == round(5 * MILE_M)  # 8047
        assert data["miles"] == 5
        # 5 miles should cover more postcodes than 0.25
        assert data["postcodes_searched"] > 10

    def test_one_mile_radius(self, tok):
        r = requests.get(f"{API}/sold-prices?postcode=NG7+1AA&miles=1&years=3",
                         headers=_h(tok), timeout=90)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["radius_m"] == round(1 * MILE_M)
        assert data["miles"] == 1


class TestCache:
    def test_second_call_is_fast(self, tok):
        # First call (should be cached from previous test)
        requests.get(f"{API}/sold-prices?postcode=NG7+1AA&miles=0.25&years=3",
                     headers=_h(tok), timeout=60)
        t0 = time.time()
        r = requests.get(f"{API}/sold-prices?postcode=NG7+1AA&miles=0.25&years=3",
                         headers=_h(tok), timeout=60)
        dt = time.time() - t0
        assert r.status_code == 200
        # Cached response should be well under 5 seconds
        assert dt < 5, f"Cached call took {dt:.1f}s - cache may not be working"


class TestErrors:
    def test_malformed_postcode(self, tok):
        r = requests.get(f"{API}/sold-prices?postcode=ZZZ&miles=0.25&years=3",
                         headers=_h(tok), timeout=20)
        assert r.status_code == 400, r.text

    def test_unknown_postcode(self, tok):
        # Valid UK postcode format but not real
        r = requests.get(f"{API}/sold-prices?postcode=ZZ99+9ZZ&miles=0.25&years=3",
                         headers=_h(tok), timeout=30)
        assert r.status_code == 404, f"Expected 404, got {r.status_code} {r.text}"

    def test_scottish_postcode_rejected(self, tok):
        r = requests.get(f"{API}/sold-prices?postcode=EH1+2NG&miles=0.25&years=3",
                         headers=_h(tok), timeout=30)
        assert r.status_code == 400, r.text
        assert "England and Wales" in r.json().get("detail", "")

    def test_invalid_miles(self, tok):
        r = requests.get(f"{API}/sold-prices?postcode=NG7+1AA&miles=10&years=3",
                         headers=_h(tok), timeout=20)
        assert r.status_code == 422, f"Expected 422, got {r.status_code} {r.text}"

    def test_invalid_years(self, tok):
        r = requests.get(f"{API}/sold-prices?postcode=NG7+1AA&miles=0.25&years=99",
                         headers=_h(tok), timeout=20)
        assert r.status_code == 422, f"Expected 422, got {r.status_code} {r.text}"


class TestComparablesBasicPlan:
    """GET /api/project/comparables must now work for basic-plan users."""

    def test_comparables_ok_for_basic(self, tok):
        r = requests.get(f"{API}/project/comparables", headers=_h(tok), timeout=60)
        # Could be 200 with data, or 400 if the demo project has no postcode in address.
        # It must NOT be 402 (payment required / pro-only).
        assert r.status_code != 402, f"Comparables should be free for basic: {r.status_code} {r.text}"
        assert r.status_code in (200, 400, 404), f"Unexpected status {r.status_code}: {r.text}"
