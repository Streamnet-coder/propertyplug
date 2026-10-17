"""Property "Report a problem" links (no tenancy needed) and assigning reported issues to the team (co-owners, managers, trades)
with an emailed job link where the assignee marks it fixed with a photo."""
import asyncio
import logging
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from core import APP_NAME, E, db, money, now_iso, oid
from deps import active_pid, current_user
from email_service import EmailError, send_email
from html_utils import brand_block, owner_branding, page, serve_logo
from models import Snag, User
from routes.email_settings import owner_reply_to
from routes.messages import log_message
from routes.rentals import _ctx, _row, _wrap
from sms import send_sms, sms_enabled
from storage import get_object, put_object

router = APIRouter()
logger = logging.getLogger(__name__)
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
    owner = await db.users.find_one({"_id": ObjectId(user.id)}, {"branding.phone": 1}) or {}
    return {"url": _url(d["origin"], f"/api/r/{d['token']}") if d else None, "reports": reports,
            "sms_enabled": sms_enabled(), "alert_phone": (owner.get("branding") or {}).get("phone", "")}


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
                     "role": "Co-owner" if (c.get("role") or ("co_owner" if c.get("project_ids") is None else "manager")) == "co_owner" else "Manager", "has_account": bool(u)})
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
        u = await db.users.find_one({"email": c["email"]}, {"name": 1, "branding.phone": 1})
        who = {"kind": "team", "id": body.id, "name": u["name"] if u else c["email"].split("@")[0], "email": c["email"], "user_id": str(u["_id"]) if u else None,
               "phone": ((u or {}).get("branding") or {}).get("phone", "")}
    else:
        c = await db.contacts.find_one({"_id": oid(body.id), "user_id": user.id, "project_id": snag["project_id"], "kind": "trade"})
        if not c:
            raise HTTPException(404, "Trade not found")
        who = {"kind": "trade", "id": body.id, "name": c["name"], "email": (c.get("email") or "").strip(), "phone": c.get("phone", ""), "user_id": None}
    token = snag.get("job_token") or secrets.token_urlsafe(14)
    url = _url(body.origin_url, f"/api/job/{token}")
    await db.snags.update_one({"_id": snag["_id"]}, {"$set": {"assignee": who["name"], "assigned_to": {**who, "at": now_iso()}, "job_token": token, "job_origin": body.origin_url}})
    emailed = await _job_email(user.id, snag, who, url)
    texted = False
    if snag.get("priority") == "high" and who.get("phone"):
        address, sender, _ = await _ctx(user.id, snag)
        texted = await send_sms(who["phone"], f"URGENT job from {sender}: {snag['description'][:140]} ({snag['room']}, {address}). Open & mark fixed: {url}")
        if texted:
            await log_message(user.id, snag["project_id"], name=who["name"], phone=who["phone"], channel="sms", kind="urgent_alert", summary=f"Urgent job texted: {snag['description'][:100]}")
    await log_message(user.id, snag["project_id"], name=who["name"], email=who["email"], channel="email" if who["email"] else "app", kind="snag_assigned",
                      summary=f"Assigned: {snag['description'][:120]} ({snag['room']})", status="sent" if emailed else ("failed" if who["email"] else "logged"))
    return {"snag": Snag.from_mongo(await db.snags.find_one({"_id": snag["_id"]})).out(), "emailed": emailed, "texted": texted, "url": url, "assignee": who["name"]}


async def _job_email(uid: str, snag: dict, who: dict, url: str, reminder: int = 0) -> bool:
    """New-job email (or a gentle reminder) with the issue, photo and the mark-fixed link."""
    if not who.get("email"):
        return False
    address, sender, head = await _ctx(uid, snag)
    urgent = snag.get("priority") == "high"
    img = f'<p><img src="{E(url)}/photo" alt="Photo of the issue" style="max-width:100%;border-radius:8px"/></p>' if snag.get("storage_path") else ""
    reporter = snag.get("reporter_name") or (snag.get("reported_by") or "").replace("Tenant: ", "")
    days = max(1, (datetime.now(timezone.utc) - datetime.fromisoformat(snag["created_at"])).days) if reminder else 0
    label = ("FRIENDLY REMINDER" if reminder else "URGENT JOB" if urgent else "NEW JOB") + f' · {E(snag.get("priority", "medium").upper())}'
    intro = (f"Just a gentle nudge: this job from {E(sender)} is still open ({days} day{'s' if days != 1 else ''} since it was reported). If it's already done, please mark it fixed with a photo."
             if reminder else f"{E(sender)} has assigned you this issue{' and marked it URGENT' if urgent else ''}:")
    html = _wrap(f'{head}<p style="font-size:12px;letter-spacing:1px;color:{PRIO.get(snag.get("priority", "medium"))};font-weight:bold;margin:0">{label}</p>'
                 f'<h1 style="font-size:20px;margin:8px 0 12px">{E(address)}</h1><p>Hi {E(who["name"])},</p><p style="line-height:1.5">{intro}</p>'
                 f'<table width="100%" style="border-collapse:collapse;font-size:14px;margin:12px 0">{_row("Location", E(snag["room"]))}{_row("Issue", E(snag["description"]))}'
                 + (_row("Reported by", E(reporter)) if reporter else "") + (_row("Tenant phone", E(snag["reporter_phone"])) if snag.get("reporter_phone") else "")
                 + f'{_row("Reported", E(snag["created_at"][:10]))}</table>{img}'
                 f'<p><a href="{E(url)}" style="display:inline-block;background:#f97316;color:#fff;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:bold">Open job &amp; mark fixed</a></p>'
                 f'<p style="font-size:12px;color:#888">When it&#39;s done, add a photo of the fix. The tenant is told automatically.</p>')
    subject = (f"Reminder: {snag['room']} job still open · {address}" if reminder
               else f"{'URGENT: ' if urgent else ''}New job: {snag['room']} · {address}")
    try:
        await send_email(to=who["email"], subject=subject, html=html, reply_to=await owner_reply_to(uid))
        return True
    except EmailError:
        return False


# ---------- Assignee reminders: 2 days after assigning, then every 3 days (urgent: daily), max 3 ----------

MAX_REMINDERS = 3


def reminder_due(snag: dict, now: datetime) -> bool:
    a = snag.get("assigned_to") or {}
    sent = a.get("reminders", 0)
    if not a.get("at") or sent >= MAX_REMINDERS or not a.get("email"):
        return False
    last = datetime.fromisoformat(a.get("last_reminded_at") or a["at"])
    gap = 1 if snag.get("priority") == "high" else (2 if sent == 0 else 3)
    return now - last >= timedelta(days=gap)


async def run_assignee_reminders() -> int:
    now, n = datetime.now(timezone.utc), 0
    async for s in db.snags.find({"status": "open", "assigned_to.at": {"$exists": True}, "job_token": {"$exists": True}}):
        if not reminder_due(s, now):
            continue
        a = s["assigned_to"]
        url = _url(s.get("job_origin") or "", f"/api/job/{s['job_token']}")
        ok = await _job_email(s["user_id"], s, a, url, reminder=a.get("reminders", 0) + 1)
        await db.snags.update_one({"_id": s["_id"]}, {"$inc": {"assigned_to.reminders": 1}, "$set": {"assigned_to.last_reminded_at": now.isoformat()}})
        await log_message(s["user_id"], s["project_id"], name=a["name"], email=a["email"], channel="email", kind="job_reminder",
                          summary=f"Reminder {a.get('reminders', 0) + 1}/{MAX_REMINDERS}: {s['description'][:100]} ({s['room']})", status="sent" if ok else "failed")
        n += 1
    return n


async def reminder_scheduler():
    while True:
        try:
            await run_assignee_reminders()
        except Exception as e:
            logger.error(f"Job reminder scheduler error: {e}")
        await asyncio.sleep(3600)


# ---------- Public: report a problem ----------

GONE = "<div class='card'><h2>This link is no longer active</h2><p>Please contact your landlord for a new link.</p></div>"


async def _link(token: str):
    return await db.report_links.find_one({"token": token}) if token else None


@router.get("/r/{token}", response_class=HTMLResponse)
async def report_page(token: str, sent: Optional[str] = None, track: Optional[str] = None):
    link = await _link(token)
    if not link:
        return page("Link expired", GONE)
    address, sender, _ = await _ctx(link["user_id"], link)
    tk = E(token)
    body = brand_block(await owner_branding(link["user_id"]), f"/api/r/{tk}/logo")
    body += (f"<div class='hdr'><div class='brand'><i>Property<b>Plug</b></i> · REPORT A PROBLEM</div><h1>{E(address)}</h1>"
             f"<div>Managed by {E(sender)}</div></div>")
    if sent:
        trk = (f"<p><a href='/api/track/{E(track)}' id='report-track-link' style='display:inline-block;background:#0f766e;color:#fff;padding:12px 16px;border-radius:10px;text-decoration:none;font-weight:700'>"
               f"Track your report</a></p><p class='cap'>Bookmark this link to check progress any time: reported → assigned → fixed.</p>") if track else ""
        body += ("<div class='card' id='report-sent-msg'><b class='under'>Thanks! Your report was sent.</b>"
                 f"<p class='cap'>Your landlord will arrange for someone to look at it. If you left an email, you'll get the tracking link and hear when it's fixed.</p>{trk}</div>")
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
           "report_link_id": str(link["_id"]), "created_at": now_iso(), "storage_path": await _save_photo(link["user_id"], photo),
           "track_token": secrets.token_urlsafe(14), "track_origin": link.get("origin", "")}
    await db.snags.insert_one(doc)
    await log_message(link["user_id"], link["project_id"], name=name, email=email, phone=doc["reporter_phone"], channel="web", kind="tenant_repair",
                      direction="in", summary=f"Problem reported: {description[:120]} ({room})")
    urgent = doc["priority"] == "high"
    address, sender, head = await _ctx(link["user_id"], link)
    owner = await db.users.find_one({"_id": ObjectId(link["user_id"])}, {"email": 1, "branding.phone": 1}) or {}
    if owner.get("email"):
        html = _wrap(f'<p style="font-size:12px;letter-spacing:1px;color:{PRIO[doc["priority"]]};font-weight:bold;margin:0">{"URGENT " if urgent else ""}PROBLEM REPORTED · {doc["priority"].upper()}</p>'
                     f'<h1 style="font-size:20px;margin:8px 0 12px">{E(address)}</h1><p><b>{E(name)}</b> reported a problem in <b>{E(room)}</b>:</p>'
                     f'<p style="background:#f1f5f9;padding:12px;border-radius:8px">{E(description)}</p>'
                     + (f'<p>Tenant contact: {E(doc["reporter_phone"])}</p>' if doc["reporter_phone"] else "")
                     + f'<p>{"The tenant marked this as urgent (leak, no heating or safety). " if urgent else ""}Open the snagging list in PropertyPlug to assign it to your team.</p>')
        try:
            await send_email(to=owner["email"], subject=f"{'URGENT: ' if urgent else ''}Problem reported by {name} · {address}", html=html, reply_to=email or None)
        except EmailError:
            pass
    alert_phone = (owner.get("branding") or {}).get("phone", "")
    if urgent and alert_phone and await send_sms(alert_phone, f"URGENT repair at {address}: {description[:140]} ({room}). Reported by {name}{' ' + doc['reporter_phone'] if doc['reporter_phone'] else ''}. Assign it in PropertyPlug."):
        await log_message(link["user_id"], link["project_id"], name="You", phone=alert_phone, channel="sms", kind="urgent_alert", summary=f"Urgent report texted to you: {description[:100]}")
    if email:
        turl = _url(doc["track_origin"], f"/api/track/{doc['track_token']}")
        html = _wrap(f'{head}<p style="font-size:12px;letter-spacing:1px;color:#0f766e;font-weight:bold;margin:0">REPORT RECEIVED</p>'
                     f'<h1 style="font-size:20px;margin:8px 0 12px">{E(address)}</h1><p>Hi {E(name)},</p>'
                     f'<p style="line-height:1.5">Thanks, we&#39;ve received your report about <b>{E(room)}</b>: {E(description)}</p>'
                     f'<p><a href="{E(turl)}" style="display:inline-block;background:#0f766e;color:#fff;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:bold">Track your report</a></p>'
                     f'<p style="font-size:12px;color:#888">You can check whether it&#39;s been assigned or fixed any time. We&#39;ll also email you once it&#39;s fixed.</p><p>Kind regards,<br/>{E(sender)}</p>')
        try:
            await send_email(to=email, subject=f"We've received your report · {address}", html=html, reply_to=await owner_reply_to(link["user_id"]))
        except EmailError:
            pass
    return RedirectResponse(f"/api/r/{token}?sent=1&track={doc['track_token']}", status_code=303)


@router.get("/r/{token}/logo")
async def report_logo(token: str):
    link = await _link(token)
    if not link:
        raise HTTPException(404, "Not found")
    return await serve_logo(link["user_id"])


# ---------- Public: tenant progress tracking ----------

@router.get("/track/{token}", response_class=HTMLResponse)
async def track_page(token: str):
    s = await db.snags.find_one({"track_token": token}) if token else None
    if not s:
        return page("Not found", "<div class='card'><h2>This tracking link is no longer active</h2><p>Please contact your landlord.</p></div>")
    address, sender, _ = await _ctx(s["user_id"], s)
    tk = E(token)
    fmt = lambda iso: datetime.fromisoformat(iso).strftime("%d %b %Y") if iso else ""
    a = s.get("assigned_to") or {}
    assigned = bool(s.get("assignee") or a)
    fixed = s["status"] == "fixed"
    stage = "fixed" if fixed else "assigned" if assigned else "reported"
    steps = [("reported", "Reported", f"on {fmt(s['created_at'])}", True),
             ("assigned", "Assigned", (f"to {E(a.get('name') or s.get('assignee'))}" + (f" on {fmt(a['at'])}" if a.get("at") else "")) if assigned else "Waiting for your landlord to arrange someone", assigned or fixed),
             ("fixed", "Fixed", f"on {fmt(s.get('fixed_at'))}" if fixed else "Not fixed yet", fixed)]
    line = "".join(f"<div class='ms' id='track-step-{k}'><span class='dot {'done' if on else ''}'></span><div><b>{lbl}</b><div class='cap'>{sub}</div></div></div>" for k, lbl, sub, on in steps)
    status = {"reported": ("REPORTED", "#64748b"), "assigned": ("IN PROGRESS", "#f97316"), "fixed": ("FIXED", "#10b981")}[stage]
    img = f"<img src='/api/track/{tk}/photo' style='width:100%;max-height:220px;object-fit:cover;border-radius:10px;margin-top:8px'/>" if s.get("storage_path") else ""
    body = brand_block(await owner_branding(s["user_id"]), f"/api/track/{tk}/logo")
    body += (f"<div class='hdr'><div class='brand'><i>Property<b>Plug</b></i> · REPAIR TRACKER</div><h1>{E(address)}</h1><div>Managed by {E(sender)}</div></div>"
             f"<div class='card' id='track-issue'><div style='display:flex;justify-content:space-between;gap:8px'><b>{E(s['description'])}</b>"
             f"<span class='tag' id='track-status' style='color:{status[1]}'>{status[0]}</span></div><div class='cap'>{E(s['room'])}</div>{img}</div>"
             f"<div class='card' id='track-timeline'><h2>Progress</h2>{line}</div>")
    if fixed:
        fix = f"<img src='/api/track/{tk}/photo?kind=fix' style='width:100%;max-height:220px;object-fit:cover;border-radius:10px;margin-top:8px'/>" if s.get("fix_photo_path") else ""
        note = f"<p>{E(s['fix_note'])}</p>" if s.get("fix_note") else ""
        body += f"<div class='card' id='track-fix'><h2>The fix</h2>{note}{fix}<p class='cap'>Problem back? Report it again from the link your landlord shared.</p></div>"
    return page(f"Repair tracker · {address}", body)


@router.get("/track/{token}/photo")
async def track_photo(token: str, kind: str = "issue"):
    s = await db.snags.find_one({"track_token": token}) if token else None
    path = (s or {}).get("fix_photo_path" if kind == "fix" else "storage_path")
    if not path:
        raise HTTPException(404, "Not found")
    data, ctype = await run_in_threadpool(get_object, path)
    return Response(content=data, media_type=ctype, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/track/{token}/logo")
async def track_logo(token: str):
    s = await db.snags.find_one({"track_token": token}) if token else None
    if not s:
        raise HTTPException(404, "Not found")
    return await serve_logo(s["user_id"])


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
                 f"<label>Cost of the fix (optional)</label><input name='cost' id='job-cost' type='number' inputmode='decimal' min='0' max='1000000' step='0.01' placeholder='e.g. 120.00'/>"
                 f"<p class='cap'>Parts and labour total. It's added to the property's repair expenses.</p>"
                 f"<button type='submit' id='job-fix'>Mark as fixed</button></form>")
    else:
        fix = f"<img src='/api/job/{tk}/photo?kind=fix' style='width:100%;max-height:260px;object-fit:cover;border-radius:10px;margin-top:8px'/>" if s.get("fix_photo_path") else ""
        cost = f"<p class='cap' id='job-cost-logged'>Cost logged: {money(s['fix_cost'], 2)}</p>" if s.get("fix_cost") else ""
        body += f"<div class='card' id='job-done'>{head}<p class='under'>✓ Fixed {E((s.get('fixed_at') or '')[:10])}{(' by ' + E(s['fixed_by'])) if s.get('fixed_by') else ''}</p>{cost}{fix}</div>"
    return page(f"Job · {address}", body)


@router.post("/job/{token}/fix")
async def job_fix(token: str, note: str = Form(""), cost: str = Form(""), photo: Optional[UploadFile] = File(None)):
    s = await _job(token)
    if not s:
        raise HTTPException(404, "Link not active")
    try:
        amount = round(float(cost.replace(",", "").replace("£", "").strip() or 0), 2)
    except ValueError:
        raise HTTPException(400, "Cost must be a number")
    if not 0 <= amount <= 1_000_000:
        raise HTTPException(400, "Cost must be between 0 and 1,000,000")
    if s["status"] == "open":
        who = (s.get("assigned_to") or {}).get("name") or s.get("assignee") or "Assignee"
        upd = {"status": "fixed", "fixed_at": now_iso(), "fixed_by": who, "fix_note": note.strip()[:500]}
        path = await _save_photo(s["user_id"], photo)
        if path:
            upd["fix_photo_path"] = path
        if amount > 0:
            upd["fix_cost"] = amount
            await db.rental_expenses.insert_one({"user_id": s["user_id"], "project_id": s["project_id"], "category": "repairs", "amount": amount,
                                                 "date": date.today().isoformat(), "description": f"Repair: {s['room']} · {s['description'][:80]} (fixed by {who})"[:200],
                                                 "snag_id": str(s["_id"]), "source": "job_link", "created_at": now_iso()})
        await db.snags.update_one({"_id": s["_id"]}, {"$set": upd})
        from routes.tenant_portal import notify_tenant_repair_fixed
        await notify_tenant_repair_fixed({**s, **upd})
        await _ctx(s["user_id"], s)  # sets the project currency for money()
        await log_message(s["user_id"], s["project_id"], name=who, channel="web", kind="snag_fixed", direction="in",
                          summary=f"Marked fixed: {s['description'][:120]} ({s['room']})" + (" · photo added" if path else "") + (f" · cost {money(amount, 2)}" if amount else ""))
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
