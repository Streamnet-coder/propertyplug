"""Rental & tenancy tracker: tenancies, monthly rent log (paid/partial/late), letting expenses and a yearly net cashflow summary."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from core import db, now_iso, oid
from deps import active_pid, current_user
from models import User

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
            sched.append({"month": mo, "due_on": due_on.isoformat(), "due": t["rent"], "paid": paid, "paid_on": p.get("paid_on") if p else None, "status": status})
            monthly[mo]["due"] += t["rent"]
            monthly[mo]["received"] += paid
        arrears = sum(r["due"] - r["paid"] for r in sched if r["status"] in ("late", "partial") and r["due_on"] <= today.isoformat())
        t_out.append({**{k: v for k, v in t.items() if k not in ("_id", "user_id")}, "id": tid, "status": _tenancy_status(t, today),
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
