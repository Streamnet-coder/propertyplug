from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Literal, Optional
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
                  "rent_yield": rent_yield(p, total_budget)})
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
    if "lat" in upd or "lon" in upd:
        if "lat" not in upd or "lon" not in upd:
            raise HTTPException(400, "Enter both latitude and longitude")
        upd["pin_manual"] = True
    elif clear:
        upd.update({"lat": None, "lon": None, "pin_manual": False, "geocoded_for": None})
    if "property_type" in upd:
        upd["target_type"] = "Land Investment" if upd["property_type"] == "land" else "BRRR Refurbishment"
    pid = await active_pid(user)
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
    if body.property_type == "land":
        body.target_type = "Land Investment"
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
    for coll in (db.line_items, db.contacts, db.receipts, db.media, db.milestones, db.quote_requests, db.stage_payments, db.snags, db.snag_links, db.shopping_items, db.documents, db.doc_folders, db.planning_apps):
        await coll.delete_many({"user_id": user.id, "project_id": pid})
    for coll in (db.portal_members, db.portal_activity, db.portal_questions):
        await coll.delete_many({"owner_id": user.id, "project_id": pid})
    if user.active_project_id == pid:
        await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"active_project_id": None}})
    return {"ok": True}
