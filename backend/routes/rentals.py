"""Rental & tenancy tracker: tenancies, monthly rent log (paid/partial/late), letting expenses and a yearly net cashflow summary."""
from datetime import date, datetime, timezone
from typing import Literal, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from core import CURRENCY, E, db, money, now_iso, oid
from deps import active_pid, current_user
from email_service import EMAIL_FROM_NAME, EmailError, send_email
from models import User
from routes.email_settings import owner_reply_to
from routes.messages import log_message

router = APIRouter()

EXPENSE_CATEGORIES = ("repairs", "letting_agent", "insurance", "mortgage", "service_charge", "utilities", "other")


def _iso(v):
    if not v:
        return None
    try:
        date.fromisoformat(v)
    except ValueError:
        raise ValueError("Use date format YYYY-MM-DD")
    return v


class TenancyIn(BaseModel):
    tenant_name: str
    tenant_email: str = ""
    tenant_phone: str = ""
    rent: float = Field(gt=0)
    deposit: float = Field(default=0, ge=0)
    deposit_scheme: str = ""
    deposit_protected: bool = False
    start_date: str
    end_date: Optional[str] = None
    rent_day: int = Field(default=1, ge=1, le=28)
    receipts_auto: bool = True
    statements_auto: bool = True
    arrears_auto: bool = True
    notes: str = ""

    _d = field_validator("start_date", "end_date")(classmethod(lambda cls, v: _iso(v)))

    @field_validator("tenant_name")
    @classmethod
    def name_req(cls, v):
        if not v.strip():
            raise ValueError("Enter the tenant's name")
        return v.strip()


class RentIn(BaseModel):
    paid_amount: float = Field(ge=0)
    paid_on: Optional[str] = None

    _d = field_validator("paid_on")(classmethod(lambda cls, v: _iso(v)))


class ExpenseIn(BaseModel):
    category: Literal[EXPENSE_CATEGORIES] = "other"  # type: ignore[valid-type]
    amount: float = Field(gt=0)
    date: str
    description: str = ""

    _d = field_validator("date")(classmethod(lambda cls, v: _iso(v)))


def _months(start: date, end: Optional[date], year: int):
    """YYYY-MM months in `year` covered by the tenancy."""
    out = []
    for m in range(1, 13):
        first = date(year, m, 1)
        last = date(year + (m == 12), m % 12 + 1, 1)
        if start < last and (end is None or end >= first):
            out.append(f"{year}-{m:02d}")
    return out


def rent_for(t: dict, month: str) -> float:
    """Rent due for YYYY-MM, honouring any renewal rent changes."""
    rent = t["rent"]
    for c in sorted(t.get("rent_changes") or [], key=lambda c: c["from_month"]):
        if c["from_month"] <= month:
            rent = c["rent"]
    return rent


def build_schedule(t: dict, year: int, pays: dict, reminded: dict, today: date) -> list:
    """Month-by-month rent rows for `year`; pays/reminded are keyed by (tenancy_id, YYYY-MM)."""
    tid = str(t["_id"])
    out = []
    for mo in _months(date.fromisoformat(t["start_date"]), date.fromisoformat(t["end_date"]) if t.get("end_date") else None, year):
        due_on = date(int(mo[:4]), int(mo[5:]), t.get("rent_day", 1))
        p = pays.get((tid, mo))
        paid = float(p["paid_amount"]) if p else 0.0
        due = rent_for(t, mo)
        status = "paid" if paid >= due else "partial" if paid > 0 else "late" if due_on < today else "due"
        out.append({"month": mo, "due_on": due_on.isoformat(), "due": due, "paid": paid, "paid_on": p.get("paid_on") if p else None,
                    "status": status, "reminded_at": reminded.get((tid, mo))})
    return out


def _tenancy_status(t: dict, today: date):
    s = date.fromisoformat(t["start_date"])
    e = date.fromisoformat(t["end_date"]) if t.get("end_date") else None
    return "upcoming" if s > today else "ended" if e and e < today else "active"


async def _scoped(user: User):
    return {"user_id": user.id, "project_id": await active_pid(user)}


@router.get("/rentals")
async def rentals(year: Optional[int] = None, user: User = Depends(current_user)):
    return await compute_rentals(await _scoped(user), year or date.today().year)


async def compute_rentals(q: dict, year: int) -> dict:
    today = date.today()
    tenancies = await db.tenancies.find(q).sort("start_date", -1).to_list(100)
    pays = {(p["tenancy_id"], p["month"]): p for p in await db.rent_payments.find({**q, "month": {"$regex": f"^{year}-"}}).to_list(2000)}
    reminded = {(r["tenancy_id"], r["month"]): r["sent_at"] for r in await db.rent_reminders.find({**q, "month": {"$regex": f"^{year}-"}}).sort("sent_at", 1).to_list(2000)}
    expenses = await db.rental_expenses.find({**q, "date": {"$regex": f"^{year}-"}}).sort("date", -1).to_list(1000)

    monthly = {f"{year}-{m:02d}": {"month": f"{year}-{m:02d}", "due": 0.0, "received": 0.0, "expenses": 0.0} for m in range(1, 13)}
    t_out = []
    for t in tenancies:
        tid = str(t["_id"])
        sched = build_schedule(t, year, pays, reminded, today)
        for r in sched:
            monthly[r["month"]]["due"] += r["due"]
            monthly[r["month"]]["received"] += r["paid"]
        arrears = sum(r["due"] - r["paid"] for r in sched if r["status"] in ("late", "partial") and r["due_on"] <= today.isoformat())
        st = _tenancy_status(t, today)
        end = t.get("end_date")
        t_out.append({**{k: v for k, v in t.items() if k not in ("_id", "user_id", "portal_token", "portal_origin")}, "id": tid, "status": st,
                      "deposit_protected": bool(t.get("deposit_protected")), "shared_doc_ids": t.get("shared_doc_ids") or [], "receipts_auto": t.get("receipts_auto", True), "statements_auto": t.get("statements_auto", True),
                      "portal_url": f"{t['portal_origin'].rstrip('/')}/api/t/{t['portal_token']}" if t.get("portal_token") else None,
                      "current_rent": rent_for(t, today.isoformat()[:7]), "rent_changes": t.get("rent_changes") or [], "renewals": t.get("renewals") or [],
                      "days_to_end": (date.fromisoformat(end) - today).days if end and st != "ended" else None,
                      "schedule": sched, "arrears": round(arrears, 2), "late_count": sum(r["status"] == "late" for r in sched)})

    by_cat = {c: 0.0 for c in EXPENSE_CATEGORIES}
    for e in expenses:
        by_cat[e["category"]] += e["amount"]
        monthly[e["date"][:7]]["expenses"] += e["amount"]
    received = sum(m["received"] for m in monthly.values())
    spent = sum(by_cat.values())
    return {
        "year": year,
        "tenancies": t_out,
        "expenses": [{**{k: v for k, v in e.items() if k not in ("_id", "user_id")}, "id": str(e["_id"])} for e in expenses],
        "summary": {
            "rent_due": round(sum(m["due"] for m in monthly.values()), 2),
            "received": round(received, 2),
            "arrears": round(sum(t["arrears"] for t in t_out), 2),
            "expenses": round(spent, 2),
            "net": round(received - spent, 2),
            "by_category": {k: round(v, 2) for k, v in by_cat.items() if v},
            "monthly": [{**m, "net": round(m["received"] - m["expenses"], 2)} for m in monthly.values()],
            "active_rent": sum(t["current_rent"] for t in t_out if t["status"] == "active"),
            "active_tenancies": sum(t["status"] == "active" for t in t_out),
            "late_months": sum(t["late_count"] for t in t_out),
        },
    }


@router.post("/rentals/tenancies")
async def create_tenancy(body: TenancyIn, user: User = Depends(current_user)):
    if body.end_date and body.end_date < body.start_date:
        raise HTTPException(400, "End date must be after the start date")
    doc = {**body.model_dump(), **await _scoped(user), "created_at": now_iso()}
    doc["_id"] = (await db.tenancies.insert_one(doc)).inserted_id
    return {"id": str(doc["_id"])}


@router.put("/rentals/tenancies/{tid}")
async def update_tenancy(tid: str, body: TenancyIn, user: User = Depends(current_user)):
    if body.end_date and body.end_date < body.start_date:
        raise HTTPException(400, "End date must be after the start date")
    r = await db.tenancies.update_one({"_id": oid(tid), "user_id": user.id}, {"$set": body.model_dump()})
    if not r.matched_count:
        raise HTTPException(404, "Tenancy not found")
    return {"ok": True}


@router.delete("/rentals/tenancies/{tid}")
async def delete_tenancy(tid: str, user: User = Depends(current_user)):
    await db.tenancies.delete_one({"_id": oid(tid), "user_id": user.id})
    await db.rent_payments.delete_many({"tenancy_id": tid, "user_id": user.id})
    await db.rent_reminders.delete_many({"tenancy_id": tid, "user_id": user.id})
    await db.rent_statements.delete_many({"tenancy_id": tid, "user_id": user.id})
    return {"ok": True}


@router.put("/rentals/tenancies/{tid}/rent/{month}")
async def log_rent(tid: str, month: str, body: RentIn, user: User = Depends(current_user)):
    t = await db.tenancies.find_one({"_id": oid(tid), "user_id": user.id})
    if not t:
        raise HTTPException(404, "Tenancy not found")
    try:
        date.fromisoformat(f"{month}-01")
    except ValueError:
        raise HTTPException(400, "Month must be YYYY-MM")
    if body.paid_amount == 0:
        await db.rent_payments.delete_one({"tenancy_id": tid, "month": month, "user_id": user.id})
        return {"ok": True}
    prev = await db.rent_payments.find_one({"tenancy_id": tid, "month": month, "user_id": user.id})
    paid_on = body.paid_on or date.today().isoformat()
    await db.rent_payments.update_one(
        {"tenancy_id": tid, "month": month, "user_id": user.id},
        {"$set": {"paid_amount": body.paid_amount, "paid_on": paid_on, "project_id": t["project_id"], "updated_at": now_iso()}},
        upsert=True)
    receipt = None
    if t.get("receipts_auto", True) and t.get("tenant_email") and (not prev or float(prev["paid_amount"]) != body.paid_amount):
        receipt = await _send_receipt(user, t, month, body.paid_amount, paid_on)
    return {"ok": True, "receipt": receipt}


@router.post("/rentals/expenses")
async def create_expense(body: ExpenseIn, user: User = Depends(current_user)):
    doc = {**body.model_dump(), **await _scoped(user), "created_at": now_iso()}
    doc["_id"] = (await db.rental_expenses.insert_one(doc)).inserted_id
    return {"id": str(doc["_id"])}


@router.put("/rentals/expenses/{eid}")
async def update_expense(eid: str, body: ExpenseIn, user: User = Depends(current_user)):
    r = await db.rental_expenses.update_one({"_id": oid(eid), "user_id": user.id}, {"$set": body.model_dump()})
    if not r.matched_count:
        raise HTTPException(404, "Expense not found")
    return {"ok": True}


@router.delete("/rentals/expenses/{eid}")
async def delete_expense(eid: str, user: User = Depends(current_user)):
    await db.rental_expenses.delete_one({"_id": oid(eid), "user_id": user.id})
    return {"ok": True}


class RemindIn(BaseModel):
    month: str


def reminder_html(name: str, address: str, amount: str, due_on: str, late: bool, paid: str, sender: str) -> str:
    when = date.fromisoformat(due_on).strftime("%d %B %Y")
    msg = (f"Our records show the rent of <b>{amount}</b> that was due on <b>{when}</b> has not been received yet"
           + (f" (we have received {paid} so far)" if paid else "") + ". Please arrange payment as soon as you can, or reply to this email if you have already paid."
           if late else f"Just a friendly reminder that your rent of <b>{amount}</b> is due on <b>{when}</b>. Thank you for paying on time.")
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
            f'<p style="font-size:12px;letter-spacing:1px;color:{"#ef4444" if late else "#0f766e"};font-weight:bold;margin:0">{"RENT OVERDUE" if late else "RENT REMINDER"}</p>'
            f'<h1 style="font-size:20px;margin:8px 0 12px">{E(address)}</h1><p>Hi {E(name)},</p><p style="line-height:1.5">{msg}</p>'
            f'<p>Kind regards,<br/>{E(sender)}</p>'
            f'<p style="font-size:12px;color:#888;margin-top:24px">Sent by {E(EMAIL_FROM_NAME)} on behalf of {E(sender)}. '
            f'We never ask for card details or passwords by email; pay using the bank details in your tenancy agreement.</p></td></tr></table>')


@router.post("/rentals/tenancies/{tid}/remind")
async def send_reminder(tid: str, body: RemindIn, user: User = Depends(current_user)):
    t = await db.tenancies.find_one({"_id": oid(tid), "user_id": user.id})
    if not t:
        raise HTTPException(404, "Tenancy not found")
    if not t.get("tenant_email"):
        raise HTTPException(400, "Add the tenant's email address first")
    try:
        date.fromisoformat(f"{body.month}-01")
    except ValueError:
        raise HTTPException(400, "Month must be YYYY-MM")
    if body.month not in _months(date.fromisoformat(t["start_date"]), date.fromisoformat(t["end_date"]) if t.get("end_date") else None, int(body.month[:4])):
        raise HTTPException(400, "No rent is due for that month")
    last = await db.rent_reminders.find_one({"tenancy_id": tid, "month": body.month}, sort=[("sent_at", -1)])
    if last and (datetime.now(timezone.utc) - datetime.fromisoformat(last["sent_at"])).total_seconds() < 600:
        raise HTTPException(429, "Reminder already sent, try again in 10 minutes")
    paid_doc = await db.rent_payments.find_one({"tenancy_id": tid, "month": body.month})
    paid = float(paid_doc["paid_amount"]) if paid_doc else 0.0
    due_amt = rent_for(t, body.month)
    if paid >= due_amt:
        raise HTTPException(400, "This month is already paid")
    due_on = date(int(body.month[:4]), int(body.month[5:]), t.get("rent_day", 1))
    late = due_on < date.today()
    address, sender, _ = await _ctx(user.id, t)
    owed = money(due_amt - paid, 2) if late and paid else money(due_amt, 2)
    subject = f"{'Rent overdue' if late else 'Friendly reminder: rent due'} {due_on.strftime('%d %b')} · {address}"
    html = reminder_html(t["tenant_name"], address, owed, due_on.isoformat(), late, money(paid, 2) if paid else "", sender)
    try:
        await send_email(to=t["tenant_email"], subject=subject, html=html, reply_to=await owner_reply_to(user.id))
        status = "sent"
    except EmailError:
        status = "failed"
    await log_message(user.id, t["project_id"], name=t["tenant_name"], email=t["tenant_email"], channel="email",
                      kind="rent_reminder", summary=subject, status=status)
    if status == "failed":
        raise HTTPException(503, "Email is temporarily unavailable. Please try again later")
    sent_at = now_iso()
    await db.rent_reminders.insert_one({"user_id": user.id, "project_id": t["project_id"], "tenancy_id": tid, "month": body.month,
                                        "kind": "late" if late else "upcoming", "sent_at": sent_at})
    return {"ok": True, "kind": "late" if late else "upcoming", "sent_at": sent_at}


async def _ctx(uid: str, t: dict):
    """(property address, sender name, branding footer html) for tenant emails; also sets the money() currency."""
    proj = await db.projects.find_one({"_id": ObjectId(t["project_id"])}, {"address": 1, "name": 1, "currency": 1}) or {}
    CURRENCY.set(proj.get("currency") or "GBP")
    owner = await db.users.find_one({"_id": ObjectId(uid)}, {"name": 1, "branding": 1}) or {}
    b = owner.get("branding") or {}
    sender = b.get("company_name") or owner.get("name", "Your landlord")
    contacts = " · ".join(E(x) for x in (b.get("contact_name"), b.get("phone"), b.get("email"), b.get("website")) if x)
    color = b.get("color") or "#0f766e"
    head = (f'<div style="border-bottom:3px solid {E(color)};padding-bottom:10px;margin-bottom:14px"><div style="font-size:18px;font-weight:bold">{E(sender)}</div>'
            + (f'<div style="font-size:12px;color:#555">{E(b["tagline"])}</div>' if b.get("tagline") else "")
            + (f'<div style="font-size:12px;color:#555">{contacts}</div>' if contacts else "") + "</div>")
    return proj.get("address") or proj.get("name") or "Your rental", sender, head


def _wrap(inner: str) -> str:
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">{inner}</td></tr></table>'


def _row(k: str, v: str) -> str:
    return f'<tr><td style="padding:6px 0;color:#555">{k}</td><td style="padding:6px 0;text-align:right;font-weight:bold">{v}</td></tr>'


async def _send_receipt(user: User, t: dict, month: str, amount: float, paid_on: str):
    address, sender, head = await _ctx(user.id, t)
    due = rent_for(t, month)
    mlabel = date.fromisoformat(f"{month}-01").strftime("%B %Y")
    balance = max(0.0, due - amount)
    html = _wrap(f'{head}<p style="font-size:12px;letter-spacing:1px;color:#10b981;font-weight:bold;margin:0">RENT RECEIPT</p>'
                 f'<h1 style="font-size:20px;margin:8px 0 12px">{E(address)}</h1><p>Hi {E(t["tenant_name"])}, thank you. This confirms we have received your rent payment.</p>'
                 f'<table width="100%" style="border-collapse:collapse;font-size:14px;margin:12px 0">{_row("Rent period", mlabel)}{_row("Amount received", money(amount, 2))}'
                 f'{_row("Date received", date.fromisoformat(paid_on).strftime("%d %B %Y"))}{_row("Rent due for period", money(due, 2))}'
                 f'{_row("Balance outstanding", money(balance, 2))}</table><p>Kind regards,<br/>{E(sender)}</p>'
                 f'<p style="font-size:12px;color:#888;margin-top:24px">Receipt sent by {E(EMAIL_FROM_NAME)} on behalf of {E(sender)}. Please keep this email for your records.</p>')
    subject = f"Rent receipt · {mlabel} · {address}"
    try:
        await send_email(to=t["tenant_email"], subject=subject, html=html, reply_to=await owner_reply_to(user.id))
        status = "sent"
    except EmailError:
        status = "failed"
    await log_message(user.id, t["project_id"], name=t["tenant_name"], email=t["tenant_email"], channel="email", kind="rent_receipt", summary=subject, status=status)
    return status


class RenewIn(BaseModel):
    end_date: Optional[str] = None  # None = rolling (periodic) tenancy
    new_rent: Optional[float] = Field(None, gt=0)
    rent_from: Optional[str] = None
    notify: bool = True

    _d = field_validator("end_date", "rent_from")(classmethod(lambda cls, v: _iso(v)))


@router.post("/rentals/tenancies/{tid}/renew")
async def renew_tenancy(tid: str, body: RenewIn, user: User = Depends(current_user)):
    t = await db.tenancies.find_one({"_id": oid(tid), "user_id": user.id})
    if not t:
        raise HTTPException(404, "Tenancy not found")
    if body.end_date and body.end_date <= max(t["start_date"], date.today().isoformat()):
        raise HTTPException(400, "New end date must be in the future")
    if body.new_rent and not body.rent_from:
        raise HTTPException(400, "Choose the date the new rent starts")
    if body.rent_from and body.rent_from < t["start_date"]:
        raise HTTPException(400, "New rent can't start before the tenancy")
    upd: dict = {"$set": {"end_date": body.end_date}}
    old_rent = rent_for(t, (body.rent_from or date.today().isoformat())[:7])
    if body.new_rent:
        changes = [c for c in (t.get("rent_changes") or []) if c["from_month"] != body.rent_from[:7]]
        upd["$set"]["rent_changes"] = sorted(changes + [{"from_month": body.rent_from[:7], "rent": body.new_rent}], key=lambda c: c["from_month"])
    entry = {"at": now_iso(), "previous_end": t.get("end_date"), "end_date": body.end_date, "new_rent": body.new_rent, "rent_from": body.rent_from}
    upd["$push"] = {"renewals": entry}
    await db.tenancies.update_one({"_id": t["_id"]}, upd)
    emailed = None
    if body.notify and t.get("tenant_email"):
        address, sender, head = await _ctx(user.id, t)
        fmt = lambda d: date.fromisoformat(d).strftime("%d %B %Y")
        rows = _row("Tenancy term", f"{fmt(t['start_date'])} to {fmt(body.end_date)}" if body.end_date else "Rolling month-to-month (periodic)")
        rows += _row("Previous end date", fmt(t["end_date"]) if t.get("end_date") else "Rolling")
        if body.new_rent:
            rows += _row("Current rent", f"{money(old_rent, 2)} / month") + _row("New rent", f"{money(body.new_rent, 2)} / month") + _row("New rent starts", fmt(body.rent_from))
        else:
            rows += _row("Rent", f"{money(old_rent, 2)} / month (unchanged)")
        rows += _row("Rent due day", f"Day {t.get('rent_day', 1)} of each month")
        html = _wrap(f'{head}<p style="font-size:12px;letter-spacing:1px;color:#0f766e;font-weight:bold;margin:0">TENANCY RENEWAL</p>'
                     f'<h1 style="font-size:20px;margin:8px 0 12px">{E(address)}</h1><p>Hi {E(t["tenant_name"])},</p>'
                     f'<p style="line-height:1.5">We are pleased to confirm your tenancy has been {"extended" if body.end_date else "moved to a rolling periodic tenancy"}. The updated terms are below.</p>'
                     f'<table width="100%" style="border-collapse:collapse;font-size:14px;margin:12px 0">{rows}</table>'
                     f'<p style="line-height:1.5">All other terms of your tenancy agreement stay the same. Just reply to this email if you have any questions.</p><p>Kind regards,<br/>{E(sender)}</p>'
                     f'<p style="font-size:12px;color:#888;margin-top:24px">Sent by {E(EMAIL_FROM_NAME)} on behalf of {E(sender)}. This is a summary; any formal renewal agreement or notice will be sent separately.</p>')
        subject = f"Your tenancy renewal · {address}"
        try:
            await send_email(to=t["tenant_email"], subject=subject, html=html, reply_to=await owner_reply_to(user.id))
            emailed = "sent"
        except EmailError:
            emailed = "failed"
        await log_message(user.id, t["project_id"], name=t["tenant_name"], email=t["tenant_email"], channel="email", kind="tenancy_renewal", summary=subject, status=emailed)
    return {"ok": True, "emailed": emailed}
