from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import Response, HTMLResponse, RedirectResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from typing import Optional, Literal
from bson import ObjectId
import re, uuid, secrets
from core import db, now_iso, oid, E, APP_NAME
from models import User, Snag
from deps import current_user, active_pid
from storage import put_object, get_object
from html_utils import page, owner_branding, brand_block, serve_logo

router = APIRouter()


class SnagIn(BaseModel):
    room: str
    description: str
    priority: Literal["low", "medium", "high"] = "medium"
    storage_path: Optional[str] = None
    assignee: str = ""


class SnagUpdate(BaseModel):
    room: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[Literal["low", "medium", "high"]] = None
    status: Optional[Literal["open", "fixed"]] = None
    assignee: Optional[str] = None


@router.get("/snags")
async def list_snags(user: User = Depends(current_user)):
    docs = await db.snags.find({"user_id": user.id, "project_id": await active_pid(user)}).sort("created_at", -1).to_list(1000)
    return [Snag.from_mongo(d).out() for d in docs]


@router.post("/snags")
async def create_snag(body: SnagIn, user: User = Depends(current_user)):
    if not body.room.strip() or not body.description.strip():
        raise HTTPException(400, "Room and description are required")
    s = Snag(user_id=user.id, project_id=await active_pid(user), **{**body.model_dump(), "room": body.room.strip(), "description": body.description.strip()})
    s.id = str((await db.snags.insert_one(s.to_mongo())).inserted_id)
    return s.out()


@router.put("/snags/{sid}")
async def update_snag(sid: str, body: SnagUpdate, user: User = Depends(current_user)):
    upd = body.model_dump(exclude_unset=True)
    if "status" in upd:
        upd["fixed_at"] = now_iso() if upd["status"] == "fixed" else None
    r = await db.snags.update_one({"_id": oid(sid), "user_id": user.id}, {"$set": upd})
    if not r.matched_count:
        raise HTTPException(404, "Snag not found")
    return Snag.from_mongo(await db.snags.find_one({"_id": oid(sid)})).out()


@router.delete("/snags/{sid}")
async def delete_snag(sid: str, user: User = Depends(current_user)):
    await db.snags.delete_one({"_id": oid(sid), "user_id": user.id})
    return {"ok": True}


# ---------------- Snag share links for trades ----------------
class SnagLinkIn(BaseModel):
    assignee: str
    origin_url: str


def snag_link_url(d: dict) -> str:
    return f"{d['origin'].rstrip('/')}/api/s/{d['token']}"


def assignee_query(pid: str, assignee: str) -> dict:
    return {"project_id": pid, "assignee": {"$regex": f"^{re.escape(assignee.strip())}$", "$options": "i"}}


@router.get("/snag-links")
async def list_snag_links(user: User = Depends(current_user)):
    docs = await db.snag_links.find({"user_id": user.id, "project_id": await active_pid(user)}).to_list(100)
    return [{"assignee": d["assignee"], "url": snag_link_url(d)} for d in docs]


@router.post("/snag-links")
async def create_snag_link(body: SnagLinkIn, user: User = Depends(current_user)):
    name = body.assignee.strip()
    if not name:
        raise HTTPException(400, "Choose a trade")
    pid = await active_pid(user)
    if not await db.snags.find_one(assignee_query(pid, name)):
        raise HTTPException(400, f"No snags are assigned to {name}")
    d = await db.snag_links.find_one({"user_id": user.id, "project_id": pid, "assignee_lc": name.lower()})
    if not d:
        d = {"token": secrets.token_urlsafe(14), "user_id": user.id, "project_id": pid, "assignee": name, "assignee_lc": name.lower(),
             "origin": body.origin_url, "created_at": now_iso()}
        await db.snag_links.insert_one(d)
    else:
        await db.snag_links.update_one({"_id": d["_id"]}, {"$set": {"origin": body.origin_url}})
        d["origin"] = body.origin_url
    return {"assignee": d["assignee"], "url": snag_link_url(d)}


async def load_snag_link(token: str):
    return await db.snag_links.find_one({"token": token}) if token else None


@router.get("/s/{token}", response_class=HTMLResponse)
async def public_snags(token: str, done: Optional[str] = None):
    link = await load_snag_link(token)
    if not link:
        return page("Not found", "<div class='card'><h2>This snag link is no longer active</h2></div>")
    p = await db.projects.find_one({"_id": ObjectId(link["project_id"])}) or {}
    snags = await db.snags.find(assignee_query(link["project_id"], link["assignee"])).sort("created_at", 1).to_list(500)
    open_s = [x for x in snags if x["status"] == "open"]
    body = brand_block(await owner_branding(link["user_id"]), f"/api/s/{E(token)}/logo")
    body += (f"<div class='hdr'><div class='brand'>BUILDER <b>ASSIST</b> · SNAGGING LIST</div><h1>Snags for {E(link['assignee'])}</h1>"
             f"<div>{E(p.get('name', ''))} · {E(p.get('address', ''))}</div>"
             f"<div style='margin-top:6px;font-size:13px' id='snag-count'>{len(open_s)} open · {len(snags) - len(open_s)} fixed</div></div>")
    if done:
        body += "<div class='card' id='snag-fixed-msg'><b class='under'>Thanks! Marked as fixed and sent to the project owner.</b></div>"
    for x in sorted(snags, key=lambda s: s["status"] != "open"):
        sid = str(x["_id"])
        img = f"<img src='/api/s/{E(token)}/photo/{sid}' style='width:100%;max-height:220px;object-fit:cover;border-radius:10px;margin-top:8px'/>" if x.get("storage_path") else ""
        prio = {"high": "#ef4444", "medium": "#f97316", "low": "#64748b"}[x.get("priority", "medium")]
        head = (f"<div style='display:flex;justify-content:space-between;gap:8px'><b>{E(x['description'])}</b>"
                f"<span class='tag' style='color:{prio}'>{E(x.get('priority', '').upper())}</span></div><div class='cap'>{E(x['room'])}</div>{img}")
        if x["status"] == "open":
            body += (f"<form class='card' id='snag-{sid}' method='post' action='/api/s/{E(token)}/fix/{sid}' enctype='multipart/form-data'>{head}"
                     f"<label>Photo of the fix (recommended)</label><input type='file' name='photo' accept='image/*' capture='environment'/>"
                     f"<label>Note (optional)</label><input name='note' placeholder='What was done'/>"
                     f"<button type='submit' id='fix-{sid}'>Mark as fixed</button></form>")
        else:
            fix = f"<img src='/api/s/{E(token)}/photo/{sid}?kind=fix' style='width:100%;max-height:220px;object-fit:cover;border-radius:10px;margin-top:8px'/>" if x.get("fix_photo_path") else ""
            body += f"<div class='card' style='opacity:.75'>{head}<p class='under'>✓ Fixed {E((x.get('fixed_at') or '')[:10])}</p>{fix}</div>"
    if not snags:
        body += "<div class='card'><h2>No snags assigned right now</h2></div>"
    return page(f"Snags for {link['assignee']}", body, ref="snag", by=link["user_id"])


@router.post("/s/{token}/fix/{sid}")
async def public_fix_snag(token: str, sid: str, photo: Optional[UploadFile] = File(None), note: str = Form("")):
    link = await load_snag_link(token)
    if not link:
        raise HTTPException(404, "Link not active")
    q = {**assignee_query(link["project_id"], link["assignee"]), "_id": oid(sid)}
    snag = await db.snags.find_one(q)
    if not snag:
        raise HTTPException(404, "Snag not found")
    upd = {"status": "fixed", "fixed_at": now_iso(), "fixed_by": link["assignee"], "fix_note": note.strip()[:500]}
    if photo is not None and photo.filename:
        data = await photo.read()
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(413, "Photo too large (max 10MB)")
        ext = photo.filename.rsplit(".", 1)[-1].lower() if "." in photo.filename else "jpg"
        ctype = photo.content_type or "image/jpeg"
        res = await run_in_threadpool(put_object, f"{APP_NAME}/uploads/{link['user_id']}/{uuid.uuid4()}.{ext}", data, ctype)
        await db.files.insert_one({"storage_path": res["path"], "owner_id": link["user_id"], "content_type": ctype,
                                   "original_filename": photo.filename, "is_deleted": False, "created_at": now_iso()})
        upd["fix_photo_path"] = res["path"]
    await db.snags.update_one({"_id": snag["_id"]}, {"$set": upd})
    return RedirectResponse(f"/api/s/{token}?done=1", status_code=303)


@router.get("/s/{token}/photo/{sid}")
async def public_snag_photo(token: str, sid: str, kind: str = "defect"):
    link = await load_snag_link(token)
    snag = await db.snags.find_one({**assignee_query(link["project_id"], link["assignee"]), "_id": oid(sid)}) if link else None
    path = (snag or {}).get("fix_photo_path" if kind == "fix" else "storage_path")
    if not path:
        raise HTTPException(404, "Not found")
    data, ctype = await run_in_threadpool(get_object, path)
    return Response(content=data, media_type=ctype, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/s/{token}/logo")
async def snag_logo(token: str):
    link = await load_snag_link(token)
    if not link:
        raise HTTPException(404, "Not found")
    return await serve_logo(link["user_id"])
