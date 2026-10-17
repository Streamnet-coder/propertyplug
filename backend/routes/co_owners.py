"""Co-owners: another PropertyPlug account with full edit access to all of an owner's current and future projects.
Co-owners can't delete projects, manage the owner's billing, or remove the owner. Matching is by email, so an invite
works whether or not the person already has an account."""
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

from core import E, db, logger, now_iso, oid
from deps import real_user
from email_service import EMAIL_FROM_NAME, EmailError, send_email
from models import User

router = APIRouter()
MAX_CO_OWNERS = 10


class CoOwnerIn(BaseModel):
    email: EmailStr
    project_ids: Optional[List[str]] = Field(None, max_length=200)  # None = co-owner of everything; list = manager of those projects
    money_access: bool = True


class ScopeIn(BaseModel):
    project_ids: Optional[List[str]] = Field(None, max_length=200)
    money_access: bool = True


async def _check_pids(owner_id: str, pids: Optional[List[str]]) -> Optional[List[str]]:
    if pids is None:
        return None
    pids = list(dict.fromkeys(pids))
    if not pids:
        raise HTTPException(400, "Pick at least one project for the manager")
    n = await db.projects.count_documents({"_id": {"$in": [oid(p) for p in pids]}, "user_id": owner_id})
    if n != len(pids):
        raise HTTPException(404, "Project not found")
    return pids


async def _out(c: dict) -> dict:
    u = await db.users.find_one({"email": c["email"]}, {"name": 1})
    pids = c.get("project_ids")
    names = [p["name"] async for p in db.projects.find({"_id": {"$in": [oid(i) for i in pids]}}, {"name": 1})] if pids is not None else None
    return {"id": str(c["_id"]), "email": c["email"], "name": u["name"] if u else None, "has_account": bool(u), "invited_at": c["invited_at"],
            "role": "co_owner" if pids is None else "manager", "project_ids": pids, "project_names": names,
            "money_access": c.get("money_access", True) is not False}


@router.get("/co-owners")
async def list_co_owners(user: User = Depends(real_user)):
    return [await _out(c) for c in await db.co_owners.find({"owner_id": user.id}).sort("invited_at", 1).to_list(MAX_CO_OWNERS)]


@router.post("/co-owners")
async def invite_co_owner(body: CoOwnerIn, user: User = Depends(real_user)):
    email = body.email.lower()
    if email == user.email:
        raise HTTPException(400, "You already own these projects")
    if await db.co_owners.find_one({"owner_id": user.id, "email": email}):
        raise HTTPException(400, "This person already has access. Change their projects instead")
    if await db.co_owners.count_documents({"owner_id": user.id}) >= MAX_CO_OWNERS:
        raise HTTPException(400, f"Up to {MAX_CO_OWNERS} co-owners and managers")
    pids = await _check_pids(user.id, body.project_ids)
    c = {"owner_id": user.id, "email": email, "invited_at": now_iso(), "project_ids": pids, "money_access": body.money_access}
    c["_id"] = (await db.co_owners.insert_one(c)).inserted_id
    has_account = bool(await db.users.find_one({"email": email}, {"_id": 1}))
    step = ("Open PropertyPlug and sign in. The shared projects appear in <b>My projects</b>, marked with the owner's name."
            if has_account else f"Download PropertyPlug and create an account with <b>{E(email)}</b>. The shared projects appear in <b>My projects</b>.")
    out = await _out(c)
    what = (f"a co-owner of all their {E(EMAIL_FROM_NAME)} projects" if pids is None
            else f"manager of {'the project' if len(pids) == 1 else 'these projects'} <b>{E(', '.join(out['project_names']))}</b> on {E(EMAIL_FROM_NAME)}")
    title = "You're now a co-owner" if pids is None else "You're now a project manager"
    html = (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
            f'<h2 style="margin:0 0 12px">{title}</h2><p>{E(user.name)} has made you {what}. '
            + ('You can view and edit budgets, snags, quotes, documents, tenancies and everything else.' if body.money_access else
               'You can manage day-to-day work: timeline, snags, photos, documents, team and messages. Budgets, rent and other money figures are kept private.')
            + f'</p><p>{step}</p></td></tr></table>')
    try:
        await send_email(to=email, subject=f"{user.name} made you a {'co-owner' if pids is None else 'project manager'} on {EMAIL_FROM_NAME}", html=html, reply_to=user.email)
        sent = True
    except EmailError as e:
        logger.warning(f"Co-owner invite email failed: {e}")
        sent = False
    return {**out, "email_sent": sent}


@router.put("/co-owners/{cid}")
async def change_scope(cid: str, body: ScopeIn, user: User = Depends(real_user)):
    pids = await _check_pids(user.id, body.project_ids)
    r = await db.co_owners.update_one({"_id": oid(cid), "owner_id": user.id}, {"$set": {"project_ids": pids, "money_access": body.money_access}})
    if not r.matched_count:
        raise HTTPException(404, "Not found")
    return await _out(await db.co_owners.find_one({"_id": oid(cid)}))


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
            pids = c.get("project_ids")
            q = {"user_id": c["owner_id"]} if pids is None else {"user_id": c["owner_id"], "_id": {"$in": [oid(i) for i in pids]}}
            out.append({"owner_id": c["owner_id"], "owner_name": o["name"], "owner_email": o["email"], "since": c["invited_at"],
                        "role": "co_owner" if pids is None else "manager", "projects": await db.projects.count_documents(q),
                        "money_access": c.get("money_access", True) is not False})
    return out


@router.delete("/co-owners/shared/{owner_id}")
async def leave(owner_id: str, user: User = Depends(real_user)):
    r = await db.co_owners.delete_one({"owner_id": owner_id, "email": user.email})
    if not r.deleted_count:
        raise HTTPException(404, "Not found")
    if user.acting_owner_id == owner_id:
        await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"acting_owner_id": None, "active_project_id": None}})
    return {"ok": True}


# ---------- Shareable invite links (one person, 7 days, cancellable) ----------
import secrets  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

LINK_DAYS = 7


class LinkIn(BaseModel):
    project_ids: Optional[List[str]] = Field(None, max_length=200)
    money_access: bool = True


async def _link_out(d: dict) -> dict:
    pids = d.get("project_ids")
    names = [p["name"] async for p in db.projects.find({"_id": {"$in": [oid(i) for i in pids]}}, {"name": 1})] if pids is not None else None
    return {"id": str(d["_id"]), "token": d["token"], "role": "co_owner" if pids is None else "manager", "project_ids": pids, "project_names": names,
            "money_access": d.get("money_access", True), "expires_at": d["expires_at"], "created_at": d["created_at"]}


def _active_link_q() -> dict:
    return {"used_at": None, "expires_at": {"$gt": now_iso()}}


@router.get("/co-owner-links")
async def list_links(user: User = Depends(real_user)):
    return [await _link_out(d) async for d in db.co_owner_links.find({"owner_id": user.id, **_active_link_q()}).sort("created_at", -1)]


@router.post("/co-owner-links")
async def create_link(body: LinkIn, user: User = Depends(real_user)):
    if await db.co_owners.count_documents({"owner_id": user.id}) >= MAX_CO_OWNERS:
        raise HTTPException(400, f"Up to {MAX_CO_OWNERS} co-owners and managers")
    if await db.co_owner_links.count_documents({"owner_id": user.id, **_active_link_q()}) >= 20:
        raise HTTPException(400, "Too many open invite links. Cancel some first")
    pids = await _check_pids(user.id, body.project_ids)
    d = {"owner_id": user.id, "token": secrets.token_urlsafe(18), "project_ids": pids, "money_access": body.money_access, "used_at": None,
         "expires_at": (datetime.now(timezone.utc) + timedelta(days=LINK_DAYS)).isoformat(), "created_at": now_iso()}
    d["_id"] = (await db.co_owner_links.insert_one(d)).inserted_id
    return await _link_out(d)


@router.delete("/co-owner-links/{lid}")
async def cancel_link(lid: str, user: User = Depends(real_user)):
    await db.co_owner_links.delete_one({"_id": oid(lid), "owner_id": user.id})
    return {"ok": True}


async def _usable(token: str) -> dict:
    d = await db.co_owner_links.find_one({"token": token}) if token else None
    if not d:
        raise HTTPException(404, "This invite link isn't valid. Ask for a new one")
    if d.get("used_at"):
        raise HTTPException(410, "This invite link has already been used. Ask for a new one")
    if d["expires_at"] <= now_iso():
        raise HTTPException(410, "This invite link has expired. Ask for a new one")
    return d


@router.get("/join/{token}")
async def link_info(token: str):
    """Public preview of an invite link (no login) so the app can show who is inviting and to what."""
    d = await _usable(token)
    owner = await db.users.find_one({"_id": ObjectId(d["owner_id"])}, {"name": 1}) or {}
    out = await _link_out(d)
    return {"owner_name": owner.get("name", "A PropertyPlug user"), "role": out["role"], "project_names": out["project_names"],
            "money_access": out["money_access"], "expires_at": out["expires_at"]}


@router.post("/join/{token}")
async def accept_link(token: str, user: User = Depends(real_user)):
    d = await _usable(token)
    if d["owner_id"] == user.id:
        raise HTTPException(400, "This is your own invite link. Share it with the person you want to add")
    if await db.co_owners.find_one({"owner_id": d["owner_id"], "email": user.email}):
        raise HTTPException(400, "You already have access to these projects")
    # Claim atomically so a link can only ever be used once.
    claimed = await db.co_owner_links.update_one({"_id": d["_id"], "used_at": None}, {"$set": {"used_at": now_iso(), "used_by": user.email}})
    if not claimed.modified_count:
        raise HTTPException(410, "This invite link has already been used. Ask for a new one")
    await db.co_owners.insert_one({"owner_id": d["owner_id"], "email": user.email, "invited_at": now_iso(), "project_ids": d.get("project_ids"),
                                   "money_access": d.get("money_access", True), "via_link": True})
    owner = await db.users.find_one({"_id": ObjectId(d["owner_id"])}, {"name": 1, "email": 1}) or {}
    if owner.get("email"):
        try:
            await send_email(to=owner["email"], subject=f"{user.name} joined your projects on {EMAIL_FROM_NAME}",
                             html=f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
                                  f'<p><b>{E(user.name)}</b> ({E(user.email)}) used your invite link and now has '
                                  f'{"co-owner access to all your projects" if d.get("project_ids") is None else "manager access to the projects you chose"}'
                                  f'{"" if d.get("money_access", True) else " (tasks only, no money)"}.</p><p>You can change or remove their access any time in Profile → Co-owners &amp; managers.</p></td></tr></table>',
                             reply_to=user.email)
        except Exception as e:
            logger.warning(f"Join notification failed: {e}")
    return {"ok": True, "owner_name": owner.get("name"), "owner_id": d["owner_id"]}
