from fastapi import HTTPException, Depends
from fastapi.security import HTTPAuthorizationCredentials
from datetime import datetime, timezone, timedelta
from bson import ObjectId
import jwt
from core import db, bearer, JWT_SECRET
from models import User, Project


def make_token(uid: str, minutes: int = 60 * 24 * 7) -> str:
    n = datetime.now(timezone.utc)
    return jwt.encode({"sub": uid, "iat": n, "exp": n + timedelta(minutes=minutes)}, JWT_SECRET, algorithm="HS256")


def decode_uid(token: str) -> str:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")


async def load_user(uid: str) -> User:
    try:
        doc = await db.users.find_one({"_id": ObjectId(uid)})
    except Exception:
        doc = None
    if not doc:
        raise HTTPException(401, "User not found")
    u = User.from_mongo(doc)
    # Monthly/yearly Pro passes lapse back to Basic; lifetime never does.
    if u.plan == "pro" and u.pro_tier in ("monthly", "yearly") and u.pro_until and u.pro_until < datetime.now(timezone.utc).isoformat():
        from routes.subscriptions import refresh_if_lapsed
        if await refresh_if_lapsed(u):  # auto-renewed on Stripe: reload the new period
            return User.from_mongo(await db.users.find_one({"_id": doc["_id"]}))
        await db.users.update_one({"_id": doc["_id"]}, {"$set": {"plan": "basic"}})
        u.plan = "basic"
    return u


async def real_user(cred: HTTPAuthorizationCredentials = Depends(bearer)) -> User:
    """The signed-in person themselves (billing, account, project list, co-owner management)."""
    if not cred:
        raise HTTPException(401, "Not authenticated")
    return await load_user(decode_uid(cred.credentials))


async def effective(u: User) -> User:
    """When a co-owner has a shared project open, act as that project's owner so every data route works unchanged.
    The returned owner object keeps the co-owner's own active project and remembers who is really signed in (real_id)."""
    if not u.acting_owner_id or u.acting_owner_id == u.id:
        return u
    share = await db.co_owners.find_one({"owner_id": u.acting_owner_id, "email": u.email})
    if share and share.get("project_ids") is not None:
        # Manager: only the chosen projects. Keep the open one if allowed, else switch to the first allowed that still exists.
        allowed = [p for p in share["project_ids"] if ObjectId.is_valid(p)]
        ok = [str(d["_id"]) async for d in db.projects.find({"_id": {"$in": [ObjectId(p) for p in allowed]}, "user_id": u.acting_owner_id}, {"_id": 1})]
        if not ok:
            share = None
        elif u.active_project_id not in ok:
            u.active_project_id = ok[0]
            await db.users.update_one({"_id": ObjectId(u.id)}, {"$set": {"active_project_id": ok[0]}})
    if share:
        try:
            owner = await load_user(u.acting_owner_id)
        except HTTPException:
            owner = None
        if owner:
            owner.active_project_id, owner.real_id, owner.real_name = u.active_project_id, u.id, u.name
            return owner
    # Access was removed: fall back to their own projects.
    await db.users.update_one({"_id": ObjectId(u.id)}, {"$set": {"acting_owner_id": None, "active_project_id": None}})
    u.acting_owner_id = u.active_project_id = None
    return u


async def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer)) -> User:
    return await effective(await real_user(cred))


async def user_from_token(raw: str) -> User:
    return await effective(await load_user(decode_uid(raw)))


async def pro_user(user: User = Depends(current_user)) -> User:
    if user.plan != "pro":
        raise HTTPException(403, "Pro plan required")
    return user


def user_out(u: User, eff: User | None = None):
    """eff = the effective (possibly owner) user: plan follows the project owner on shared projects."""
    eff = eff or u
    return {"id": u.id, "name": u.name, "email": u.email, "plan": eff.plan, "own_plan": u.plan, "paid_pro": u.paid_pro, "trial_ends": u.trial_ends,
            "pro_tier": u.pro_tier, "pro_until": u.pro_until, "active_project_id": u.active_project_id,
            "auto_renew": bool(u.stripe_subscription_id and u.sub_status in ("active", "trialing", "past_due") and not u.cancel_at_period_end and u.pro_tier != "lifetime"),
            "has_subscription": bool(u.stripe_subscription_id and u.sub_status in ("active", "trialing", "past_due") and u.pro_tier != "lifetime"),
            "sub_status": u.sub_status,
            "acting_as": {"owner_id": eff.id, "owner_name": eff.name} if eff.id != u.id else None}


async def active_pid(user: User) -> str:
    if user.active_project_id and ObjectId.is_valid(user.active_project_id) and await db.projects.find_one(
            {"_id": ObjectId(user.active_project_id), "user_id": user.id}, {"_id": 1}):
        return user.active_project_id
    doc = await db.projects.find_one({"user_id": user.id}, sort=[("_id", 1)])
    if not doc:
        raise HTTPException(404, "Project not found")
    pid = str(doc["_id"])
    await db.users.update_one({"_id": ObjectId(user.real_id or user.id)}, {"$set": {"active_project_id": pid}})
    user.active_project_id = pid
    return pid


async def get_project_doc(user: User) -> Project:
    pid = await active_pid(user)
    return Project.from_mongo(await db.projects.find_one({"_id": ObjectId(pid)}))
