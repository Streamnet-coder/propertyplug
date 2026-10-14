from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Literal
from core import db, now_iso, oid, money
from models import User, StagePayment
from deps import current_user, active_pid

router = APIRouter()


class StagePaymentIn(BaseModel):
    quote_id: str
    label: str
    amount: float
    due_date: Optional[str] = None


async def sync_line_item_actual(q: dict, user_id: str):
    if not q.get("added_line_item_id"):
        return
    paid = sum(p["amount"] for p in await db.stage_payments.find({"quote_id": str(q["_id"]), "status": "paid"}).to_list(500))
    await db.line_items.update_one({"_id": oid(q["added_line_item_id"]), "user_id": user_id},
                                   {"$set": {"actual": round(paid, 2), "status": "Paid" if paid else "Quoted"}})


@router.get("/stage-payments")
async def list_contracts(user: User = Depends(current_user)):
    pid = await active_pid(user)
    out = []
    async for q in db.quote_requests.find({"user_id": user.id, "project_id": pid}).sort("created_at", -1):
        acc = next((e for e in q["quotes"] if e["status"] == "accepted"), None)
        if not acc:
            continue
        pays = [StagePayment.from_mongo(d).out() for d in await db.stage_payments.find({"quote_id": str(q["_id"])}).sort("created_at", 1).to_list(200)]
        paid = sum(p["amount"] for p in pays if p["status"] == "paid")
        sched = sum(p["amount"] for p in pays)
        out.append({"quote_id": str(q["_id"]), "title": q["title"], "payee": acc["name"], "phone": acc.get("phone", ""),
                    "contract_amount": acc["amount"], "paid": round(paid, 2), "scheduled": round(sched, 2),
                    "remaining": round(acc["amount"] - paid, 2), "unscheduled": round(acc["amount"] - sched, 2), "payments": pays})
    return out


@router.post("/stage-payments")
async def add_stage_payment(body: StagePaymentIn, user: User = Depends(current_user)):
    q = await db.quote_requests.find_one({"_id": oid(body.quote_id), "user_id": user.id})
    acc = next((e for e in (q or {}).get("quotes", []) if e["status"] == "accepted"), None)
    if not acc:
        raise HTTPException(404, "Accepted quote not found")
    if body.amount <= 0 or not body.label.strip():
        raise HTTPException(400, "Enter a label and an amount above £0")
    sched = sum(p["amount"] for p in await db.stage_payments.find({"quote_id": body.quote_id}).to_list(500))
    if sched + body.amount > acc["amount"] + 0.009:
        raise HTTPException(400, f"This would exceed the agreed quote by {money(sched + body.amount - acc['amount'], 2)}. "
                                 f"Only {money(acc['amount'] - sched, 2)} is left to schedule.")
    sp = StagePayment(user_id=user.id, project_id=q["project_id"], quote_id=body.quote_id, label=body.label.strip(),
                      amount=round(body.amount, 2), due_date=body.due_date or None)
    sp.id = str((await db.stage_payments.insert_one(sp.to_mongo())).inserted_id)
    return sp.out()


class PayStatusIn(BaseModel):
    status: Literal["due", "paid"]


@router.put("/stage-payments/{sid}")
async def set_payment_status(sid: str, body: PayStatusIn, user: User = Depends(current_user)):
    d = await db.stage_payments.find_one({"_id": oid(sid), "user_id": user.id})
    if not d:
        raise HTTPException(404, "Payment not found")
    await db.stage_payments.update_one({"_id": d["_id"]}, {"$set": {"status": body.status, "paid_at": now_iso() if body.status == "paid" else None}})
    await sync_line_item_actual(await db.quote_requests.find_one({"_id": oid(d["quote_id"])}) or {}, user.id)
    return StagePayment.from_mongo(await db.stage_payments.find_one({"_id": d["_id"]})).out()


@router.delete("/stage-payments/{sid}")
async def delete_stage_payment(sid: str, user: User = Depends(current_user)):
    d = await db.stage_payments.find_one({"_id": oid(sid), "user_id": user.id})
    if d:
        await db.stage_payments.delete_one({"_id": d["_id"]})
        await sync_line_item_actual(await db.quote_requests.find_one({"_id": oid(d["quote_id"])}) or {}, user.id)
    return {"ok": True}
