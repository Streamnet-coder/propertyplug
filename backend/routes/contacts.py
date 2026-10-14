from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Literal
from core import db, oid
from models import User, Contact
from deps import current_user, active_pid

router = APIRouter()


class ContactIn(BaseModel):
    kind: Literal["trade", "subcontractor", "stakeholder"]
    name: str
    role: str = ""
    phone: str = ""
    email: str = ""
    status: str = ""
    schedule: str = ""
    cost: str = ""


@router.get("/contacts")
async def list_contacts(kind: str = Query("trade"), user: User = Depends(current_user)):
    if kind != "trade" and user.plan != "pro":
        raise HTTPException(403, "Pro plan required")
    docs = await db.contacts.find({"user_id": user.id, "project_id": await active_pid(user), "kind": kind}).sort("created_at", 1).to_list(500)
    return [Contact.from_mongo(d).out() for d in docs]


@router.post("/contacts")
async def create_contact(body: ContactIn, user: User = Depends(current_user)):
    if body.kind != "trade" and user.plan != "pro":
        raise HTTPException(403, "Pro plan required")
    c = Contact(user_id=user.id, project_id=await active_pid(user), **body.model_dump())
    res = await db.contacts.insert_one(c.to_mongo())
    c.id = str(res.inserted_id)
    return c.out()


@router.delete("/contacts/{cid}")
async def delete_contact(cid: str, user: User = Depends(current_user)):
    await db.contacts.delete_one({"_id": oid(cid), "user_id": user.id})
    return {"ok": True}
