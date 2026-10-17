from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr, Field
from typing import Literal
from bson import ObjectId
import bcrypt
import time
from core import db
from models import User
from deps import current_user, effective, real_user, user_out, make_token
from seed import create_user

router = APIRouter()


class RegisterIn(BaseModel):
    name: str
    email: EmailStr
    password: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str


@router.post("/auth/register")
async def register(body: RegisterIn):
    u = await create_user(body.name, body.email, body.password)
    return {"access_token": make_token(u.id), "user": user_out(u)}


@router.post("/auth/login")
async def login(body: LoginIn):
    u = User.from_mongo(await db.users.find_one({"email": body.email.lower()}))
    if not u or not bcrypt.checkpw(body.password.encode(), u.password_hash.encode()):
        raise HTTPException(401, "Incorrect email or password")
    return {"access_token": make_token(u.id), "user": user_out(u)}


@router.get("/auth/me")
async def me(user: User = Depends(real_user)):
    return user_out(user, await effective(user))


class DeleteAccountIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


_failed: dict = {}  # uid -> [timestamps of failed confirmations]
USER_COLLECTIONS = ("line_items", "contacts", "receipts", "media", "milestones", "quote_requests", "stage_payments",
                    "snags", "snag_links", "snag_signoffs", "messages", "trade_ratings", "documents", "doc_folders", "shopping_items", "estimates", "payment_transactions", "planning_apps", "tenancies", "rent_payments", "rental_expenses", "rent_reminders", "compare_links", "projects")


@router.delete("/auth/account")
async def delete_account(body: DeleteAccountIn, user: User = Depends(real_user)):
    now = time.time()
    recent = [t for t in _failed.get(user.id, []) if now - t < 900]
    if len(recent) >= 5:
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes")
    if not bcrypt.checkpw(body.password.encode(), user.password_hash.encode()):
        _failed[user.id] = recent + [now]
        raise HTTPException(401, "Password confirmation failed")
    _failed.pop(user.id, None)
    for name in USER_COLLECTIONS:
        await db[name].delete_many({"user_id": user.id})
    await db.files.delete_many({"owner_id": user.id})
    await db.referrals.delete_many({"$or": [{"referrer_id": user.id}, {"new_user_id": user.id}]})
    for coll in (db.portal_members, db.portal_activity, db.portal_questions, db.project_activity, db.portal_doc_requests):
        await coll.delete_many({"owner_id": user.id})
    await db.co_owners.delete_many({"$or": [{"owner_id": user.id}, {"email": user.email}]})
    # User doc last so a failed run can be retried with the same token
    await db.users.delete_one({"_id": ObjectId(user.id)})
    return {"ok": True}


class PlanIn(BaseModel):
    plan: Literal["basic", "pro"]


@router.post("/auth/plan")
async def set_plan(body: PlanIn, user: User = Depends(real_user)):
    await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"plan": body.plan}})
    user.plan = body.plan
    return user_out(user, await effective(user))
