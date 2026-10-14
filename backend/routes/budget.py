from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Literal
from core import db, oid
from models import User, LineItem, Receipt
from deps import current_user, active_pid

router = APIRouter()


class LineItemIn(BaseModel):
    category: Literal["Hard Cost", "Soft Cost", "Contingency"]
    name: str
    budgeted: float = 0
    actual: float = 0
    supplier: str = ""
    status: str = "Planned"


@router.get("/line-items")
async def list_items(user: User = Depends(current_user)):
    docs = await db.line_items.find({"user_id": user.id, "project_id": await active_pid(user)}).sort("created_at", -1).to_list(1000)
    return [LineItem.from_mongo(d).out() for d in docs]


@router.post("/line-items")
async def create_item(body: LineItemIn, user: User = Depends(current_user)):
    li = LineItem(user_id=user.id, project_id=await active_pid(user), **body.model_dump())
    res = await db.line_items.insert_one(li.to_mongo())
    li.id = str(res.inserted_id)
    return li.out()



@router.put("/line-items/{item_id}")
async def update_item(item_id: str, body: LineItemIn, user: User = Depends(current_user)):
    r = await db.line_items.update_one({"_id": oid(item_id), "user_id": user.id}, {"$set": body.model_dump()})
    if not r.matched_count:
        raise HTTPException(404, "Not found")
    return LineItem.from_mongo(await db.line_items.find_one({"_id": oid(item_id)})).out()


@router.delete("/line-items/{item_id}")
async def delete_item(item_id: str, user: User = Depends(current_user)):
    await db.line_items.delete_one({"_id": oid(item_id), "user_id": user.id})
    return {"ok": True}


class ReceiptIn(BaseModel):
    title: str
    amount: float
    date: str
    category: str = "Hard Cost"
    supplier: str = ""
    storage_path: Optional[str] = None


@router.get("/receipts")
async def list_receipts(user: User = Depends(current_user)):
    docs = await db.receipts.find({"user_id": user.id, "project_id": await active_pid(user)}).sort("date", -1).to_list(1000)
    return [Receipt.from_mongo(d).out() for d in docs]


@router.post("/receipts")
async def create_receipt(body: ReceiptIn, user: User = Depends(current_user)):
    r = Receipt(user_id=user.id, project_id=await active_pid(user), **body.model_dump())
    res = await db.receipts.insert_one(r.to_mongo())
    r.id = str(res.inserted_id)
    return r.out()


@router.delete("/receipts/{rid}")
async def delete_receipt(rid: str, user: User = Depends(current_user)):
    await db.receipts.delete_one({"_id": oid(rid), "user_id": user.id})
    return {"ok": True}
