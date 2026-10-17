"""Cleanup iter50: reset demo cover_path to null, delete any TEST_ co-owners/splits/payouts
for the demo project, and delete the delivered@resend.dev co-owner if lingering."""
import os
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://dev-budget-tracker-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"


def main():
    r = requests.post(f"{API}/auth/login", json={"email": "demo@mybuilder.app", "password": "demo1234"}, timeout=20)
    r.raise_for_status()
    tok = r.json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}

    # Clear cover
    r = requests.put(f"{API}/project/cover", headers=h, json={"storage_path": None}, timeout=20)
    print("cover reset:", r.status_code, r.json())

    # Delete all payouts for all co-owners of active project
    r = requests.get(f"{API}/project/payouts", headers=h, timeout=20)
    if r.status_code == 200:
        people = r.json().get("people", [])
        for p in people:
            for x in p.get("payouts", []):
                dr = requests.delete(f"{API}/project/payouts/{x['id']}", headers=h, timeout=10)
                print(f"  payout del {x['id']}: {dr.status_code}")

    # Clear split
    r = requests.put(f"{API}/project/split", headers=h, json={"shares": {}, "contributions": {}}, timeout=20)
    print("split cleared:", r.status_code)

    # Delete all co-owners whose email starts with TEST_ or is delivered@resend.dev
    r = requests.get(f"{API}/co-owners", headers=h, timeout=20)
    if r.status_code == 200:
        for c in r.json():
            em = c.get("email", "")
            if em.startswith("TEST_") or em == "delivered@resend.dev":
                dr = requests.delete(f"{API}/co-owners/{c['id']}", headers=h, timeout=10)
                print(f"  co-owner del {em}: {dr.status_code}")


if __name__ == "__main__":
    main()
