"""Per-stakeholder communication log: every link, email, WhatsApp, call and reply recorded with a timestamp."""
from typing import Literal, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from core import db, now_iso
from deps import active_pid, current_user
from models import User

router = APIRouter()

Channel = Literal["email", "whatsapp", "call", "link", "share", "web"]


def stakeholder_key(name: str = "", email: str = "") -> str:
    return (email or "").strip().lower() or (name or "").strip().lower()


async def log_message(user_id: str, project_id: str, *, name: str, email: str = "", phone: str = "", channel: str, kind: str,
                      summary: str, url: Optional[str] = None, direction: str = "out", status: str = "sent"):
    await db.messages.insert_one({"user_id": user_id, "project_id": project_id, "key": stakeholder_key(name, email),
                                  "name_lc": (name or "").strip().lower(), "name": name.strip(), "email": email.strip().lower(), "phone": phone,
                                  "channel": channel, "kind": kind, "direction": direction, "status": status,
                                  "summary": summary[:500], "url": url, "created_at": now_iso()})


def _match(name: str, email: str) -> dict:
    keys = [k for k in {(email or "").strip().lower(), (name or "").strip().lower()} if k]
    return {"$or": [{"key": {"$in": keys}}, {"name_lc": {"$in": keys}}]}


class MessageIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field("", max_length=200)
    phone: str = Field("", max_length=40)
    channel: Channel
    kind: str = Field("message", max_length=40)
    summary: str = Field(min_length=1, max_length=500)
    url: Optional[str] = Field(None, max_length=500)


@router.post("/messages")
async def add_message(body: MessageIn, user: User = Depends(current_user)):
    await log_message(user.id, await active_pid(user), **body.model_dump())
    return {"ok": True}


@router.get("/messages")
async def list_messages(name: str = Query(""), email: str = Query(""), user: User = Depends(current_user)):
    docs = await db.messages.find({"user_id": user.id, "project_id": await active_pid(user), **_match(name, email)}).sort("created_at", -1).to_list(500)
    return [{**{k: d.get(k) for k in ("name", "email", "channel", "kind", "direction", "status", "summary", "url", "created_at")}, "id": str(d["_id"])} for d in docs]


@router.get("/stakeholders")
async def list_stakeholders(user: User = Depends(current_user)):
    """Team contacts + weekly-update partners, each with message count and last activity."""
    pid = await active_pid(user)
    people: dict = {}

    def add(name, email, phone, role, source, contact_id=None):
        k = stakeholder_key(name, email)
        if k and k not in people:
            people[k] = {"key": k, "name": name or email, "email": email, "phone": phone, "role": role, "source": source, "contact_id": contact_id}

    async for c in db.contacts.find({"user_id": user.id}).sort("name", 1):
        add(c["name"], c.get("email", ""), c.get("phone", ""), c.get("role") or c["kind"].title(), c["kind"], str(c["_id"]))
    proj = await db.projects.find_one({"_id": ObjectId(pid)}, {"digest_recipients": 1}) or {}
    for r in proj.get("digest_recipients", []):
        add(r.get("name") or r["email"], r["email"], "", "Weekly update partner", "partner")
    msgs = await db.messages.find({"user_id": user.id, "project_id": pid}, {"key": 1, "name_lc": 1, "summary": 1, "created_at": 1, "direction": 1}).sort("created_at", -1).to_list(5000)
    by_name = {p["name"].strip().lower(): k for k, p in people.items()}
    for m in msgs:
        k = m["key"] if m["key"] in people else by_name.get(m.get("name_lc", ""))
        if not k:
            continue
        p = people[k]
        p["count"] = p.get("count", 0) + 1
        if "last_at" not in p:
            p.update({"last_at": m["created_at"], "last_summary": m["summary"], "last_direction": m["direction"]})
    return sorted(people.values(), key=lambda p: p.get("last_at") or "", reverse=True)
