"""Iter49 cleanup: remove TEST_ users, their projects, leftover co_owners, splits, and clear demo cover."""
import asyncio
import sys
sys.path.insert(0, "/app/backend")
from core import db


async def main():
    # Demo project: clear cover_path
    demo = await db.users.find_one({"email": "demo@mybuilder.app"})
    if demo:
        await db.projects.update_many({"user_id": str(demo["_id"])}, {"$set": {"cover_path": None}})

    # Find test users
    test_users = [u async for u in db.users.find({"email": {"$regex": "^TEST_", "$options": "i"}})]
    print(f"deleting {len(test_users)} TEST_ users")
    uids = [str(u["_id"]) for u in test_users]
    emails = [u["email"] for u in test_users]

    # Delete their data
    collections = ["projects", "line_items", "contacts", "receipts", "media", "milestones", "quote_requests",
                   "stage_payments", "snags", "snag_links", "snag_signoffs", "messages", "trade_ratings",
                   "documents", "doc_folders", "shopping_items", "estimates", "payment_transactions",
                   "planning_apps", "tenancies", "rent_payments", "rental_expenses", "rent_reminders",
                   "rent_statements", "compare_links", "files", "ownership_shares", "coowner_payouts",
                   "coowner_statements"]
    for c in collections:
        r = await db[c].delete_many({"$or": [{"user_id": {"$in": uids}}, {"owner_id": {"$in": uids}}]})
        if r.deleted_count:
            print(f"  {c}: {r.deleted_count}")

    # Remove co_owners referencing test emails
    r = await db.co_owners.delete_many({"email": {"$in": emails}})
    print(f"co_owners by test emails: {r.deleted_count}")
    # Remove co_owners docs owned by test users
    r = await db.co_owners.delete_many({"owner_id": {"$in": uids}})
    print(f"co_owners by test users: {r.deleted_count}")
    # Remove any leftover invite links from test users
    r = await db.co_owner_links.delete_many({"owner_id": {"$in": uids}})
    print(f"co_owner_links: {r.deleted_count}")

    # Delete the users
    r = await db.users.delete_many({"_id": {"$in": [u["_id"] for u in test_users]}})
    print(f"users deleted: {r.deleted_count}")

    # Also clear demo project's ownership_shares (we didn't touch it, but just in case)
    if demo:
        pids = [str(p["_id"]) async for p in db.projects.find({"user_id": str(demo["_id"])}, {"_id": 1})]
        for pid in pids:
            await db.ownership_shares.delete_many({"project_id": pid})
            await db.coowner_payouts.delete_many({"project_id": pid})
        # Remove any demo co_owners/links we created during tests
        r = await db.co_owners.delete_many({"owner_id": str(demo["_id"])})
        print(f"demo co_owners cleaned: {r.deleted_count}")
        r = await db.co_owner_links.delete_many({"owner_id": str(demo["_id"])})
        print(f"demo co_owner_links cleaned: {r.deleted_count}")

    print("Cleanup done.")


asyncio.run(main())
