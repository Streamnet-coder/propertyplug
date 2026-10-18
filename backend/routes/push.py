"""Emergent managed push notifications (SuprSend relay). Devices register their native token; the backend triggers pushes by user id."""
import asyncio
import logging
import os
from typing import List, Optional

import httpx
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import db
from deps import real_user
from models import User

logger = logging.getLogger(__name__)
router = APIRouter()

PUSH_BASE_URL = "https://integrations.emergentagent.com"
PUSH_KEY = os.environ.get("EMERGENT_PUSH_KEY", "placeholder")
_client = httpx.AsyncClient(base_url=PUSH_BASE_URL, headers={"X-Push-Key": PUSH_KEY}, timeout=10.0)


class RegisterPushBody(BaseModel):
    user_id: str
    platform: str  # "android" | "ios"
    device_token: str


@router.post("/register-push", status_code=201)
async def register_push(body: RegisterPushBody, user: User = Depends(real_user)):
    if body.user_id != user.id:
        raise HTTPException(403, "You can only register your own device")
    resp = await _client.post("/api/v1/push/users/register", json=body.model_dump())
    if resp.status_code == 401:
        raise HTTPException(500, "EMERGENT_PUSH_KEY missing or invalid")
    if resp.status_code >= 500:
        raise HTTPException(502, "Push provider unavailable")
    resp.raise_for_status()
    return {"status": "registered"}


async def send_push(recipients: List[str], data: dict, idempotency_key: Optional[str] = None, _attempt: int = 0) -> None:
    if not recipients:
        return
    if len(recipients) > 100:
        raise ValueError("max 100 recipients per /trigger call; chunk before sending")
    if "title" not in data or "message" not in data:
        raise ValueError("data must include title and message")
    payload: dict = {"recipients": recipients, "data": data}
    if idempotency_key:
        payload["$idempotency_key"] = idempotency_key
    resp = await _client.post("/api/v1/push/trigger", json=payload)
    if resp.status_code == 401:
        raise HTTPException(500, "EMERGENT_PUSH_KEY missing or invalid")
    code = resp.json().get("code", "") if resp.headers.get("content-type", "").startswith("application/json") else ""
    if code == "idempotency_key_in_progress" and idempotency_key and _attempt < 3:
        await asyncio.sleep(3)
        return await send_push(recipients, data, idempotency_key=idempotency_key, _attempt=_attempt + 1)
    if code in ("insufficient_credits", "integration_disabled", "daily_limit_reached"):
        logger.warning(f"Push paused: {code} ({resp.status_code}): {resp.json().get('message', '')}")
        return
    if resp.status_code >= 500:
        raise HTTPException(502, "Push provider unavailable")
    resp.raise_for_status()


PREF_KINDS = ("repairs", "jobs", "fixed", "payouts", "invites")


class PrefsIn(BaseModel):
    repairs: bool = True   # tenant reports a problem
    jobs: bool = True      # a job is assigned to me
    fixed: bool = True     # a job is marked fixed
    payouts: bool = True   # a payout is recorded to me
    invites: bool = True   # someone accepts my invite


@router.get("/notification-prefs")
async def get_prefs(user: User = Depends(real_user)):
    u = await db.users.find_one({"_id": ObjectId(user.id)}, {"notify_prefs": 1}) or {}
    return {**PrefsIn().model_dump(), **(u.get("notify_prefs") or {})}


@router.put("/notification-prefs")
async def put_prefs(body: PrefsIn, user: User = Depends(real_user)):
    await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"notify_prefs": body.model_dump()}})
    return body.model_dump()


async def notify(user_ids: List[Optional[str]], title: str, message: str, action_url: Optional[str] = None, kind: Optional[str] = None) -> None:
    """Fire-and-forget push to app users who haven't switched this kind of alert off; never blocks the calling action."""
    ids = [u for u in dict.fromkeys(user_ids) if u and ObjectId.is_valid(u)]
    if kind and ids:
        off = {str(d["_id"]) async for d in db.users.find({"_id": {"$in": [ObjectId(i) for i in ids]}, f"notify_prefs.{kind}": False}, {"_id": 1})}
        ids = [i for i in ids if i not in off]
    if not ids:
        return
    data = {"title": title[:80], "message": message[:200], **({"action_url": action_url} if action_url else {})}
    try:
        await send_push(ids, data)
    except Exception as e:
        logger.warning(f"Push failed (non-blocking): {e}")


async def user_id_for_email(email: str) -> Optional[str]:
    u = await db.users.find_one({"email": (email or "").lower()}, {"_id": 1}) if email else None
    return str(u["_id"]) if u else None
