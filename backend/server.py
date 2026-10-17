from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware

from core import client, db, logger
from seed import seed_milestones
from storage import init_storage
import asyncio

from routes import (ai, auth, branding, budget, contacts, digest, documents, portal, email_settings, export, media, messages, ratings, milestones, payments, projects, quotes,
                    referrals, share, shopping, snags, stage_payments, trades, fx, planning, co_owners, activity, subscriptions, rentals)

app = FastAPI()
api = APIRouter(prefix="/api")

for m in (auth, projects, budget, contacts, media, ai, payments, trades, milestones, branding, referrals, share, quotes,
          stage_payments, snags, shopping, digest, export, messages, email_settings, ratings, documents, portal, fx, planning, co_owners, activity, subscriptions, rentals):
    api.include_router(m.router)


@api.get("/")
async def root():
    return {"message": "Builder Assist API"}


@app.get("/health")
@api.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(api)


@app.middleware("http")
async def activity_middleware(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/") and request.method != "GET":
        from routes.activity import log_write
        await log_write(request, response.status_code)
    return response


app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    # Migrate single-project data to multi-project: attach orphan docs to each user's first project
    async for u in db.users.find({}, {"_id": 1, "active_project_id": 1}):
        uid = str(u["_id"])
        first = await db.projects.find_one({"user_id": uid}, sort=[("_id", 1)])
        if not first:
            continue
        fpid = str(first["_id"])
        for coll in (db.line_items, db.contacts, db.receipts, db.media):
            await coll.update_many({"user_id": uid, "$or": [{"project_id": {"$exists": False}}, {"project_id": None}]}, {"$set": {"project_id": fpid}})
        if not u.get("active_project_id"):
            await db.users.update_one({"_id": u["_id"]}, {"$set": {"active_project_id": fpid}})
    async for pr in db.projects.find({}, {"_id": 1, "user_id": 1}):
        if not await db.milestones.find_one({"project_id": str(pr["_id"])}, {"_id": 1}):
            await seed_milestones(pr["user_id"], str(pr["_id"]))
    await db.quote_requests.create_index("quotes.token")
    for coll in (db.line_items, db.receipts, db.milestones, db.snags, db.stage_payments, db.shopping_items, db.media):
        await coll.create_index("project_id")
    await db.projects.create_index("user_id")
    await db.users.create_index("company_email_token", sparse=True)
    await db.documents.create_index([("user_id", 1), ("project_id", 1), ("created_at", -1)])
    await db.documents.create_index("share_token", sparse=True)
    await db.doc_folders.create_index("token", unique=True)
    await db.portal_handles.create_index("handle", unique=True)
    await db.portal_handles.create_index("email", unique=True)
    await db.portal_members.create_index([("email", 1), ("project_id", 1)])
    await db.portal_codes.create_index("email", unique=True)
    await db.trade_ratings.create_index([("user_id", 1), ("assignee_lc", 1)])
    await db.messages.create_index([("user_id", 1), ("project_id", 1), ("created_at", -1)])
    await db.projects.create_index("digest_token", sparse=True)
    await db.co_owners.create_index([("owner_id", 1), ("email", 1)], unique=True)
    await db.co_owners.create_index("email")
    await db.project_activity.create_index([("owner_id", 1), ("project_id", 1), ("at", -1)])
    for coll in (db.tenancies, db.rent_payments, db.rental_expenses):
        await coll.create_index([("user_id", 1), ("project_id", 1)])
    asyncio.create_task(digest.digest_scheduler())
    try:
        init_storage()
    except Exception as e:
        logger.error(f"Storage init failed: {e}")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
