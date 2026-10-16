"""Iteration 20 — Map Filters.

Covers GET /api/portfolio/map `country` field:
- Country derived from Nominatim addressdetails and cached on project (`country` persisted; subsequent calls don't re-geocode when address unchanged)
- Projects without address → country is None
- Manual pins keep their lat/lon but still get country from the geocoded address
- Multi-currency / multi-type / multi-country mix is returned so the UI can filter by it
"""
import os
import uuid
import time
import pytest
import requests

BASE_URL = (os.environ.get('EXPO_BACKEND_URL') or os.environ['EXPO_PUBLIC_BACKEND_URL']).rstrip('/')


@pytest.fixture(scope="module")
def user():
    email = f"TEST_iter20_{uuid.uuid4().hex[:8]}@mybuilder.app"
    r = requests.post(f"{BASE_URL}/api/auth/register", json={"name": "Iter20", "email": email, "password": "testpass1234"}, timeout=30)
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    yield {"token": token, "email": email}
    try:
        requests.delete(f"{BASE_URL}/api/auth/account", headers={"Authorization": f"Bearer {token}"}, timeout=20)
    except Exception:
        pass


@pytest.fixture(scope="module")
def h(user):
    return {"Authorization": f"Bearer {user['token']}", "Content-Type": "application/json"}


class TestPortfolioMapCountry:
    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/portfolio/map", timeout=20)
        assert r.status_code in (401, 403)

    def test_country_field_present(self, h):
        # First call triggers geocoding of the seeded Nottingham project
        r = requests.get(f"{BASE_URL}/api/portfolio/map", headers=h, timeout=60)
        assert r.status_code == 200, r.text
        pins = r.json()
        assert pins, "demo seed should produce at least one project"
        for p in pins:
            assert "country" in p, f"'country' missing in {p}"
            # value is either a non-empty string or None
            assert p["country"] is None or isinstance(p["country"], str)

    def test_seed_resolves_to_united_kingdom(self, h):
        # Nottingham address → United Kingdom
        r = requests.get(f"{BASE_URL}/api/portfolio/map", headers=h, timeout=60)
        pins = r.json()
        uk = [p for p in pins if p.get("country") and "United Kingdom" in p["country"]]
        assert uk, f"expected a UK pin for the seeded Nottingham project, got {[(p['name'], p.get('country')) for p in pins]}"

    def test_country_cached_no_regeocode(self, h):
        # Second call should NOT re-geocode (already cached); must still return country
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/api/portfolio/map", headers=h, timeout=30)
        dt = time.time() - t0
        assert r.status_code == 200
        # 1 req/s rate limit is only hit when something is to-do; cached call should be fast (<5s)
        assert dt < 10, f"cached map call took too long: {dt:.1f}s"
        pins = r.json()
        assert any(p.get("country") for p in pins)

    def test_project_without_address_country_none(self, h):
        # Create a project with no address → country must be None
        r = requests.post(f"{BASE_URL}/api/projects", headers=h, json={"name": "TEST_iter20_noaddr", "property_type": "land"}, timeout=20)
        assert r.status_code == 200
        pid = r.json()["id"]
        try:
            r = requests.get(f"{BASE_URL}/api/portfolio/map", headers=h, timeout=60)
            assert r.status_code == 200
            pins = {p["id"]: p for p in r.json()}
            assert pid in pins
            assert pins[pid]["country"] is None
            assert pins[pid]["lat"] is None and pins[pid]["lon"] is None
        finally:
            # cleanup: switch active off this project if needed, then delete
            projs = requests.get(f"{BASE_URL}/api/projects", headers=h, timeout=20).json()
            other = next((x for x in projs if x["id"] != pid), None)
            if other:
                requests.post(f"{BASE_URL}/api/projects/{other['id']}/activate", headers=h, timeout=20)
            requests.delete(f"{BASE_URL}/api/projects/{pid}", headers=h, timeout=20)

    def test_spain_eur_land_project(self, h):
        # Create a EUR land project in Spain → country=Spain, currency=EUR, property_type=land
        r = requests.post(f"{BASE_URL}/api/projects", headers=h, json={
            "name": "TEST_iter20_madrid",
            "property_type": "land",
            "currency": "EUR",
            "address": "Calle Mayor 1, Madrid, Spain",
        }, timeout=20)
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        try:
            r = requests.get(f"{BASE_URL}/api/portfolio/map", headers=h, timeout=60)
            assert r.status_code == 200
            pins = {p["id"]: p for p in r.json()}
            assert pid in pins
            p = pins[pid]
            assert p["currency"] == "EUR"
            assert p["property_type"] == "land"
            # Country should resolve to a Spain-ish string (Nominatim returns "España" or "Spain")
            assert p["country"] is not None, f"expected country for Madrid, got None in {p}"
            assert "Spain" in p["country"] or "España" in p["country"], f"unexpected country: {p['country']}"
            # Multi-country / multi-currency / multi-type mix present
            countries = {x.get("country") for x in pins.values() if x.get("country")}
            assert len(countries) >= 2, f"expected multiple countries, got {countries}"
            currencies = {x["currency"] for x in pins.values()}
            assert {"EUR", "GBP"}.issubset(currencies), f"expected EUR+GBP mix, got {currencies}"
            types = {x["property_type"] for x in pins.values()}
            assert {"land", "residential"}.issubset(types), f"expected land+residential mix, got {types}"
        finally:
            projs = requests.get(f"{BASE_URL}/api/projects", headers=h, timeout=20).json()
            other = next((x for x in projs if x["id"] != pid), None)
            if other:
                requests.post(f"{BASE_URL}/api/projects/{other['id']}/activate", headers=h, timeout=20)
            requests.delete(f"{BASE_URL}/api/projects/{pid}", headers=h, timeout=20)

    def test_manual_pin_keeps_coords_but_gets_country(self, h):
        # Create a project with manual pin coords AND a different-country address.
        # Backend should keep the manual lat/lon but still fill `country` from the geocoded address.
        r = requests.post(f"{BASE_URL}/api/projects", headers=h, json={
            "name": "TEST_iter20_manualpin",
            "property_type": "residential",
            "currency": "USD",
            "address": "1600 Pennsylvania Ave NW, Washington, DC",
            "lat": 10.0,
            "lon": 20.0,
        }, timeout=20)
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        try:
            r = requests.get(f"{BASE_URL}/api/portfolio/map", headers=h, timeout=60)
            assert r.status_code == 200
            pins = {p["id"]: p for p in r.json()}
            p = pins[pid]
            assert p["pin_manual"] is True
            assert p["lat"] == 10.0 and p["lon"] == 20.0, "manual pin coords must not be overwritten"
            # Country learned from address (United States)
            assert p["country"] is not None, "country should still be filled for manual-pin projects"
            assert "United States" in p["country"] or "USA" in p["country"], f"unexpected country: {p['country']}"
        finally:
            projs = requests.get(f"{BASE_URL}/api/projects", headers=h, timeout=20).json()
            other = next((x for x in projs if x["id"] != pid), None)
            if other:
                requests.post(f"{BASE_URL}/api/projects/{other['id']}/activate", headers=h, timeout=20)
            requests.delete(f"{BASE_URL}/api/projects/{pid}", headers=h, timeout=20)
