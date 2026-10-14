"""Safe test-data cleanup: only ever deletes data owned by TEST_-prefixed users/records."""
import os
from pymongo import MongoClient
from bson import ObjectId

USER_COLLECTIONS = ("line_items", "contacts", "receipts", "media", "milestones",
                    "quote_requests", "projects", "snags", "stage_payments", "snag_links")


def get_db():
    cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    return cli, cli[os.environ.get("DB_NAME", "test_database")]


def is_test_email(email):
    return (email or "").lower().startswith("test_")


def delete_test_user(uid):
    """Delete a user and all their data ONLY if their email is TEST_-prefixed."""
    cli, db = get_db()
    try:
        u = db.users.find_one({"_id": ObjectId(uid)}, {"email": 1})
        if not u or not is_test_email(u.get("email")):
            print(f"refusing to clean up non-test user {uid}")
            return
        for coll in USER_COLLECTIONS:
            db[coll].delete_many({"user_id": uid})
        db.referrals.delete_many({"new_user_id": uid})
        db.users.delete_one({"_id": ObjectId(uid)})
    finally:
        cli.close()
