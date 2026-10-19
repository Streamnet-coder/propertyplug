"""Arrears payment plans: agree weekly/monthly instalments for overdue rent, pause automatic chasers while the tenant keeps up, resume if an instalment is missed."""
import calendar
from datetime import date, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import E, db, money, now_iso, oid
from deps import current_user
from email_service import EMAIL_FROM_NAME, EmailError, send_email
from models import User
from routes.email_settings import owner_reply_to
from routes.messages import log_message
from routes.push import notify
from routes.rentals import _ctx, _wrap, rent_for

router = APIRouter()
GRACE = timedelta(days=3)
MAX_INSTALMENTS = 104


def _add_month(d: date, start_day: int) -> date:
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(y, m, min(start_day, calendar.monthrange(y, m)[1]))


def schedule(plan: dict) -> list:
    """Instalment list [{n, due_on, amount}] covering plan amount; last instalment is the remainder."""
    out, left, d = [], round(plan["amount"], 2), date.fromisoformat(plan["start_date"])
    start_day = d.day
    while left > 0.005 and len(out) < MAX_INSTALMENTS:
        amt = round(min(plan["instalment"], left), 2)
        out.append({"n": len(out) + 1, "due_on": d.isoformat(), "amount": amt})
        left = round(left - amt, 2)
        d = d + timedelta(days=7) if plan["frequency"] == "weekly" else _add_month(d, start_day)
    return out


def evaluate(plan: dict, today: Optional[date] = None) -> dict:
    """On-track check (3-day grace), next instalment, and per-instalment paid state (payments fill instalments in order)."""
    today = today or date.today()
    rows, paid = schedule(plan), plan.get("paid", 0.0)
    expected = sum(r["amount"] for r in rows if date.fromisoformat(r["due_on"]) + GRACE < today)
    cum, nxt = 0.0, None
    for r in rows:
        cum = round(cum + r["amount"], 2)
        r["status"] = "paid" if paid >= cum - 0.005 else ("missed" if date.fromisoformat(r["due_on"]) + GRACE < today else "due")
        if r["status"] != "paid" and not nxt:
            nxt = r
    return {"rows": rows, "on_track": paid >= expected - 0.005, "next": nxt, "behind": round(max(0.0, expected - paid), 2)}


async def refresh(plan: dict) -> dict:
    """Flip active<->broken based on today's position; tell the landlord the first time it breaks."""
    if plan["status"] not in ("active", "broken"):
        return plan
    ev = evaluate(plan)
    new = "active" if ev["on_track"] else "broken"
    if new != plan["status"]:
        await db.payment_plans.update_one({"_id": plan["_id"]}, {"$set": {"status": new, "broken_at": now_iso() if new == "broken" else None}})
        plan = {**plan, "status": new}
        if new == "broken":
            await notify([plan["user_id"]], "Payment plan missed", f"{plan['tenant_name']} missed an instalment. Rent reminders have resumed.", "/arrears")
            await log_message(plan["user_id"], plan["project_id"], name=plan["tenant_name"], email="", channel="web", kind="payment_plan",
                              direction="in", summary="Missed a payment plan instalment, reminders resumed")
    return plan


async def active_plan(tid: str) -> Optional[dict]:
    p = await db.payment_plans.find_one({"tenancy_id": tid, "status": {"$in": ["active", "broken"]}})
    return await refresh(p) if p else None


def plan_out(p: dict) -> dict:
    ev = evaluate(p)
    return {"id": str(p["_id"]), "tenancy_id": p["tenancy_id"], "status": p["status"], "amount": p["amount"], "paid": round(p.get("paid", 0.0), 2),
            "remaining": round(max(0.0, p["amount"] - p.get("paid", 0.0)), 2), "instalment": p["instalment"], "frequency": p["frequency"],
            "start_date": p["start_date"], "months": p["months"], "on_track": ev["on_track"], "behind": ev["behind"], "next": ev["next"],
            "schedule": ev["rows"], "payments": p.get("payments", []), "created_at": p["created_at"]}


async def _own(tid: str, user: User) -> dict:
    if user.no_money:
        raise HTTPException(403, "Your access to this project doesn't include money")
    t = await db.tenancies.find_one({"_id": oid(tid), "user_id": user.id})
    if not t:
        raise HTTPException(404, "Tenancy not found")
    return t


async def _email_plan(uid: str, t: dict, p: dict) -> str:
    address, sender, head = await _ctx(uid, t)
    rows = schedule(p)
    every = "week" if p["frequency"] == "weekly" else "month"
    lines = "".join(f'<tr><td style="padding:5px 0">Instalment {r["n"]}</td><td style="text-align:right">{date.fromisoformat(r["due_on"]).strftime("%a %d %b %Y")}</td>'
                    f'<td style="text-align:right;font-weight:bold">{money(r["amount"], 2)}</td></tr>' for r in rows)
    html = _wrap(f'{head}<p style="font-size:12px;letter-spacing:1px;color:#0f766e;font-weight:bold;margin:0">PAYMENT PLAN AGREED</p>'
                 f'<h1 style="font-size:20px;margin:8px 0 12px">{E(address)}</h1><p>Hi {E(t["tenant_name"])},</p>'
                 f'<p style="line-height:1.5">Thanks for agreeing a plan to clear your overdue rent of <b>{money(p["amount"], 2)}</b>. '
                 f'Please pay <b>{money(p["instalment"], 2)} every {every}</b> on the dates below, <b>in addition to your normal rent</b>. '
                 f'While instalments arrive on time we won&apos;t send you any further arrears reminders.</p>'
                 f'<table width="100%" style="border-collapse:collapse;font-size:13px;margin:12px 0">{lines}</table>'
                 f'<p style="line-height:1.5">If an instalment is more than 3 days late the plan lapses and the full balance becomes due. '
                 f'Reply to this email if anything changes. You can also see this plan in your tenant portal.</p>'
                 f'<p>Kind regards,<br/>{E(sender)}</p><p style="font-size:12px;color:#888;margin-top:24px">Sent by {E(EMAIL_FROM_NAME)} on behalf of {E(sender)}.</p>')
    subject = f"Payment plan agreed: {money(p['instalment'], 2)} per {every} · {address}"
    try:
        await send_email(to=t["tenant_email"], subject=subject, html=html, reply_to=await owner_reply_to(uid))
        status = "sent"
    except EmailError:
        status = "failed"
    await log_message(uid, t["project_id"], name=t["tenant_name"], email=t["tenant_email"], channel="email", kind="payment_plan", summary=subject, status=status)
    return status


class PlanIn(BaseModel):
    instalment: float = Field(gt=0, le=1_000_000)
    frequency: Literal["weekly", "monthly"] = "monthly"
    start_date: str
    notify: bool = True


@router.get("/rentals/tenancies/{tid}/payment-plan")
async def get_plan(tid: str, user: User = Depends(current_user)):
    await _own(tid, user)
    p = await active_plan(tid)
    return plan_out(p) if p else None


@router.post("/rentals/tenancies/{tid}/payment-plan")
async def create_plan(tid: str, body: PlanIn, user: User = Depends(current_user)):
    from routes.arrears import overdue_rows
    t = await _own(tid, user)
    try:
        start = date.fromisoformat(body.start_date)
    except ValueError:
        raise HTTPException(400, "Start date must be YYYY-MM-DD")
    if start < date.today() - timedelta(days=7):
        raise HTTPException(400, "Start date can't be more than a week in the past")
    if await active_plan(tid):
        raise HTTPException(409, "This tenancy already has a payment plan. Cancel it first to agree a new one")
    rows = await overdue_rows(t, date.today())
    amount = round(sum(r["owed"] for r in rows), 2)
    if amount <= 0:
        raise HTTPException(400, "This tenancy has no overdue rent")
    p = {"user_id": user.id, "project_id": t["project_id"], "tenancy_id": tid, "tenant_name": t["tenant_name"], "amount": amount,
         "instalment": round(min(body.instalment, amount), 2), "frequency": body.frequency, "start_date": start.isoformat(),
         "months": [r["month"] for r in rows], "status": "active", "paid": 0.0, "payments": [], "created_at": now_iso()}
    if len(schedule({**p, "amount": amount + 0.01})) >= MAX_INSTALMENTS:
        raise HTTPException(400, f"That instalment is too small: the plan would run over {MAX_INSTALMENTS} payments")
    p["_id"] = (await db.payment_plans.insert_one(p)).inserted_id
    emailed = await _email_plan(user.id, t, p) if body.notify and t.get("tenant_email") else None
    return {**plan_out(p), "emailed": emailed}


class InstalmentIn(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)
    paid_on: Optional[str] = None


@router.post("/payment-plans/{pid}/payments")
async def log_instalment(pid: str, body: InstalmentIn, user: User = Depends(current_user)):
    """Record an instalment and apply it to the plan's overdue months (oldest first) so the rent ledger stays in step."""
    p = await db.payment_plans.find_one({"_id": oid(pid), "user_id": user.id, "status": {"$in": ["active", "broken"]}})
    if not p:
        raise HTTPException(404, "Payment plan not found")
    t = await _own(p["tenancy_id"], user)
    remaining = round(p["amount"] - p.get("paid", 0.0), 2)
    if body.amount > remaining + 0.005:
        raise HTTPException(400, f"Only {money(remaining, 2)} is left on this plan")
    paid_on = body.paid_on or date.today().isoformat()
    left = body.amount
    for m in p["months"]:
        if left <= 0.005:
            break
        doc = await db.rent_payments.find_one({"tenancy_id": p["tenancy_id"], "month": m})
        have = float(doc["paid_amount"]) if doc else 0.0
        add = min(left, max(0.0, rent_for(t, m) - have))
        if add > 0:
            await db.rent_payments.update_one({"tenancy_id": p["tenancy_id"], "month": m, "user_id": user.id},
                                              {"$set": {"paid_amount": round(have + add, 2), "paid_on": paid_on, "project_id": p["project_id"], "updated_at": now_iso()}}, upsert=True)
            left = round(left - add, 2)
    paid = round(p.get("paid", 0.0) + body.amount, 2)
    done = paid >= p["amount"] - 0.005
    await db.payment_plans.update_one({"_id": p["_id"]}, {"$set": {"paid": paid, **({"status": "completed", "completed_at": now_iso()} if done else {})},
                                                          "$push": {"payments": {"amount": body.amount, "paid_on": paid_on, "at": now_iso()}}})
    p = await db.payment_plans.find_one({"_id": p["_id"]})
    return plan_out(await refresh(p))


@router.delete("/payment-plans/{pid}")
async def cancel_plan(pid: str, user: User = Depends(current_user)):
    r = await db.payment_plans.update_one({"_id": oid(pid), "user_id": user.id, "status": {"$in": ["active", "broken"]}},
                                          {"$set": {"status": "cancelled", "cancelled_at": now_iso()}})
    if not r.matched_count:
        raise HTTPException(404, "Payment plan not found")
    return {"ok": True}
