"""Task inbox: open snags, tenant repairs and upcoming/overdue stages across every project the person can open."""
import uuid
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from core import APP_NAME, db, now_iso, oid
from deps import real_user
from models import User
from routes.messages import log_message
from routes.projects import access_filter
from storage import put_object

router = APIRouter()
PRIORITY = {"high": 0, "medium": 1, "low": 2}


@router.get("/inbox")
async def inbox(days: int = 30, user: User = Depends(real_user)):
    projects = {str(p["_id"]): p["name"] async for p in db.projects.find(await access_filter(user), {"name": 1})}
    pids = list(projects)
    today = date.today().isoformat()
    horizon = (date.today() + timedelta(days=max(1, min(days, 365)))).isoformat()
    items = []
    async for s in db.snags.find({"project_id": {"$in": pids}, "status": "open"}):
        tenant = bool(s.get("tenancy_id")) or s.get("source") == "report_link"
        a = s.get("assigned_to") or {}
        mine = a.get("kind") == "team" and (a.get("user_id") == user.id or (a.get("email") or "").lower() == user.email.lower())
        items.append({"id": str(s["_id"]), "kind": "repair" if tenant else "snag", "project_id": s["project_id"], "project_name": projects[s["project_id"]],
                      "title": s["description"], "detail": " · ".join(x for x in (s.get("room"), s.get("reported_by"), (f"Assigned: {s['assignee']}" if s.get("assignee") else "")) if x),
                      "priority": s.get("priority", "medium"), "date": s.get("created_at", "")[:10], "overdue": False, "mine": mine})
    async for m in db.milestones.find({"project_id": {"$in": pids}, "status": {"$ne": "done"}, "target_date": {"$nin": [None, ""], "$lte": horizon}}):
        items.append({"id": str(m["_id"]), "kind": "stage", "project_id": m["project_id"], "project_name": projects[m["project_id"]],
                      "title": m["name"], "detail": "In progress" if m["status"] == "in_progress" else "Not started",
                      "priority": "high" if m["target_date"] < today else "medium", "date": m["target_date"], "overdue": m["target_date"] < today, "mine": False})
    # Jobs assigned to me, overdue stages and urgent repairs first, then by priority and date.
    items.sort(key=lambda i: (not i["mine"], not i["overdue"], i["kind"] != "repair" or i["priority"] != "high", PRIORITY[i["priority"]], i["date"] or "9999"))
    counts = {k: sum(i["kind"] == k for i in items) for k in ("repair", "snag", "stage")}
    counts["mine"] = sum(i["mine"] for i in items)
    return {"items": items, "counts": {**counts, "overdue": sum(i["overdue"] for i in items), "total": len(items)}, "projects": len(pids)}


@router.post("/inbox/snags/{sid}/fix")
async def quick_fix(sid: str, note: str = Form(""), file: Optional[UploadFile] = File(None), user: User = Depends(real_user)):
    """Mark a snag / tenant repair fixed from My tasks (any accessible project), with an optional after photo and note."""
    snag = await db.snags.find_one({"_id": oid(sid)})
    if not snag or not await db.projects.find_one({"_id": oid(snag["project_id"]), **await access_filter(user)}, {"_id": 1}):
        raise HTTPException(404, "Snag not found")
    if snag.get("status") == "fixed":
        raise HTTPException(400, "Already marked fixed")
    upd = {"status": "fixed", "fixed_at": now_iso(), "fixed_by": user.name, "fix_note": note.strip()[:500]}
    if file is not None and file.filename:
        data = await file.read()
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(413, "Photo too large (max 10MB)")
        if not (file.content_type or "image/jpeg").startswith("image/"):
            raise HTTPException(400, "Please attach an image")
        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
        ctype = file.content_type or "image/jpeg"
        res = await run_in_threadpool(put_object, f"{APP_NAME}/uploads/{snag['user_id']}/{uuid.uuid4()}.{ext}", data, ctype)
        await db.files.insert_one({"storage_path": res["path"], "owner_id": snag["user_id"], "content_type": ctype,
                                   "original_filename": file.filename, "is_deleted": False, "created_at": now_iso()})
        upd["fix_photo_path"] = res["path"]
    await db.snags.update_one({"_id": snag["_id"]}, {"$set": upd})
    from routes.tenant_portal import notify_tenant_repair_fixed
    await notify_tenant_repair_fixed({**snag, **upd})
    if user.id != snag["user_id"]:
        from routes.push import notify
        await notify([snag["user_id"]], f"Fixed: {snag.get('room', 'snag')}", f"{user.name} marked fixed: {snag['description'][:120]}", "/snags", kind="fixed")
    await log_message(snag["user_id"], snag["project_id"], name=user.name, channel="app", kind="snag_fixed", direction="in",
                      summary=f"Marked fixed from My tasks: {snag['description'][:120]} ({snag.get('room', '')})" + (" · photo added" if upd.get("fix_photo_path") else ""))
    await db.project_activity.insert_one({"owner_id": snag["user_id"], "project_id": snag["project_id"], "actor_id": user.id, "actor_name": user.name,
                                          "is_owner": user.id == snag["user_id"], "action": "marked fixed snag", "at": now_iso()})
    return {"ok": True, "photo": bool(upd.get("fix_photo_path"))}
