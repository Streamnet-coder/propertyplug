import asyncio
import secrets
from typing import List
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field

from core import E, db, logger, money
from deps import active_pid, current_user, get_project_doc
from email_service import EMAIL_FROM_NAME, EmailError, send_email
from html_utils import brand_block, owner_branding, page, serve_logo
from models import Project, User

router = APIRouter()


def week_bounds(offset: int):
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=today.weekday()) - timedelta(weeks=offset)
    return start, start + timedelta(days=6)


async def week_spend(pid: str, start, end) -> dict:
    s, e = start.isoformat(), end.isoformat()
    receipts = await db.receipts.find({"project_id": pid, "date": {"$gte": s, "$lte": e}}).sort("amount", -1).to_list(500)
    pays = await db.stage_payments.find({"project_id": pid, "status": "paid", "paid_at": {"$gte": s, "$lt": (end + timedelta(days=1)).isoformat()}}).to_list(500)
    r_total, p_total = sum(r["amount"] for r in receipts), sum(p["amount"] for p in pays)
    return {"total": round(r_total + p_total, 2), "receipts_total": round(r_total, 2), "receipts_count": len(receipts),
            "payments_total": round(p_total, 2), "payments_count": len(pays),
            "top": [{"title": r["title"], "supplier": r.get("supplier", ""), "amount": r["amount"], "date": r["date"]} for r in receipts[:3]]}


async def build_digest(pid: str, week: int) -> dict:
    start, end = week_bounds(week)
    ps, pe = week_bounds(week + 1)
    lo, hi = start.isoformat(), (end + timedelta(days=1)).isoformat()
    spend = await week_spend(pid, start, end)
    prev = await week_spend(pid, ps, pe)
    fixed = await db.snags.find({"project_id": pid, "status": "fixed", "fixed_at": {"$gte": lo, "$lt": hi}}).sort("fixed_at", -1).to_list(200)
    opened = await db.snags.count_documents({"project_id": pid, "created_at": {"$gte": lo, "$lt": hi}})
    open_now = await db.snags.count_documents({"project_id": pid, "status": "open"})
    ms = await db.milestones.find({"project_id": pid, "status": "done", "completed_at": {"$gte": lo, "$lt": hi}}).sort("completed_at", 1).to_list(100)
    nxt = await db.milestones.find_one({"project_id": pid, "status": {"$ne": "done"}}, sort=[("order", 1)])
    return {
        "week_start": start.isoformat(), "week_end": end.isoformat(), "week": week,
        "spend": spend, "prev_spend": prev["total"],
        "snags_fixed": [{"id": str(x["_id"]), "room": x["room"], "description": x["description"], "fixed_by": x.get("fixed_by")} for x in fixed],
        "snags_opened": opened, "snags_open_now": open_now,
        "milestones_done": [{"id": str(m["_id"]), "name": m["name"], "completed_at": m["completed_at"]} for m in ms],
        "next_milestone": {"name": nxt["name"], "target_date": nxt.get("target_date"), "status": nxt["status"]} if nxt else None,
    }


@router.get("/digest")
async def weekly_digest(week: int = Query(0, ge=0, le=52), user: User = Depends(current_user)):
    return await build_digest(await active_pid(user), week)


# ---------- Shareable digest (read-only public page for partners / lenders / investors) ----------
class DigestShareIn(BaseModel):
    origin_url: str


def digest_url(p: Project):
    return f"{p.digest_origin.rstrip('/')}/api/d/{p.digest_token}" if p.digest_token and p.digest_origin else None


@router.get("/digest/share")
async def get_digest_share(user: User = Depends(current_user)):
    return {"url": digest_url(await get_project_doc(user))}


@router.post("/digest/share")
async def create_digest_share(body: DigestShareIn, user: User = Depends(current_user)):
    p = await get_project_doc(user)
    p.digest_token = p.digest_token or secrets.token_urlsafe(16)
    p.digest_origin = body.origin_url
    await db.projects.update_one({"_id": ObjectId(p.id)}, {"$set": {"digest_token": p.digest_token, "digest_origin": p.digest_origin}})
    return {"url": digest_url(p)}


@router.delete("/digest/share")
async def revoke_digest_share(user: User = Depends(current_user)):
    p = await get_project_doc(user)
    await db.projects.update_one({"_id": ObjectId(p.id)}, {"$set": {"digest_token": None}})
    return {"url": None}


def _d(s: str) -> str:
    return datetime.fromisoformat(s[:10]).strftime("%d %b")


@router.get("/d/{token}", response_class=HTMLResponse)
async def public_digest(token: str, week: int = Query(0, ge=0, le=52)):
    doc = await db.projects.find_one({"digest_token": token}) if token else None
    if not doc:
        return page("Link expired", "<div class='card'><h2>This weekly update link is no longer active</h2><p>Ask the project owner for a new link.</p></div>")
    p = Project.from_mongo(doc)
    d = await build_digest(p.id, week)
    sp = d["spend"]
    diff = sp["total"] - d["prev_spend"]
    label = "This week" if week == 0 else "Last week" if week == 1 else f"{week} weeks ago"
    nav = ("<div class='card' style='display:flex;justify-content:space-between'>"
           + (f"<a id='digest-prev' href='/api/d/{E(token)}?week={week + 1}'>&larr; Previous week</a>" if week < 52 else "<span></span>")
           + (f"<a id='digest-next' href='/api/d/{E(token)}?week={week - 1}'>Next week &rarr;</a>" if week > 0 else "<span></span>") + "</div>")
    body = brand_block(await owner_branding(p.user_id), f"/api/d/{E(token)}/logo")
    body += (f"<div class='hdr'><div class='brand'>BUILDER <b>ASSIST</b> · WEEKLY UPDATE</div><h1>{E(p.name)}</h1>"
             f"<div>{E(p.address)}</div><div style='font-size:12px;opacity:.85;margin-top:6px' id='digest-week'>{label} · {_d(d['week_start'])} – {_d(d['week_end'])}</div></div>")
    body += (f"<div class='kpis' style='margin-top:14px' id='digest-kpis'><div class='kpi'><span>Spent</span><div>{money(sp['total'], 2)}</div></div>"
             f"<div class='kpi'><span>vs week before</span><div>{'+' if diff > 0 else '-' if diff < 0 else ''}{money(abs(diff))}</div></div>"
             f"<div class='kpi'><span>Snags fixed</span><div>{len(d['snags_fixed'])}</div></div>"
             f"<div class='kpi'><span>Stages done</span><div>{len(d['milestones_done'])}</div></div></div>")
    if sp["top"]:
        body += "<div class='card'><h2>Biggest spends</h2><table>" + "".join(
            f"<tr><td>{E(r['title'])}<div class='cap'>{E(r['supplier'])} · {_d(r['date'])}</div></td><td class='n'>{money(r['amount'], 2)}</td></tr>" for r in sp["top"]) + "</table></div>"
    body += "<div class='card' id='digest-milestones'><h2>Milestones hit</h2>" + ("".join(
        f"<div class='ms'><div class='dot done'></div><div style='flex:1'>{E(m['name'])}</div></div>" for m in d["milestones_done"]) or "<div class='cap'>No stages completed this week</div>")
    if d["next_milestone"] and week == 0:
        n = d["next_milestone"]
        body += f"<div class='ms'><div class='dot in_progress'></div><div style='flex:1'>Up next: {E(n['name'])}</div><div class='cap'>{E(n.get('target_date') or '')}</div></div>"
    body += "</div>"
    body += "<div class='card' id='digest-snags'><h2>Snags fixed</h2>" + ("<table>" + "".join(
        f"<tr><td>{E(x['description'])}<div class='cap'>{E(x['room'])}{' · fixed by ' + E(x['fixed_by']) if x.get('fixed_by') else ''}</div></td></tr>" for x in d["snags_fixed"]) + "</table>"
        if d["snags_fixed"] else "<div class='cap'>No snags fixed this week</div>") + f"<div class='cap' style='margin-top:8px'>{d['snags_open_now']} still open</div></div>"
    body += nav
    return page(f"{p.name} · Weekly update", body, ref="digest", by=p.user_id)


@router.get("/d/{token}/logo")
async def digest_logo(token: str):
    doc = await db.projects.find_one({"digest_token": token}, {"user_id": 1}) if token else None
    if not doc:
        raise HTTPException(404, "Not found")
    return await serve_logo(doc["user_id"])


# ---------- Email delivery (manual + automatic every Monday) ----------
class Recipient(BaseModel):
    name: str = Field("", max_length=80)
    email: EmailStr


class DigestSettingsIn(BaseModel):
    recipients: List[Recipient] = Field(default_factory=list, max_length=10)
    auto: bool = False


def _settings(p: Project) -> dict:
    return {"recipients": p.digest_recipients, "auto": p.digest_auto, "last_sent_at": p.digest_last_sent_at, "url": digest_url(p)}


@router.get("/digest/settings")
async def get_digest_settings(user: User = Depends(current_user)):
    return _settings(await get_project_doc(user))


@router.put("/digest/settings")
async def put_digest_settings(body: DigestSettingsIn, user: User = Depends(current_user)):
    p = await get_project_doc(user)
    seen, recips = set(), []
    for r in body.recipients:
        e = r.email.lower()
        if e not in seen:
            seen.add(e)
            recips.append({"name": r.name.strip(), "email": e})
    await db.projects.update_one({"_id": ObjectId(p.id)}, {"$set": {"digest_recipients": recips, "digest_auto": body.auto}})
    p.digest_recipients, p.digest_auto = recips, body.auto
    return _settings(p)


def digest_email_html(p: Project, owner: str, d: dict, url: str) -> str:
    sp = d["spend"]
    cell = "padding:12px;border:1px solid #e2e8f0;border-radius:8px;font-family:Arial,sans-serif"
    ms = "".join(f"<li>{E(m['name'])}</li>" for m in d["milestones_done"]) or "<li>No stages completed</li>"
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
            f'<p style="font-size:12px;letter-spacing:1px;color:#0f766e;font-weight:bold;margin:0">{E(EMAIL_FROM_NAME.upper())} · WEEKLY UPDATE</p>'
            f'<h1 style="font-size:22px;margin:8px 0 4px">{E(p.name)}</h1>'
            f'<p style="margin:0 0 16px;color:#64748b">{E(p.address)} · {_d(d["week_start"])} – {_d(d["week_end"])}</p>'
            f'<p>Hi, here is {E(owner)}\'s progress update for last week.</p>'
            f'<table role="presentation" width="100%" cellspacing="8"><tr>'
            f'<td style="{cell}"><div style="font-size:11px;color:#64748b">SPENT</div><div style="font-size:18px;font-weight:bold">{money(sp["total"], 2)}</div></td>'
            f'<td style="{cell}"><div style="font-size:11px;color:#64748b">SNAGS FIXED</div><div style="font-size:18px;font-weight:bold">{len(d["snags_fixed"])}</div></td>'
            f'<td style="{cell}"><div style="font-size:11px;color:#64748b">STAGES DONE</div><div style="font-size:18px;font-weight:bold">{len(d["milestones_done"])}</div></td>'
            f'</tr></table><p style="margin:16px 0 4px;font-weight:bold">Milestones hit</p><ul style="margin:0 0 16px">{ms}</ul>'
            f'<p><a href="{E(url)}" style="display:inline-block;background:#0f766e;color:#ffffff;padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:bold">View the full weekly update</a></p>'
            f'<p style="font-size:12px;color:#888;margin-top:24px">Sent by {E(EMAIL_FROM_NAME)} on behalf of {E(owner)}. This is a read-only project update; '
            f'we never ask for your password or payment details by email.</p></td></tr></table>')


async def send_digest_emails(p: Project, week: int = 1) -> dict:
    """Email the weekly update link to the project's saved recipients. Returns {sent, failed}."""
    url = digest_url(p)
    owner = await db.users.find_one({"_id": ObjectId(p.user_id)}, {"name": 1, "email": 1})
    d = await build_digest(p.id, week)
    link = f"{url}?week={week}" if week else url
    subject = f"{p.name}: weekly update {_d(d['week_start'])} – {_d(d['week_end'])}"
    html = digest_email_html(p, owner["name"], d, link)
    sent = failed = 0
    for r in p.digest_recipients:
        try:
            await send_email(to=r["email"], subject=subject, html=html, reply_to=owner.get("email"))
            sent += 1
        except EmailError:
            failed += 1
    now = datetime.now(timezone.utc)
    await db.projects.update_one({"_id": ObjectId(p.id)}, {"$set": {"digest_last_sent_at": now.isoformat(), "digest_last_sent_week": now.strftime("%G-W%V")}})
    return {"sent": sent, "failed": failed}


@router.post("/digest/send-now")
async def digest_send_now(week: int = Query(0, ge=0, le=52), user: User = Depends(current_user)):
    p = await get_project_doc(user)
    if not p.digest_token or not digest_url(p):
        raise HTTPException(400, "Create the weekly update link first")
    if not p.digest_recipients:
        raise HTTPException(400, "Add at least one email recipient")
    if not digest_url(p).startswith("https://"):
        raise HTTPException(400, "Update link must be https to email it")
    if p.digest_last_sent_at and (datetime.now(timezone.utc) - datetime.fromisoformat(p.digest_last_sent_at)).total_seconds() < 120:
        raise HTTPException(429, "Just sent — try again in a couple of minutes")
    res = await send_digest_emails(p, week)
    if not res["sent"]:
        raise HTTPException(503, "Email is temporarily unavailable. Please try again later")
    return {**res, "last_sent_at": datetime.now(timezone.utc).isoformat()}


async def run_weekly_digests():
    """Every Monday from 08:00 UK time, email last week's update once per project with auto-send on."""
    now = datetime.now(ZoneInfo("Europe/London"))
    if now.weekday() != 0 or now.hour < 8:
        return
    week_key = datetime.now(timezone.utc).strftime("%G-W%V")
    q = {"digest_auto": True, "digest_token": {"$ne": None}, "digest_recipients.0": {"$exists": True}, "digest_last_sent_week": {"$ne": week_key}}
    async for doc in db.projects.find(q):
        p = Project.from_mongo(doc)
        if (digest_url(p) or "").startswith("https://"):
            try:
                res = await send_digest_emails(p, 1)
                logger.info(f"Weekly digest for project {p.id}: {res}")
            except Exception as e:
                logger.error(f"Weekly digest failed for {p.id}: {e}")


async def digest_scheduler():
    while True:
        try:
            await run_weekly_digests()
        except Exception as e:
            logger.error(f"Digest scheduler error: {e}")
        await asyncio.sleep(900)
