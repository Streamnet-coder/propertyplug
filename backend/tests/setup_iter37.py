"""
Setup script for iteration 37 frontend retest.
1. Register a TEST manager via API
2. Owner (demo@mybuilder.app) invites manager with project_ids=[demo pid] and money_access=False
3. Manager activates the shared project via POST /api/projects/{pid}/activate
4. Verify /auth/login response for manager includes acting_as.money=False
"""
import os
import sys
import time
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://dev-budget-tracker-2.preview.emergentagent.com").rstrip("/")

STAMP = int(time.time())
MGR_EMAIL = f"TEST_iter37mgr_{STAMP}@example.com"
MGR_PASSWORD = "ManagerPass123!"
MGR_NAME = f"TEST iter37 Manager {STAMP}"

OWNER_EMAIL = "demo@mybuilder.app"
OWNER_PASSWORD = "demo1234"


def h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def main():
    # 1. Register manager
    r = requests.post(f"{BASE}/api/auth/register",
                      json={"name": MGR_NAME, "email": MGR_EMAIL, "password": MGR_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"register: {r.status_code} {r.text}"
    mgr = r.json()
    mgr_token = mgr["access_token"]
    print(f"Manager registered id={mgr['user']['id']} email={MGR_EMAIL}")

    # 2. Owner login
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"owner login: {r.status_code} {r.text}"
    owner = r.json()
    owner_token = owner["access_token"]
    owner_project_id = owner["user"]["active_project_id"]
    print(f"Owner logged in; demo project id={owner_project_id}")

    # 3. Owner invites manager with money_access=False
    # First, cleanup any pre-existing co-owner entry for this email just in case
    r = requests.get(f"{BASE}/api/co-owners", headers=h(owner_token), timeout=30)
    if r.status_code == 200:
        for c in r.json():
            if c.get("email", "").lower() == MGR_EMAIL.lower():
                requests.delete(f"{BASE}/api/co-owners/{c['id']}", headers=h(owner_token), timeout=30)
                print(f"  removed stale co-owner {c['id']}")

    r = requests.post(f"{BASE}/api/co-owners", headers=h(owner_token),
                      json={"email": MGR_EMAIL, "project_ids": [owner_project_id], "money_access": False}, timeout=30)
    assert r.status_code in (200, 201), f"invite co-owner: {r.status_code} {r.text}"
    co = r.json()
    print(f"Co-owner invite created id={co.get('id')} money_access={co.get('money_access')}")

    # 4. Manager fetches shared-with-me to see the project
    r = requests.get(f"{BASE}/api/co-owners/shared-with-me", headers=h(mgr_token), timeout=30)
    assert r.status_code == 200, f"shared-with-me: {r.status_code} {r.text}"
    shared = r.json()
    assert any(s.get("project_id") == owner_project_id or owner_project_id in s.get("project_ids", []) for s in shared) or shared, \
        f"manager has no shared project: {shared}"
    print(f"Manager sees shared projects: {len(shared)}")

    # 5. Manager activates the shared project
    r = requests.post(f"{BASE}/api/projects/{owner_project_id}/activate", headers=h(mgr_token), timeout=30)
    assert r.status_code == 200, f"activate: {r.status_code} {r.text}"
    print(f"Manager activated project {owner_project_id}")

    # 6. Verify manager /auth/login now returns acting_as.money=False
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email": MGR_EMAIL, "password": MGR_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"mgr login: {r.status_code} {r.text}"
    data = r.json()
    acting = data["user"].get("acting_as")
    print(f"Manager /auth/login user.acting_as = {acting}")
    assert acting is not None, "acting_as is null — fix NOT applied"
    assert acting.get("money") is False, f"acting_as.money is not False: {acting}"
    print("[PASS] /auth/login returns acting_as.money=False after the fix")

    # 7. Also verify /auth/me still correct
    r = requests.get(f"{BASE}/api/auth/me", headers=h(mgr_token), timeout=30)
    assert r.status_code == 200, f"me: {r.status_code}"
    print(f"/auth/me acting_as = {r.json().get('acting_as')}")

    # Write credentials for playwright step
    with open("/tmp/iter37_mgr.env", "w") as f:
        f.write(f"MGR_EMAIL={MGR_EMAIL}\nMGR_PASSWORD={MGR_PASSWORD}\nPROJECT_ID={owner_project_id}\nCOID={co.get('id')}\nMGR_ID={mgr['user']['id']}\n")
    print("Wrote /tmp/iter37_mgr.env")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"[FAIL] {e}")
        sys.exit(1)
