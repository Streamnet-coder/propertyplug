from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from core import db
from models import Branding, User
from deps import current_user
from html_utils import serve_logo

router = APIRouter()


@router.get("/branding")
async def get_branding(user: User = Depends(current_user)):
    return user.branding.model_dump()


@router.put("/branding")
async def put_branding(body: Branding, user: User = Depends(current_user)):
    if body.logo_path and not await db.files.find_one({"storage_path": body.logo_path, "owner_id": user.id}):
        raise HTTPException(400, "Invalid logo")
    await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"branding": body.model_dump()}})
    return body.model_dump()


@router.get("/share/{token}/logo")
async def share_logo(token: str):
    doc = await db.projects.find_one({"share_token": token}) if token else None
    if not doc:
        raise HTTPException(404, "Not found")
    return await serve_logo(doc["user_id"])
