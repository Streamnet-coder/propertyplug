"""Owner ratings of trades after snag sign-off → a trusted trades list across all projects."""
import re
from typing import List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import db, now_iso
from deps import active_pid, current_user
from models import User

router = APIRouter()

TAGS = ("Quality work", "On time", "Tidy", "Good value", "Communicative", "Would hire again")


class RatingIn(BaseModel):
    assignee: str = Field(min_length=1, max_length=120)
    stars: int = Field(ge=1, le=5)
    tags: List[str] = Field(default_factory=list, max_length=6)
    comment: str = Field("", max_length=1000)


def rating_out(d: dict) -> dict:
    return {"id": str(d["_id"]), "assignee": d["assignee"], "stars": d["stars"], "tags": d.get("tags", []), "comment": d.get("comment", ""),
            "project_id": d["project_id"], "project_name": d.get("project_name", ""), "contact_id": d.get("contact_id"), "updated_at": d["updated_at"]}


@router.post("/trade-ratings")
async def rate_trade(body: RatingIn, user: User = Depends(current_user)):
    pid = await active_pid(user)
    lc = body.assignee.strip().lower()
    so = await db.snag_signoffs.find_one({"project_id": pid, "assignee_lc": lc})
    if not so or not so.get("owner"):
        raise HTTPException(400, "Sign off this trade's snags before rating them")
    contact = await db.contacts.find_one({"user_id": user.id, "name": {"$regex": f"^{re.escape(body.assignee.strip())}$", "$options": "i"}}, {"_id": 1})
    proj = await db.projects.find_one({"_id": ObjectId(pid)}, {"name": 1}) or {}
    await db.trade_ratings.update_one(
        {"user_id": user.id, "project_id": pid, "assignee_lc": lc},
        {"$set": {"assignee": body.assignee.strip(), "stars": body.stars, "tags": [t for t in body.tags if t in TAGS], "comment": body.comment.strip(),
                  "contact_id": str(contact["_id"]) if contact else None, "project_name": proj.get("name", ""), "updated_at": now_iso()},
         "$setOnInsert": {"created_at": now_iso()}}, upsert=True)
    return rating_out(await db.trade_ratings.find_one({"user_id": user.id, "project_id": pid, "assignee_lc": lc}))


@router.get("/trade-ratings")
async def list_ratings(project: Optional[str] = None, user: User = Depends(current_user)):
    q = {"user_id": user.id, **({"project_id": await active_pid(user)} if project == "active" else {})}
    return [rating_out(d) for d in await db.trade_ratings.find(q).sort("updated_at", -1).to_list(1000)]


@router.get("/trusted-trades")
async def trusted_trades(user: User = Depends(current_user)):
    """Per-trade averages across every project, best first."""
    out = []
    async for g in db.trade_ratings.aggregate([
        {"$match": {"user_id": user.id}},
        {"$sort": {"updated_at": -1}},
        {"$group": {"_id": "$assignee_lc", "name": {"$first": "$assignee"}, "avg": {"$avg": "$stars"}, "count": {"$sum": 1},
                    "tags": {"$push": "$tags"}, "last_comment": {"$first": "$comment"}, "contact_id": {"$first": "$contact_id"}}},
    ]):
        tags: dict = {}
        for ts in g["tags"]:
            for t in ts:
                tags[t] = tags.get(t, 0) + 1
        contact = await db.contacts.find_one({"_id": ObjectId(g["contact_id"]), "user_id": user.id}) if ObjectId.is_valid(g.get("contact_id") or "") else None
        out.append({"name": g["name"], "avg": round(g["avg"], 1), "count": g["count"], "top_tags": sorted(tags, key=tags.get, reverse=True)[:3],
                    "last_comment": g.get("last_comment", ""), "role": (contact or {}).get("role", ""), "phone": (contact or {}).get("phone", ""),
                    "email": (contact or {}).get("email", ""), "contact_id": g.get("contact_id")})
    return sorted(out, key=lambda x: (-x["avg"], -x["count"]))
