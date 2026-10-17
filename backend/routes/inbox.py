"""Task inbox: open snags, tenant repairs and upcoming/overdue stages across every project the person can open."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends

from core import db
from deps import real_user
from models import User
from routes.projects import access_filter

router = APIRouter()
PRIORITY = {"high": 0, "medium": 1, "low": 2}


@router.get("/inbox")
async def inbox(days: int = 30, user: User = Depends(real_user)):
    projects = {str(p["_id"]): p["name"] async for p in db.projects.find(await access_filter(user), {"name": 1})}
    pids = list(projects)
    today = date.today().isoformat()
    horizon = (date.today() + timedelta(days=max(1, min(days, 365)))).isoformat()
    items = []
    async for s in db.snags.find({"project_id": {"$in": pids}, "status": "open"}):
        tenant = bool(s.get("tenancy_id"))
        items.append({"id": str(s["_id"]), "kind": "repair" if tenant else "snag", "project_id": s["project_id"], "project_name": projects[s["project_id"]],
                      "title": s["description"], "detail": " · ".join(x for x in (s.get("room"), s.get("reported_by") or s.get("assignee")) if x),
                      "priority": s.get("priority", "medium"), "date": s.get("created_at", "")[:10], "overdue": False})
    async for m in db.milestones.find({"project_id": {"$in": pids}, "status": {"$ne": "done"}, "target_date": {"$nin": [None, ""], "$lte": horizon}}):
        items.append({"id": str(m["_id"]), "kind": "stage", "project_id": m["project_id"], "project_name": projects[m["project_id"]],
                      "title": m["name"], "detail": "In progress" if m["status"] == "in_progress" else "Not started",
                      "priority": "high" if m["target_date"] < today else "medium", "date": m["target_date"], "overdue": m["target_date"] < today})
    # Overdue stages and urgent repairs first, then by priority and date.
    items.sort(key=lambda i: (not i["overdue"], i["kind"] != "repair" or i["priority"] != "high", PRIORITY[i["priority"]], i["date"] or "9999"))
    counts = {k: sum(i["kind"] == k for i in items) for k in ("repair", "snag", "stage")}
    return {"items": items, "counts": {**counts, "overdue": sum(i["overdue"] for i in items), "total": len(items)}, "projects": len(pids)}
