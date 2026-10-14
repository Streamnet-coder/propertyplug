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
    return User.from_mongo(doc)


async def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer)) -> User:
    if not cred:
        raise HTTPException(401, "Not authenticated")
    return await load_user(decode_uid(cred.credentials))


async def pro_user(user: User = Depends(current_user)) -> User:
    if user.plan != "pro":
        raise HTTPException(403, "Pro plan required")
    return user


def user_out(u: User):
    return {"id": u.id, "name": u.name, "email": u.email, "plan": u.plan, "paid_pro": u.paid_pro, "trial_ends": u.trial_ends,
            "active_project_id": u.active_project_id}


async def active_pid(user: User) -> str:
    if user.active_project_id and ObjectId.is_valid(user.active_project_id) and await db.projects.find_one(
            {"_id": ObjectId(user.active_project_id), "user_id": user.id}, {"_id": 1}):
        return user.active_project_id
    doc = await db.projects.find_one({"user_id": user.id}, sort=[("_id", 1)])
    if not doc:
        raise HTTPException(404, "Project not found")
    pid = str(doc["_id"])
    await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"active_project_id": pid}})
    user.active_project_id = pid
    return pid


async def get_project_doc(user: User) -> Project:
    pid = await active_pid(user)
    return Project.from_mongo(await db.projects.find_one({"_id": ObjectId(pid)}))
