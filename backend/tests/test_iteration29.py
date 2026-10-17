"""Iteration 29 — AI estimate with photo + AI-designed finished image with pins.

Scope (per review_request):
- POST /api/ai/estimate {description, finish_type, photo_path?}: items with spec+visible+low/high+supplier+id;
  photo_path from POST /api/upload is accepted; photo_path from another user -> 404; empty description -> 400.
- POST /api/ai/estimate/{id}/design: returns {image_path, pins:[{i,x,y,name,spec,low,high,supplier}]} with x,y in 4..96;
  image_path downloadable via GET /api/files/{path}?token=...; a media row (phase 'after', title starting 'AI design:')
  is appended to GET /api/media; cross-user estimate id -> 404.
NOTE: each design call takes ~15-30s and costs credits — total of 2 design calls (one without photo, one with photo).
"""
import os
import sys
import io
import asyncio
import pytest
import requests
from PIL import Image
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
sys.path.insert(0, "/app/backend")

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
DEMO = {"email": "demo@mybuilder.app", "password": "demo1234"}


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


def _tiny_jpeg_bytes(color=(200, 180, 140), size=(320, 240)):
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


# ---- fixtures ---------------------------------------------------------------

@pytest.fixture(scope="module")
def demo_token():
    r = requests.post(f"{API}/auth/login", json=DEMO, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def demo_headers(demo_token):
    return {"Authorization": f"Bearer {demo_token}"}


@pytest.fixture(scope="module")
def other_user():
    """Fresh user to prove cross-user isolation."""
    import uuid as _u
    email = f"TEST_iter29_other_{_u.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/auth/register", json={"name": "Iter29 Other", "email": email, "password": "pw12345678"}, timeout=20)
    assert r.status_code in (200, 201), r.text
    tok = r.json()["access_token"]
    uid = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=10).json()["id"]
    yield {"email": email, "token": tok, "id": uid}

    async def _cleanup(db):
        await db.estimates.delete_many({"user_id": uid})
        await db.files.delete_many({"owner_id": uid})
        await db.media.delete_many({"user_id": uid})
        await db.projects.delete_many({"user_id": uid})
        await db.line_items.delete_many({"user_id": uid})
        await db.users.delete_many({"id": uid})
    _run(_cleanup)


@pytest.fixture(scope="module")
def demo_photo_path(demo_headers):
    files = {"file": ("iter29.jpg", _tiny_jpeg_bytes(), "image/jpeg")}
    r = requests.post(f"{API}/upload", headers=demo_headers, files=files, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["path"]


@pytest.fixture(scope="module")
def other_photo_path(other_user):
    files = {"file": ("other.jpg", _tiny_jpeg_bytes(color=(100, 120, 150)), "image/jpeg")}
    r = requests.post(f"{API}/upload", headers={"Authorization": f"Bearer {other_user['token']}"}, files=files, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["path"]


# shared estimate ids & paths captured for cleanup
_created = {"estimate_ids": [], "design_paths": [], "media_ids": []}


@pytest.fixture(scope="module", autouse=True)
def _teardown():
    yield

    async def _cleanup(db):
        from bson import ObjectId
        for eid in _created["estimate_ids"]:
            try:
                await db.estimates.delete_one({"_id": ObjectId(eid)})
            except Exception:
                pass
        for p in _created["design_paths"]:
            await db.files.delete_many({"storage_path": p})
        # Keep ONE AI design media row per main-agent instructions; delete the rest.
        for mid in _created["media_ids"][1:]:
            try:
                await db.media.delete_one({"_id": ObjectId(mid)})
            except Exception:
                pass
    _run(_cleanup)


# ---- /api/ai/estimate -------------------------------------------------------

class TestEstimate:
    def test_empty_description_returns_400(self, demo_headers):
        r = requests.post(f"{API}/ai/estimate", headers=demo_headers,
                          json={"description": "   ", "finish_type": "Medium Finish"}, timeout=30)
        assert r.status_code == 400, r.text

    def test_cross_user_photo_path_returns_404(self, demo_headers, other_photo_path):
        r = requests.post(f"{API}/ai/estimate", headers=demo_headers,
                          json={"description": "Replace kitchen worktop with laminate",
                                "finish_type": "Medium Finish",
                                "photo_path": other_photo_path}, timeout=60)
        assert r.status_code == 404, r.text

    def test_estimate_without_photo(self, demo_headers):
        r = requests.post(f"{API}/ai/estimate", headers=demo_headers,
                          json={"description": "Re-plaster and paint one small bedroom, 3m x 3m",
                                "finish_type": "Medium Finish"}, timeout=90)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "id" in data and isinstance(data["id"], str)
        assert isinstance(data.get("items"), list) and 3 <= len(data["items"]) <= 8
        for it in data["items"]:
            assert isinstance(it.get("name"), str) and it["name"]
            assert "spec" in it
            assert "visible" in it and isinstance(it["visible"], bool)
            assert isinstance(it["low"], (int, float)) and isinstance(it["high"], (int, float))
            assert it["high"] >= it["low"] >= 0
            assert isinstance(it.get("supplier"), str)
        assert isinstance(data.get("total_low"), (int, float))
        assert isinstance(data.get("total_high"), (int, float))
        _created["estimate_ids"].append(data["id"])
        # stash for the design test below
        pytest.estimate_without_photo_id = data["id"]

    def test_estimate_with_photo(self, demo_headers, demo_photo_path):
        r = requests.post(f"{API}/ai/estimate", headers=demo_headers,
                          json={"description": "Refit a small bathroom - new suite, tiles, taps",
                                "finish_type": "Medium Finish",
                                "photo_path": demo_photo_path}, timeout=90)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "id" in data
        assert len(data["items"]) >= 3
        _created["estimate_ids"].append(data["id"])
        pytest.estimate_with_photo_id = data["id"]


# ---- /api/ai/estimate/{id}/design -------------------------------------------

class TestDesign:
    def test_cross_user_design_returns_404(self, other_user):
        eid = getattr(pytest, "estimate_without_photo_id", None)
        if not eid:
            pytest.skip("estimate without photo not available")
        r = requests.post(f"{API}/ai/estimate/{eid}/design",
                          headers={"Authorization": f"Bearer {other_user['token']}"}, timeout=120)
        assert r.status_code == 404, r.text

    def test_design_without_photo(self, demo_headers, demo_token):
        eid = getattr(pytest, "estimate_without_photo_id", None)
        if not eid:
            pytest.skip("estimate without photo not available")
        # Count media before to assert +1 after
        before = requests.get(f"{API}/media", headers=demo_headers, timeout=15)
        assert before.status_code == 200
        before_count = len(before.json())

        r = requests.post(f"{API}/ai/estimate/{eid}/design", headers=demo_headers, timeout=180)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data.get("image_path"), str) and data["image_path"]
        _created["design_paths"].append(data["image_path"])
        pins = data.get("pins")
        assert isinstance(pins, list)
        # Pins may be empty if locator fails, but when present, must have required keys and coords in [4,96]
        for p in pins:
            assert set(["i", "x", "y", "name", "spec", "low", "high", "supplier"]).issubset(p.keys())
            assert 4 <= p["x"] <= 96, p
            assert 4 <= p["y"] <= 96, p

        # image_path downloadable via GET /api/files/{path}?token=
        dl = requests.get(f"{API}/files/{data['image_path']}", params={"token": demo_token}, timeout=30)
        assert dl.status_code == 200, dl.text
        assert dl.headers.get("content-type", "").startswith("image/")
        assert len(dl.content) > 1000  # non-trivial image bytes

        # Also works via Authorization header
        dl2 = requests.get(f"{API}/files/{data['image_path']}", headers=demo_headers, timeout=30)
        assert dl2.status_code == 200

        # A new media row with phase=after and title starting "AI design:" exists
        after = requests.get(f"{API}/media", headers=demo_headers, timeout=15)
        assert after.status_code == 200
        rows = after.json()
        assert len(rows) == before_count + 1, f"media count {before_count} -> {len(rows)}"
        ai_rows = [m for m in rows if (m.get("title") or "").startswith("AI design:")]
        assert ai_rows, "no AI design media row created"
        assert ai_rows[0]["phase"] == "after"
        assert ai_rows[0].get("storage_path") == data["image_path"]
        _created["media_ids"].append(ai_rows[0]["id"])

    def test_design_with_photo(self, demo_headers, demo_token):
        eid = getattr(pytest, "estimate_with_photo_id", None)
        if not eid:
            pytest.skip("estimate with photo not available")
        r = requests.post(f"{API}/ai/estimate/{eid}/design", headers=demo_headers, timeout=180)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data.get("image_path"), str) and data["image_path"]
        _created["design_paths"].append(data["image_path"])
        for p in data.get("pins", []):
            assert 4 <= p["x"] <= 96
            assert 4 <= p["y"] <= 96
        dl = requests.get(f"{API}/files/{data['image_path']}", params={"token": demo_token}, timeout=30)
        assert dl.status_code == 200
        assert dl.headers.get("content-type", "").startswith("image/")

        # record this media id for cleanup (we'll keep one, delete this one in teardown)
        media = requests.get(f"{API}/media", headers=demo_headers, timeout=15).json()
        for m in media:
            if m.get("storage_path") == data["image_path"]:
                _created["media_ids"].append(m["id"])
                break
