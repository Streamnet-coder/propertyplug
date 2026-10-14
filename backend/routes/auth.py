from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from typing import Literal
from bson import ObjectId
import bcrypt
from core import db
from models import User
from deps import current_user, user_out, make_token
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
async def me(user: User = Depends(current_user)):
    return user_out(user)


class PlanIn(BaseModel):
    plan: Literal["basic", "pro"]


@router.post("/auth/plan")
async def set_plan(body: PlanIn, user: User = Depends(current_user)):
    await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"plan": body.plan}})
    user.plan = body.plan
    return user_out(user)
