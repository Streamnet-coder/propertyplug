"""Company reply-to address (verified) + owner notifications.

Emails always leave from the platform's managed sender (display name = PropertyPlug); a verified
company address is used as Reply-To so partners' replies land in the owner's company inbox.
"""
import secrets
import time
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr

from core import E, db, logger
from deps import current_user
from email_service import EMAIL_FROM_NAME, EmailError, send_email
from html_utils import page
from models import User

router = APIRouter()
_sends: dict = {}  # uid -> [timestamps] for verification-email rate limiting


class CompanyEmailIn(BaseModel):
    email: EmailStr
    origin_url: str


async def _raw(uid: str) -> dict:
    return await db.users.find_one({"_id": ObjectId(uid)}, {"email": 1, "name": 1, "branding": 1, "company_email": 1, "company_email_verified": 1}) or {}


async def owner_reply_to(uid: str) -> str | None:
    u = await _raw(uid)
    return u.get("company_email") if u.get("company_email_verified") else u.get("email")


def _settings(u: dict) -> dict:
    return {"company_email": u.get("company_email"), "verified": bool(u.get("company_email_verified")), "sender_name": EMAIL_FROM_NAME,
            "company_name": (u.get("branding") or {}).get("company_name", ""), "account_email": u.get("email")}


@router.get("/email-settings")
async def get_email_settings(user: User = Depends(current_user)):
    return _settings(await _raw(user.id))


@router.post("/email-settings")
async def set_company_email(body: CompanyEmailIn, user: User = Depends(current_user)):
    if not body.origin_url.startswith("https://"):
        raise HTTPException(400, "Verification links need an https address")
    now = time.time()
    recent = [t for t in _sends.get(user.id, []) if now - t < 3600]
    if len(recent) >= 3:
        raise HTTPException(429, "Too many verification emails. Try again in an hour")
    _sends[user.id] = recent + [now]
    token = secrets.token_urlsafe(24)
    email = body.email.lower()
    await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"company_email": email, "company_email_verified": False,
                                                                   "company_email_token": token, "company_email_origin": body.origin_url}})
    link = f"{body.origin_url.rstrip('/')}/api/verify-email/{token}"
    html = (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
            f'<p>Hi {E(user.name)},</p><p>Confirm that <b>{E(email)}</b> is your company address. Replies to your weekly updates and '
            f'partner emails sent from {E(EMAIL_FROM_NAME)} will go to this inbox.</p>'
            f'<p><a href="{E(link)}" style="display:inline-block;background:#0f766e;color:#ffffff;padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:bold">Confirm this address</a></p>'
            f'<p style="font-size:12px;color:#888">If you did not request this, ignore this email. Sent by {E(EMAIL_FROM_NAME)}. '
            f'We never ask for your password by email.</p></td></tr></table>')
    try:
        await send_email(to=email, subject=f"Confirm your company email for {EMAIL_FROM_NAME}", html=html)
    except EmailError as e:
        raise HTTPException(503, str(e))
    return _settings(await _raw(user.id))


@router.delete("/email-settings")
async def clear_company_email(user: User = Depends(current_user)):
    await db.users.update_one({"_id": ObjectId(user.id)}, {"$unset": {"company_email": "", "company_email_verified": "", "company_email_token": ""}})
    return _settings(await _raw(user.id))


@router.get("/verify-email/{token}", response_class=HTMLResponse)
async def verify_company_email(token: str):
    u = await db.users.find_one({"company_email_token": token}) if token else None
    if not u:
        return page("Link expired", "<div class='card'><h2>This confirmation link has expired</h2><p>Request a new one from the app.</p></div>")
    await db.users.update_one({"_id": u["_id"]}, {"$set": {"company_email_verified": True, "company_email_verified_at": datetime.now(timezone.utc).isoformat()},
                                                  "$unset": {"company_email_token": ""}})
    return page("Email confirmed", f"<div class='card' id='email-verified'><h2>✓ {E(u['company_email'])} confirmed</h2>"
                                   "<p>Replies to your updates will now go to this inbox. You can close this page.</p></div>")


async def notify_owner_signoff(uid: str, project_name: str, assignee: str, signer: str, count: int, complete: bool, url: str):
    """Email the owner as soon as a trade signs off their snags."""
    u = await _raw(uid)
    to = await owner_reply_to(uid)
    if not to:
        return
    status = "Both signatures are in, so this list is fully signed off." if complete else "Add your signature in the app to close the job."
    html = (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
            f'<p style="font-size:12px;letter-spacing:1px;color:#0f766e;font-weight:bold;margin:0">{E(EMAIL_FROM_NAME.upper())} · SNAG SIGN-OFF</p>'
            f'<h1 style="font-size:20px;margin:8px 0">{E(assignee)} signed off their snags</h1>'
            f'<p>Hi {E(u.get("name", ""))}, <b>{E(signer)}</b> confirmed {count} fixed snag{"s" if count != 1 else ""} on <b>{E(project_name)}</b>.</p>'
            f'<p>{status}</p>'
            + (f'<p><a href="{E(url)}" style="display:inline-block;background:#0f766e;color:#ffffff;padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:bold">View the signed list</a></p>' if url.startswith("https://") else "")
            + f'<p style="font-size:12px;color:#888">Sent by {E(EMAIL_FROM_NAME)} because you manage this project.</p></td></tr></table>')
    try:
        await send_email(to=to, subject=f"{assignee} signed off snags on {project_name}", html=html)
    except (EmailError, ValueError) as e:
        logger.warning(f"Sign-off notification failed for {uid}: {e}")
