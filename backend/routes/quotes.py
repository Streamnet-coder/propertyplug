from fastapi import APIRouter, HTTPException, Depends, Form
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List, Literal
from bson import ObjectId
from core import db, now_iso, oid, money, E
from models import User, LineItem, QuoteEntry, QuoteRequest
from deps import current_user, active_pid
from html_utils import page, owner_branding, brand_block, serve_logo
from routes.messages import log_message

router = APIRouter()


def quote_out(q: QuoteRequest):
    d = q.out()
    for e in d["quotes"]:
        e["link"] = f"{q.origin.rstrip('/')}/api/q/{e['token']}"
    return d


class QuoteCreate(BaseModel):
    title: str
    description: str
    trade: str = ""
    contact_ids: List[str]
    origin_url: str


class EntryUpdate(BaseModel):
    amount: Optional[float] = None
    days: Optional[int] = None
    notes: Optional[str] = None
    sent: Optional[bool] = None
    status: Optional[Literal["requested", "received", "declined"]] = None


async def load_quote(qid: str, user: User) -> QuoteRequest:
    q = QuoteRequest.from_mongo(await db.quote_requests.find_one({"_id": oid(qid), "user_id": user.id}))
    if not q:
        raise HTTPException(404, "Quote request not found")
    return q


@router.get("/quotes")
async def list_quotes(user: User = Depends(current_user)):
    docs = await db.quote_requests.find({"user_id": user.id, "project_id": await active_pid(user)}).sort("created_at", -1).to_list(200)
    return [quote_out(QuoteRequest.from_mongo(d)) for d in docs]


@router.post("/quotes")
async def create_quote(body: QuoteCreate, user: User = Depends(current_user)):
    if not body.title.strip() or not body.description.strip():
        raise HTTPException(400, "Title and job description are required")
    ids = [oid(c) for c in body.contact_ids]
    contacts = await db.contacts.find({"_id": {"$in": ids}, "user_id": user.id}).to_list(50)
    if not contacts:
        raise HTTPException(400, "Choose at least one tradesperson")
    q = QuoteRequest(user_id=user.id, project_id=await active_pid(user), title=body.title.strip(), description=body.description.strip(),
                     trade=body.trade, origin=body.origin_url,
                     quotes=[QuoteEntry(contact_id=str(c["_id"]), name=c["name"], role=c.get("role", ""), phone=c.get("phone", ""),
                                        email=c.get("email", "")) for c in contacts])
    q.id = str((await db.quote_requests.insert_one(q.to_mongo())).inserted_id)
    return quote_out(q)


@router.get("/quotes/{qid}")
async def get_quote(qid: str, user: User = Depends(current_user)):
    return quote_out(await load_quote(qid, user))


@router.put("/quotes/{qid}/entries/{eid}")
async def update_entry(qid: str, eid: str, body: EntryUpdate, user: User = Depends(current_user)):
    q = await load_quote(qid, user)
    e = next((x for x in q.quotes if x.id == eid), None)
    if not e:
        raise HTTPException(404, "Quote not found")
    upd = body.model_dump(exclude_unset=True)
    for k, v in upd.items():
        setattr(e, k, v)
    if body.amount is not None and e.status == "requested":
        e.status, e.responded_at = "received", now_iso()
    await db.quote_requests.update_one({"_id": ObjectId(q.id)}, {"$set": {"quotes": [x.model_dump() for x in q.quotes]}})
    return quote_out(q)


class AcceptIn(BaseModel):
    add_to_budget: bool = True


@router.post("/quotes/{qid}/entries/{eid}/accept")
async def accept_entry(qid: str, eid: str, body: AcceptIn, user: User = Depends(current_user)):
    q = await load_quote(qid, user)
    e = next((x for x in q.quotes if x.id == eid), None)
    if not e:
        raise HTTPException(404, "Quote not found")
    if e.amount is None:
        raise HTTPException(400, "This quote has no price yet")
    for x in q.quotes:
        x.status = "accepted" if x.id == eid else ("declined" if x.status in ("received", "accepted", "requested") else x.status)
    upd = {"quotes": [x.model_dump() for x in q.quotes]}
    if body.add_to_budget:
        if q.added_line_item_id:
            await db.line_items.delete_one({"_id": oid(q.added_line_item_id), "user_id": user.id})
        li = LineItem(user_id=user.id, project_id=q.project_id, category="Hard Cost", name=q.title, budgeted=e.amount,
                      actual=0, supplier=e.name, status="Quoted")
        upd["added_line_item_id"] = q.added_line_item_id = str((await db.line_items.insert_one(li.to_mongo())).inserted_id)
    await db.quote_requests.update_one({"_id": ObjectId(q.id)}, {"$set": upd})
    return quote_out(q)


@router.delete("/quotes/{qid}")
async def delete_quote(qid: str, user: User = Depends(current_user)):
    await db.stage_payments.delete_many({"quote_id": qid, "user_id": user.id})
    await db.quote_requests.delete_one({"_id": oid(qid), "user_id": user.id})
    return {"ok": True}


async def find_entry(token: str):
    doc = await db.quote_requests.find_one({"quotes.token": token})
    if not doc:
        return None, None
    q = QuoteRequest.from_mongo(doc)
    return q, next(x for x in q.quotes if x.token == token)


@router.get("/q/{token}", response_class=HTMLResponse)
async def public_quote_form(token: str):
    q, e = await find_entry(token)
    if not q:
        return page("Not found", "<div class='card'><h2>This quote link is no longer active</h2></div>")
    p = await db.projects.find_one({"_id": ObjectId(q.project_id)}) or {}
    closed = e.status in ("accepted", "declined")
    body = brand_block(await owner_branding(q.user_id), f"/api/q/{E(token)}/logo") + f"""<div class='hdr'><div class='brand'>BUILDER <b>ASSIST</b> · QUOTE REQUEST</div><h1>{E(q.title)}</h1>
<div>For {E(e.name)} · {E(p.get('address', ''))}</div></div>
<div class='card'><h2>Job description</h2><div style='white-space:pre-wrap;line-height:1.5'>{E(q.description)}</div></div>"""
    if closed:
        body += f"<div class='card'><h2>This job has been {'awarded to you 🎉' if e.status == 'accepted' else 'awarded to another trade'}</h2><p>Thanks for quoting.</p></div>"
    else:
        body += f"""<form class='card' method='post'><h2>{'Update your quote' if e.amount is not None else 'Submit your quote'}</h2>
<label>Total price (£, inc. materials)</label><input name='amount' type='number' step='0.01' min='1' required value='{e.amount if e.amount is not None else ''}'/>
<label>Time to complete (working days)</label><input name='days' type='number' min='0' value='{e.days if e.days is not None else ''}'/>
<label>Notes (what's included, availability)</label><textarea name='notes' rows='4'>{E(e.notes)}</textarea>
<button type='submit'>Send quote</button></form>"""
    return page(f"Quote: {q.title}", body, ref="quote", by=q.user_id)


@router.get("/q/{token}/logo")
async def quote_logo(token: str):
    q, _ = await find_entry(token)
    if not q:
        raise HTTPException(404, "Not found")
    return await serve_logo(q.user_id)


@router.post("/q/{token}", response_class=HTMLResponse)
async def public_quote_submit(token: str, amount: float = Form(...), days: Optional[str] = Form(None), notes: str = Form("")):
    q, e = await find_entry(token)
    if not q:
        return page("Not found", "<div class='card'><h2>This quote link is no longer active</h2></div>")
    if e.status in ("accepted", "declined"):
        return page("Closed", "<div class='card'><h2>This job is already closed</h2></div>")
    if amount <= 0:
        return page("Invalid", "<div class='card'><h2>Please enter a valid price</h2></div>")
    e.amount, e.notes, e.status, e.responded_at = float(amount), notes.strip()[:2000], "received", now_iso()
    e.days = int(days) if days and days.strip().isdigit() else None
    await db.quote_requests.update_one({"_id": ObjectId(q.id)}, {"$set": {"quotes": [x.model_dump() for x in q.quotes]}})
    await log_message(q.user_id, q.project_id, name=e.name, email=e.email, phone=e.phone, channel="web", kind="quote", direction="in",
                      summary=f"Submitted a quote of {money(e.amount, 2)} for “{q.title}”" + (f" · {e.days} days" if e.days else ""))
    return page("Quote sent", f"<div class='card'><h2>Thanks {E(e.name)} — your quote of {money(e.amount, 2)} was sent</h2><p>The project owner will be in touch. You can reopen this link to update your quote.</p></div>", ref="quote", by=q.user_id)
