"""Property "Report a problem" links (no tenancy needed) and assigning reported issues to the team (co-owners, managers, trades)
with an emailed job link where the assignee marks it fixed with a photo."""
import secrets
import uuid
from datetime import date
from typing import Literal, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from core import APP_NAME, E, db, now_iso, oid
from deps import active_pid, current_user
from email_service import EmailError, send_email
from html_utils import brand_block, owner_branding, page, serve_logo
from models import Snag, User
from routes.email_settings import owner_reply_to
from routes.messages import log_message
from routes.rentals import _ctx, _row, _wrap
from storage import get_object, put_object

router = APIRouter()
DAILY_LIMIT = 20
PRIO = {"high": "#ef4444", "medium": "#f97316", "low": "#64748b"}
INPUT = "width:100%;padding:10px;border:1px solid #cbd5e1;border-radius:10px;font:inherit"


async def _save_photo(uid: str, photo: Optional[UploadFile]) -> Optional[str]:
    if photo is None or not photo.filename:
        return None
    data = await photo.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Photo too large (max 10MB)")
    ctype = photo.content_type or "image/jpeg"
    if not ctype.startswith("image/"):
        raise HTTPException(400, "Please attach an image")
    ext = photo.filename.rsplit(".", 1)[-1].lower() if "." in photo.filename else "jpg"
    res = await run_in_threadpool(put_object, f"{APP_NAME}/uploads/{uid}/{uuid.uuid4()}.{ext}", data, ctype)
    await db.files.insert_one({"storage_path": res["path"], "owner_id": uid, "content_type": ctype,
                               "original_filename": photo.filename, "is_deleted": False, "created_at": now_iso()})
    return res["path"]


def _url(origin: str, path: str) -> str:
    return f"{origin.rstrip('/')}{path}"


# ---------- Owner: property report link ----------

class OriginIn(BaseModel):
    origin_url: str = Field(min_length=8, max_length=300)


@router.get("/report-link")
async def get_report_link(user: User = Depends(current_user)):
    pid = await active_pid(user)
    d = await db.report_links.find_one({"user_id": user.id, "project_id": pid})
    reports = await db.snags.count_documents({"project_id": pid, "source": "report_link"})
    return {"url": _url(d["origin"], f"/api/r/{d['token']}") if d else None, "reports": reports}


@router.post("/report-link")
async def create_report_link(body: OriginIn, user: User = Depends(current_user)):
    pid = await active_pid(user)
    d = await db.report_links.find_one({"user_id": user.id, "project_id": pid})
    if d:
        await db.report_links.update_one({"_id": d["_id"]}, {"$set": {"origin": body.origin_url}})
        token = d["token"]
    else:
        token = secrets.token_urlsafe(14)
        await db.report_links.insert_one({"user_id": user.id, "project_id": pid, "token": token, "origin": body.origin_url, "created_at": now_iso()})
    return {"url": _url(body.origin_url, f"/api/r/{token}")}


@router.delete("/report-link")
async def revoke_report_link(user: User = Depends(current_user)):
    await db.report_links.delete_one({"user_id": user.id, "project_id": await active_pid(user)})
    return {"ok": True}


# ---------- Owner: assign to team ----------

@router.get("/snag-assignees")
async def assignees(user: User = Depends(current_user)):
    pid = await active_pid(user)
    team = []
    async for c in db.co_owners.find({"owner_id": user.id, "$or": [{"project_ids": None}, {"project_ids": pid}]}):
        u = await db.users.find_one({"email": c["email"]}, {"name": 1})
        team.append({"kind": "team", "id": str(c["_id"]), "name": u["name"] if u else c["email"].split("@")[0], "email": c["email"],
                     "role": "Co-owner" if c.get("project_ids") is None else "Manager", "has_account": bool(u)})
    trades = [{"kind": "trade", "id": str(c["_id"]), "name": c["name"], "email": c.get("email", ""), "role": c.get("role") or "Trade", "phone": c.get("phone", "")}
              async for c in db.contacts.find({"user_id": user.id, "project_id": pid, "kind": "trade"}).sort("created_at", 1)]
    return {"team": team, "trades": trades}


class AssignIn(BaseModel):
    kind: Literal["team", "trade"]
    id: str
    origin_url: str = Field(min_length=8, max_length=300)


@router.post("/snags/{sid}/assign")
async def assign(sid: str, body: AssignIn, user: User = Depends(current_user)):
    snag = await db.snags.find_one({"_id": oid(sid), "user_id": user.id})
    if not snag:
        raise HTTPException(404, "Snag not found")
    if body.kind == "team":
        c = await db.co_owners.find_one({"_id": oid(body.id), "owner_id": user.id, "$or": [{"project_ids": None}, {"project_ids": snag["project_id"]}]})
        if not c:
            raise HTTPException(404, "Team member not found")
        u = await db.users.find_one({"email": c["email"]}, {"name": 1})
        who = {"kind": "team", "id": body.id, "name": u["name"] if u else c["email"].split("@")[0], "email": c["email"], "user_id": str(u["_id"]) if u else None}
    else:
        c = await db.contacts.find_one({"_id": oid(body.id), "user_id": user.id, "project_id": snag["project_id"], "kind": "trade"})
        if not c:
            raise HTTPException(404, "Trade not found")
        who = {"kind": "trade", "id": body.id, "name": c["name"], "email": (c.get("email") or "").strip(), "phone": c.get("phone", ""), "user_id": None}
    token = snag.get("job_token") or secrets.token_urlsafe(14)
    url = _url(body.origin_url, f"/api/job/{token}")
    await db.snags.update_one({"_id": snag["_id"]}, {"$set": {"assignee": who["name"], "assigned_to": {**who, "at": now_iso()}, "job_token": token, "job_origin": body.origin_url}})
    emailed = False
    if who["email"]:
        address, sender, head = await _ctx(user.id, snag)
        img = f'<p><img src="{E(url)}/photo" alt="Photo of the issue" style="max-width:100%;border-radius:8px"/></p>' if snag.get("storage_path") else ""
        reporter = snag.get("reporter_name") or (snag.get("reported_by") or "").replace("Tenant: ", "")
        html = _wrap(f'{head}<p style="font-size:12px;letter-spacing:1px;color:{PRIO.get(snag.get("priority", "medium"))};font-weight:bold;margin:0">NEW JOB · {E(snag.get("priority", "medium").upper())}</p>'
                     f'<h1 style="font-size:20px;margin:8px 0 12px">{E(address)}</h1><p>Hi {E(who["name"])},</p><p>{E(sender)} has assigned you this issue:</p>'
                     f'<table width="100%" style="border-collapse:collapse;font-size:14px;margin:12px 0">{_row("Location", E(snag["room"]))}{_row("Issue", E(snag["description"]))}'
                     + (_row("Reported by", E(reporter)) if reporter else "") + (_row("Tenant phone", E(snag["reporter_phone"])) if snag.get("reporter_phone") else "")
                     + f'{_row("Reported", E(snag["created_at"][:10]))}</table>{img}'
                     f'<p><a href="{E(url)}" style="display:inline-block;background:#f97316;color:#fff;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:bold">Open job &amp; mark fixed</a></p>'
                     f'<p style="font-size:12px;color:#888">When it&#39;s done, add a photo of the fix. The tenant is told automatically.</p>')
        try:
            await send_email(to=who["email"], subject=f"New job: {snag['room']} · {address}", html=html, reply_to=await owner_reply_to(user.id))
            emailed = True
        except EmailError:
            emailed = False
    await log_message(user.id, snag["project_id"], name=who["name"], email=who["email"], channel="email" if who["email"] else "app", kind="snag_assigned",
                      summary=f"Assigned: {snag['description'][:120]} ({snag['room']})", status="sent" if emailed else ("failed" if who["email"] else "logged"))
    return {"snag": Snag.from_mongo(await db.snags.find_one({"_id": snag["_id"]})).out(), "emailed": emailed, "url": url, "assignee": who["name"]}


# ---------- Public: report a problem ----------

GONE = "<div class='card'><h2>This link is no longer active</h2><p>Please contact your landlord for a new link.</p></div>"


async def _link(token: str):
    return await db.report_links.find_one({"token": token}) if token else None


@router.get("/r/{token}", response_class=HTMLResponse)
async def report_page(token: str, sent: Optional[str] = None):
    link = await _link(token)
    if not link:
        return page("Link expired", GONE)
    address, sender, _ = await _ctx(link["user_id"], link)
    tk = E(token)
    body = brand_block(await owner_branding(link["user_id"]), f"/api/r/{tk}/logo")
    body += (f"<div class='hdr'><div class='brand'><i>Property<b>Plug</b></i> · REPORT A PROBLEM</div><h1>{E(address)}</h1>"
             f"<div>Managed by {E(sender)}</div></div>")
    if sent:
        body += ("<div class='card' id='report-sent-msg'><b class='under'>Thanks! Your report was sent.</b>"
                 "<p class='cap'>Your landlord will arrange for someone to look at it. If you left an email, you'll hear when it's fixed.</p></div>")
    body += (f"<form class='card' id='report-form' method='post' action='/api/r/{tk}' enctype='multipart/form-data'><h2>Tell us what's wrong</h2>"
             f"<label>Your name</label><input name='name' id='report-name' required maxlength='80' placeholder='Full name'/>"
             f"<label>Email (to get updates)</label><input name='email' id='report-email' type='email' maxlength='120' placeholder='you@example.com'/>"
             f"<label>Phone (optional)</label><input name='phone' id='report-phone' type='tel' maxlength='30' placeholder='07...'/>"
             f"<label>Where is it?</label><input name='room' id='report-room' required maxlength='60' placeholder='e.g. Bathroom'/>"
             f"<label>What's the problem?</label><textarea name='description' id='report-description' required maxlength='600' rows='3' placeholder='Describe the issue' style='{INPUT}'></textarea>"
             f"<label>How urgent?</label><select name='priority' id='report-priority' style='{INPUT}'>"
             f"<option value='low'>Not urgent</option><option value='medium' selected>Soon</option><option value='high'>Urgent (leak, no heating, safety)</option></select>"
             f"<label>Photo (optional)</label><input type='file' name='photo' id='report-photo' accept='image/*'/>"
             f"<button type='submit' id='report-submit'>Send report</button></form>"
             f"<p class='cap' style='text-align:center'>In an emergency (gas, fire, flooding) call the emergency services first.</p>")
    return page(f"Report a problem · {address}", body)


@router.post("/r/{token}")
async def submit_report(token: str, name: str = Form(...), room: str = Form(...), description: str = Form(...), email: str = Form(""), phone: str = Form(""),
                        priority: str = Form("medium"), photo: Optional[UploadFile] = File(None)):
    link = await _link(token)
    if not link:
        raise HTTPException(404, "Link not active")
    name, room, description, email = name.strip()[:80], room.strip()[:60], description.strip()[:600], email.strip().lower()[:120]
    if not name or not room or not description:
        raise HTTPException(400, "Tell us your name, where and what the problem is")
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        raise HTTPException(400, "That email doesn't look right")
    if await db.snags.count_documents({"report_link_id": str(link["_id"]), "created_at": {"$gte": date.today().isoformat()}}) >= DAILY_LIMIT:
        raise HTTPException(429, "Too many reports today. Please contact your landlord directly")
    doc = {"user_id": link["user_id"], "project_id": link["project_id"], "room": room, "description": description,
           "priority": priority if priority in PRIO else "medium", "status": "open", "assignee": "", "reported_by": f"Tenant: {name}",
           "reporter_name": name, "reporter_email": email, "reporter_phone": phone.strip()[:30], "source": "report_link",
           "report_link_id": str(link["_id"]), "created_at": now_iso(), "storage_path": await _save_photo(link["user_id"], photo)}
    await db.snags.insert_one(doc)
    await log_message(link["user_id"], link["project_id"], name=name, email=email, phone=doc["reporter_phone"], channel="web", kind="tenant_repair",
                      direction="in", summary=f"Problem reported: {description[:120]} ({room})")
    owner = await db.users.find_one({"_id": ObjectId(link["user_id"])}, {"email": 1}) or {}
    if owner.get("email"):
        address, _, _ = await _ctx(link["user_id"], link)
        html = _wrap(f'<p style="font-size:12px;letter-spacing:1px;color:{PRIO[doc["priority"]]};font-weight:bold;margin:0">PROBLEM REPORTED · {doc["priority"].upper()}</p>'
                     f'<h1 style="font-size:20px;margin:8px 0 12px">{E(address)}</h1><p><b>{E(name)}</b> reported a problem in <b>{E(room)}</b>:</p>'
                     f'<p style="background:#f1f5f9;padding:12px;border-radius:8px">{E(description)}</p>'
                     f'<p>Open the snagging list in PropertyPlug to assign it to your team.</p>')
        try:
            await send_email(to=owner["email"], subject=f"Problem reported by {name} · {address}", html=html, reply_to=email or None)
        except EmailError:
            pass
    return RedirectResponse(f"/api/r/{token}?sent=1", status_code=303)


@router.get("/r/{token}/logo")
async def report_logo(token: str):
    link = await _link(token)
    if not link:
        raise HTTPException(404, "Not found")
    return await serve_logo(link["user_id"])


# ---------- Public: assignee job page ----------

async def _job(token: str):
    return await db.snags.find_one({"job_token": token}) if token else None


@router.get("/job/{token}", response_class=HTMLResponse)
async def job_page(token: str, done: Optional[str] = None):
    s = await _job(token)
    if not s:
        return page("Job not found", "<div class='card'><h2>This job link is no longer active</h2></div>")
    address, sender, _ = await _ctx(s["user_id"], s)
    tk = E(token)
    who = (s.get("assigned_to") or {}).get("name") or s.get("assignee") or "you"
    body = brand_block(await owner_branding(s["user_id"]), f"/api/job/{tk}/logo")
    body += (f"<div class='hdr'><div class='brand'><i>Property<b>Plug</b></i> · JOB</div><h1>{E(address)}</h1>"
             f"<div>Assigned to {E(who)} by {E(sender)}</div></div>")
    if done:
        body += "<div class='card' id='job-fixed-msg'><b class='under'>Thanks! Marked as fixed. The owner and tenant have been told.</b></div>"
    img = f"<img src='/api/job/{tk}/photo' style='width:100%;max-height:260px;object-fit:cover;border-radius:10px;margin-top:8px'/>" if s.get("storage_path") else ""
    reporter = s.get("reporter_name") or (s.get("reported_by") or "").replace("Tenant: ", "")
    contact = " · ".join(x for x in (E(reporter), f"<a href='tel:{E(s['reporter_phone'])}'>{E(s['reporter_phone'])}</a>" if s.get("reporter_phone") else "") if x)
    head = (f"<div style='display:flex;justify-content:space-between;gap:8px'><b>{E(s['description'])}</b>"
            f"<span class='tag' style='color:{PRIO.get(s.get('priority', 'medium'))}'>{E(s.get('priority', 'medium').upper())}</span></div>"
            f"<div class='cap'>{E(s['room'])} · reported {E(s['created_at'][:10])}{(' · ' + contact) if contact else ''}</div>{img}")
    if s["status"] == "open":
        body += (f"<form class='card' id='job-form' method='post' action='/api/job/{tk}/fix' enctype='multipart/form-data'>{head}"
                 f"<label>Photo of the fix (recommended)</label><input type='file' name='photo' id='job-photo' accept='image/*' capture='environment'/>"
                 f"<label>Note (optional)</label><input name='note' id='job-note' placeholder='What was done'/>"
                 f"<button type='submit' id='job-fix'>Mark as fixed</button></form>")
    else:
        fix = f"<img src='/api/job/{tk}/photo?kind=fix' style='width:100%;max-height:260px;object-fit:cover;border-radius:10px;margin-top:8px'/>" if s.get("fix_photo_path") else ""
        body += f"<div class='card' id='job-done'>{head}<p class='under'>✓ Fixed {E((s.get('fixed_at') or '')[:10])}{(' by ' + E(s['fixed_by'])) if s.get('fixed_by') else ''}</p>{fix}</div>"
    return page(f"Job · {address}", body)


@router.post("/job/{token}/fix")
async def job_fix(token: str, note: str = Form(""), photo: Optional[UploadFile] = File(None)):
    s = await _job(token)
    if not s:
        raise HTTPException(404, "Link not active")
    if s["status"] == "open":
        who = (s.get("assigned_to") or {}).get("name") or s.get("assignee") or "Assignee"
        upd = {"status": "fixed", "fixed_at": now_iso(), "fixed_by": who, "fix_note": note.strip()[:500]}
        path = await _save_photo(s["user_id"], photo)
        if path:
            upd["fix_photo_path"] = path
        await db.snags.update_one({"_id": s["_id"]}, {"$set": upd})
        from routes.tenant_portal import notify_tenant_repair_fixed
        await notify_tenant_repair_fixed({**s, **upd})
        await log_message(s["user_id"], s["project_id"], name=who, channel="web", kind="snag_fixed", direction="in",
                          summary=f"Marked fixed: {s['description'][:120]} ({s['room']})" + (" · photo added" if path else ""))
    return RedirectResponse(f"/api/job/{token}?done=1", status_code=303)


@router.get("/job/{token}/photo")
async def job_photo(token: str, kind: str = "issue"):
    s = await _job(token)
    path = (s or {}).get("fix_photo_path" if kind == "fix" else "storage_path")
    if not path:
        raise HTTPException(404, "Not found")
    data, ctype = await run_in_threadpool(get_object, path)
    return Response(content=data, media_type=ctype, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/job/{token}/logo")
async def job_logo(token: str):
    s = await _job(token)
    if not s:
        raise HTTPException(404, "Not found")
    return await serve_logo(s["user_id"])
