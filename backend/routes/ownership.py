"""Per-project ownership split: each co-owner/manager with access gets a %, the owner keeps the rest.
Profit (valuation minus purchase + budget) and rent cashflow are divided by share for the money summary and PDF report."""
import asyncio
from datetime import date
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import E, db, logger, money, now_iso, oid
from deps import active_pid, block_money, current_user, get_project_doc, load_user
from email_service import EmailError, send_email
from models import Project, User
from routes.email_settings import owner_reply_to
from routes.messages import log_message
from routes.projects import project_summary
from routes.rentals import _ctx, _row, _wrap, compute_rentals

router = APIRouter(dependencies=[Depends(block_money)])


async def _people(owner_id: str, pid: str) -> list:
    out = []
    async for c in db.co_owners.find({"owner_id": owner_id, "$or": [{"project_ids": None}, {"project_ids": pid}]}).sort("invited_at", 1):
        u = await db.users.find_one({"email": c["email"]}, {"name": 1})
        out.append({"co_owner_id": str(c["_id"]), "name": u["name"] if u else c["email"].split("@")[0], "email": c["email"]})
    return out


@router.get("/project/split")
async def get_split(user: User = Depends(current_user)):
    return {**await compute_split(user, await get_project_doc(user)), "can_edit": user.real_id is None}


async def compute_split(user: User, p) -> dict:
    s = await project_summary(p)
    people = await _people(user.id, p.id)
    doc = await db.ownership_shares.find_one({"project_id": p.id}) or {}
    saved, contrib = doc.get("shares", {}), doc.get("contributions", {})
    for x in people:
        x["pct"] = float(saved.get(x["co_owner_id"], 0))
    owner_pct = round(100 - sum(x["pct"] for x in people), 2)
    ry = s["rent_yield"]
    profit = round(p.estimated_valuation - ry["invested"], 2) if p.estimated_valuation else None
    figures = {"profit": profit, "monthly_rent": p.monthly_rent, "monthly_cashflow": ry["monthly_cashflow"], "annual_cashflow": round(ry["monthly_cashflow"] * 12, 2)}
    rows = [{"co_owner_id": None, "name": user.name, "email": user.email, "pct": owner_pct, "is_owner": True}] + [{**x, "is_owner": False} for x in people]
    for r in rows:
        r["profit"] = round(profit * r["pct"] / 100, 2) if profit is not None else None
        r["monthly_rent"] = round(p.monthly_rent * r["pct"] / 100, 2)
        r["monthly_cashflow"] = round(ry["monthly_cashflow"] * r["pct"] / 100, 2)
        r["annual_cashflow"] = round(figures["annual_cashflow"] * r["pct"] / 100, 2)
        r["contribution"] = float(contrib.get(r["co_owner_id"] or "owner", 0))
        r["cash_return_pct"] = round(r["annual_cashflow"] / r["contribution"] * 100, 1) if r["contribution"] else None
        r["profit_return_pct"] = round(r["profit"] / r["contribution"] * 100, 1) if r["contribution"] and r["profit"] is not None else None
    total_in = round(sum(r["contribution"] for r in rows), 2)
    return {"rows": rows, "figures": {**figures, "total_contributed": total_in},
            "has_split": any(x["pct"] for x in people), "has_contributions": total_in > 0}


class SplitIn(BaseModel):
    shares: Dict[str, float] = Field(default_factory=dict, max_length=50)
    contributions: Optional[Dict[str, float]] = Field(None, max_length=51)  # co_owner_id or "owner" -> cash put into the deal


@router.put("/project/split")
async def save_split(body: SplitIn, user: User = Depends(current_user)):
    if user.real_id is not None:
        raise HTTPException(403, "Only the project owner can change ownership shares")
    pid = await active_pid(user)
    allowed = {x["co_owner_id"] for x in await _people(user.id, pid)}
    if set(body.shares) - allowed:
        raise HTTPException(400, "Shares can only be given to people with access to this project")
    if any(v < 0 or v > 100 for v in body.shares.values()):
        raise HTTPException(400, "Each share must be between 0 and 100%")
    if sum(body.shares.values()) > 100:
        raise HTTPException(400, "Shares add up to more than 100%")
    shares = {k: round(v, 2) for k, v in body.shares.items() if v > 0}
    upd = {"project_id": pid, "owner_id": user.id, "shares": shares}
    if body.contributions is not None:
        if set(body.contributions) - allowed - {"owner"}:
            raise HTTPException(400, "Contributions can only be recorded for people with access to this project")
        if any(v < 0 or v > 1e9 for v in body.contributions.values()):
            raise HTTPException(400, "Contributions must be between 0 and 1,000,000,000")
        upd["contributions"] = {k: round(v, 2) for k, v in body.contributions.items() if v > 0}
    await db.ownership_shares.update_one({"project_id": pid}, {"$set": upd}, upsert=True)
    return await get_split(user)


# ---------- Co-owner statements (UK tax year 6 April - 5 April, by month Apr-Mar) ----------

def tax_year_now(today: Optional[date] = None) -> int:
    """Start year of the most recently *ended* tax year."""
    t = today or date.today()
    return t.year - 1 if (t.month, t.day) >= (4, 6) else t.year - 2


async def statement_figures(owner_id: str, pid: str, ty: int) -> dict:
    q = {"user_id": owner_id, "project_id": pid}
    a, b = await compute_rentals(q, ty), await compute_rentals(q, ty + 1)
    months = [m for m in a["summary"]["monthly"] if m["month"] >= f"{ty}-04"] + [m for m in b["summary"]["monthly"] if m["month"] < f"{ty + 1}-04"]
    rent, exp = round(sum(m["received"] for m in months), 2), round(sum(m["expenses"] for m in months), 2)
    return {"tax_year": ty, "label": f"6 Apr {ty} – 5 Apr {ty + 1}", "rent_received": rent, "expenses": exp, "net": round(rent - exp, 2)}


async def statement_preview(owner: User, p, ty: int) -> dict:
    split, f = await compute_split(owner, p), await statement_figures(owner.id, p.id, ty)
    rows = [{"co_owner_id": r["co_owner_id"], "name": r["name"], "email": r["email"], "is_owner": r["is_owner"], "pct": r["pct"],
             "rent_received": round(f["rent_received"] * r["pct"] / 100, 2), "expenses": round(f["expenses"] * r["pct"] / 100, 2),
             "net": round(f["net"] * r["pct"] / 100, 2), "profit": r["profit"], "contribution": r["contribution"]} for r in split["rows"]]
    last = await db.coowner_statements.find_one({"project_id": p.id, "tax_year": ty}, sort=[("sent_at", -1)])
    return {**f, "rows": rows, "has_split": split["has_split"], "last_sent_at": last["sent_at"] if last else None}


def _statement_html(head: str, address: str, sender: str, f: dict, r: dict) -> str:
    rows = (_row("Your share", f"{r['pct']}%") + _row("Rent received (your share)", E(money(r["rent_received"], 2)))
            + _row("Property expenses (your share)", E(money(r["expenses"], 2))) + _row("<b>Net income (your share)</b>", f"<b>{E(money(r['net'], 2))}</b>")
            + (_row("Share of estimated profit", E(money(r["profit"], 2))) if r["profit"] is not None else "")
            + (_row("Your capital contribution", E(money(r["contribution"], 2))) if r["contribution"] else ""))
    return _wrap(f'{head}<p style="font-size:12px;letter-spacing:1px;color:#0f766e;font-weight:bold;margin:0">CO-OWNER STATEMENT · {E(f["label"].upper())}</p>'
                 f'<h1 style="font-size:20px;margin:8px 0 12px">{E(address)}</h1><p>Hi {E(r["name"])},</p>'
                 f'<p style="line-height:1.5">Here is your share of this property for the tax year {E(f["label"])}.</p>'
                 f'<table width="100%" style="border-collapse:collapse;font-size:14px;margin:12px 0">{rows}</table>'
                 f'<p style="font-size:12px;color:#888">Whole property: rent received {E(money(f["rent_received"], 2))}, expenses {E(money(f["expenses"], 2))}, net {E(money(f["net"], 2))}. '
                 f'Profit is an estimate (valuation minus purchase and budget). Figures are grouped by month (April to March). Please check with your accountant before filing.</p>'
                 f'<p>Kind regards,<br/>{E(sender)}</p>')


async def send_statements(owner: User, p, ty: int, auto: bool = False) -> dict:
    prev = await statement_preview(owner, p, ty)
    if not prev["has_split"]:
        raise HTTPException(400, "Set ownership shares first")
    address, sender, head = await _ctx(owner.id, {"project_id": p.id})
    sent, failed = [], []
    for r in prev["rows"]:
        if r["is_owner"] or r["pct"] <= 0:
            continue
        subject = f"Co-owner statement {prev['label']} · {address}"
        try:
            await send_email(to=r["email"], subject=subject, html=_statement_html(head, address, sender, prev, r), reply_to=await owner_reply_to(owner.id))
            sent.append(r["email"])
            status = "sent"
        except EmailError as e:
            logger.warning(f"Co-owner statement failed: {e}")
            failed.append(r["email"])
            status = "failed"
        await log_message(owner.id, p.id, name=r["name"], email=r["email"], channel="email", kind="coowner_statement", summary=subject, status=status)
    own = next(r for r in prev["rows"] if r["is_owner"])
    try:  # owner's own copy
        await send_email(to=owner.email, subject=f"Your copy: co-owner statements {prev['label']} · {address}",
                         html=_statement_html(head, address, sender, prev, own), reply_to=None)
    except EmailError:
        pass
    await db.coowner_statements.insert_one({"project_id": p.id, "owner_id": owner.id, "tax_year": ty, "sent_at": now_iso(), "auto": auto, "sent": sent, "failed": failed})
    return {"sent": sent, "failed": failed, "label": prev["label"]}


@router.get("/project/statements")
async def get_statements(tax_year: Optional[int] = None, user: User = Depends(current_user)):
    return await statement_preview(user, await get_project_doc(user), tax_year or tax_year_now())


class StatementIn(BaseModel):
    tax_year: int = Field(ge=2000, le=2100)


@router.post("/project/statements")
async def post_statements(body: StatementIn, user: User = Depends(current_user)):
    if user.real_id is not None:
        raise HTTPException(403, "Only the project owner can send statements")
    return await send_statements(user, await get_project_doc(user), body.tax_year)


async def run_auto_statements() -> int:
    """From 6 April (for 60 days), send each project's statements for the tax year just ended (once)."""
    ty, n = tax_year_now(), 0
    if (date.today() - date(ty + 1, 4, 6)).days > 60:
        return 0
    async for d in db.ownership_shares.find({"shares": {"$ne": {}}}):
        if await db.coowner_statements.find_one({"project_id": d["project_id"], "tax_year": ty}):
            continue
        pdoc = await db.projects.find_one({"_id": oid(d["project_id"])})
        if not pdoc:
            continue
        try:
            owner = await load_user(pdoc["user_id"])
            await send_statements(owner, Project.from_mongo(pdoc), ty, auto=True)
            n += 1
        except HTTPException:
            await db.coowner_statements.insert_one({"project_id": d["project_id"], "owner_id": pdoc["user_id"], "tax_year": ty, "sent_at": now_iso(), "auto": True, "sent": [], "failed": [], "skipped": True})
    return n


async def statement_scheduler():
    while True:
        try:
            await run_auto_statements()
        except Exception as e:
            logger.error(f"Co-owner statement scheduler error: {e}")
        await asyncio.sleep(6 * 3600)


# ---------- Payout tracker: share of net rental income earned vs money paid out ----------

async def net_income_to_date(owner_id: str, pid: str) -> dict:
    q = {"user_id": owner_id, "project_id": pid}
    rent = sum([float(p.get("paid_amount") or 0) async for p in db.rent_payments.find(q, {"paid_amount": 1})])
    exp = sum([float(e.get("amount") or 0) async for e in db.rental_expenses.find(q, {"amount": 1})])
    return {"rent_received": round(rent, 2), "expenses": round(exp, 2), "net": round(rent - exp, 2)}


async def payout_ledger(owner: User, p) -> dict:
    split, inc = await compute_split(owner, p), await net_income_to_date(owner.id, p.id)
    pays = [{**{k: v for k, v in d.items() if k != "_id"}, "id": str(d["_id"])} async for d in db.coowner_payouts.find({"project_id": p.id}).sort("date", -1)]
    people = []
    for r in split["rows"]:
        if r["is_owner"]:
            continue
        mine = [x for x in pays if x["co_owner_id"] == r["co_owner_id"]]
        earned = round(inc["net"] * r["pct"] / 100, 2)
        paid = round(sum(x["amount"] for x in mine), 2)
        people.append({"co_owner_id": r["co_owner_id"], "name": r["name"], "email": r["email"], "pct": r["pct"], "earned": earned, "paid": paid,
                       "balance": round(earned - paid, 2), "payouts": mine})
    return {"income": inc, "people": people, "total_owed": round(sum(x["balance"] for x in people if x["balance"] > 0), 2)}


@router.get("/project/payouts")
async def get_payouts(user: User = Depends(current_user)):
    return await payout_ledger(user, await get_project_doc(user))


class PayoutIn(BaseModel):
    co_owner_id: str
    amount: float = Field(gt=0, le=1e9)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    note: str = Field("", max_length=200)


@router.post("/project/payouts")
async def add_payout(body: PayoutIn, user: User = Depends(current_user)):
    if user.real_id is not None:
        raise HTTPException(403, "Only the project owner can record payouts")
    pid = await active_pid(user)
    if body.co_owner_id not in {x["co_owner_id"] for x in await _people(user.id, pid)}:
        raise HTTPException(400, "Payouts can only be recorded for people with access to this project")
    try:
        date.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(400, "Date must be YYYY-MM-DD")
    await db.coowner_payouts.insert_one({"project_id": pid, "owner_id": user.id, "co_owner_id": body.co_owner_id, "amount": round(body.amount, 2),
                                         "date": body.date, "note": body.note.strip(), "created_at": now_iso()})
    return await get_payouts(user)


@router.delete("/project/payouts/{payout_id}")
async def delete_payout(payout_id: str, user: User = Depends(current_user)):
    if user.real_id is not None:
        raise HTTPException(403, "Only the project owner can remove payouts")
    await db.coowner_payouts.delete_one({"_id": oid(payout_id), "owner_id": user.id, "project_id": await active_pid(user)})
    return await get_payouts(user)
