"""Iteration 61 backend tests: credits endpoint, charging per tool, 402 exhaustion, rent-comparables shape & validation.
Uses demo user demo@mybuilder.app / demo1234 (basic plan). Cleans credit_log for current month at end.
"""
import os
from datetime import date, datetime, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") if os.environ.get("EXPO_PUBLIC_BACKEND_URL") else None
# Prefer backend env (same codebase uses this file)
if not BASE_URL:
    # fall back to reading frontend .env
    import pathlib, re
    env = pathlib.Path("/app/frontend/.env").read_text()
    m = re.search(r"EXPO_PUBLIC_BACKEND_URL=(\S+)", env)
    BASE_URL = m.group(1).rstrip("/")

DEMO_EMAIL = "demo@mybuilder.app"
DEMO_PASSWORD = "demo1234"
PERIOD = date.today().strftime("%Y-%m")


def _mongo():
    mu = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    dbn = os.environ.get("DB_NAME") or "test_database"
    # read from backend/.env if envs not inherited
    if "MONGO_URL" not in os.environ:
        import pathlib, re
        env = pathlib.Path("/app/backend/.env").read_text()
        mu = re.search(r'MONGO_URL="?([^"\n]+)"?', env).group(1)
        dbn = re.search(r'DB_NAME="?([^"\n]+)"?', env).group(1)
    return MongoClient(mu)[dbn]


@pytest.fixture(scope="module")
def db():
    return _mongo()


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json()["access_token"]
    s.headers["Authorization"] = f"Bearer {tok}"
    # ensure basic plan
    s.post(f"{BASE_URL}/api/auth/plan", json={"plan": "basic"}, timeout=15)
    # whoami to retrieve user id
    me = s.get(f"{BASE_URL}/api/auth/me", timeout=15)
    assert me.status_code == 200
    s.user_id = me.json()["id"]
    return s


@pytest.fixture(autouse=True)
def _cleanup_before(session, db):
    # Clean our test month before each test
    db.credit_log.delete_many({"user_id": session.user_id, "period": PERIOD})
    yield
    # final cleanup done in module teardown


@pytest.fixture(scope="module", autouse=True)
def _final_cleanup(db):
    yield
    # cleanup for all demo user credit_log for this period
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}, timeout=15)
    if r.status_code == 200:
        tok = r.json()["access_token"]
        me = s.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()
        db.credit_log.delete_many({"user_id": me["id"], "period": PERIOD})
        # ensure left on basic
        s.post(f"{BASE_URL}/api/auth/plan", json={"plan": "basic"}, headers={"Authorization": f"Bearer {tok}"})


# ---------- /api/credits -----------
class TestCredits:
    def test_credits_shape_basic(self, session):
        r = session.get(f"{BASE_URL}/api/credits", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("unlimited", "allowance", "used", "remaining", "resets_on", "costs", "recent"):
            assert k in d, f"missing {k}"
        assert d["unlimited"] is False
        assert d["allowance"] == 100
        assert d["used"] == 0
        assert d["remaining"] == 100
        # resets_on is 1st of next month
        today = date.today()
        exp = date(today.year + 1, 1, 1) if today.month == 12 else date(today.year, today.month + 1, 1)
        assert d["resets_on"] == exp.isoformat()
        # costs include all 4 tools
        labels = {c["tool"]: c["cost"] for c in d["costs"]}
        assert labels == {"Sold prices search": 5, "Rent comparables": 2, "EPC lookup": 2, "AI cost estimate": 10}
        assert isinstance(d["recent"], list)

    def test_credits_shape_pro(self, session):
        session.post(f"{BASE_URL}/api/auth/plan", json={"plan": "pro"}, timeout=15)
        try:
            r = session.get(f"{BASE_URL}/api/credits", timeout=15)
            assert r.status_code == 200
            assert r.json()["unlimited"] is True
        finally:
            session.post(f"{BASE_URL}/api/auth/plan", json={"plan": "basic"}, timeout=15)


# ---------- /api/rent-comparables -----------
class TestRentComparables:
    def test_valid_postcode_shape(self, session, db):
        r = session.get(f"{BASE_URL}/api/rent-comparables?postcode=NG3%205AP", timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["postcode"].replace(" ", "") == "NG35AP"
        assert d["local"]["code"] == "E06000018"  # Nottingham local authority
        assert d["local"]["month"]
        for k in ("all", "1", "2", "3", "4", "detached", "semi", "terraced", "flat"):
            assert k in d["local"]["prices"], f"missing local price bucket {k}"
        assert "annual_change" in d["local"]
        # region = East Midlands
        assert d["region"] is not None
        assert "east midland" in d["region"]["name"].lower()
        # uk key K02000001
        assert d["uk"] is not None and d["uk"]["code"] == "K02000001"
        # credits used (rent_comps costs 2)
        c = session.get(f"{BASE_URL}/api/credits").json()
        assert c["used"] == 2

    def test_valid_postcode_charges_once_in_24h(self, session):
        session.get(f"{BASE_URL}/api/rent-comparables?postcode=NG3%205AP", timeout=20)
        used_after_first = session.get(f"{BASE_URL}/api/credits").json()["used"]
        session.get(f"{BASE_URL}/api/rent-comparables?postcode=NG3%205AP", timeout=20)
        used_after_second = session.get(f"{BASE_URL}/api/credits").json()["used"]
        assert used_after_first == used_after_second == 2

    def test_invalid_postcode_400(self, session):
        r = session.get(f"{BASE_URL}/api/rent-comparables?postcode=NOTAPC", timeout=15)
        assert r.status_code == 400

    def test_unknown_postcode_404(self, session):
        r = session.get(f"{BASE_URL}/api/rent-comparables?postcode=ZZ99%209ZZ", timeout=20)
        assert r.status_code == 404


# ---------- 402 exhaustion ----------
class TestCreditsExhaustion:
    def test_402_when_exhausted(self, session, db):
        # Insert 99 credits worth of history so next 2-credit rent_comps charge pushes to 101 > 100.
        now = datetime.now(timezone.utc).isoformat()
        db.credit_log.insert_one({"user_id": session.user_id, "tool": "sold_prices", "key": "SEED|exhaust",
                                   "cost": 99, "period": PERIOD, "at": now})
        try:
            # new postcode (different key) → not deduped
            r = session.get(f"{BASE_URL}/api/rent-comparables?postcode=NG1%205DU", timeout=20)
            assert r.status_code == 402, f"expected 402, got {r.status_code} {r.text}"
            detail = r.json().get("detail", "")
            assert "Upgrade to Pro" in detail
            assert "100 free credits" in detail
        finally:
            db.credit_log.delete_many({"user_id": session.user_id, "period": PERIOD})

    def test_pro_never_charged(self, session, db):
        session.post(f"{BASE_URL}/api/auth/plan", json={"plan": "pro"}, timeout=15)
        try:
            # Even with 100 used, pro should still succeed
            now = datetime.now(timezone.utc).isoformat()
            db.credit_log.insert_one({"user_id": session.user_id, "tool": "sold_prices", "key": "SEED|pro",
                                       "cost": 100, "period": PERIOD, "at": now})
            r = session.get(f"{BASE_URL}/api/rent-comparables?postcode=NG3%205AP", timeout=20)
            assert r.status_code == 200
        finally:
            session.post(f"{BASE_URL}/api/auth/plan", json={"plan": "basic"}, timeout=15)
            db.credit_log.delete_many({"user_id": session.user_id, "period": PERIOD})
