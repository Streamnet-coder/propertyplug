from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import Response
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime, timezone
import uuid
from core import db, now_iso, oid, bearer, APP_NAME
from models import User, Media
from deps import current_user, decode_uid, active_pid
from storage import put_object, get_object

router = APIRouter()


@router.post("/upload")
async def upload(file: UploadFile = File(...), user: User = Depends(current_user)):
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 10MB)")
    ext = (file.filename or "img.jpg").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "jpg"
    path = f"{APP_NAME}/uploads/{user.id}/{uuid.uuid4()}.{ext}"
    ctype = file.content_type or "image/jpeg"
    result = await run_in_threadpool(put_object, path, data, ctype)
    await db.files.insert_one({"storage_path": result["path"], "owner_id": user.id, "content_type": ctype,
                               "original_filename": file.filename, "is_deleted": False, "created_at": now_iso()})
    return {"path": result["path"]}


@router.get("/files/{path:path}")
async def download(path: str, token: Optional[str] = None, cred: HTTPAuthorizationCredentials = Depends(bearer)):
    raw = cred.credentials if cred else token
    if not raw:
        raise HTTPException(401, "Not authenticated")
    uid = decode_uid(raw)
    rec = await db.files.find_one({"storage_path": path, "owner_id": uid, "is_deleted": False})
    if not rec:
        raise HTTPException(404, "File not found")
    data, ctype = await run_in_threadpool(get_object, path)
    return Response(content=data, media_type=rec.get("content_type", ctype), headers={"Cache-Control": "private, max-age=86400"})


class MediaIn(BaseModel):
    title: str
    phase: Literal["before", "progress", "after"] = "progress"
    storage_path: Optional[str] = None
    url: Optional[str] = None
    date: Optional[str] = None
    milestone_id: Optional[str] = None


@router.get("/media")
async def list_media(user: User = Depends(current_user)):
    docs = await db.media.find({"user_id": user.id, "project_id": await active_pid(user)}).sort("created_at", -1).to_list(1000)
    return [Media.from_mongo(d).out() for d in docs]


@router.post("/media")
async def create_media(body: MediaIn, user: User = Depends(current_user)):
    m = Media(user_id=user.id, project_id=await active_pid(user), title=body.title, phase=body.phase, storage_path=body.storage_path, url=body.url,
              milestone_id=body.milestone_id or None,
              date=body.date or datetime.now(timezone.utc).date().isoformat())
    res = await db.media.insert_one(m.to_mongo())
    m.id = str(res.inserted_id)
    return m.out()


@router.delete("/media/{mid}")
async def delete_media(mid: str, user: User = Depends(current_user)):
    await db.media.delete_one({"_id": oid(mid), "user_id": user.id})
    return {"ok": True}
