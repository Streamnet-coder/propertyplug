"""Iteration 19 — Land uplift, planning CRUD, portfolio map pins.

Covers:
- /api/planning CRUD (list/create/update/delete), ref-or-description required, date validation, days_to_decision
- PUT /api/project pins (lat+lon both required, clear_pin resets, out-of-range 422)
- POST /api/projects accepts lat/lon on create
- GET /api/portfolio/map returns pins with required fields; manual pin preserved
- Project deletion cleans up planning docs
"""
import os
import uuid
import pytest
import requests

BASE_URL = (os.environ.get('EXPO_BACKEND_URL') or os.environ['EXPO_PUBLIC_BACKEND_URL']).rstrip('/')


# ---------- helpers / fixtures ----------
@pytest.fixture(scope="module")
def user():
    email = f"TEST_iter19_{uuid.uuid4().hex[:8]}@mybuilder.app"
    pw = "testpass1234"
    r = requests.post(f"{BASE_URL}/api/auth/register", json={"name": "Iter19", "email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    yield {"token": token, "email": email}
    # cleanup user & all their data
    try:
        requests.delete(f"{BASE_URL}/api/auth/account", headers={"Authorization": f"Bearer {token}"}, timeout=20)
    except Exception:
        pass


@pytest.fixture
def h(user):
    return {"Authorization": f"Bearer {user['token']}", "Content-Type": "application/json"}


def _active_pid(h):
    r = requests.get(f"{BASE_URL}/api/project", headers=h, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------- /api/planning ----------
class TestPlanning:
    def test_list_empty(self, h):
        r = requests.get(f"{BASE_URL}/api/planning", headers=h, timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_requires_ref_or_description(self, h):
        r = requests.post(f"{BASE_URL}/api/planning", headers=h, json={"authority": "Rushcliffe"}, timeout=20)
        assert r.status_code == 400
        assert "reference" in r.text.lower() or "description" in r.text.lower()

    def test_create_bad_date_returns_422(self, h):
        r = requests.post(f"{BASE_URL}/api/planning", headers=h, json={"reference": "X/1", "submitted_date": "2025/01/01"}, timeout=20)
        assert r.status_code == 422

    def test_full_lifecycle_and_days(self, h):
        # Create pending w/ future target date -> days_to_decision positive
        from datetime import date, timedelta
        future = (date.today() + timedelta(days=10)).isoformat()
        payload = {
            "authority": "Rushcliffe Borough Council",
            "reference": "24/01234/FUL",
            "description": "Outline for 4 dwellings",
            "submitted_date": "2025-01-05",
            "target_decision_date": future,
            "notes": "n/a",
        }
        r = requests.post(f"{BASE_URL}/api/planning", headers=h, json=payload, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["reference"] == "24/01234/FUL"
        assert d["decision"] == "pending"
        assert d["days_to_decision"] == 10
        assert "_id" not in d and "user_id" not in d
        aid = d["id"]

        # List includes it
        lst = requests.get(f"{BASE_URL}/api/planning", headers=h, timeout=20).json()
        assert any(a["id"] == aid for a in lst)

        # Update -> approved: days_to_decision must be None
        upd = {**payload, "decision": "approved", "decision_date": "2025-02-20"}
        r = requests.put(f"{BASE_URL}/api/planning/{aid}", headers=h, json=upd, timeout=20)
        assert r.status_code == 200, r.text
        d2 = r.json()
        assert d2["decision"] == "approved"
        assert d2["days_to_decision"] is None
        assert d2["decision_date"] == "2025-02-20"

        # Update with bad date -> 422
        bad = {**upd, "validated_date": "not-a-date"}
        r = requests.put(f"{BASE_URL}/api/planning/{aid}", headers=h, json=bad, timeout=20)
        assert r.status_code == 422

        # Delete
        r = requests.delete(f"{BASE_URL}/api/planning/{aid}", headers=h, timeout=20)
        assert r.status_code == 200 and r.json().get("ok") is True
        lst = requests.get(f"{BASE_URL}/api/planning", headers=h, timeout=20).json()
        assert not any(a["id"] == aid for a in lst)

    def test_planning_scoped_to_active_project_and_deleted_with_it(self, h):
        # Create secondary project, activate, add planning, delete project -> gone
        r = requests.post(f"{BASE_URL}/api/projects", headers=h, json={"name": "TEST_land_scope", "property_type": "land", "address": "Field Lane, Nottingham"}, timeout=20)
        assert r.status_code == 200
        pid = r.json()["id"]
        r = requests.post(f"{BASE_URL}/api/planning", headers=h, json={"reference": "SCOPE/1"}, timeout=20)
        assert r.status_code == 200
        apps_pid = requests.get(f"{BASE_URL}/api/planning", headers=h, timeout=20).json()
        assert any(a["reference"] == "SCOPE/1" for a in apps_pid)

        # Create and activate another project
        r = requests.post(f"{BASE_URL}/api/projects", headers=h, json={"name": "TEST_other"}, timeout=20)
        other = r.json()["id"]
        apps_other = requests.get(f"{BASE_URL}/api/planning", headers=h, timeout=20).json()
        assert not any(a["reference"] == "SCOPE/1" for a in apps_other)

        # Delete original project -> its planning should also be removed
        requests.post(f"{BASE_URL}/api/projects/{pid}/activate", headers=h, timeout=20)
        r = requests.delete(f"{BASE_URL}/api/projects/{pid}", headers=h, timeout=20)
        assert r.status_code == 200
        # Switch to other, confirm no cross-project leakage
        requests.post(f"{BASE_URL}/api/projects/{other}/activate", headers=h, timeout=20)
        apps_after = requests.get(f"{BASE_URL}/api/planning", headers=h, timeout=20).json()
        assert not any(a["reference"] == "SCOPE/1" for a in apps_after)
        # cleanup
        requests.delete(f"{BASE_URL}/api/projects/{other}", headers=h, timeout=20)


# ---------- PUT /api/project pin + land values ----------
class TestProjectPin:
    def test_land_values_round_trip(self, h):
        r = requests.put(f"{BASE_URL}/api/project", headers=h, json={"value_without_planning": 150000, "value_with_planning": 500000}, timeout=20)
        assert r.status_code == 200
        p = r.json()
        assert p["value_without_planning"] == 150000
        assert p["value_with_planning"] == 500000

    def test_both_lat_lon_required(self, h):
        r = requests.put(f"{BASE_URL}/api/project", headers=h, json={"lat": 52.9}, timeout=20)
        assert r.status_code == 400

    def test_lat_out_of_range(self, h):
        r = requests.put(f"{BASE_URL}/api/project", headers=h, json={"lat": 100, "lon": 10}, timeout=20)
        assert r.status_code == 422

    def test_set_and_clear_pin(self, h):
        r = requests.put(f"{BASE_URL}/api/project", headers=h, json={"lat": 52.9548, "lon": -1.1581}, timeout=20)
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["lat"] == 52.9548 and p["lon"] == -1.1581
        assert p["pin_manual"] is True
        # Clear
        r = requests.put(f"{BASE_URL}/api/project", headers=h, json={"clear_pin": True}, timeout=20)
        assert r.status_code == 200
        p2 = r.json()
        assert p2["pin_manual"] is False
        assert p2["lat"] is None and p2["lon"] is None

    def test_create_project_with_pin(self, h):
        r = requests.post(f"{BASE_URL}/api/projects", headers=h, json={"name": "TEST_pin_create", "lat": 51.5, "lon": -0.1}, timeout=20)
        assert r.status_code == 200
        p = r.json()
        assert p["lat"] == 51.5 and p["lon"] == -0.1
        assert p["pin_manual"] is True
        # cleanup: activate another and delete
        projs = requests.get(f"{BASE_URL}/api/projects", headers=h, timeout=20).json()
        other = next((x for x in projs if x["id"] != p["id"]), None)
        if other:
            requests.post(f"{BASE_URL}/api/projects/{other['id']}/activate", headers=h, timeout=20)
            requests.delete(f"{BASE_URL}/api/projects/{p['id']}", headers=h, timeout=20)


# ---------- GET /api/portfolio/map ----------
class TestPortfolioMap:
    def test_shape_and_manual_pin_preserved(self, h):
        # Ensure a project has a manual pin
        requests.put(f"{BASE_URL}/api/project", headers=h, json={"lat": 52.9548, "lon": -1.1581}, timeout=20)
        r = requests.get(f"{BASE_URL}/api/portfolio/map", headers=h, timeout=60)
        assert r.status_code == 200, r.text
        pins = r.json()
        assert isinstance(pins, list) and pins, "expected at least one project"
        required = {"id", "name", "address", "lat", "lon", "pin_manual", "property_type", "currency", "active"}
        for p in pins:
            assert required.issubset(p.keys()), f"missing keys in {p}"
        # The one we pinned should still have manual coords
        manual = [p for p in pins if p["pin_manual"]]
        assert manual, "manual pin not surfaced on map"
        assert any(abs(p["lat"] - 52.9548) < 1e-6 and abs(p["lon"] + 1.1581) < 1e-6 for p in manual)

    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/portfolio/map", timeout=20)
        assert r.status_code in (401, 403)
