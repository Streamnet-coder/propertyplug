"""Cleanup iteration 37 test data."""
import os
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://dev-budget-tracker-2.preview.emergentagent.com").rstrip("/")

env = {}
with open("/tmp/iter37_mgr.env") as f:
    for line in f:
        k, v = line.strip().split("=", 1)
        env[k] = v

def h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

# Owner login & remove co-owner entry
r = requests.post(f"{BASE}/api/auth/login", json={"email": "demo@mybuilder.app", "password": "demo1234"})
owner_token = r.json()["access_token"]

r = requests.get(f"{BASE}/api/co-owners", headers=h(owner_token))
removed = 0
for c in r.json():
    if "TEST_iter37" in c.get("email", "") or c.get("id") == env.get("COID"):
        dr = requests.delete(f"{BASE}/api/co-owners/{c['id']}", headers=h(owner_token))
        print(f"  deleted co-owner {c['id']} email={c.get('email')} -> {dr.status_code}")
        removed += 1
print(f"Co-owners removed: {removed}")

# Manager delete account
mr = requests.post(f"{BASE}/api/auth/login", json={"email": env["MGR_EMAIL"], "password": env["MGR_PASSWORD"]})
if mr.status_code == 200:
    mgr_token = mr.json()["access_token"]
    dr = requests.delete(f"{BASE}/api/auth/account", headers=h(mgr_token),
                         json={"password": env["MGR_PASSWORD"]})
    print(f"Delete manager account -> {dr.status_code} {dr.text[:120]}")
else:
    print(f"Manager login failed: {mr.status_code}")

# Reactivate owner's demo project
r = requests.post(f"{BASE}/api/projects/{env['PROJECT_ID']}/activate", headers=h(owner_token))
print(f"Reactivated demo project for owner -> {r.status_code}")

# Verify owner /auth/me
r = requests.get(f"{BASE}/api/auth/me", headers=h(owner_token))
print(f"Owner active_project_id = {r.json().get('active_project_id')}")
