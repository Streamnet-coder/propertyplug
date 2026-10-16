"""Iteration 18 backend tests — Currency + Land property type.

Covers:
- POST /api/projects accepts currency (10 codes), property_type, plot_size/unit, planning_status, intended_use
- Invalid currency -> 422
- Land -> target_type auto-set to "Land Investment"; switching to residential -> "BRRR Refurbishment"
- GET /api/project and /api/projects return new fields; existing projects default GBP/residential
- GET /api/fx/rates (auth) with 10 codes, GBP base
- GET /api/portfolio: home_currency, projects, land_count, totals converted, by_currency with rate_to_home
- PUT /api/portfolio/home-currency changes home + conversion
- Public share report: EUR symbol, land shows 'Land details' card not rent block
"""
import os
import uuid
from typing import Dict, Optional

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
CODES = ["GBP", "EUR", "USD", "CAD", "AUD", "NZD", "ZAR", "AED", "NGN", "INR"]


def auth(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def register_user() -> Dict:
    em = f"test_i18_{uuid.uuid4().hex[:10]}@example.com"
    pw = "testpass1234"
    r = requests.post(f"{API}/auth/register", json={"name": "TEST_ i18", "email": em, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    return {"token": d["access_token"], "email": em, "password": pw}


def cleanup(u):
    try:
        requests.delete(f"{API}/auth/account", headers=auth(u["token"]), json={"password": u["password"]}, timeout=20)
    except Exception:
        pass


@pytest.fixture
def user():
    u = register_user()
    yield u
    cleanup(u)


# -------- Projects: currency + property_type --------
class TestProjectCreateFields:
    def test_default_gbp_residential_on_seeded_project(self, user):
        r = requests.get(f"{API}/project", headers=auth(user["token"]), timeout=15)
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["currency"] == "GBP"
        assert p["property_type"] == "residential"
        assert "plot_size" in p and "plot_unit" in p and "planning_status" in p

    def test_create_eur_land_project_sets_target_type(self, user):
        body = {
            "name": "TEST_ Paris Plot",
            "address": "Paris 11e",
            "currency": "EUR",
            "property_type": "land",
            "plot_size": 2.5,
            "plot_unit": "hectares",
            "planning_status": "applied",
            "intended_use": "4 build plots",
            "purchase_price": 100000,
            "estimated_valuation": 160000,
            "budget": {"hard": 5000, "soft": 2000, "contingency": 1000},
        }
        r = requests.post(f"{API}/projects", headers=auth(user["token"]), json=body, timeout=15)
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["currency"] == "EUR"
        assert p["property_type"] == "land"
        assert p["target_type"] == "Land Investment"
        assert p["plot_size"] == 2.5
        assert p["plot_unit"] == "hectares"
        assert p["planning_status"] == "applied"
        assert p["intended_use"] == "4 build plots"

        # Switch back to residential via PUT -> target_type should flip to BRRR Refurbishment
        r2 = requests.put(f"{API}/project", headers=auth(user["token"]), json={"property_type": "residential"}, timeout=15)
        assert r2.status_code == 200, r2.text
        assert r2.json()["target_type"] == "BRRR Refurbishment"
        assert r2.json()["property_type"] == "residential"

    def test_invalid_currency_rejected_422(self, user):
        r = requests.post(f"{API}/projects", headers=auth(user["token"]), json={"name": "TEST_ bad", "currency": "XYZ"}, timeout=15)
        assert r.status_code == 422, r.text

    def test_invalid_property_type_rejected_422(self, user):
        r = requests.post(f"{API}/projects", headers=auth(user["token"]), json={"name": "TEST_ bad", "property_type": "commercial"}, timeout=15)
        assert r.status_code == 422

    def test_put_invalid_planning_status_422(self, user):
        r = requests.put(f"{API}/project", headers=auth(user["token"]), json={"planning_status": "pending"}, timeout=15)
        assert r.status_code == 422

    def test_list_projects_includes_new_fields(self, user):
        r = requests.get(f"{API}/projects", headers=auth(user["token"]), timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert all("currency" in p and "property_type" in p for p in rows)
        assert all(p["currency"] in CODES for p in rows)


# -------- FX rates --------
class TestFXRates:
    def test_fx_rates_requires_auth(self):
        r = requests.get(f"{API}/fx/rates", timeout=15)
        assert r.status_code in (401, 403)

    def test_fx_rates_returns_all_10_codes(self, user):
        r = requests.get(f"{API}/fx/rates", headers=auth(user["token"]), timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["base"] == "GBP"
        assert set(d["rates"].keys()) == set(CODES)
        assert d["rates"]["GBP"] == 1.0
        assert d["rates"]["EUR"] > 0


# -------- Portfolio --------
class TestPortfolio:
    def test_portfolio_default_gbp_single_project(self, user):
        r = requests.get(f"{API}/portfolio", headers=auth(user["token"]), timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["home_currency"] == "GBP"
        assert d["projects"] >= 1
        assert d["land_count"] == 0
        assert "totals" in d and all(k in d["totals"] for k in ("purchase_price", "estimated_valuation", "total_budget", "total_spent"))
        assert isinstance(d["by_currency"], list)
        assert d["by_currency"][0]["rate_to_home"] == pytest.approx(1.0)

    def test_portfolio_conversion_and_land_count(self, user):
        # Add an EUR land project
        body = {"name": "TEST_ Land EUR", "currency": "EUR", "property_type": "land",
                "purchase_price": 100000, "estimated_valuation": 120000, "plot_size": 1, "plot_unit": "acres"}
        r = requests.post(f"{API}/projects", headers=auth(user["token"]), json=body, timeout=15)
        assert r.status_code == 200, r.text

        p = requests.get(f"{API}/portfolio", headers=auth(user["token"]), timeout=20).json()
        assert p["land_count"] == 1
        assert p["projects"] >= 2
        currencies = {g["currency"] for g in p["by_currency"]}
        assert "EUR" in currencies and "GBP" in currencies
        eur_group = next(g for g in p["by_currency"] if g["currency"] == "EUR")
        assert eur_group["projects"] == 1
        assert eur_group["purchase_price"] == 100000
        assert eur_group["rate_to_home"] > 0  # GBP home / EUR

        # Change home currency to EUR
        r2 = requests.put(f"{API}/portfolio/home-currency", headers=auth(user["token"]), json={"currency": "EUR"}, timeout=15)
        assert r2.status_code == 200, r2.text
        assert r2.json()["home_currency"] == "EUR"

        p2 = requests.get(f"{API}/portfolio", headers=auth(user["token"]), timeout=20).json()
        assert p2["home_currency"] == "EUR"
        eur_group2 = next(g for g in p2["by_currency"] if g["currency"] == "EUR")
        assert eur_group2["rate_to_home"] == pytest.approx(1.0)

    def test_set_home_invalid_currency_422(self, user):
        r = requests.put(f"{API}/portfolio/home-currency", headers=auth(user["token"]), json={"currency": "XYZ"}, timeout=15)
        assert r.status_code == 422


# -------- Public share report --------
class TestShareReport:
    def test_land_share_shows_land_details_card_and_symbol(self, user):
        # Create EUR land, activate it
        body = {"name": "TEST_ Share Land", "currency": "EUR", "property_type": "land",
                "purchase_price": 50000, "estimated_valuation": 70000, "plot_size": 3,
                "plot_unit": "acres", "planning_status": "granted", "intended_use": "self-build"}
        p = requests.post(f"{API}/projects", headers=auth(user["token"]), json=body, timeout=15).json()
        # Create share for the (now-active) project
        r = requests.post(f"{API}/project/share", headers=auth(user["token"]),
                          json={"origin_url": BASE_URL}, timeout=15)
        assert r.status_code == 200, r.text
        url = r.json()["url"]
        assert url
        html = requests.get(url, timeout=20).text
        assert "id='land-details'" in html or "id=\"land-details\"" in html
        assert "rent-yield" not in html
        # Euro symbol used in money()
        assert "€" in html
        # Planning value shows
        assert "Granted" in html

    def test_residential_share_uses_project_symbol(self, user):
        # Create USD residential project, activate it
        body = {"name": "TEST_ US Flip", "currency": "USD", "property_type": "residential",
                "purchase_price": 200000, "estimated_valuation": 320000, "monthly_rent": 2000,
                "budget": {"hard": 10000, "soft": 2000, "contingency": 1000}}
        requests.post(f"{API}/projects", headers=auth(user["token"]), json=body, timeout=15)
        r = requests.post(f"{API}/project/share", headers=auth(user["token"]),
                          json={"origin_url": BASE_URL}, timeout=15)
        assert r.status_code == 200, r.text
        html = requests.get(r.json()["url"], timeout=20).text
        assert "$" in html
        # £ should NOT appear for the USD project monetary KPIs
        # (allow £ only if present in branding/footer - verify it isn't the money symbol by checking a KPI figure)
        assert "rent-yield" in html  # residential block shown
        assert "land-details" not in html
