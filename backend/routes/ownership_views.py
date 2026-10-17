"""Read-only ownership views: a co-owner's own shares + statement history across everyone who shared with them,
and the owner's portfolio-wide ownership summary per person. Uses the signed-in person (real_user), not the open project."""
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from core import db, oid
from deps import load_user, real_user
from models import Project, User
from routes.ownership import compute_split, statement_preview

router = APIRouter()


async def _my_rows(user: User):
    """Yield (owner, project, split_row, co_owner_doc) for every project where this person holds a share or contribution."""
    async for c in db.co_owners.find({"email": user.email}):
        if c.get("money_access", True) is False:
            continue  # tasks-only access never shows money
        cid = str(c["_id"])
        q = {"owner_id": c["owner_id"], "$or": [{f"shares.{cid}": {"$gt": 0}}, {f"contributions.{cid}": {"$gt": 0}}]}
        docs = await db.ownership_shares.find(q).to_list(200)
        if not docs:
            continue
        owner = await load_user(c["owner_id"])
        for d in docs:
            pids = c.get("project_ids")
            if pids is not None and d["project_id"] not in pids:
                continue
            pdoc = await db.projects.find_one({"_id": oid(d["project_id"]), "user_id": c["owner_id"]})
            if not pdoc:
                continue
            p = Project.from_mongo(pdoc)
            row = next((r for r in (await compute_split(owner, p))["rows"] if r["co_owner_id"] == cid), None)
            if row:
                yield owner, p, row, c


@router.get("/my-ownership")
async def my_ownership(user: User = Depends(real_user)):
    projects = []
    async for owner, p, r, _ in _my_rows(user):
        stmts = [{"tax_year": s["tax_year"], "sent_at": s["sent_at"], "label": f"6 Apr {s['tax_year']} – 5 Apr {s['tax_year'] + 1}"}
                 async for s in db.coowner_statements.find({"project_id": p.id, "sent": user.email}).sort("tax_year", -1)]
        projects.append({"project_id": p.id, "project_name": p.name, "address": p.address, "owner_name": owner.name, "currency": p.currency,
                         "pct": r["pct"], "contribution": r["contribution"], "profit": r["profit"], "monthly_cashflow": r["monthly_cashflow"],
                         "annual_cashflow": r["annual_cashflow"], "cash_return_pct": r["cash_return_pct"], "profit_return_pct": r["profit_return_pct"], "statements": stmts})
    tot = lambda k: round(sum(x[k] or 0 for x in projects), 2)
    return {"projects": projects, "totals": {"contribution": tot("contribution"), "profit": tot("profit"), "annual_cashflow": tot("annual_cashflow")}}


@router.get("/my-ownership/statement")
async def my_statement(project_id: str, tax_year: int, user: User = Depends(real_user)):
    async for owner, p, _, c in _my_rows(user):
        if p.id == project_id:
            if not await db.coowner_statements.find_one({"project_id": p.id, "tax_year": tax_year, "sent": user.email}):
                raise HTTPException(404, "No statement was sent to you for that year")
            prev = await statement_preview(owner, p, tax_year)
            row = next(r for r in prev["rows"] if r["co_owner_id"] == str(c["_id"]))
            return {"project_name": p.name, "address": p.address, "owner_name": owner.name, "label": prev["label"], "tax_year": tax_year,
                    "whole": {k: prev[k] for k in ("rent_received", "expenses", "net")}, "mine": row}
    raise HTTPException(404, "Project not found")


@router.get("/ownership/portfolio")
async def portfolio(user: User = Depends(real_user)):
    """Owner view: every person's share, cash in and returns across all the owner's properties."""
    people: dict = {}
    projects = []
    async for d in db.ownership_shares.find({"owner_id": user.id}):
        pdoc = await db.projects.find_one({"_id": ObjectId(d["project_id"]), "user_id": user.id})
        if not pdoc:
            continue
        p = Project.from_mongo(pdoc)
        split = await compute_split(user, p)
        if not split["has_split"] and not split["has_contributions"]:
            continue
        projects.append({"project_id": p.id, "project_name": p.name, "rows": [{k: r[k] for k in ("co_owner_id", "name", "pct", "contribution", "profit", "annual_cashflow")} for r in split["rows"]]})
        for r in split["rows"]:
            k = r["co_owner_id"] or "owner"
            e = people.setdefault(k, {"key": k, "name": r["name"], "email": r["email"], "is_owner": r["is_owner"], "projects": 0, "contribution": 0.0, "profit": 0.0, "annual_cashflow": 0.0})
            if r["pct"] > 0 or r["contribution"] > 0:
                e["projects"] += 1
            e["contribution"] += r["contribution"]
            e["profit"] += r["profit"] or 0
            e["annual_cashflow"] += r["annual_cashflow"]
    rows = sorted(people.values(), key=lambda e: (not e["is_owner"], -e["contribution"]))
    for e in rows:
        for k in ("contribution", "profit", "annual_cashflow"):
            e[k] = round(e[k], 2)
        e["cash_return_pct"] = round(e["annual_cashflow"] / e["contribution"] * 100, 1) if e["contribution"] else None
    return {"people": rows, "projects": projects}
