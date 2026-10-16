"""Planning applications per land plot, with decision-date reminders surfaced on the dashboard."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from core import db, now_iso, oid
from deps import active_pid, current_user
from models import User

router = APIRouter()

DATE_FIELDS = ("submitted_date", "validated_date", "consultation_end", "target_decision_date")


class PlanningIn(BaseModel):
    authority: str = ""
    reference: str = ""
    description: str = ""
    submitted_date: Optional[str] = None
    validated_date: Optional[str] = None
    consultation_end: Optional[str] = None
    target_decision_date: Optional[str] = None
    decision: Literal["pending", "approved", "refused", "withdrawn"] = "pending"
    decision_date: Optional[str] = None
    notes: str = ""

    @field_validator(*DATE_FIELDS, "decision_date")
    @classmethod
    def iso_date(cls, v):
        if not v:
            return None
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError("Use date format YYYY-MM-DD")
        return v


def out(d: dict) -> dict:
    o = {k: v for k, v in d.items() if k not in ("_id", "user_id")}
    o["id"] = str(d["_id"])
    t = d.get("target_decision_date")
    o["days_to_decision"] = (date.fromisoformat(t) - date.today()).days if t and d.get("decision") == "pending" else None
    return o


@router.get("/planning")
async def list_planning(user: User = Depends(current_user)):
    docs = await db.planning_apps.find({"user_id": user.id, "project_id": await active_pid(user)}).sort("created_at", -1).to_list(200)
    return [out(d) for d in docs]


@router.post("/planning")
async def create_planning(body: PlanningIn, user: User = Depends(current_user)):
    if not (body.reference.strip() or body.description.strip()):
        raise HTTPException(400, "Enter a reference number or description")
    doc = {**body.model_dump(), "user_id": user.id, "project_id": await active_pid(user), "created_at": now_iso()}
    doc["_id"] = (await db.planning_apps.insert_one(doc)).inserted_id
    return out(doc)


@router.put("/planning/{aid}")
async def update_planning(aid: str, body: PlanningIn, user: User = Depends(current_user)):
    r = await db.planning_apps.update_one({"_id": oid(aid), "user_id": user.id}, {"$set": body.model_dump()})
    if not r.matched_count:
        raise HTTPException(404, "Not found")
    return out(await db.planning_apps.find_one({"_id": oid(aid)}))


@router.delete("/planning/{aid}")
async def delete_planning(aid: str, user: User = Depends(current_user)):
    await db.planning_apps.delete_one({"_id": oid(aid), "user_id": user.id})
    return {"ok": True}
