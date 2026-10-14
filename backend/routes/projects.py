from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from bson import ObjectId
from core import db, oid
from models import User, Budget, Project
from deps import current_user, pro_user, active_pid, get_project_doc
from seed import seed_milestones

router = APIRouter()


@router.get("/project")
async def get_project(user: User = Depends(current_user)):
    return await project_summary(await get_project_doc(user))


async def project_summary(p: Project) -> dict:
    items = await db.line_items.find({"project_id": p.id}).to_list(1000)
    receipts = await db.receipts.find({"project_id": p.id}).to_list(1000)
    spent = {"hard": 0.0, "soft": 0.0, "contingency": 0.0}
    key = {"Hard Cost": "hard", "Soft Cost": "soft", "Contingency": "contingency"}
    for i in items:
        spent[key[i["category"]]] += i.get("actual", 0)
    for r in receipts:
        spent[key.get(r.get("category"), "hard")] += r.get("amount", 0)
    out = p.out()
    out.pop("comparables", None)
    total_budget = p.budget.hard + p.budget.soft + p.budget.contingency
    total_spent = sum(spent.values())
    ms = await db.milestones.find({"project_id": p.id}).sort("order", 1).to_list(200)
    current = next((m for m in ms if m["status"] == "in_progress"), None) or next((m for m in ms if m["status"] == "todo"), None)
    out.update({"spent": spent, "total_budget": total_budget, "total_spent": round(total_spent, 2),
                "line_item_count": len(items), "receipt_count": len(receipts),
                "milestones_total": len(ms), "milestones_done": sum(1 for m in ms if m["status"] == "done"),
                "current_stage": current["name"] if current else ("Complete" if ms else None),
                "rent_yield": rent_yield(p, total_budget)})
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


@router.put("/project")
async def update_project(body: ProjectUpdate, user: User = Depends(current_user)):
    upd = body.model_dump(exclude_none=True)
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


@router.get("/projects")
async def list_projects(user: User = Depends(current_user)):
    pid = await active_pid(user)
    docs = await db.projects.find({"user_id": user.id}).sort("_id", 1).to_list(200)
    out = []
    for d in docs:
        s = await project_summary(Project.from_mongo(d))
        s["active"] = s["id"] == pid
        out.append(s)
    return out


@router.post("/projects")
async def create_project(body: ProjectCreate, user: User = Depends(current_user)):
    if not body.name.strip():
        raise HTTPException(400, "Project name is required")
    p = Project(user_id=user.id, **body.model_dump())
    p.id = str((await db.projects.insert_one(p.to_mongo())).inserted_id)
    await seed_milestones(user.id, p.id)
    await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"active_project_id": p.id}})
    return await project_summary(p)


@router.post("/projects/{pid}/activate")
async def activate_project(pid: str, user: User = Depends(current_user)):
    doc = await db.projects.find_one({"_id": oid(pid), "user_id": user.id})
    if not doc:
        raise HTTPException(404, "Project not found")
    await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"active_project_id": pid}})
    return await project_summary(Project.from_mongo(doc))


@router.delete("/projects/{pid}")
async def delete_project(pid: str, user: User = Depends(current_user)):
    if await db.projects.count_documents({"user_id": user.id}) <= 1:
        raise HTTPException(400, "You need at least one project")
    r = await db.projects.delete_one({"_id": oid(pid), "user_id": user.id})
    if not r.deleted_count:
        raise HTTPException(404, "Project not found")
    for coll in (db.line_items, db.contacts, db.receipts, db.media, db.milestones, db.quote_requests, db.stage_payments, db.snags, db.snag_links, db.shopping_items):
        await coll.delete_many({"user_id": user.id, "project_id": pid})
    if user.active_project_id == pid:
        await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"active_project_id": None}})
    return {"ok": True}
