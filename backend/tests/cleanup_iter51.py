"""Iter 51 cleanup: delete TEST-created line items from choose flow, reset all estimates to chosen=false/added_items=[], and reset notify_prefs to all true for the demo user."""
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")

import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://dev-budget-tracker-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"
DEMO = ("demo@mybuilder.app", "demo1234")


async def main():
    r = requests.post(f"{API}/auth/login", json={"email": DEMO[0], "password": DEMO[1]}, timeout=20)
    r.raise_for_status()
    j = r.json()
    tok = j["access_token"]
    uid = j["user"]["id"]
    hdrs = {"Authorization": f"Bearer {tok}"}

    cli = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = cli[os.environ.get("DB_NAME", "test_database")]

    # Gather item names on this user's estimates to help identify line items from choose
    names = set()
    async for est in db.estimates.find({"user_id": uid}):
        for it in (est.get("result") or {}).get("items", []):
            if it.get("name"):
                names.add(it["name"][:120])

    today = datetime.now(timezone.utc).date().isoformat()
    deleted = 0
    # delete line items with actual=0, name in names, created today
    async for li in db.line_items.find({"user_id": uid, "actual": 0}):
        created = (li.get("created_at") or "")[:10]
        if created == today and li.get("name") in names:
            await db.line_items.delete_one({"_id": li["_id"]})
            deleted += 1
    print(f"deleted {deleted} line_items created today matching estimate items")

    # Reset estimates
    rres = await db.estimates.update_many(
        {"user_id": uid},
        {"$set": {"chosen": False, "added_items": []}, "$unset": {"chosen_at": ""}},
    )
    print(f"reset {rres.modified_count} estimates")

    # Reset notify prefs
    ures = await db.users.update_one(
        {"email": DEMO[0]},
        {"$set": {"notify_prefs": {"repairs": True, "jobs": True, "fixed": True, "payouts": True, "invites": True}}},
    )
    print(f"notify_prefs reset matched={ures.matched_count}")

    cli.close()


if __name__ == "__main__":
    asyncio.run(main())
