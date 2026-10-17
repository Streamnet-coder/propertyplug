"""Tenant-facing extras: annual rent statements (manual + every January) and a private, view-only tenant portal with receipts and repair reporting."""
import asyncio
import logging
import secrets
import uuid
from datetime import date
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from core import APP_NAME, E, db, money, now_iso, oid
from deps import active_pid, current_user
from email_service import EMAIL_FROM_NAME, EmailError, send_email
from html_utils import brand_block, owner_branding, page, serve_logo
from models import User
from routes.email_settings import owner_reply_to
from routes.messages import log_message
from routes.rentals import _ctx, _row, _tenancy_status, _wrap, build_schedule, rent_for
from storage import put_object

router = APIRouter()
logger = logging.getLogger(__name__)


async def _year_rows(t: dict, year: int) -> list:
    tid = str(t["_id"])
    pays = {(tid, p["month"]): p async for p in db.rent_payments.find({"tenancy_id": tid, "month": {"$regex": f"^{year}-"}})}
    return build_schedule(t, year, pays, {}, date.today())


def _mlabel(ym: str) -> str:
    return date.fromisoformat(f"{ym}-01").strftime("%b %Y")


async def send_statement(uid: str, t: dict, year: int, auto: bool = False) -> str:
    rows = await _year_rows(t, year)
    if not rows:
        return "skipped"
    address, sender, head = await _ctx(uid, t)
    due, paid = sum(r["due"] for r in rows), sum(r["paid"] for r in rows)
    lines = "".join(f'<tr><td style="padding:5px 0">{_mlabel(r["month"])}</td><td style="text-align:right">{money(r["due"], 2)}</td>'
                    f'<td style="text-align:right">{money(r["paid"], 2)}</td><td style="text-align:right;color:#555">{E(r["paid_on"] or "-")}</td></tr>' for r in rows)
    html = _wrap(f'{head}<p style="font-size:12px;letter-spacing:1px;color:#0f766e;font-weight:bold;margin:0">ANNUAL RENT STATEMENT {year}</p>'
                 f'<h1 style="font-size:20px;margin:8px 0 12px">{E(address)}</h1><p>Hi {E(t["tenant_name"])},</p>'
                 f'<p style="line-height:1.5">Here is your rent statement for {year}. You can keep it for your records or use it as proof of rent paid, for example for a housing benefit or Universal Credit claim.</p>'
                 f'<table width="100%" style="border-collapse:collapse;font-size:14px;margin:12px 0">{_row("Tenant", E(t["tenant_name"]))}{_row("Property", E(address))}'
                 f'{_row("Rent due in " + str(year), money(due, 2))}{_row("Rent paid in " + str(year), money(paid, 2))}{_row("Balance outstanding", money(max(0.0, due - paid), 2))}</table>'
                 f'<table width="100%" style="border-collapse:collapse;font-size:13px;margin:12px 0"><tr style="color:#555;text-align:left"><th style="padding:5px 0">Month</th>'
                 f'<th style="text-align:right">Due</th><th style="text-align:right">Paid</th><th style="text-align:right">Paid on</th></tr>{lines}</table>'
                 f'<p>Kind regards,<br/>{E(sender)}</p><p style="font-size:12px;color:#888;margin-top:24px">Statement sent by {E(EMAIL_FROM_NAME)} on behalf of {E(sender)}. Figures are as recorded by your landlord.</p>')
    subject = f"Your {year} rent statement · {address}"
    try:
        await send_email(to=t["tenant_email"], subject=subject, html=html, reply_to=await owner_reply_to(uid))
        status = "sent"
    except EmailError:
        status = "failed"
    await log_message(uid, t["project_id"], name=t["tenant_name"], email=t["tenant_email"], channel="email", kind="rent_statement",
                      summary=subject + (" (auto)" if auto else ""), status=status)
    if status == "sent":
        await db.rent_statements.update_one({"tenancy_id": str(t["_id"]), "year": year},
                                            {"$set": {"user_id": uid, "project_id": t["project_id"], "sent_at": now_iso(), "auto": auto}}, upsert=True)
    return status


class StatementIn(BaseModel):
    year: int = Field(ge=2000, le=2100)


@router.post("/rentals/tenancies/{tid}/statement")
async def statement_one(tid: str, body: StatementIn, user: User = Depends(current_user)):
    t = await db.tenancies.find_one({"_id": oid(tid), "user_id": user.id})
    if not t:
        raise HTTPException(404, "Tenancy not found")
    if not t.get("tenant_email"):
        raise HTTPException(400, "Add the tenant's email address first")
    status = await send_statement(user.id, t, body.year)
    if status == "skipped":
        raise HTTPException(400, f"No rent was due in {body.year} for this tenancy")
    if status == "failed":
        raise HTTPException(503, "Email is temporarily unavailable. Please try again later")
    return {"ok": True}


@router.post("/rentals/statements")
async def statement_all(body: StatementIn, user: User = Depends(current_user)):
    out = {"sent": 0, "failed": 0, "skipped": 0, "no_email": 0}
    async for t in db.tenancies.find({"user_id": user.id, "project_id": await active_pid(user)}):
        if not t.get("tenant_email"):
            out["no_email"] += 1
            continue
        out[await send_statement(user.id, t, body.year)] += 1
    return out


@router.get("/rentals/statements")
async def statements_sent(year: int, user: User = Depends(current_user)):
    docs = await db.rent_statements.find({"user_id": user.id, "year": year}).to_list(500)
    return {d["tenancy_id"]: d["sent_at"] for d in docs}


async def run_january_statements():
    today = date.today()
    if today.month != 1:
        return
    year = today.year - 1
    async for t in db.tenancies.find({"tenant_email": {"$nin": ["", None]}, "statements_auto": {"$ne": False}}):
        if await db.rent_statements.find_one({"tenancy_id": str(t["_id"]), "year": year}, {"_id": 1}):
            continue
        await send_statement(t["user_id"], t, year, auto=True)


async def statement_scheduler():
    while True:
        try:
            await run_january_statements()
        except Exception as e:
            logger.error(f"Statement scheduler error: {e}")
        await asyncio.sleep(3600)


# ---------- Tenant portal ----------

class PortalIn(BaseModel):
    origin_url: str


@router.post("/rentals/tenancies/{tid}/portal")
async def create_portal(tid: str, body: PortalIn, user: User = Depends(current_user)):
    t = await db.tenancies.find_one({"_id": oid(tid), "user_id": user.id})
    if not t:
        raise HTTPException(404, "Tenancy not found")
    token = t.get("portal_token") or secrets.token_urlsafe(16)
    await db.tenancies.update_one({"_id": t["_id"]}, {"$set": {"portal_token": token, "portal_origin": body.origin_url}})
    return {"url": f"{body.origin_url.rstrip('/')}/api/t/{token}"}


@router.delete("/rentals/tenancies/{tid}/portal")
async def revoke_portal(tid: str, user: User = Depends(current_user)):
    await db.tenancies.update_one({"_id": oid(tid), "user_id": user.id}, {"$unset": {"portal_token": "", "portal_origin": ""}})
    return {"ok": True}


async def _tenancy_by_token(token: str):
    return await db.tenancies.find_one({"portal_token": token}) if token else None


GONE = "<div class='card'><h2>This tenant link is no longer active</h2><p>Please contact your landlord for a new link.</p></div>"
STATUS_COLORS = {"paid": "#10b981", "partial": "#f97316", "late": "#ef4444", "due": "#64748b"}


@router.get("/t/{token}", response_class=HTMLResponse)
async def tenant_portal(token: str, year: Optional[int] = None, reported: Optional[str] = None):
    t = await _tenancy_by_token(token)
    if not t:
        return page("Link expired", GONE)
    address, sender, _ = await _ctx(t["user_id"], t)
    today = date.today()
    year = year or today.year
    tk = E(token)
    fmt = lambda d: date.fromisoformat(d).strftime("%d %b %Y")
    body = brand_block(await owner_branding(t["user_id"]), f"/api/t/{tk}/logo")
    body += (f"<div class='hdr'><div class='brand'>BUILDER <b>ASSIST</b> · TENANT PORTAL</div><h1>{E(address)}</h1>"
             f"<div>Hi {E(t['tenant_name'])} · managed by {E(sender)}</div></div>")
    if reported:
        body += "<div class='card' id='repair-sent-msg'><b class='under'>Thanks! Your repair report was sent to your landlord.</b></div>"
    st = _tenancy_status(t, today)
    dep = (f"{money(t['deposit'], 2)} · " + (f"protected{(' with ' + E(t['deposit_scheme'])) if t.get('deposit_scheme') else ''}" if t.get("deposit_protected") else "protection pending")) if t.get("deposit") else "No deposit"
    body += (f"<div class='card' id='tenancy-terms'><h2>Your tenancy</h2><table>"
             f"<tr><td>Status</td><td class='n'><b>{st.title()}</b></td></tr>"
             f"<tr><td>Start date</td><td class='n'>{fmt(t['start_date'])}</td></tr>"
             f"<tr><td>End date</td><td class='n'>{fmt(t['end_date']) if t.get('end_date') else 'Rolling (periodic)'}</td></tr>"
             f"<tr><td>Monthly rent</td><td class='n'><b>{money(rent_for(t, today.isoformat()[:7]), 2)}</b></td></tr>"
             f"<tr><td>Rent due</td><td class='n'>Day {t.get('rent_day', 1)} of each month</td></tr>"
             f"<tr><td>Deposit</td><td class='n' id='deposit-status'>{dep}</td></tr></table>")
    nxt = [c for c in (t.get("rent_changes") or []) if c["from_month"] > today.isoformat()[:7]]
    if nxt:
        body += f"<p class='cap'>Rent changes to {money(nxt[0]['rent'], 2)} from {_mlabel(nxt[0]['from_month'])}.</p>"
    body += "</div>"
    rows = await _year_rows(t, year)
    arrears = sum(r["due"] - r["paid"] for r in rows if r["status"] in ("late", "partial") and r["due_on"] <= today.isoformat())
    nav = (f"<div style='display:flex;justify-content:space-between;align-items:center'><a href='/api/t/{tk}?year={year - 1}' id='prev-year'>&larr; {year - 1}</a>"
           f"<h2 style='margin:0'>Rent {year}</h2><a href='/api/t/{tk}?year={year + 1}' id='next-year'>{year + 1} &rarr;</a></div>")
    lines = "".join(
        f"<tr><td>{_mlabel(r['month'])}<div class='cap'>due {fmt(r['due_on'])}</div></td><td class='n'>{money(r['due'], 2)}</td><td class='n'>{money(r['paid'], 2)}</td>"
        f"<td class='n'><span class='tag' style='color:{STATUS_COLORS[r['status']]}'>{r['status'].upper()}</span>"
        + (f"<div><a href='/api/t/{tk}/receipt/{r['month']}' class='cap' id='receipt-{r['month']}'>Receipt</a></div>" if r["paid"] > 0 else "") + "</td></tr>"
        for r in rows)
    body += (f"<div class='card' id='rent-schedule'>{nav}" + (f"<table style='margin-top:8px'><tr><th>Month</th><th class='n'>Due</th><th class='n'>Paid</th><th class='n'>Status</th></tr>{lines}</table>"
             f"<p class='cap' id='rent-summary'>Paid {money(sum(r['paid'] for r in rows), 2)} of {money(sum(r['due'] for r in rows), 2)} due"
             + (f" · <b style='color:#ef4444'>{money(arrears, 2)} overdue</b>" if arrears > 0 else "") + "</p>" if rows else f"<p class='cap'>No rent due in {year}.</p>") + "</div>")
    body += (f"<form class='card' id='repair-form' method='post' action='/api/t/{tk}/repair' enctype='multipart/form-data'><h2>Report a repair</h2>"
             f"<label>Where is it?</label><input name='room' required maxlength='60' placeholder='e.g. Kitchen'/>"
             f"<label>What's the problem?</label><textarea name='description' required maxlength='600' rows='3' placeholder='Describe the issue' style='width:100%;padding:10px;border:1px solid #cbd5e1;border-radius:10px;font:inherit'></textarea>"
             f"<label>How urgent?</label><select name='priority' style='width:100%;padding:10px;border:1px solid #cbd5e1;border-radius:10px'>"
             f"<option value='low'>Not urgent</option><option value='medium' selected>Soon</option><option value='high'>Urgent (leak, no heating, safety)</option></select>"
             f"<label>Photo (optional)</label><input type='file' name='photo' accept='image/*'/>"
             f"<button type='submit' id='repair-submit'>Send repair report</button></form>")
    if t.get("portal_last_viewed") != today.isoformat():
        await db.tenancies.update_one({"_id": t["_id"]}, {"$set": {"portal_last_viewed": today.isoformat()}})
        await log_message(t["user_id"], t["project_id"], name=t["tenant_name"], channel="web", kind="tenant_portal", direction="in", summary="Opened their tenant portal")
    return page(f"{address} · Tenant portal", body)


@router.get("/t/{token}/receipt/{month}", response_class=HTMLResponse)
async def tenant_receipt(token: str, month: str):
    t = await _tenancy_by_token(token)
    if not t:
        return page("Link expired", GONE)
    p = await db.rent_payments.find_one({"tenancy_id": str(t["_id"]), "month": month})
    if not p:
        raise HTTPException(404, "No payment recorded for that month")
    address, sender, _ = await _ctx(t["user_id"], t)
    due = rent_for(t, month)
    body = brand_block(await owner_branding(t["user_id"]), f"/api/t/{E(token)}/logo")
    body += (f"<div class='card' id='receipt'><div class='brand' style='color:#10b981;font-weight:bold'>RENT RECEIPT</div><h1 style='margin:6px 0'>{E(address)}</h1><table>"
             f"<tr><td>Tenant</td><td class='n'>{E(t['tenant_name'])}</td></tr><tr><td>Rent period</td><td class='n'>{_mlabel(month)}</td></tr>"
             f"<tr><td>Amount received</td><td class='n'><b>{money(p['paid_amount'], 2)}</b></td></tr>"
             f"<tr><td>Date received</td><td class='n'>{E(date.fromisoformat(p['paid_on']).strftime('%d %B %Y'))}</td></tr>"
             f"<tr><td>Rent due for period</td><td class='n'>{money(due, 2)}</td></tr><tr><td>Balance outstanding</td><td class='n'>{money(max(0.0, due - p['paid_amount']), 2)}</td></tr></table>"
             f"<p class='cap'>Received by {E(sender)}.</p><div style='display:flex;gap:8px'><button onclick='window.print()' id='print-receipt'>Print / save PDF</button>"
             f"<a href='/api/t/{E(token)}' style='padding:12px'>Back</a></div></div>")
    return page(f"Rent receipt {_mlabel(month)}", body)


@router.post("/t/{token}/repair")
async def tenant_repair(token: str, room: str = Form(...), description: str = Form(...), priority: str = Form("medium"), photo: Optional[UploadFile] = File(None)):
    t = await _tenancy_by_token(token)
    if not t:
        raise HTTPException(404, "Link not active")
    if not room.strip() or not description.strip():
        raise HTTPException(400, "Tell us where and what the problem is")
    since = date.today().isoformat()
    if await db.snags.count_documents({"tenancy_id": str(t["_id"]), "created_at": {"$gte": since}}) >= 10:
        raise HTTPException(429, "Too many reports today. Please contact your landlord directly")
    doc = {"user_id": t["user_id"], "project_id": t["project_id"], "room": room.strip()[:60], "description": description.strip()[:600],
           "priority": priority if priority in ("low", "medium", "high") else "medium", "status": "open", "assignee": "",
           "reported_by": f"Tenant: {t['tenant_name']}", "tenancy_id": str(t["_id"]), "created_at": now_iso()}
    if photo is not None and photo.filename:
        data = await photo.read()
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(413, "Photo too large (max 10MB)")
        ext = photo.filename.rsplit(".", 1)[-1].lower() if "." in photo.filename else "jpg"
        ctype = photo.content_type or "image/jpeg"
        res = await run_in_threadpool(put_object, f"{APP_NAME}/uploads/{t['user_id']}/{uuid.uuid4()}.{ext}", data, ctype)
        await db.files.insert_one({"storage_path": res["path"], "owner_id": t["user_id"], "content_type": ctype,
                                   "original_filename": photo.filename, "is_deleted": False, "created_at": now_iso()})
        doc["storage_path"] = res["path"]
    await db.snags.insert_one(doc)
    summary = f"Repair reported: {doc['description'][:120]} ({doc['room']})"
    await log_message(t["user_id"], t["project_id"], name=t["tenant_name"], email=t.get("tenant_email"), channel="web", kind="tenant_repair", direction="in", summary=summary)
    owner = await db.users.find_one({"_id": ObjectId(t["user_id"])}, {"email": 1}) or {}
    if owner.get("email"):
        address, _, _ = await _ctx(t["user_id"], t)
        html = _wrap(f'<p style="font-size:12px;letter-spacing:1px;color:{"#ef4444" if doc["priority"] == "high" else "#f97316"};font-weight:bold;margin:0">TENANT REPAIR REPORT · {doc["priority"].upper()}</p>'
                     f'<h1 style="font-size:20px;margin:8px 0 12px">{E(address)}</h1><p><b>{E(t["tenant_name"])}</b> reported a repair in <b>{E(doc["room"])}</b>:</p>'
                     f'<p style="background:#f1f5f9;padding:12px;border-radius:8px">{E(doc["description"])}</p><p>It has been added to your snagging list in Builder Assist.</p>')
        try:
            await send_email(to=owner["email"], subject=f"Repair reported by {t['tenant_name']} · {address}", html=html, reply_to=t.get("tenant_email") or None)
        except EmailError:
            pass
    return RedirectResponse(f"/api/t/{token}?reported=1", status_code=303)


@router.get("/t/{token}/logo")
async def tenant_logo(token: str):
    t = await _tenancy_by_token(token)
    if not t:
        raise HTTPException(404, "Not found")
    return await serve_logo(t["user_id"])
