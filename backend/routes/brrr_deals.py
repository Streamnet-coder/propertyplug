"""Saved BRRR deals: named calculator inputs (incl. bridging and time to refinance) so investors can compare deals side by side."""
import math

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from core import db, now_iso, oid
from deps import pro_user
from models import User

router = APIRouter()

KEYS = ("purchase", "fees", "refurb", "valuation", "ltv", "rate", "rent", "costs", "months", "bridge_pct", "bridge_rate", "bridge_fee", "holding")
MAX_DEALS = 50


class DealIn(BaseModel):
    name: str = Field(max_length=80)
    inputs: dict[str, float]

    @field_validator("name")
    @classmethod
    def name_req(cls, v):
        if not v.strip():
            raise ValueError("Give the deal a name")
        return v.strip()

    @field_validator("inputs")
    @classmethod
    def clean(cls, v):
        bad = set(v) - set(KEYS)
        if bad:
            raise ValueError(f"Unknown fields: {', '.join(sorted(bad))}")
        if any(not math.isfinite(x) or x < 0 for x in v.values()):
            raise ValueError("Figures must be zero or more")
        return {k: float(v.get(k, 0)) for k in KEYS}


def _out(d: dict) -> dict:
    return {"id": str(d["_id"]), "name": d["name"], "inputs": d["inputs"], "created_at": d["created_at"], "updated_at": d.get("updated_at", d["created_at"])}


@router.get("/brrr/deals")
async def list_deals(user: User = Depends(pro_user)):
    return [_out(d) async for d in db.brrr_deals.find({"user_id": user.id}).sort("updated_at", -1)]


@router.post("/brrr/deals")
async def create_deal(body: DealIn, user: User = Depends(pro_user)):
    if await db.brrr_deals.count_documents({"user_id": user.id}) >= MAX_DEALS:
        raise HTTPException(400, f"You can save up to {MAX_DEALS} deals. Delete one to save another")
    at = now_iso()
    doc = {"user_id": user.id, "name": body.name, "inputs": body.inputs, "created_at": at, "updated_at": at}
    doc["_id"] = (await db.brrr_deals.insert_one(doc)).inserted_id
    return _out(doc)


@router.put("/brrr/deals/{did}")
async def update_deal(did: str, body: DealIn, user: User = Depends(pro_user)):
    r = await db.brrr_deals.find_one_and_update({"_id": oid(did), "user_id": user.id},
                                                 {"$set": {"name": body.name, "inputs": body.inputs, "updated_at": now_iso()}}, return_document=True)
    if not r:
        raise HTTPException(404, "Deal not found")
    return _out(r)


@router.delete("/brrr/deals/{did}")
async def delete_deal(did: str, user: User = Depends(pro_user)):
    await db.brrr_deals.delete_one({"_id": oid(did), "user_id": user.id})
    return {"ok": True}
