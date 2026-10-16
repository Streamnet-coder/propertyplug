"""Co-owners: another Builder Assist account with full edit access to all of an owner's current and future projects.
Co-owners can't delete projects, manage the owner's billing, or remove the owner. Matching is by email, so an invite
works whether or not the person already has an account."""
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from core import E, db, logger, now_iso, oid
from deps import real_user
from email_service import EMAIL_FROM_NAME, EmailError, send_email
from models import User

router = APIRouter()
MAX_CO_OWNERS = 10


class CoOwnerIn(BaseModel):
    email: EmailStr


async def _out(c: dict) -> dict:
    u = await db.users.find_one({"email": c["email"]}, {"name": 1})
    return {"id": str(c["_id"]), "email": c["email"], "name": u["name"] if u else None, "has_account": bool(u), "invited_at": c["invited_at"]}


@router.get("/co-owners")
async def list_co_owners(user: User = Depends(real_user)):
    return [await _out(c) for c in await db.co_owners.find({"owner_id": user.id}).sort("invited_at", 1).to_list(MAX_CO_OWNERS)]


@router.post("/co-owners")
async def invite_co_owner(body: CoOwnerIn, user: User = Depends(real_user)):
    email = body.email.lower()
    if email == user.email:
        raise HTTPException(400, "You already own these projects")
    if await db.co_owners.find_one({"owner_id": user.id, "email": email}):
        raise HTTPException(400, "This person is already a co-owner")
    if await db.co_owners.count_documents({"owner_id": user.id}) >= MAX_CO_OWNERS:
        raise HTTPException(400, f"Up to {MAX_CO_OWNERS} co-owners")
    c = {"owner_id": user.id, "email": email, "invited_at": now_iso()}
    c["_id"] = (await db.co_owners.insert_one(c)).inserted_id
    has_account = bool(await db.users.find_one({"email": email}, {"_id": 1}))
    step = ("Open Builder Assist and sign in. The shared projects appear in <b>My projects</b>, marked with the owner's name."
            if has_account else f"Download Builder Assist and create an account with <b>{E(email)}</b>. The shared projects appear in <b>My projects</b>.")
    html = (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
            f'<h2 style="margin:0 0 12px">You\'re now a co-owner</h2><p>{E(user.name)} has made you a co-owner of all their {E(EMAIL_FROM_NAME)} projects. '
            f'You can view and edit budgets, snags, quotes, documents and everything else.</p><p>{step}</p></td></tr></table>')
    try:
        await send_email(to=email, subject=f"{user.name} made you a co-owner on {EMAIL_FROM_NAME}", html=html, reply_to=user.email)
        sent = True
    except EmailError as e:
        logger.warning(f"Co-owner invite email failed: {e}")
        sent = False
    return {**await _out(c), "email_sent": sent}


@router.delete("/co-owners/{cid}")
async def remove_co_owner(cid: str, user: User = Depends(real_user)):
    r = await db.co_owners.delete_one({"_id": oid(cid), "owner_id": user.id})
    if not r.deleted_count:
        raise HTTPException(404, "Not found")
    return {"ok": True}


@router.get("/co-owners/shared-with-me")
async def shared_with_me(user: User = Depends(real_user)):
    out = []
    async for c in db.co_owners.find({"email": user.email}):
        o = await db.users.find_one({"_id": ObjectId(c["owner_id"])}, {"name": 1, "email": 1})
        if o:
            out.append({"owner_id": c["owner_id"], "owner_name": o["name"], "owner_email": o["email"], "since": c["invited_at"],
                        "projects": await db.projects.count_documents({"user_id": c["owner_id"]})})
    return out


@router.delete("/co-owners/shared/{owner_id}")
async def leave(owner_id: str, user: User = Depends(real_user)):
    r = await db.co_owners.delete_one({"owner_id": owner_id, "email": user.email})
    if not r.deleted_count:
        raise HTTPException(404, "Not found")
    if user.acting_owner_id == owner_id:
        await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"acting_owner_id": None, "active_project_id": None}})
    return {"ok": True}
