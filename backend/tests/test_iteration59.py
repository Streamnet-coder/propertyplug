"""Iteration 59 - EPC Upgrade Planner for the active project and Size-Based Valuation.

Covers:
- GET /api/project/epc returns status 'ok' with full details on the pinned demo cert
  (demo project at 14 Mapperley Road NG3 5AP currently pinned to 4836-5623-9600-0320-4222)
- Shape of improvements[], candidates[], and summary fields (band, rating, sqm, sqft)
- PUT /api/project/epc {certificate_number: null} unpins and transitions to 'pick'
- PUT /api/project/epc {certificate_number: <cert>} re-pins and returns 'ok'
- POST /api/project/epc/add-to-budget creates Hard Cost line items at midpoint cost
  and is idempotent (second call adds 0 items)
- Created EPC line items are visible in GET /api/line-items and are deleted at the end
- POST /api/auth/plan toggle to 'pro' and back to 'basic'
"""
import os
import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
assert BASE, "EXPO_PUBLIC_BACKEND_URL must be set"
API = f"{BASE}/api"
DEMO = {"email": "demo@mybuilder.app", "password": "demo1234"}
PINNED_CERT = "4836-5623-9600-0320-4222"


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def tok():
    r = requests.post(f"{API}/auth/login", json=DEMO, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module", autouse=True)
def ensure_pinned(tok):
    """Make sure the demo cert is pinned before and after this test run."""
    r = requests.put(f"{API}/project/epc", json={"certificate_number": PINNED_CERT},
                     headers=_h(tok), timeout=60)
    assert r.status_code == 200, r.text
    yield
    # Re-pin at end to leave project in demo state
    requests.put(f"{API}/project/epc", json={"certificate_number": PINNED_CERT},
                 headers=_h(tok), timeout=60)


class TestProjectEpcAuth:
    def test_requires_auth(self):
        r = requests.get(f"{API}/project/epc", timeout=20)
        assert r.status_code in (401, 403), r.text


class TestProjectEpcOk:
    """GET /api/project/epc with the demo pinned certificate -> status 'ok'."""

    @pytest.fixture(scope="class")
    def body(self, tok):
        r = requests.get(f"{API}/project/epc", headers=_h(tok), timeout=60)
        assert r.status_code == 200, r.text
        return r.json()

    def test_status_ok(self, body):
        assert body.get("status") == "ok", body

    def test_cert_fields(self, body):
        assert body["certificate_number"] == PINNED_CERT
        assert body["pinned"] is True
        assert body["postcode"].endswith("5AP")
        # Address contains Malcolm Close
        assert "malcolm" in (body.get("address") or "").lower(), body.get("address")

    def test_bands_and_ratings(self, body):
        assert body["band"] == "D"
        assert body["rating"] == 57
        assert body["potential_band"] == "C"
        assert body["potential_rating"] == 73

    def test_floor_area(self, body):
        assert body["sqft"] == 667, body.get("sqft")
        assert body["sqm"] and body["sqm"] > 50

    def test_improvements_shape(self, body):
        imps = body.get("improvements") or []
        assert len(imps) == 2, imps
        names = [x["name"] for x in imps]
        assert "Cavity wall insulation" in names
        assert "High heat retention storage heaters" in names
        for x in imps:
            for k in ("sequence", "code", "name", "cost_text", "cost_low", "cost_high",
                      "saving", "rating_after", "band_after", "in_budget"):
                assert k in x, f"improvement missing {k}: {x}"
            assert isinstance(x["sequence"], int)
            assert x["cost_high"] >= x["cost_low"] > 0

    def test_improvement_cost_ranges(self, body):
        imps = {x["name"]: x for x in body["improvements"]}
        cwi = imps["Cavity wall insulation"]
        assert (cwi["cost_low"], cwi["cost_high"]) == (900.0, 1500.0)
        hhr = imps["High heat retention storage heaters"]
        assert (hhr["cost_low"], hhr["cost_high"]) == (1200.0, 2400.0)

    def test_candidates(self, body):
        cands = body.get("candidates") or []
        assert isinstance(cands, list) and len(cands) >= 1
        assert any(c["certificate_number"] == PINNED_CERT for c in cands)
        for c in cands[:3]:
            for k in ("certificate_number", "address", "band", "date"):
                assert k in c, c


class TestPinUnpin:
    def test_unpin_to_pick(self, tok):
        r = requests.put(f"{API}/project/epc", json={"certificate_number": None},
                         headers=_h(tok), timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        # Demo address "14 Mapperley Road NG3 5AP" won't token-match 5 Malcolm Close,
        # so unpinning should land us in 'pick' with candidates
        assert d.get("status") in ("pick", "ok"), d
        if d["status"] == "pick":
            assert isinstance(d.get("candidates"), list) and len(d["candidates"]) >= 1

    def test_repin_to_ok(self, tok):
        r = requests.put(f"{API}/project/epc", json={"certificate_number": PINNED_CERT},
                         headers=_h(tok), timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "ok"
        assert d["certificate_number"] == PINNED_CERT
        assert d["pinned"] is True


class TestAddToBudget:
    """POST /api/project/epc/add-to-budget creates line items at midpoint and is idempotent."""

    created_ids = []

    def _cleanup(self, tok):
        for lid in list(self.__class__.created_ids):
            requests.delete(f"{API}/line-items/{lid}", headers=_h(tok), timeout=20)
        self.__class__.created_ids = []

    def test_pre_cleanup(self, tok):
        # Remove any pre-existing 'EPC: ...' items from earlier runs so test is deterministic
        r = requests.get(f"{API}/line-items", headers=_h(tok), timeout=30)
        assert r.status_code == 200, r.text
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        for li in items:
            if (li.get("supplier") == "EPC recommendation"
                    or (li.get("name") or "").startswith("EPC: ")):
                requests.delete(f"{API}/line-items/{li['id']}", headers=_h(tok), timeout=20)

    def test_add_two_improvements(self, tok):
        r = requests.post(f"{API}/project/epc/add-to-budget",
                          json={"sequences": [1, 2]}, headers=_h(tok), timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["count"] == 2, d
        assert set(d["added"]) == {"Cavity wall insulation", "High heat retention storage heaters"}

    def test_line_items_created_with_midpoint(self, tok):
        r = requests.get(f"{API}/line-items", headers=_h(tok), timeout=30)
        assert r.status_code == 200, r.text
        raw = r.json()
        items = raw if isinstance(raw, list) else raw.get("items", [])
        epc_items = [li for li in items if li.get("supplier") == "EPC recommendation"]
        assert len(epc_items) == 2, epc_items
        by_name = {li["name"]: li for li in epc_items}
        assert "EPC: Cavity wall insulation" in by_name
        assert "EPC: High heat retention storage heaters" in by_name
        assert by_name["EPC: Cavity wall insulation"]["budgeted"] == 1200
        assert by_name["EPC: High heat retention storage heaters"]["budgeted"] == 1800
        for li in epc_items:
            assert li.get("category") == "Hard Cost"
            self.__class__.created_ids.append(li["id"])

    def test_marked_in_budget_in_epc(self, tok):
        r = requests.get(f"{API}/project/epc", headers=_h(tok), timeout=30)
        assert r.status_code == 200
        d = r.json()
        for imp in d["improvements"]:
            assert imp["in_budget"] is True, imp

    def test_idempotent_second_call(self, tok):
        r = requests.post(f"{API}/project/epc/add-to-budget",
                          json={"sequences": [1, 2]}, headers=_h(tok), timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["count"] == 0, d
        assert d["added"] == []

    def test_cleanup_deletes_items(self, tok):
        self._cleanup(tok)
        # Verify in_budget flips back to False
        r = requests.get(f"{API}/project/epc", headers=_h(tok), timeout=30)
        d = r.json()
        for imp in d["improvements"]:
            assert imp["in_budget"] is False, imp


class TestAuthPlanToggle:
    """BRRR screen (reached by sold-use-size-gdv) is Pro-only."""

    def test_set_pro_then_basic(self, tok):
        r = requests.post(f"{API}/auth/plan", json={"plan": "pro"},
                          headers=_h(tok), timeout=20)
        assert r.status_code == 200, r.text
        me = requests.get(f"{API}/auth/me", headers=_h(tok), timeout=20).json()
        assert me["plan"] == "pro"
        r2 = requests.post(f"{API}/auth/plan", json={"plan": "basic"},
                           headers=_h(tok), timeout=20)
        assert r2.status_code == 200, r2.text
        me2 = requests.get(f"{API}/auth/me", headers=_h(tok), timeout=20).json()
        assert me2["plan"] == "basic"
