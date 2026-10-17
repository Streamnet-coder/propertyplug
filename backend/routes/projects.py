from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from datetime import date
from typing import List, Literal, Optional
from bson import ObjectId
from core import db, oid
from models import User, Budget, Currency, Project
from deps import current_user, effective, pro_user, real_user, active_pid, get_project_doc
from seed import seed_milestones

router = APIRouter()


@router.get("/project")
async def get_project(user: User = Depends(current_user)):
    return await project_summary(await get_project_doc(user))


async def project_summary(p: Project) -> dict:
    return (await project_summaries([p]))[0]


async def project_summaries(projects: list) -> list:
    """Summaries for many projects using 3 aggregate queries in total (no per-project fan-out)."""
    pids = [p.id for p in projects]
    key = {"Hard Cost": "hard", "Soft Cost": "soft", "Contingency": "contingency"}
    spent = {pid: {"hard": 0.0, "soft": 0.0, "contingency": 0.0} for pid in pids}
    counts = {pid: {"items": 0, "receipts": 0} for pid in pids}
    for coll, field, kind in ((db.line_items, "$actual", "items"), (db.receipts, "$amount", "receipts")):
        async for g in coll.aggregate([{"$match": {"project_id": {"$in": pids}}},
                                       {"$group": {"_id": {"p": "$project_id", "c": "$category"}, "sum": {"$sum": {"$ifNull": [field, 0]}}, "n": {"$sum": 1}}}]):
            pid = g["_id"]["p"]
            spent[pid][key.get(g["_id"].get("c"), "hard")] += g["sum"]
            counts[pid][kind] += g["n"]
    ms_by: dict = {pid: [] for pid in pids}
    async for m in db.milestones.find({"project_id": {"$in": pids}}, {"project_id": 1, "status": 1, "name": 1, "order": 1}).sort("order", 1):
        ms_by[m["project_id"]].append(m)
    out = []
    for p in projects:
        ms = ms_by[p.id]
        o = p.out()
        o.pop("comparables", None)
        o.pop("geocoded_for", None)
        total_budget = p.budget.hard + p.budget.soft + p.budget.contingency
        current = next((m for m in ms if m["status"] == "in_progress"), None) or next((m for m in ms if m["status"] == "todo"), None)
        o.update({"spent": spent[p.id], "total_budget": total_budget, "total_spent": round(sum(spent[p.id].values()), 2),
                  "line_item_count": counts[p.id]["items"], "receipt_count": counts[p.id]["receipts"],
                  "milestones_total": len(ms), "milestones_done": sum(1 for m in ms if m["status"] == "done"),
                  "current_stage": current["name"] if current else ("Complete" if ms else None),
                  "rent_yield": rent_yield(p, total_budget), "home_finance": home_finance(p, total_budget)})
        out.append(o)
    return out


def rent_yield(p: Project, total_budget: float) -> dict:
    invested = p.purchase_price + total_budget
    refi = p.estimated_valuation * p.refinance_ltv / 100
    mortgage = refi * p.refinance_rate / 100 / 12
    annual_rent = p.monthly_rent * 12
    return {"gross_yield": round(annual_rent / p.estimated_valuation * 100, 2) if p.estimated_valuation else 0,
            "yield_on_cost": round(annual_rent / invested * 100, 2) if invested else 0,
            "invested": round(invested, 2), "refinance_amount": round(refi, 2),
            "cash_left_in": round(invested - refi, 2), "monthly_mortgage": round(mortgage, 2),
            "monthly_cashflow": round(p.monthly_rent - mortgage, 2)}


def monthly_payment(loan: float, rate: float, years: int, kind: str) -> float:
    r, n = rate / 100 / 12, max(1, years) * 12
    if kind == "interest_only":
        return loan * r
    return loan / n if r == 0 else loan * r / (1 - (1 + r) ** -n)


def home_finance(p: Project, total_budget: float) -> dict:
    """Personal-home mortgage view: payments, equity before/after the refurb, and remortgaging to fund it."""
    loan = max(0.0, p.purchase_price - p.deposit)
    n = max(1, p.mortgage_term) * 12
    pay = monthly_payment(loan, p.mortgage_rate, p.mortgage_term, p.mortgage_type)
    total_interest = pay * n - (loan if p.mortgage_type == "repayment" else 0)
    value = p.estimated_valuation or p.purchase_price
    max_loan = value * p.remortgage_ltv / 100
    headroom = max(0.0, max_loan - loan)
    borrow = min(headroom, total_budget)
    new_loan = loan + borrow
    new_pay = monthly_payment(new_loan, p.mortgage_rate, p.mortgage_term, p.mortgage_type)
    r2 = lambda x: round(x, 2)
    scen = []
    for i, sc in enumerate(p.remortgage_scenarios[:3]):
        pay_i = monthly_payment(new_loan, sc["rate"], p.mortgage_term, p.mortgage_type)
        scen.append({"label": sc.get("label") or f"Option {i + 1}", "rate": sc["rate"], "fee": sc.get("fee", 0), "monthly_payment": r2(pay_i),
                     "vs_current": r2(pay_i - new_pay), "two_year_cost": r2(pay_i * 24 + sc.get("fee", 0))})
    if scen:
        best = min(scen, key=lambda x: x["monthly_payment"])
        best_2y = min(scen, key=lambda x: x["two_year_cost"])
        for x in scen:
            x["best_monthly"], x["best_two_year"] = x is best, x is best_2y
    days_left = (date.fromisoformat(p.fixed_rate_end) - date.today()).days if p.fixed_rate_end else None
    return {"fixed_rate_end": p.fixed_rate_end, "fixed_days_left": days_left, "scenarios": scen,"loan": r2(loan), "ltv_now": r2(loan / p.purchase_price * 100) if p.purchase_price else 0,
            "ltv_after": r2(loan / value * 100) if value else 0, "monthly_payment": r2(pay), "total_interest": r2(total_interest),
            "equity_now": r2(p.purchase_price - loan), "equity_after": r2(value - loan),
            "value_added": r2(value - p.purchase_price), "net_value_added": r2(value - p.purchase_price - total_budget),
            "remortgage": {"max_loan": r2(max_loan), "headroom": r2(headroom), "borrow_for_refurb": r2(borrow),
                           "covers_refurb": headroom >= total_budget, "shortfall": r2(max(0.0, total_budget - headroom)),
                           "new_loan": r2(new_loan), "new_payment": r2(new_pay), "payment_increase": r2(new_pay - pay),
                           "new_ltv": r2(new_loan / value * 100) if value else 0, "equity_after": r2(value - new_loan)}}


def target_for(property_type: str, purpose: str) -> str:
    return "Land Investment" if property_type == "land" else "Home Renovation" if purpose == "personal" else "BRRR Refurbishment"


class Scenario(BaseModel):
    label: str = Field("", max_length=40)
    rate: float = Field(gt=0, le=30)
    fee: float = Field(0, ge=0)


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    finish_type: Optional[str] = None
    purchase_price: Optional[float] = None
    estimated_valuation: Optional[float] = None
    monthly_rent: Optional[float] = None
    refinance_ltv: Optional[float] = None
    refinance_rate: Optional[float] = None
    budget: Optional[Budget] = None
    currency: Optional[Currency] = None
    property_type: Optional[Literal["residential", "land"]] = None
    purpose: Optional[Literal["investment", "personal"]] = None
    deposit: Optional[float] = Field(None, ge=0)
    mortgage_rate: Optional[float] = Field(None, ge=0, le=30)
    mortgage_term: Optional[int] = Field(None, ge=1, le=40)
    mortgage_type: Optional[Literal["repayment", "interest_only"]] = None
    remortgage_ltv: Optional[float] = Field(None, ge=0, le=100)
    fixed_rate_end: Optional[str] = None
    remortgage_scenarios: Optional[List[Scenario]] = Field(None, max_length=3)
    plot_size: Optional[float] = None
    plot_unit: Optional[Literal["acres", "hectares"]] = None
    planning_status: Optional[Literal["none", "applied", "granted"]] = None
    intended_use: Optional[str] = None
    value_without_planning: Optional[float] = None
    value_with_planning: Optional[float] = None
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)
    clear_pin: bool = False


@router.put("/project")
async def update_project(body: ProjectUpdate, user: User = Depends(current_user)):
    upd = body.model_dump(exclude_none=True)
    clear = upd.pop("clear_pin", False)
    if "fixed_rate_end" in body.model_fields_set:
        if body.fixed_rate_end:
            try:
                date.fromisoformat(body.fixed_rate_end)
            except ValueError:
                raise HTTPException(400, "Fixed-rate end date must be YYYY-MM-DD")
        upd["fixed_rate_end"] = body.fixed_rate_end or None
    if "lat" in upd or "lon" in upd:
        if "lat" not in upd or "lon" not in upd:
            raise HTTPException(400, "Enter both latitude and longitude")
        upd["pin_manual"] = True
    elif clear:
        upd.update({"lat": None, "lon": None, "pin_manual": False, "geocoded_for": None})
    pid = await active_pid(user)
    if "property_type" in upd or "purpose" in upd:
        cur = await db.projects.find_one({"_id": ObjectId(pid)}, {"property_type": 1, "purpose": 1}) or {}
        upd["target_type"] = target_for(upd.get("property_type", cur.get("property_type", "residential")), upd.get("purpose", cur.get("purpose", "investment")))
    if upd:
        await db.projects.update_one({"_id": ObjectId(pid)}, {"$set": upd})
    return await get_project(user)


@router.get("/project/comparables")
async def comparables(user: User = Depends(pro_user)):
    p = await get_project_doc(user)
    return [c.model_dump() for c in p.comparables]


class ProjectCreate(BaseModel):
    name: str
    address: str = ""
    target_type: str = "BRRR Refurbishment"
    finish_type: str = "Medium Finish"
    purchase_price: float = 0
    estimated_valuation: float = 0
    monthly_rent: float = 0
    refinance_ltv: float = 75
    refinance_rate: float = 5.5
    budget: Budget = Budget()
    currency: Currency = "GBP"
    property_type: Literal["residential", "land"] = "residential"
    purpose: Literal["investment", "personal"] = "investment"
    deposit: float = Field(0, ge=0)
    mortgage_rate: float = Field(4.5, ge=0, le=30)
    mortgage_term: int = Field(25, ge=1, le=40)
    mortgage_type: Literal["repayment", "interest_only"] = "repayment"
    remortgage_ltv: float = Field(85, ge=0, le=100)
    plot_size: float = 0
    plot_unit: Literal["acres", "hectares"] = "acres"
    planning_status: Literal["none", "applied", "granted"] = "none"
    intended_use: str = ""
    value_without_planning: float = 0
    value_with_planning: float = 0
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)


async def shared_owners(user: User) -> dict:
    """{owner_id: owner_name} for every owner who made this person a co-owner."""
    ids = [c["owner_id"] async for c in db.co_owners.find({"email": user.email}, {"owner_id": 1})]
    return {str(u["_id"]): u["name"] async for u in db.users.find({"_id": {"$in": [ObjectId(i) for i in ids]}}, {"name": 1})}


async def accessible_projects(user: User) -> list:
    """The person's own projects followed by all projects of owners who share with them (current and future)."""
    owners = await shared_owners(user)
    docs = await db.projects.find({"user_id": {"$in": [user.id, *owners]}}, {"comparables": 0}).sort("_id", 1).to_list(1000)
    docs.sort(key=lambda d: d["user_id"] != user.id)
    out = await project_summaries([Project.from_mongo(d) for d in docs])
    for d, s in zip(docs, out):
        s["shared"] = d["user_id"] != user.id
        s["owner_name"] = owners.get(d["user_id"]) if s["shared"] else None
    return out


@router.get("/projects")
async def list_projects(user: User = Depends(real_user)):
    pid = await active_pid(await effective(user))
    out = await accessible_projects(user)
    for s in out:
        s["active"] = s["id"] == pid
    return out


@router.post("/projects")
async def create_project(body: ProjectCreate, user: User = Depends(real_user)):
    if not body.name.strip():
        raise HTTPException(400, "Project name is required")
    if body.property_type == "land" or body.purpose == "personal":
        body.target_type = target_for(body.property_type, body.purpose)
    p = Project(user_id=user.id, pin_manual=body.lat is not None and body.lon is not None, **body.model_dump())
    p.id = str((await db.projects.insert_one(p.to_mongo())).inserted_id)
    await seed_milestones(user.id, p.id)
    await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"active_project_id": p.id, "acting_owner_id": None}})
    return await project_summary(p)


@router.post("/projects/{pid}/activate")
async def activate_project(pid: str, user: User = Depends(real_user)):
    doc = await db.projects.find_one({"_id": oid(pid)})
    if not doc or (doc["user_id"] != user.id and doc["user_id"] not in await shared_owners(user)):
        raise HTTPException(404, "Project not found")
    acting = None if doc["user_id"] == user.id else doc["user_id"]
    await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"active_project_id": pid, "acting_owner_id": acting}})
    return await project_summary(Project.from_mongo(doc))


@router.delete("/projects/{pid}")
async def delete_project(pid: str, user: User = Depends(real_user)):
    if not await db.projects.find_one({"_id": oid(pid), "user_id": user.id}, {"_id": 1}):
        if await db.projects.find_one({"_id": oid(pid)}, {"_id": 1}):
            raise HTTPException(403, "Only the project owner can delete this project")
        raise HTTPException(404, "Project not found")
    if await db.projects.count_documents({"user_id": user.id}) <= 1:
        raise HTTPException(400, "You need at least one project")
    r = await db.projects.delete_one({"_id": oid(pid), "user_id": user.id})
    if not r.deleted_count:
        raise HTTPException(404, "Project not found")
    for coll in (db.line_items, db.contacts, db.receipts, db.media, db.milestones, db.quote_requests, db.stage_payments, db.snags, db.snag_links, db.shopping_items, db.documents, db.doc_folders, db.planning_apps, db.tenancies, db.rent_payments, db.rental_expenses, db.rent_reminders, db.compare_links):
        await coll.delete_many({"user_id": user.id, "project_id": pid})
    for coll in (db.portal_members, db.portal_activity, db.portal_questions, db.project_activity, db.portal_doc_requests):
        await coll.delete_many({"owner_id": user.id, "project_id": pid})
    if user.active_project_id == pid:
        await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"active_project_id": None}})
    return {"ok": True}
