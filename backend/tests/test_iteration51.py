"""Iteration 51 – PropertyPlug:
(1) Notification Preferences: GET defaults all true, PUT persists, routes.push.notify() filters out users with that kind False.
(2) Pick Winning Option: POST /api/ai/estimates/{id}/choose creates line items (budgeted=mid),
    marks chosen True, un-chooses other estimates in the project, is idempotent (added returns 0 on repeat),
    POST /api/ai/estimates/{id}/added {index} marks a single item so choose skips it, 404 for unknown id.
"""
import os
import sys
import asyncio
import uuid

import pytest
import requests

# Allow importing backend modules for unit-testing notify() filter logic
sys.path.insert(0, "/app/backend")

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
assert BASE, "EXPO_PUBLIC_BACKEND_URL env var must be set"
API = f"{BASE}/api"

DEMO_EMAIL = "demo@mybuilder.app"
DEMO_PASS = "demo1234"


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


# ============================= 1) Notification Preferences =============================

class TestNotificationPrefs:
    def test_get_defaults_or_current(self, owner):
        """GET /api/notification-prefs returns an object with all 5 kinds as booleans."""
        # Reset to defaults first so subsequent tests have a clean baseline
        reset = {"repairs": True, "jobs": True, "fixed": True, "payouts": True, "invites": True}
        r = requests.put(f"{API}/notification-prefs", headers=_h(owner), json=reset, timeout=20)
        assert r.status_code == 200, r.text

        r = requests.get(f"{API}/notification-prefs", headers=_h(owner), timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("repairs", "jobs", "fixed", "payouts", "invites"):
            assert k in data, f"missing key {k} in prefs {data}"
            assert isinstance(data[k], bool), f"{k} not bool: {data[k]!r}"
        # After explicit reset they should all be True
        assert all(data[k] is True for k in ("repairs", "jobs", "fixed", "payouts", "invites")), data

    def test_put_persists(self, owner):
        """PUT persists – toggle a couple, GET reflects, then restore."""
        body = {"repairs": False, "jobs": True, "fixed": False, "payouts": True, "invites": False}
        r = requests.put(f"{API}/notification-prefs", headers=_h(owner), json=body, timeout=20)
        assert r.status_code == 200
        assert r.json() == body

        r = requests.get(f"{API}/notification-prefs", headers=_h(owner), timeout=20)
        assert r.status_code == 200
        got = r.json()
        for k, v in body.items():
            assert got[k] == v, f"{k} not persisted: expected {v} got {got[k]}"

        # Restore to all-true for other tests / cleanup contract
        restore = {k: True for k in body}
        r = requests.put(f"{API}/notification-prefs", headers=_h(owner), json=restore, timeout=20)
        assert r.status_code == 200
        assert r.json() == restore

    def test_notify_filter_skips_users_with_kind_off(self, owner):
        """Unit-test routes.push.notify(kind=...) with a mocked send_push: users with the kind False are filtered out."""
        from routes import push as push_mod

        captured = {"recipients": None, "data": None}

        async def fake_send(recipients, data, idempotency_key=None, _attempt=0):
            captured["recipients"] = list(recipients)
            captured["data"] = dict(data)

        async def run():
            orig = push_mod.send_push
            push_mod.send_push = fake_send
            try:
                # Owner has prefs restored to all True → should receive
                await push_mod.notify([owner["user"]["id"]], "T", "M", kind="repairs")
                assert captured["recipients"] == [owner["user"]["id"]], captured
                assert captured["data"]["title"] == "T"
                assert captured["data"]["message"] == "M"

                # Flip repairs off via API, then notify should filter the user out
                requests.put(
                    f"{API}/notification-prefs", headers=_h(owner),
                    json={"repairs": False, "jobs": True, "fixed": True, "payouts": True, "invites": True},
                    timeout=20,
                )
                captured["recipients"] = None
                await push_mod.notify([owner["user"]["id"]], "T2", "M2", kind="repairs")
                assert captured["recipients"] is None, f"user should have been filtered out, got {captured}"

                # But a DIFFERENT kind (jobs) still delivers
                captured["recipients"] = None
                await push_mod.notify([owner["user"]["id"]], "T3", "M3", kind="jobs")
                assert captured["recipients"] == [owner["user"]["id"]], captured

                # No kind supplied → never filtered
                captured["recipients"] = None
                await push_mod.notify([owner["user"]["id"]], "T4", "M4")
                assert captured["recipients"] == [owner["user"]["id"]], captured
            finally:
                push_mod.send_push = orig
                # restore all-true
                requests.put(
                    f"{API}/notification-prefs", headers=_h(owner),
                    json={"repairs": True, "jobs": True, "fixed": True, "payouts": True, "invites": True},
                    timeout=20,
                )

        asyncio.run(run())


# ============================= 2) Pick Winning Option =============================

def _list_line_items(owner):
    r = requests.get(f"{API}/line-items", headers=_h(owner), timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


class TestChooseEstimate:
    """These tests rely on there being at least 2 saved estimates (demo has 13).
    They clean up every line item they add and reset chosen/added_items when done."""

    @pytest.fixture(scope="class")
    def estimates(self, owner):
        r = requests.get(f"{API}/ai/estimates", headers=_h(owner), timeout=20)
        assert r.status_code == 200
        ests = r.json()
        # pick two estimates that have at least 1 item
        with_items = [e for e in ests if e.get("items")]
        assert len(with_items) >= 2, f"need 2 estimates with items, got {len(with_items)}"
        a, b = with_items[0], with_items[1]
        return {"a": a, "b": b}

    @pytest.fixture(scope="class")
    def created_line_item_ids(self):
        return set()

    def test_404_unknown_id(self, owner):
        r = requests.post(f"{API}/ai/estimates/507f1f77bcf86cd799439011/choose",
                          headers=_h(owner), timeout=20)
        assert r.status_code == 404

    def test_choose_adds_all_items_and_marks_chosen(self, owner, estimates, created_line_item_ids):
        a = estimates["a"]
        before_items = {li["id"] for li in _list_line_items(owner)}

        r = requests.post(f"{API}/ai/estimates/{a['id']}/choose", headers=_h(owner), timeout=30)
        assert r.status_code == 200, r.text
        resp = r.json()
        assert "added" in resp and "estimate" in resp
        # Items that weren't previously added should all have been added now
        remaining = [i for i in range(len(a["items"])) if i not in (a.get("added_items") or [])]
        assert resp["added"] == len(remaining), f"expected to add {len(remaining)} items, added={resp['added']}"
        est = resp["estimate"]
        assert est["chosen"] is True
        assert est["chosen_at"]
        assert sorted(est["added_items"]) == list(range(len(a["items"])))

        # verify each item ended up in /api/line-items with budgeted = round(mid(low,high))
        after_items = _list_line_items(owner)
        new_items = [li for li in after_items if li["id"] not in before_items]
        created_line_item_ids.update(li["id"] for li in new_items)
        assert len(new_items) == resp["added"], f"line-items created ({len(new_items)}) != added count ({resp['added']})"

        # check budgeted values match mid(low,high) for the estimate's items (by name)
        est_items_by_name = {it["name"][:120]: it for it in a["items"]}
        matched = 0
        for li in new_items:
            src = est_items_by_name.get(li["name"])
            if not src:
                continue
            expected = round((float(src["low"]) + float(src["high"])) / 2)
            assert li["budgeted"] == expected, f"item {li['name']}: budgeted={li['budgeted']} expected={expected}"
            # category must be Hard Cost or Soft Cost
            assert li["category"] in ("Hard Cost", "Soft Cost"), li
            matched += 1
        assert matched >= 1, "no new line items could be matched back to the estimate by name"

    def test_choose_again_adds_zero(self, owner, estimates):
        """Second call for the same estimate adds nothing (idempotent)."""
        a = estimates["a"]
        r = requests.post(f"{API}/ai/estimates/{a['id']}/choose", headers=_h(owner), timeout=20)
        assert r.status_code == 200, r.text
        resp = r.json()
        assert resp["added"] == 0, f"expected 0 adds on repeat, got {resp['added']}"
        assert resp["estimate"]["chosen"] is True

    def test_choosing_other_unmarks_previous(self, owner, estimates, created_line_item_ids):
        """Choosing estimate B un-chooses estimate A (chosen=False)."""
        b = estimates["b"]
        before_items = {li["id"] for li in _list_line_items(owner)}
        r = requests.post(f"{API}/ai/estimates/{b['id']}/choose", headers=_h(owner), timeout=30)
        assert r.status_code == 200, r.text
        est_b = r.json()["estimate"]
        assert est_b["chosen"] is True

        # Previously chosen A should now be chosen=False
        ra = requests.get(f"{API}/ai/estimates/{estimates['a']['id']}", headers=_h(owner), timeout=20)
        assert ra.status_code == 200
        assert ra.json()["chosen"] is False, "previous estimate should be un-chosen when another is chosen"

        # Track new items for cleanup
        after_items = _list_line_items(owner)
        new_items = [li for li in after_items if li["id"] not in before_items]
        created_line_item_ids.update(li["id"] for li in new_items)

    def test_added_endpoint_marks_single_item(self, owner):
        """POST /api/ai/estimates/{id}/added {index} adds that index to added_items so later choose skips it."""
        # Find a FRESH estimate that is not currently chosen and has items
        ests = requests.get(f"{API}/ai/estimates", headers=_h(owner), timeout=20).json()
        candidate = next((e for e in ests if not e["chosen"] and e["items"] and not e.get("added_items")), None)
        if not candidate:
            pytest.skip("No fresh un-chosen estimate with items available for /added test")

        # mark index 0 as added
        r = requests.post(f"{API}/ai/estimates/{candidate['id']}/added",
                          headers=_h(owner), json={"index": 0}, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True}

        detail = requests.get(f"{API}/ai/estimates/{candidate['id']}", headers=_h(owner), timeout=20).json()
        assert 0 in detail["added_items"], detail

        # /added should be idempotent (addToSet) – call again, still just [0]
        r2 = requests.post(f"{API}/ai/estimates/{candidate['id']}/added",
                           headers=_h(owner), json={"index": 0}, timeout=20)
        assert r2.status_code == 200
        detail2 = requests.get(f"{API}/ai/estimates/{candidate['id']}", headers=_h(owner), timeout=20).json()
        assert detail2["added_items"].count(0) == 1

        # Now reset the added_items for this estimate directly via DB so we don't leak state
        # (there is no public API to clear added_items — the server does it only during choose)
        # Clean up via direct Mongo call will be done in teardown.
        self._fresh_est_id = candidate["id"]

    def test_cleanup_delete_created_line_items_and_reset_estimates(self, owner, estimates, created_line_item_ids):
        """Delete every line item created above and reset chosen/added_items on the two estimates."""
        # Delete the created line items
        failures = []
        for li_id in list(created_line_item_ids):
            r = requests.delete(f"{API}/line-items/{li_id}", headers=_h(owner), timeout=15)
            if r.status_code not in (200, 204, 404):
                failures.append((li_id, r.status_code, r.text[:80]))
        assert not failures, f"cleanup line-item deletes failed: {failures}"

        # Reset chosen/added_items in Mongo directly (no public endpoint)
        import asyncio as _asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        from bson import ObjectId

        async def _reset():
            cli = AsyncIOMotorClient(os.environ.get("MONGO_URL"))
            db_ = cli[os.environ.get("DB_NAME", "test_database")]
            uid = owner["user"]["id"]
            await db_.estimates.update_many(
                {"user_id": uid},
                {"$set": {"chosen": False, "added_items": []}, "$unset": {"chosen_at": ""}},
            )
            cli.close()

        _asyncio.run(_reset())

        # verify none are chosen now
        ests = requests.get(f"{API}/ai/estimates", headers=_h(owner), timeout=20).json()
        assert not any(e["chosen"] for e in ests), "still have chosen estimates after cleanup"
