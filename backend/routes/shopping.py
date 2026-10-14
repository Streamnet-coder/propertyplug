from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional

from datetime import datetime, timezone

from core import BaseDocument, db, now_iso, oid
from deps import active_pid, current_user
from models import Receipt, User

router = APIRouter()


class ShoppingItem(BaseDocument):
    user_id: str
    project_id: str
    line_item_id: Optional[str] = None
    name: str
    supplier: str = ""
    qty: str = ""
    est_cost: float = 0
    checked: bool = False
    checked_at: Optional[str] = None
    actual_cost: Optional[float] = None
    receipt_id: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)


class ShoppingIn(BaseModel):
    name: str
    supplier: str = ""
    qty: str = ""
    est_cost: float = 0


class ShoppingUpdate(BaseModel):
    name: Optional[str] = None
    supplier: Optional[str] = None
    qty: Optional[str] = None
    est_cost: Optional[float] = None
    checked: Optional[bool] = None


class PurchaseIn(BaseModel):
    amount: float = Field(gt=0)
    date: Optional[str] = None


class FromItemsIn(BaseModel):
    line_item_ids: List[str]


@router.get("/shopping")
async def list_shopping(user: User = Depends(current_user)):
    docs = await db.shopping_items.find({"user_id": user.id, "project_id": await active_pid(user)}).sort("created_at", 1).to_list(1000)
    return [ShoppingItem.from_mongo(d).out() for d in docs]


@router.post("/shopping")
async def add_shopping(body: ShoppingIn, user: User = Depends(current_user)):
    if not body.name.strip():
        raise HTTPException(400, "Item name is required")
    it = ShoppingItem(user_id=user.id, project_id=await active_pid(user), **{**body.model_dump(), "name": body.name.strip(), "supplier": body.supplier.strip()})
    it.id = str((await db.shopping_items.insert_one(it.to_mongo())).inserted_id)
    return it.out()


@router.post("/shopping/from-line-items")
async def add_from_line_items(body: FromItemsIn, user: User = Depends(current_user)):
    pid = await active_pid(user)
    items = await db.line_items.find({"_id": {"$in": [oid(i) for i in body.line_item_ids]}, "user_id": user.id, "project_id": pid}).to_list(500)
    if not items:
        raise HTTPException(400, "Choose at least one budget item")
    existing = {d["line_item_id"] for d in await db.shopping_items.find(
        {"project_id": pid, "line_item_id": {"$in": [str(i["_id"]) for i in items]}}, {"line_item_id": 1}).to_list(500)}
    new = [ShoppingItem(user_id=user.id, project_id=pid, line_item_id=str(i["_id"]), name=i["name"], supplier=i.get("supplier", ""),
                        est_cost=max(0, i.get("budgeted", 0) - i.get("actual", 0)) or i.get("budgeted", 0)).to_mongo()
           for i in items if str(i["_id"]) not in existing]
    if new:
        await db.shopping_items.insert_many(new)
    return {"added": len(new), "skipped": len(items) - len(new)}


@router.put("/shopping/{sid}")
async def update_shopping(sid: str, body: ShoppingUpdate, user: User = Depends(current_user)):
    upd = body.model_dump(exclude_unset=True)
    if "checked" in upd:
        upd["checked_at"] = now_iso() if upd["checked"] else None
        if not upd["checked"]:
            # Un-ticking undoes the logged purchase so spend isn't counted twice
            doc = await db.shopping_items.find_one({"_id": oid(sid), "user_id": user.id}, {"receipt_id": 1})
            if doc and doc.get("receipt_id"):
                await db.receipts.delete_one({"_id": oid(doc["receipt_id"]), "user_id": user.id})
            upd.update({"receipt_id": None, "actual_cost": None})
    r = await db.shopping_items.update_one({"_id": oid(sid), "user_id": user.id}, {"$set": upd})
    if not r.matched_count:
        raise HTTPException(404, "Item not found")
    return ShoppingItem.from_mongo(await db.shopping_items.find_one({"_id": oid(sid)})).out()


@router.post("/shopping/{sid}/purchase")
async def purchase_shopping(sid: str, body: PurchaseIn, user: User = Depends(current_user)):
    """Tick an item off and log the actual price paid as a receipt against the budget."""
    doc = await db.shopping_items.find_one({"_id": oid(sid), "user_id": user.id})
    if not doc:
        raise HTTPException(404, "Item not found")
    category = "Hard Cost"
    if doc.get("line_item_id"):
        li = await db.line_items.find_one({"_id": oid(doc["line_item_id"])}, {"category": 1})
        category = (li or {}).get("category", category)
    rec = {"title": doc["name"], "amount": round(body.amount, 2), "date": body.date or datetime.now(timezone.utc).date().isoformat(),
           "category": category, "supplier": doc.get("supplier", ""), "storage_path": None,
           "shopping_item_id": sid, "line_item_id": doc.get("line_item_id")}
    if doc.get("receipt_id"):
        await db.receipts.update_one({"_id": oid(doc["receipt_id"])}, {"$set": rec})
        rid = doc["receipt_id"]
    else:
        rid = str((await db.receipts.insert_one(Receipt(user_id=user.id, project_id=doc["project_id"], **rec).to_mongo())).inserted_id)
    await db.shopping_items.update_one({"_id": doc["_id"]}, {"$set": {"checked": True, "checked_at": now_iso(), "actual_cost": rec["amount"], "receipt_id": rid}})
    return ShoppingItem.from_mongo(await db.shopping_items.find_one({"_id": doc["_id"]})).out()


@router.delete("/shopping/checked")
async def clear_checked(user: User = Depends(current_user)):
    r = await db.shopping_items.delete_many({"user_id": user.id, "project_id": await active_pid(user), "checked": True})
    return {"deleted": r.deleted_count}


@router.delete("/shopping/{sid}")
async def delete_shopping(sid: str, user: User = Depends(current_user)):
    await db.shopping_items.delete_one({"_id": oid(sid), "user_id": user.id})
    return {"ok": True}
