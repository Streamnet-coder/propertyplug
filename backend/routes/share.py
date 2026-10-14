from routes.projects import project_summary
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response, HTMLResponse, RedirectResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from datetime import datetime, timezone
from bson import ObjectId
import secrets
from core import db, oid, money, E
from models import User, Project
from deps import current_user, get_project_doc
from storage import get_object
from html_utils import page, owner_branding, brand_block

router = APIRouter()


class ShareIn(BaseModel):
    origin_url: str


def share_url(p: Project):
    return f"{p.share_origin.rstrip('/')}/api/share/{p.share_token}" if p.share_token and p.share_origin else None


@router.get("/project/share")
async def get_share(user: User = Depends(current_user)):
    return {"url": share_url(await get_project_doc(user))}


@router.post("/project/share")
async def create_share(body: ShareIn, user: User = Depends(current_user)):
    p = await get_project_doc(user)
    token = p.share_token or secrets.token_urlsafe(16)
    await db.projects.update_one({"_id": ObjectId(p.id)}, {"$set": {"share_token": token, "share_origin": body.origin_url}})
    p.share_token, p.share_origin = token, body.origin_url
    return {"url": share_url(p)}


@router.delete("/project/share")
async def revoke_share(user: User = Depends(current_user)):
    p = await get_project_doc(user)
    await db.projects.update_one({"_id": ObjectId(p.id)}, {"$set": {"share_token": None}})
    return {"url": None}


@router.get("/share/{token}", response_class=HTMLResponse)
async def public_report(token: str):
    doc = await db.projects.find_one({"share_token": token}) if token else None
    if not doc:
        return page("Link expired", "<div class='card'><h2>This report link is no longer active</h2><p>Ask the project owner for a new link.</p></div>")
    p = Project.from_mongo(doc)
    s = await project_summary(p)
    items = await db.line_items.find({"project_id": p.id}).sort("created_at", -1).to_list(500)
    receipts = await db.receipts.find({"project_id": p.id}).sort("date", -1).to_list(500)
    media = await db.media.find({"project_id": p.id}).sort("created_at", 1).to_list(60)
    ms = await db.milestones.find({"project_id": p.id}).sort("order", 1).to_list(200)
    pct = round(s["total_spent"] / s["total_budget"] * 100) if s["total_budget"] else 0
    rem = s["total_budget"] - s["total_spent"]
    brand = brand_block(await owner_branding(p.user_id), f"/api/share/{E(token)}/logo")
    by_ms: dict = {}
    for m in media:
        if m.get("milestone_id"):
            by_ms.setdefault(m["milestone_id"], []).append(m)
    cats = [("Hard costs", p.budget.hard, s["spent"]["hard"]), ("Soft costs", p.budget.soft, s["spent"]["soft"]),
            ("Contingency", p.budget.contingency, s["spent"]["contingency"])]
    body = brand + f"""<div class='hdr'><div class='brand'>BUILDER <b>ASSIST</b> · LIVE PROJECT REPORT</div><h1>{E(p.name)}</h1>
<div>{E(p.address)}</div><div style='font-size:12px;opacity:.85;margin-top:6px'>{E(p.target_type)} · {E(p.finish_type)} · Updated {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M')} UTC</div></div>
<div class='kpis' style='margin-top:14px'><div class='kpi'><span>Purchase</span><div>{money(p.purchase_price)}</div></div>
<div class='kpi'><span>Est. valuation</span><div>{money(p.estimated_valuation)}</div></div><div class='kpi'><span>Budget</span><div>{money(s['total_budget'])}</div></div>
<div class='kpi'><span>Spent</span><div>{money(s['total_spent'])}</div></div></div>
<div class='card'><b>{pct}% of budget used</b> · {money(rem) + ' remaining' if rem >= 0 else "<span class='over'>" + money(-rem) + ' over budget</span>'}
<div class='bar'><i style='width:{min(100, pct)}%'></i></div></div>"""
    ry = s["rent_yield"]
    if p.monthly_rent > 0:
        left = ry["cash_left_in"]
        body += (f"<div class='card' id='rent-yield'><h2>Rent & refinance</h2><div class='kpis'>"
                 f"<div class='kpi'><span>Monthly rent</span><div>{money(p.monthly_rent)}</div></div>"
                 f"<div class='kpi'><span>Gross yield</span><div>{ry['gross_yield']:.1f}%</div></div>"
                 f"<div class='kpi'><span>Refinance ({p.refinance_ltv:g}% LTV)</span><div>{money(ry['refinance_amount'])}</div></div>"
                 f"<div class='kpi'><span>{'Cash left in' if left > 0 else 'Cash pulled out'}</span><div>{money(abs(left))}</div></div></div></div>")
    if ms:
        body += f"<div class='card'><h2>Milestones · {s['milestones_done']}/{s['milestones_total']} complete</h2>" + "".join(
            f"<div class='ms'><div class='dot {m['status']}'></div><div style='flex:1'>{E(m['name'])}</div>"
            f"<div class='cap'>{'Done' if m['status'] == 'done' else 'In progress' if m['status'] == 'in_progress' else (m.get('target_date') or '')}</div></div>"
            + ("<div class='msph'>" + "".join(
                f"<figure><img loading='lazy' src='/api/share/{E(token)}/photo/{ph['_id']}'/><figcaption><span class='tag'>{E(ph['phase'].upper())}</span></figcaption></figure>"
                for ph in by_ms.get(str(m["_id"]), [])) + "</div>" if by_ms.get(str(m["_id"])) else "")
            for m in ms) + "</div>"
    snags = await db.snags.find({"project_id": p.id}).to_list(500)
    if snags:
        open_n = sum(1 for x in snags if x["status"] == "open")
        body += (f"<div class='card' id='snag-summary'><h2>Snagging · {len(snags) - open_n}/{len(snags)} fixed</h2>"
                 f"<div class='cap'>{open_n} open item{'s' if open_n != 1 else ''} before sign-off</div></div>")
    body += "<div class='card'><h2>Budget breakdown</h2><table><tr><th>Category</th><th class='n'>Budget</th><th class='n'>Spent</th><th class='n'>Variance</th></tr>" + "".join(
        f"<tr><td>{l}</td><td class='n'>{money(b)}</td><td class='n'>{money(sp)}</td><td class='n {'over' if b - sp < 0 else 'under'}'>{money(b - sp)}</td></tr>"
        for l, b, sp in cats) + "</table></div>"
    body += f"<div class='card'><h2>Line items ({len(items)})</h2><table><tr><th>Item</th><th>Status</th><th class='n'>Budget</th><th class='n'>Actual</th></tr>" + "".join(
        f"<tr><td>{E(i['name'])}<div class='cap'>{E(i.get('supplier', ''))}</div></td><td><span class='tag'>{E(i.get('status', ''))}</span></td>"
        f"<td class='n'>{money(i.get('budgeted', 0))}</td><td class='n'>{money(i.get('actual', 0))}</td></tr>" for i in items) + "</table></div>"
    body += f"<div class='card'><h2>Receipts ({len(receipts)}) · {money(sum(r['amount'] for r in receipts), 2)}</h2><table>" + "".join(
        f"<tr><td>{E(r['date'])}</td><td>{E(r['title'])}</td><td class='n'>{money(r['amount'], 2)}</td></tr>" for r in receipts) + "</table></div>"
    if media:
        body += "<div class='card'><h2>Site photos</h2><div class='grid'>" + "".join(
            f"<div><img loading='lazy' src='/api/share/{E(token)}/photo/{m['_id']}'/><div class='cap'><span class='tag'>{E(m['phase'].upper())}</span> {E(m['title'])}</div></div>"
            for m in media) + "</div></div>"
    return page(f"{p.name} · Project report", body, ref="share", by=p.user_id)


@router.get("/share/{token}/photo/{mid}")
async def public_photo(token: str, mid: str):
    doc = await db.projects.find_one({"share_token": token}) if token else None
    if not doc:
        raise HTTPException(404, "Not found")
    m = await db.media.find_one({"_id": oid(mid), "project_id": str(doc["_id"])})
    if not m:
        raise HTTPException(404, "Not found")
    if m.get("storage_path"):
        data, ctype = await run_in_threadpool(get_object, m["storage_path"])
        return Response(content=data, media_type=ctype, headers={"Cache-Control": "public, max-age=3600"})
    return RedirectResponse(m["url"])
