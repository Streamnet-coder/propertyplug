"""Rent arrears: portfolio-wide overdue list and automatic chaser emails (day after rent is missed, then every 7 days) with a per-tenancy switch."""
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import E, db, money, now_iso, oid
from deps import current_user, real_user
from email_service import EMAIL_FROM_NAME, EmailError, send_email
from models import User
from routes.email_settings import owner_reply_to
from routes.messages import log_message
from routes.rentals import _ctx, _wrap, build_schedule

router = APIRouter()
logger = logging.getLogger(__name__)
CHASE_EVERY = timedelta(days=7)


async def overdue_rows(t: dict, today: date) -> list:
    """Unpaid/part-paid months whose due date has passed (this year and last year)."""
    tid = str(t["_id"])
    years = list(range(max(today.year - 1, int(t["start_date"][:4])), today.year + 1))
    if not years:
        return []
    pays = {(tid, p["month"]): p async for p in db.rent_payments.find({"tenancy_id": tid, "month": {"$gte": f"{years[0]}-01"}})}
    reminded = {}
    async for r in db.rent_reminders.find({"tenancy_id": tid}).sort("sent_at", 1):
        reminded[(tid, r["month"])] = r["sent_at"]
    rows = [r for y in years for r in build_schedule(t, y, pays, reminded, today)]
    return [{**r, "owed": round(r["due"] - r["paid"], 2), "days_late": (today - date.fromisoformat(r["due_on"])).days}
            for r in rows if r["paid"] < r["due"] and r["due_on"] < today.isoformat()]


async def _chase_state(tid: str, rows: list):
    """(last late reminder iso or None, date the next automatic chase is due)."""
    late = [r async for r in db.rent_reminders.find({"tenancy_id": tid, "kind": "late"}, {"month": 1, "sent_at": 1})]
    chased = {r["month"] for r in late}
    last = max((r["sent_at"] for r in late), default=None)
    if any(r["month"] not in chased for r in rows) or not last:
        return last, date.today()
    return last, (datetime.fromisoformat(last) + CHASE_EVERY).date()


async def send_arrears_email(uid: str, t: dict, rows: list, auto: bool) -> str:
    address, sender, head = await _ctx(uid, t)
    total = sum(r["owed"] for r in rows)
    lines = "".join(f'<tr><td style="padding:5px 0">{date.fromisoformat(r["month"] + "-01").strftime("%B %Y")}</td>'
                    f'<td style="text-align:right">{date.fromisoformat(r["due_on"]).strftime("%d %b %Y")}</td>'
                    f'<td style="text-align:right">{money(r["paid"], 2)}</td><td style="text-align:right;font-weight:bold">{money(r["owed"], 2)}</td></tr>' for r in rows)
    html = _wrap(f'{head}<p style="font-size:12px;letter-spacing:1px;color:#ef4444;font-weight:bold;margin:0">RENT OVERDUE</p>'
                 f'<h1 style="font-size:20px;margin:8px 0 12px">{E(address)}</h1><p>Hi {E(t["tenant_name"])},</p>'
                 f'<p style="line-height:1.5">Our records show <b>{money(total, 2)}</b> of rent is overdue. Please arrange payment as soon as you can, '
                 f'or reply to this email if you have already paid or would like to agree a payment plan.</p>'
                 f'<table width="100%" style="border-collapse:collapse;font-size:13px;margin:12px 0"><tr style="color:#555;text-align:left"><th style="padding:5px 0">Rent period</th>'
                 f'<th style="text-align:right">Was due</th><th style="text-align:right">Paid</th><th style="text-align:right">Owed</th></tr>{lines}'
                 f'<tr><td colspan="3" style="padding:8px 0;font-weight:bold">Total overdue</td><td style="text-align:right;font-weight:bold;color:#ef4444">{money(total, 2)}</td></tr></table>'
                 f'<p>Kind regards,<br/>{E(sender)}</p><p style="font-size:12px;color:#888;margin-top:24px">Sent by {E(EMAIL_FROM_NAME)} on behalf of {E(sender)}. '
                 f'We never ask for card details or passwords by email; pay using the bank details in your tenancy agreement.</p>')
    subject = f"Rent overdue: {money(total, 2)} · {address}"
    try:
        await send_email(to=t["tenant_email"], subject=subject, html=html, reply_to=await owner_reply_to(uid))
        status = "sent"
    except EmailError:
        status = "failed"
    await log_message(uid, t["project_id"], name=t["tenant_name"], email=t["tenant_email"], channel="email", kind="rent_reminder",
                      summary=subject + (" (auto)" if auto else ""), status=status)
    if status == "sent":
        at = now_iso()
        await db.rent_reminders.insert_many([{"user_id": uid, "project_id": t["project_id"], "tenancy_id": str(t["_id"]), "month": r["month"],
                                              "kind": "late", "auto": auto, "sent_at": at} for r in rows])
    return status


async def run_auto_reminders():
    today = date.today()
    retry_cutoff = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    async for t in db.tenancies.find({"arrears_auto": True, "tenant_email": {"$nin": ["", None]}}):
        if (t.get("arrears_attempt_at") or "") > retry_cutoff:
            continue
        rows = [r for r in await overdue_rows(t, today) if r["days_late"] <= 365]
        if not rows:
            continue
        _, next_on = await _chase_state(str(t["_id"]), rows)
        if next_on > today:
            continue
        await db.tenancies.update_one({"_id": t["_id"]}, {"$set": {"arrears_attempt_at": now_iso()}})
        await send_arrears_email(t["user_id"], t, rows, auto=True)


async def reminder_scheduler():
    while True:
        try:
            await run_auto_reminders()
        except Exception as e:
            logger.error(f"Arrears reminder scheduler error: {e}")
        await asyncio.sleep(3600)


@router.get("/portfolio/arrears")
async def portfolio_arrears(user: User = Depends(real_user)):
    """Every tenancy with overdue rent across the person's accessible properties, worst first, totalled in their home currency."""
    from routes.fx import get_rates
    from routes.projects import accessible_projects
    home = (await db.users.find_one({"_id": ObjectId(user.id)}, {"home_currency": 1}) or {}).get("home_currency") or "GBP"
    rates = (await get_rates())["rates"]
    today = date.today()
    out, total = [], 0.0
    for s in await accessible_projects(user):
        if s.get("property_type") == "land" or s.get("money_hidden"):
            continue
        cur = s.get("currency") or "GBP"
        factor = rates[home] / rates[cur]
        async for t in db.tenancies.find({"project_id": s["id"]}):
            rows = await overdue_rows(t, today)
            if not rows:
                continue
            owed = round(sum(r["owed"] for r in rows), 2)
            total += owed * factor
            tid = str(t["_id"])
            last, next_on = await _chase_state(tid, rows)
            any_last = await db.rent_reminders.find_one({"tenancy_id": tid}, sort=[("sent_at", -1)])
            auto = bool(t.get("arrears_auto")) and bool(t.get("tenant_email"))
            out.append({"tenancy_id": tid, "project_id": s["id"], "project_name": s["name"], "address": s["address"], "currency": cur,
                        "tenant_name": t["tenant_name"], "tenant_email": t.get("tenant_email") or "", "tenant_phone": t.get("tenant_phone") or "",
                        "owed": owed, "owed_home": round(owed * factor, 2), "months": [{k: r[k] for k in ("month", "due_on", "due", "paid", "owed", "days_late")} for r in rows],
                        "oldest_days": max(r["days_late"] for r in rows), "arrears_auto": bool(t.get("arrears_auto")),
                        "last_reminder_at": any_last["sent_at"] if any_last else None, "next_auto_on": next_on.isoformat() if auto else None,
                        "can_manage": t["user_id"] == user.id, "shared": s.get("shared", False)})
    out.sort(key=lambda x: (-x["owed_home"], -x["oldest_days"]))
    return {"home_currency": home, "total": round(total, 2), "count": len(out), "auto_on": sum(x["arrears_auto"] for x in out), "tenancies": out}


async def _own_tenancy(tid: str, user: User) -> dict:
    if user.no_money:
        raise HTTPException(403, "Your access to this project doesn't include money")
    t = await db.tenancies.find_one({"_id": oid(tid), "user_id": user.id})
    if not t:
        raise HTTPException(404, "Tenancy not found")
    return t


class AutoIn(BaseModel):
    enabled: bool


@router.put("/rentals/tenancies/{tid}/auto-reminders")
async def set_auto(tid: str, body: AutoIn, user: User = Depends(current_user)):
    t = await _own_tenancy(tid, user)
    if body.enabled and not t.get("tenant_email"):
        raise HTTPException(400, "Add the tenant's email address first")
    await db.tenancies.update_one({"_id": t["_id"]}, {"$set": {"arrears_auto": body.enabled}})
    return {"arrears_auto": body.enabled}


@router.post("/rentals/tenancies/{tid}/remind-arrears")
async def remind_arrears(tid: str, user: User = Depends(current_user)):
    t = await _own_tenancy(tid, user)
    if not t.get("tenant_email"):
        raise HTTPException(400, "Add the tenant's email address first")
    rows = await overdue_rows(t, date.today())
    if not rows:
        raise HTTPException(400, "This tenancy has no overdue rent")
    last = await db.rent_reminders.find_one({"tenancy_id": tid}, sort=[("sent_at", -1)])
    if last and (datetime.now(timezone.utc) - datetime.fromisoformat(last["sent_at"])).total_seconds() < 600:
        raise HTTPException(429, "Reminder already sent, try again in 10 minutes")
    if await send_arrears_email(user.id, t, rows, auto=False) == "failed":
        raise HTTPException(503, "Email is temporarily unavailable. Please try again later")
    return {"ok": True, "owed": round(sum(r["owed"] for r in rows), 2), "months": len(rows)}
