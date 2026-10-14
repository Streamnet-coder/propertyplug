from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from core import db
from deps import active_pid, current_user
from models import User

router = APIRouter()


def week_bounds(offset: int):
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=today.weekday()) - timedelta(weeks=offset)
    return start, start + timedelta(days=6)


async def week_spend(pid: str, start, end) -> dict:
    s, e = start.isoformat(), end.isoformat()
    receipts = await db.receipts.find({"project_id": pid, "date": {"$gte": s, "$lte": e}}).sort("amount", -1).to_list(500)
    pays = await db.stage_payments.find({"project_id": pid, "status": "paid", "paid_at": {"$gte": s, "$lt": (end + timedelta(days=1)).isoformat()}}).to_list(500)
    r_total, p_total = sum(r["amount"] for r in receipts), sum(p["amount"] for p in pays)
    return {"total": round(r_total + p_total, 2), "receipts_total": round(r_total, 2), "receipts_count": len(receipts),
            "payments_total": round(p_total, 2), "payments_count": len(pays),
            "top": [{"title": r["title"], "supplier": r.get("supplier", ""), "amount": r["amount"], "date": r["date"]} for r in receipts[:3]]}


@router.get("/digest")
async def weekly_digest(week: int = Query(0, ge=0, le=52), user: User = Depends(current_user)):
    pid = await active_pid(user)
    start, end = week_bounds(week)
    ps, pe = week_bounds(week + 1)
    lo, hi = start.isoformat(), (end + timedelta(days=1)).isoformat()
    spend = await week_spend(pid, start, end)
    prev = await week_spend(pid, ps, pe)
    fixed = await db.snags.find({"project_id": pid, "status": "fixed", "fixed_at": {"$gte": lo, "$lt": hi}}).sort("fixed_at", -1).to_list(200)
    opened = await db.snags.count_documents({"project_id": pid, "created_at": {"$gte": lo, "$lt": hi}})
    open_now = await db.snags.count_documents({"project_id": pid, "status": "open"})
    ms = await db.milestones.find({"project_id": pid, "status": "done", "completed_at": {"$gte": lo, "$lt": hi}}).sort("completed_at", 1).to_list(100)
    nxt = await db.milestones.find_one({"project_id": pid, "status": {"$ne": "done"}}, sort=[("order", 1)])
    return {
        "week_start": start.isoformat(), "week_end": end.isoformat(), "week": week,
        "spend": spend, "prev_spend": prev["total"],
        "snags_fixed": [{"id": str(x["_id"]), "room": x["room"], "description": x["description"], "fixed_by": x.get("fixed_by")} for x in fixed],
        "snags_opened": opened, "snags_open_now": open_now,
        "milestones_done": [{"id": str(m["_id"]), "name": m["name"], "completed_at": m["completed_at"]} for m in ms],
        "next_milestone": {"name": nxt["name"], "target_date": nxt.get("target_date"), "status": nxt["status"]} if nxt else None,
    }
