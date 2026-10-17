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


def _tenancy_status(t: dict, today: date):
    s = date.fromisoformat(t["start_date"])
    e = date.fromisoformat(t["end_date"]) if t.get("end_date") else None
    return "upcoming" if s > today else "ended" if e and e < today else "active"


async def _scoped(user: User):
    return {"user_id": user.id, "project_id": await active_pid(user)}


@router.get("/rentals")
async def rentals(year: Optional[int] = None, user: User = Depends(current_user)):
    today = date.today()
    year = year or today.year
    q = await _scoped(user)
    tenancies = await db.tenancies.find(q).sort("start_date", -1).to_list(100)
    pays = {(p["tenancy_id"], p["month"]): p for p in await db.rent_payments.find({**q, "month": {"$regex": f"^{year}-"}}).to_list(2000)}
    reminded = {(r["tenancy_id"], r["month"]): r["sent_at"] for r in await db.rent_reminders.find({**q, "month": {"$regex": f"^{year}-"}}).sort("sent_at", 1).to_list(2000)}
    expenses = await db.rental_expenses.find({**q, "date": {"$regex": f"^{year}-"}}).sort("date", -1).to_list(1000)

    monthly = {f"{year}-{m:02d}": {"month": f"{year}-{m:02d}", "due": 0.0, "received": 0.0, "expenses": 0.0} for m in range(1, 13)}
    t_out = []
    for t in tenancies:
        tid = str(t["_id"])
        sched = []
        for mo in _months(date.fromisoformat(t["start_date"]), date.fromisoformat(t["end_date"]) if t.get("end_date") else None, year):
            due_on = date(int(mo[:4]), int(mo[5:]), t.get("rent_day", 1))
            p = pays.get((tid, mo))
            paid = float(p["paid_amount"]) if p else 0.0
            status = "paid" if paid >= t["rent"] else "partial" if paid > 0 else "late" if due_on < today else "due"
            sched.append({"month": mo, "due_on": due_on.isoformat(), "due": t["rent"], "paid": paid, "paid_on": p.get("paid_on") if p else None, "status": status,
                          "reminded_at": reminded.get((tid, mo))})
            monthly[mo]["due"] += t["rent"]
            monthly[mo]["received"] += paid
        arrears = sum(r["due"] - r["paid"] for r in sched if r["status"] in ("late", "partial") and r["due_on"] <= today.isoformat())
        st = _tenancy_status(t, today)
        end = t.get("end_date")
        t_out.append({**{k: v for k, v in t.items() if k not in ("_id", "user_id")}, "id": tid, "status": st,
                      "deposit_protected": bool(t.get("deposit_protected")),
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
            "active_rent": sum(t["rent"] for t in t_out if t["status"] == "active"),
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
    await db.rent_payments.update_one(
        {"tenancy_id": tid, "month": month, "user_id": user.id},
        {"$set": {"paid_amount": body.paid_amount, "paid_on": body.paid_on or date.today().isoformat(), "project_id": t["project_id"], "updated_at": now_iso()}},
        upsert=True)
    return {"ok": True}


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
    if paid >= t["rent"]:
        raise HTTPException(400, "This month is already paid")
    due_on = date(int(body.month[:4]), int(body.month[5:]), t.get("rent_day", 1))
    late = due_on < date.today()
    proj = await db.projects.find_one({"_id": ObjectId(t["project_id"])}, {"address": 1, "name": 1, "currency": 1})
    CURRENCY.set((proj or {}).get("currency") or "GBP")
    owner = await db.users.find_one({"_id": ObjectId(user.id)}, {"name": 1, "branding": 1})
    sender = ((owner or {}).get("branding") or {}).get("company_name") or (owner or {}).get("name", "Your landlord")
    address = (proj or {}).get("address") or (proj or {}).get("name") or "Your rental"
    owed = money(t["rent"] - paid, 2) if late and paid else money(t["rent"], 2)
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
