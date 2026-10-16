"""Project activity log: who (owner or co-owner) changed what on each project. Recorded by a middleware on
successful write requests so every route is covered without per-route code."""
from fastapi import APIRouter, Depends, Query, Request

from core import db, logger, now_iso
from deps import active_pid, current_user, user_from_token
from models import User

router = APIRouter()

AREAS = {
    "line-items": "budget item", "receipts": "receipt", "snags": "snag", "snag-signoffs": "snag sign-off", "quotes": "quote request",
    "milestones": "milestone", "documents": "document", "doc-folders": "document folder", "contacts": "contact", "shopping": "shopping item",
    "planning": "planning application", "project": "project details", "stage-payments": "stage payment", "media": "photo",
    "portal-members": "stakeholder access", "portal-questions": "stakeholder question reply", "digest": "weekly update", "trade-ratings": "trade rating",
    "messages": "message", "ai": "AI estimate",
}
VERBS = {"POST": "added", "PUT": "updated", "PATCH": "updated", "DELETE": "deleted"}
SPECIAL = {("POST", "send"): "sent", ("POST", "resend"): "resent", ("POST", "extend"): "extended", ("POST", "share"): "shared",
           ("POST", "toggle"): "updated", ("POST", "purchase"): "bought", ("POST", "fix"): "updated", ("POST", "zip"): "downloaded"}


async def log_write(request: Request, status: int):
    if request.method not in VERBS or status >= 400:
        return
    parts = request.url.path.split("/")[2:]  # after /api/
    area = AREAS.get(parts[0] if parts else "")
    auth = request.headers.get("authorization", "")
    if not area or not auth.lower().startswith("bearer "):
        return
    try:
        eff = await user_from_token(auth[7:])
        pid = await active_pid(eff)
    except Exception:
        return  # portal/public tokens or no project: nothing to attribute
    verb = next((v for (m, k), v in SPECIAL.items() if m == request.method and k in parts[1:]), VERBS[request.method])
    try:
        await db.project_activity.insert_one({"owner_id": eff.id, "project_id": pid, "actor_id": eff.real_id or eff.id,
                                              "actor_name": eff.real_name or eff.name, "is_owner": not eff.real_id,
                                              "action": f"{verb} {area}", "at": now_iso()})
    except Exception as e:
        logger.warning(f"Activity log failed: {e}")


@router.get("/project-activity")
async def project_activity(limit: int = Query(100, ge=1, le=300), user: User = Depends(current_user)):
    pid = await active_pid(user)
    docs = await db.project_activity.find({"owner_id": user.id, "project_id": pid}).sort("at", -1).to_list(limit)
    me = user.real_id or user.id
    return [{"id": str(d["_id"]), "actor_name": d["actor_name"], "is_owner": d["is_owner"], "is_you": d["actor_id"] == me,
             "action": d["action"], "at": d["at"]} for d in docs]
