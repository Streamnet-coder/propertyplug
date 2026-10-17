"""Deeper cleanup: remove any iter45* / iter44* users, co_owners, co_owner_links, projects, ownership_shares."""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os

async def main():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ["DB_NAME"]]
    pats = [{"$regex": "iter45"}, {"$regex": "iter44"}, {"$regex": "iter43"}]
    for pat in pats:
        r = await db.co_owners.delete_many({"email": pat})
        print("co_owners", pat, r.deleted_count)
        r = await db.co_owner_links.delete_many({"token": pat})
        print("co_owner_links", pat, r.deleted_count)
        # Delete users
        users = await db.users.find({"email": pat}, {"_id": 1, "email": 1}).to_list(100)
        for u in users:
            uid = str(u["_id"])
            await db.projects.delete_many({"user_id": uid})
            await db.co_owners.delete_many({"owner_id": uid})
            await db.users.delete_one({"_id": u["_id"]})
            print("deleted user+projects", u["email"])
    # Orphan ownership_shares: drop those whose project no longer exists
    all_pids = {str(p["_id"]) async for p in db.projects.find({}, {"_id": 1})}
    cur = db.ownership_shares.find({})
    async for s in cur:
        if s.get("project_id") not in all_pids:
            await db.ownership_shares.delete_one({"_id": s["_id"]})
            print("orphan ownership_shares removed", s.get("project_id"))

asyncio.run(main())
