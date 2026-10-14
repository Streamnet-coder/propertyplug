from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Literal
from core import db, now_iso, oid
from models import User, Milestone
from deps import current_user, active_pid

router = APIRouter()


class MilestoneIn(BaseModel):
    name: str
    target_date: Optional[str] = None


class MilestoneUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[Literal["todo", "in_progress", "done"]] = None
    target_date: Optional[str] = None
    notes: Optional[str] = None


@router.get("/milestones")
async def list_milestones(user: User = Depends(current_user)):
    docs = await db.milestones.find({"user_id": user.id, "project_id": await active_pid(user)}).sort("order", 1).to_list(200)
    return [Milestone.from_mongo(d).out() for d in docs]


@router.post("/milestones")
async def create_milestone(body: MilestoneIn, user: User = Depends(current_user)):
    if not body.name.strip():
        raise HTTPException(400, "Stage name is required")
    pid = await active_pid(user)
    last = await db.milestones.find_one({"project_id": pid}, sort=[("order", -1)])
    m = Milestone(user_id=user.id, project_id=pid, name=body.name.strip(), target_date=body.target_date or None,
                  order=(last["order"] + 1) if last else 0)
    m.id = str((await db.milestones.insert_one(m.to_mongo())).inserted_id)
    return m.out()


@router.put("/milestones/{mid}")
async def update_milestone(mid: str, body: MilestoneUpdate, user: User = Depends(current_user)):
    upd = body.model_dump(exclude_unset=True)
    if "status" in upd:
        upd["completed_at"] = now_iso() if upd["status"] == "done" else None
    if "target_date" in upd and not upd["target_date"]:
        upd["target_date"] = None
    r = await db.milestones.update_one({"_id": oid(mid), "user_id": user.id}, {"$set": upd})
    if not r.matched_count:
        raise HTTPException(404, "Not found")
    return Milestone.from_mongo(await db.milestones.find_one({"_id": oid(mid)})).out()


@router.delete("/milestones/{mid}")
async def delete_milestone(mid: str, user: User = Depends(current_user)):
    await db.milestones.delete_one({"_id": oid(mid), "user_id": user.id})
    return {"ok": True}
