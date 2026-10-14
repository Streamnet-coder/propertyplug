import secrets
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from core import E, db, money
from deps import active_pid, current_user, get_project_doc
from html_utils import brand_block, owner_branding, page, serve_logo
from models import Project, User

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


async def build_digest(pid: str, week: int) -> dict:
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


@router.get("/digest")
async def weekly_digest(week: int = Query(0, ge=0, le=52), user: User = Depends(current_user)):
    return await build_digest(await active_pid(user), week)


# ---------- Shareable digest (read-only public page for partners / lenders / investors) ----------
class DigestShareIn(BaseModel):
    origin_url: str


def digest_url(p: Project):
    return f"{p.digest_origin.rstrip('/')}/api/d/{p.digest_token}" if p.digest_token and p.digest_origin else None


@router.get("/digest/share")
async def get_digest_share(user: User = Depends(current_user)):
    return {"url": digest_url(await get_project_doc(user))}


@router.post("/digest/share")
async def create_digest_share(body: DigestShareIn, user: User = Depends(current_user)):
    p = await get_project_doc(user)
    p.digest_token = p.digest_token or secrets.token_urlsafe(16)
    p.digest_origin = body.origin_url
    await db.projects.update_one({"_id": ObjectId(p.id)}, {"$set": {"digest_token": p.digest_token, "digest_origin": p.digest_origin}})
    return {"url": digest_url(p)}


@router.delete("/digest/share")
async def revoke_digest_share(user: User = Depends(current_user)):
    p = await get_project_doc(user)
    await db.projects.update_one({"_id": ObjectId(p.id)}, {"$set": {"digest_token": None}})
    return {"url": None}


def _d(s: str) -> str:
    return datetime.fromisoformat(s[:10]).strftime("%d %b")


@router.get("/d/{token}", response_class=HTMLResponse)
async def public_digest(token: str, week: int = Query(0, ge=0, le=52)):
    doc = await db.projects.find_one({"digest_token": token}) if token else None
    if not doc:
        return page("Link expired", "<div class='card'><h2>This weekly update link is no longer active</h2><p>Ask the project owner for a new link.</p></div>")
    p = Project.from_mongo(doc)
    d = await build_digest(p.id, week)
    sp = d["spend"]
    diff = sp["total"] - d["prev_spend"]
    label = "This week" if week == 0 else "Last week" if week == 1 else f"{week} weeks ago"
    nav = ("<div class='card' style='display:flex;justify-content:space-between'>"
           + (f"<a id='digest-prev' href='/api/d/{E(token)}?week={week + 1}'>&larr; Previous week</a>" if week < 52 else "<span></span>")
           + (f"<a id='digest-next' href='/api/d/{E(token)}?week={week - 1}'>Next week &rarr;</a>" if week > 0 else "<span></span>") + "</div>")
    body = brand_block(await owner_branding(p.user_id), f"/api/d/{E(token)}/logo")
    body += (f"<div class='hdr'><div class='brand'>BUILDER <b>ASSIST</b> · WEEKLY UPDATE</div><h1>{E(p.name)}</h1>"
             f"<div>{E(p.address)}</div><div style='font-size:12px;opacity:.85;margin-top:6px' id='digest-week'>{label} · {_d(d['week_start'])} – {_d(d['week_end'])}</div></div>")
    body += (f"<div class='kpis' style='margin-top:14px' id='digest-kpis'><div class='kpi'><span>Spent</span><div>{money(sp['total'], 2)}</div></div>"
             f"<div class='kpi'><span>vs week before</span><div>{'+' if diff > 0 else '-' if diff < 0 else ''}{money(abs(diff))}</div></div>"
             f"<div class='kpi'><span>Snags fixed</span><div>{len(d['snags_fixed'])}</div></div>"
             f"<div class='kpi'><span>Stages done</span><div>{len(d['milestones_done'])}</div></div></div>")
    if sp["top"]:
        body += "<div class='card'><h2>Biggest spends</h2><table>" + "".join(
            f"<tr><td>{E(r['title'])}<div class='cap'>{E(r['supplier'])} · {_d(r['date'])}</div></td><td class='n'>{money(r['amount'], 2)}</td></tr>" for r in sp["top"]) + "</table></div>"
    body += "<div class='card' id='digest-milestones'><h2>Milestones hit</h2>" + ("".join(
        f"<div class='ms'><div class='dot done'></div><div style='flex:1'>{E(m['name'])}</div></div>" for m in d["milestones_done"]) or "<div class='cap'>No stages completed this week</div>")
    if d["next_milestone"] and week == 0:
        n = d["next_milestone"]
        body += f"<div class='ms'><div class='dot in_progress'></div><div style='flex:1'>Up next: {E(n['name'])}</div><div class='cap'>{E(n.get('target_date') or '')}</div></div>"
    body += "</div>"
    body += "<div class='card' id='digest-snags'><h2>Snags fixed</h2>" + ("<table>" + "".join(
        f"<tr><td>{E(x['description'])}<div class='cap'>{E(x['room'])}{' · fixed by ' + E(x['fixed_by']) if x.get('fixed_by') else ''}</div></td></tr>" for x in d["snags_fixed"]) + "</table>"
        if d["snags_fixed"] else "<div class='cap'>No snags fixed this week</div>") + f"<div class='cap' style='margin-top:8px'>{d['snags_open_now']} still open</div></div>"
    body += nav
    return page(f"{p.name} · Weekly update", body, ref="digest", by=p.user_id)


@router.get("/d/{token}/logo")
async def digest_logo(token: str):
    doc = await db.projects.find_one({"digest_token": token}, {"user_id": 1}) if token else None
    if not doc:
        raise HTTPException(404, "Not found")
    return await serve_logo(doc["user_id"])
