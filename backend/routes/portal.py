"""Stakeholder portal: owners grant investors/lenders/partners read-only access to chosen projects, documents and
weekly updates. Stakeholders sign in either with their personal access code + a password they set themselves, or with their
email / name@buildassist handle + a one-time email code. Several people from one company can each have their own login."""
import base64
import hashlib
import hmac
import re
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

import bcrypt
import jwt
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field, field_validator

from core import E, JWT_SECRET, bearer, db, logger, now_iso, oid, sym
from deps import active_pid, current_user, get_project_doc
from email_service import EMAIL_FROM_NAME, EmailError, send_email
from html_utils import PAGE_CSS
from models import Project, User
from routes.digest import build_digest
from routes.documents import _attachment, _out as doc_out
from routes.email_settings import owner_reply_to
from routes.messages import log_message
from routes.projects import project_summary
from storage import get_object

router = APIRouter()
HANDLE_DOMAIN = "buildassist"
PORTAL_SECRET = JWT_SECRET + "|portal"  # different key: portal tokens can never authenticate owner APIs
CODE_TTL = 600
MAX_FAILS = 5
LOCK_SECONDS = 900


def active_q() -> dict:
    """Memberships still in date (no end date, or end date today or later: access lasts through the end date)."""
    return {"$or": [{"expires_on": None}, {"expires_on": {"$exists": False}}, {"expires_on": {"$gte": date.today().isoformat()}}]}


def is_expired(m: dict) -> bool:
    return bool(m.get("expires_on")) and m["expires_on"] < date.today().isoformat()


def _valid_end(v):
    if not v:
        return None
    try:
        d = date.fromisoformat(v)
    except ValueError:
        raise ValueError("Use date format YYYY-MM-DD")
    return d.isoformat()


def handle_addr(h: str) -> str:
    return f"{h}@{HANDLE_DOMAIN}"


async def ensure_handle(email: str, name: str, wanted: Optional[str] = None) -> str:
    """One global handle per stakeholder email (e.g. dave@buildassist)."""
    existing = await db.portal_handles.find_one({"email": email})
    if existing:
        return existing["handle"]
    base = re.sub(r"[^a-z0-9.]", "", (wanted or name.split(" ")[0] or email.split("@")[0]).lower())[:24] or "partner"
    h, n = base, 2
    while await db.portal_handles.find_one({"handle": h}):
        h, n = f"{base}{n}", n + 1
    await db.portal_handles.insert_one({"handle": h, "email": email, "created_at": now_iso()})
    return h


# ---------------- Owner side ----------------
class MemberIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    role: str = Field("Investor", max_length=40)
    company: str = Field("", max_length=80)
    handle: Optional[str] = Field(None, max_length=24)
    doc_ids: List[str] = Field(default_factory=list, max_length=200)
    digest: bool = True
    expires_on: Optional[str] = None
    origin_url: str

    @field_validator("expires_on")
    @classmethod
    def _end(cls, v):
        return _valid_end(v)


class MemberUpdate(BaseModel):
    role: Optional[str] = Field(None, max_length=40)
    company: Optional[str] = Field(None, max_length=80)
    doc_ids: Optional[List[str]] = Field(None, max_length=200)
    digest: Optional[bool] = None
    is_lead: Optional[bool] = None
    expires_on: Optional[str] = None  # send null to remove the end date

    @field_validator("expires_on")
    @classmethod
    def _end(cls, v):
        return _valid_end(v)


class TeammateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr


async def member_out(m: dict) -> dict:
    h = await db.portal_handles.find_one({"email": m["email"]}, {"handle": 1})
    acc = await db.portal_accounts.find_one({"email": m["email"]}, {"password_hash": 1})
    return {"id": str(m["_id"]), "name": m["name"], "email": m["email"], "role": m["role"], "company": m.get("company", ""), "doc_ids": m["doc_ids"], "digest": m["digest"],
            "password_set": bool(acc and acc.get("password_hash")), "is_lead": m.get("is_lead", False), "invited_by": m.get("invited_by"),
            "expires_on": m.get("expires_on"), "expired": is_expired(m),
            "handle": handle_addr(h["handle"]) if h else None, "last_login": m.get("last_login"), "invited_at": m.get("invited_at"),
            "portal_url": f"{m['origin'].rstrip('/')}/api/portal" if m.get("origin") else None}


# ---------------- Access codes (permanent ID) + passwords ----------------
def _norm_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", code.upper()).removeprefix("BA")


def _code_lookup(code: str) -> str:
    return hmac.new(PORTAL_SECRET.encode(), f"access:{_norm_code(code)}".encode(), hashlib.sha256).hexdigest()


async def issue_access_code(email: str) -> Optional[str]:
    """New access code for stakeholders who have not set a password yet (rotates any earlier unused code).
    Returns None once they have a password: their existing code keeps working and is never re-sent in plain text."""
    acc = await db.portal_accounts.find_one({"email": email})
    if acc and acc.get("password_hash"):
        return None
    raw = base64.b32encode(secrets.token_bytes(10)).decode()  # 16 chars, 80 bits
    code = "BA-" + "-".join(raw[i:i + 4] for i in range(0, 16, 4))
    await db.portal_accounts.update_one({"email": email}, {"$set": {"code_lookup": _code_lookup(code), "code_issued_at": now_iso()},
                                                           "$setOnInsert": {"created_at": now_iso(), "failed": 0}}, upsert=True)
    return code


async def _invite_email(m: dict, owner: User, project_name: str, access_code: Optional[str] = None):
    url = f"{m['origin'].rstrip('/')}/api/portal"
    h = await db.portal_handles.find_one({"email": m["email"]}, {"handle": 1})
    html = (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
            f'<p style="font-size:12px;letter-spacing:1px;color:#0f766e;font-weight:bold;margin:0">{E(EMAIL_FROM_NAME.upper())} · STAKEHOLDER PORTAL</p>'
            f'<h1 style="font-size:20px;margin:8px 0">You have access to {E(project_name)}</h1>'
            f'<p>Hi {E(m["name"])}, {E(owner.name)} has shared project updates and documents with you.</p>'
            + (f'<p>Your access runs until <b>{E(m["expires_on"])}</b>.</p>' if m.get("expires_on") else '')
            + (f'<div style="background:#f0fdfa;border:1px solid #99f6e4;border-radius:10px;padding:14px;margin:12px 0"><p style="margin:0 0 4px">Your personal access code:</p>'
               f'<p style="font-size:20px;font-weight:bold;letter-spacing:2px;margin:0;font-family:monospace">{E(access_code)}</p>'
               f'<p style="margin:8px 0 0;font-size:13px">First time? Open the portal, choose <b>Set up password</b>, enter this code and create your password. After that, sign in with the code + your password.</p></div>'
               if access_code else '<p>Sign in with your access code and password as usual.</p>')
            + f'<p>Prefer not to use a password? Sign in with <b>{E(handle_addr(h["handle"]))}</b> or this email and we will email you a one-time code.</p>'
            f'<p><a href="{E(url)}" style="display:inline-block;background:#0f766e;color:#ffffff;padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:bold">Open the portal</a></p>'
            f'<p style="font-size:12px;color:#888">Sent by {E(EMAIL_FROM_NAME)} on behalf of {E(owner.name)}. We never ask for your password by email.</p></td></tr></table>')
    await send_email(to=m["email"], subject=f"{owner.name} shared {project_name} with you", html=html, reply_to=await owner_reply_to(owner.id))


@router.get("/portal-members")
async def list_members(user: User = Depends(current_user)):
    docs = await db.portal_members.find({"owner_id": user.id, "project_id": await active_pid(user)}).sort("created_at", 1).to_list(100)
    return [await member_out(m) for m in docs]


@router.post("/portal-members")
async def add_member(body: MemberIn, user: User = Depends(current_user)):
    if not body.origin_url.startswith("https://"):
        raise HTTPException(400, "Portal links need an https address")
    p = await get_project_doc(user)
    email = body.email.lower()
    if await db.portal_members.find_one({"project_id": p.id, "email": email}):
        raise HTTPException(400, "This person already has access to this project")
    if await db.portal_members.count_documents({"owner_id": user.id, "project_id": p.id}) >= 25:
        raise HTTPException(400, "Up to 25 stakeholders per project")
    if body.expires_on and body.expires_on < date.today().isoformat():
        raise HTTPException(400, "End date can't be in the past")
    own = {str(d["_id"]) for d in await db.documents.find({"_id": {"$in": [oid(i) for i in body.doc_ids]}, "user_id": user.id, "project_id": p.id}, {"_id": 1}).to_list(200)}
    await ensure_handle(email, body.name, body.handle)
    code = await issue_access_code(email)
    m = {"owner_id": user.id, "project_id": p.id, "name": body.name.strip(), "email": email, "role": body.role.strip() or "Investor", "company": body.company.strip(), "expires_on": body.expires_on,
         "doc_ids": [i for i in body.doc_ids if i in own], "digest": body.digest, "origin": body.origin_url, "created_at": now_iso(), "invited_at": now_iso()}
    m["_id"] = (await db.portal_members.insert_one(m)).inserted_id
    try:
        await _invite_email(m, user, p.name, code)
        await log_message(user.id, p.id, name=m["name"], email=email, channel="email", kind="portal_invite", summary=f"Invited to the stakeholder portal for {p.name}")
        sent = True
    except (EmailError, ValueError) as e:
        logger.warning(f"Portal invite email failed: {e}")
        sent = False
    return {**await member_out(m), "email_sent": sent}


@router.get("/portal-members/expiring")
async def expiring_members(days: int = Query(7, ge=1, le=60), user: User = Depends(current_user)):
    """Across all the owner's projects: access ending within `days`, plus access that ended in the last 7 days (so it can be restored)."""
    today = date.today()
    lo, hi = (today - timedelta(days=7)).isoformat(), (today + timedelta(days=days)).isoformat()
    docs = await db.portal_members.find({"owner_id": user.id, "expires_on": {"$gte": lo, "$lte": hi}}).sort("expires_on", 1).to_list(100)
    names = {str(p["_id"]): p["name"] for p in await db.projects.find({"_id": {"$in": list({ObjectId(d["project_id"]) for d in docs})}}, {"name": 1}).to_list(100)}
    return [{"id": str(d["_id"]), "name": d["name"], "email": d["email"], "role": d["role"], "company": d.get("company", ""), "project_id": d["project_id"],
             "project_name": names.get(d["project_id"], ""), "expires_on": d["expires_on"], "expired": is_expired(d),
             "days_left": (date.fromisoformat(d["expires_on"]) - today).days} for d in docs]


class ExtendIn(BaseModel):
    days: int = Field(30, ge=1, le=366)


@router.post("/portal-members/{mid}/extend")
async def extend_member(mid: str, body: ExtendIn, user: User = Depends(current_user)):
    """One-tap extension: adds days to the current end date (or to today if it already passed)."""
    m = await db.portal_members.find_one({"_id": oid(mid), "owner_id": user.id})
    if not m:
        raise HTTPException(404, "Not found")
    base = max(date.today(), date.fromisoformat(m["expires_on"])) if m.get("expires_on") else date.today()
    new = (base + timedelta(days=body.days)).isoformat()
    await db.portal_members.update_one({"_id": m["_id"]}, {"$set": {"expires_on": new}})
    return {"id": mid, "expires_on": new}


@router.put("/portal-members/{mid}")
async def update_member(mid: str, body: MemberUpdate, user: User = Depends(current_user)):
    m = await db.portal_members.find_one({"_id": oid(mid), "owner_id": user.id})
    if not m:
        raise HTTPException(404, "Not found")
    upd = body.model_dump(exclude_unset=True)
    if upd.get("expires_on") and upd["expires_on"] < date.today().isoformat():
        raise HTTPException(400, "End date can't be in the past")
    if upd.get("is_lead") and not (upd.get("company", m.get("company")) or "").strip():
        raise HTTPException(400, "Add their company first so we know which team they lead")
    if "doc_ids" in upd:
        own = {str(d["_id"]) for d in await db.documents.find({"_id": {"$in": [oid(i) for i in upd["doc_ids"]]}, "user_id": user.id, "project_id": m["project_id"]}, {"_id": 1}).to_list(200)}
        upd["doc_ids"] = [i for i in upd["doc_ids"] if i in own]
    await db.portal_members.update_one({"_id": m["_id"]}, {"$set": upd})
    return await member_out(await db.portal_members.find_one({"_id": m["_id"]}))


@router.post("/portal-members/{mid}/resend")
async def resend_invite(mid: str, user: User = Depends(current_user)):
    m = await db.portal_members.find_one({"_id": oid(mid), "owner_id": user.id})
    if not m:
        raise HTTPException(404, "Not found")
    if is_expired(m):
        raise HTTPException(400, "Their access has ended. Extend the end date first")
    if m.get("invited_at") and (datetime.now(timezone.utc) - datetime.fromisoformat(m["invited_at"])).total_seconds() < 120:
        raise HTTPException(429, "Invite just sent. Try again in a couple of minutes")
    p = await db.projects.find_one({"_id": ObjectId(m["project_id"])}, {"name": 1}) or {}
    try:
        await _invite_email(m, user, p.get("name", "your project"), await issue_access_code(m["email"]))
    except EmailError as e:
        raise HTTPException(503, str(e))
    await db.portal_members.update_one({"_id": m["_id"]}, {"$set": {"invited_at": now_iso()}})
    return {"ok": True}


@router.delete("/portal-members/{mid}")
async def remove_member(mid: str, user: User = Depends(current_user)):
    await db.portal_members.delete_one({"_id": oid(mid), "owner_id": user.id})
    return {"ok": True}


async def log_activity(m: dict, kind: str, doc: dict | None = None, detail: str | None = None):
    await db.portal_activity.insert_one({"owner_id": m["owner_id"], "project_id": m["project_id"], "email": m["email"], "name": m["name"],
                                         "kind": kind, "doc_id": str(doc["_id"]) if doc else None, "doc_title": doc["title"] if doc else None,
                                         "doc_type": doc["doc_type"] if doc else None, "detail": detail, "at": now_iso()})


@router.get("/portal-activity")
async def portal_activity(user: User = Depends(current_user)):
    docs = await db.portal_activity.find({"owner_id": user.id, "project_id": await active_pid(user)}).sort("at", -1).to_list(300)
    return [{"id": str(a["_id"]), **{k: a.get(k) for k in ("email", "name", "kind", "doc_id", "doc_title", "doc_type", "detail", "at")}} for a in docs]


# ---------------- Questions & comments ----------------
class QuestionIn(BaseModel):
    text: str = Field(min_length=2, max_length=2000)


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def q_out(q: dict) -> dict:
    return {"id": str(q["_id"]), "name": q["name"], "email": q["email"], "text": q["text"], "created_at": q["created_at"],
            "reply": q.get("reply"), "replied_at": q.get("replied_at")}


@router.get("/portal-questions")
async def owner_questions(user: User = Depends(current_user)):
    docs = await db.portal_questions.find({"owner_id": user.id, "project_id": await active_pid(user)}).sort("created_at", -1).to_list(300)
    return [q_out(q) for q in docs]


@router.post("/portal-questions/{qid}/reply")
async def reply_question(qid: str, body: ReplyIn, user: User = Depends(current_user)):
    q = await db.portal_questions.find_one({"_id": oid(qid), "owner_id": user.id})
    if not q:
        raise HTTPException(404, "Question not found")
    await db.portal_questions.update_one({"_id": q["_id"]}, {"$set": {"reply": body.text.strip(), "replied_at": now_iso()}})
    m = await db.portal_members.find_one({"email": q["email"], "project_id": q["project_id"]})
    p = await db.projects.find_one({"_id": ObjectId(q["project_id"])}, {"name": 1}) or {}
    await log_message(user.id, q["project_id"], name=q["name"], email=q["email"], channel="web", kind="portal_reply", summary=f"Replied in portal: {body.text.strip()[:200]}")
    if m and m.get("origin", "").startswith("https://"):
        html = (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
                f'<p>Hi {E(q["name"])}, {E(user.name)} replied to your question about <b>{E(p.get("name", "the project"))}</b>.</p>'
                f'<p style="color:#64748b">You asked: “{E(q["text"][:300])}”</p>'
                f'<p><a href="{E(m["origin"].rstrip("/"))}/api/portal" style="display:inline-block;background:#0f766e;color:#ffffff;padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:bold">Read the reply in the portal</a></p>'
                f'<p style="font-size:12px;color:#888">Sent by {E(EMAIL_FROM_NAME)} on behalf of {E(user.name)}.</p></td></tr></table>')
        try:
            await send_email(to=q["email"], subject=f"{user.name} replied about {p.get('name', 'your project')}", html=html, reply_to=await owner_reply_to(user.id))
        except (EmailError, ValueError) as e:
            logger.warning(f"Portal reply email failed: {e}")
    return q_out(await db.portal_questions.find_one({"_id": q["_id"]}))


# ---------------- Stakeholder sign-in (one-time email code) ----------------
class CodeRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=200)


class CodeVerify(CodeRequest):
    code: str = Field(min_length=6, max_length=6)


def _code_hash(email: str, code: str) -> str:
    return hmac.new(PORTAL_SECRET.encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


async def _resolve(identifier: str) -> Optional[str]:
    ident = identifier.strip().lower()
    if ident.endswith(f"@{HANDLE_DOMAIN}") or "@" not in ident:
        h = await db.portal_handles.find_one({"handle": ident.split("@")[0]})
        ident = h["email"] if h else ""
    return ident if ident and await db.portal_members.find_one({"email": ident, **active_q()}, {"_id": 1}) else None


@router.post("/portal/request-code")
async def request_code(body: CodeRequest):
    email = await _resolve(body.identifier)
    if email:  # silent when unknown: no account enumeration
        rec = await db.portal_codes.find_one({"email": email}) or {}
        sends = [t for t in rec.get("sends", []) if time.time() - t < 900]
        if len(sends) < 3:
            code = f"{secrets.randbelow(1_000_000):06d}"
            await db.portal_codes.update_one({"email": email}, {"$set": {"hash": _code_hash(email, code), "expires": time.time() + CODE_TTL,
                                                                         "attempts": 0, "sends": sends + [time.time()]}}, upsert=True)
            html = (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
                    f'<p>Your {E(EMAIL_FROM_NAME)} portal sign-in code is:</p><p style="font-size:30px;font-weight:bold;letter-spacing:6px">{code}</p>'
                    f'<p>It expires in 10 minutes. If you did not try to sign in, ignore this email.</p>'
                    f'<p style="font-size:12px;color:#888">Sent by {E(EMAIL_FROM_NAME)}. We never ask for this code by phone or email.</p></td></tr></table>')
            try:
                await send_email(to=email, subject=f"{code} is your {EMAIL_FROM_NAME} sign-in code", html=html)
            except EmailError as e:
                logger.warning(f"Portal code email failed: {e}")
    return {"ok": True, "message": "If that ID has portal access, we've emailed a 6-digit code."}


@router.post("/portal/verify")
async def verify_code(body: CodeVerify):
    email = await _resolve(body.identifier)
    rec = await db.portal_codes.find_one({"email": email}) if email else None
    if not rec or rec.get("expires", 0) < time.time() or rec.get("attempts", 0) >= 5:
        raise HTTPException(401, "Code expired. Request a new one")
    if not hmac.compare_digest(rec["hash"], _code_hash(email, body.code.strip())):
        await db.portal_codes.update_one({"_id": rec["_id"]}, {"$inc": {"attempts": 1}})
        raise HTTPException(401, "Incorrect code")
    await db.portal_codes.delete_one({"_id": rec["_id"]})
    return await _session(email)


async def _session(email: str) -> dict:
    await db.portal_members.update_many({"email": email, **active_q()}, {"$set": {"last_login": now_iso()}})
    async for m in db.portal_members.find({"email": email, **active_q()}):
        await log_activity(m, "login")
    n = datetime.now(timezone.utc)
    return {"token": jwt.encode({"sub": email, "typ": "portal", "iat": n, "exp": n + timedelta(days=7)}, PORTAL_SECRET, algorithm="HS256")}


class PasswordLogin(BaseModel):
    access_code: str = Field(min_length=8, max_length=40)
    password: str = Field(min_length=1, max_length=128)


class ResetRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=200)  # access code, email or name@buildassist


class ResetConfirm(ResetRequest):
    reset_code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(max_length=128)


_DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt()).decode()


def _check_password_rules(pw: str):
    if len(pw) < 8 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        raise HTTPException(400, "Password needs at least 8 characters, including a letter and a number")


async def _account_by_code(code: str) -> Optional[dict]:
    acc = await db.portal_accounts.find_one({"code_lookup": _code_lookup(code)})
    # Access only while they are still a member of at least one project.
    return acc if acc and await db.portal_members.find_one({"email": acc["email"], **active_q()}, {"_id": 1}) else None


@router.post("/portal/activate")
async def activate(body: PasswordLogin):
    """First sign-in: stakeholder proves the emailed access code and chooses their password."""
    _check_password_rules(body.password)
    acc = await _account_by_code(body.access_code)
    if not acc:
        raise HTTPException(400, "That access code isn't valid. Check your invite email")
    if acc.get("password_hash"):
        raise HTTPException(409, "Password already set. Sign in with your access code and password")
    hashed = await run_in_threadpool(lambda: bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode())
    await db.portal_accounts.update_one({"_id": acc["_id"]}, {"$set": {"password_hash": hashed, "activated_at": now_iso(), "failed": 0, "locked_until": 0}})
    return await _session(acc["email"])


@router.post("/portal/login-password")
async def login_password(body: PasswordLogin):
    acc = await _account_by_code(body.access_code)
    if acc and acc.get("locked_until", 0) > time.time():
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes or reset your password")
    stored = (acc or {}).get("password_hash") or _DUMMY_HASH  # constant work for unknown codes
    ok = await run_in_threadpool(bcrypt.checkpw, body.password.encode(), stored.encode())
    if not acc or not acc.get("password_hash") or not ok:
        if acc:
            fails = acc.get("failed", 0) + 1
            await db.portal_accounts.update_one({"_id": acc["_id"]}, {"$set": {"failed": 0 if fails >= MAX_FAILS else fails,
                                                                               **({"locked_until": time.time() + LOCK_SECONDS} if fails >= MAX_FAILS else {})}})
            if not acc.get("password_hash"):
                raise HTTPException(401, "No password set yet. Choose Set up password first")
        raise HTTPException(401, "Access code or password is incorrect")
    await db.portal_accounts.update_one({"_id": acc["_id"]}, {"$set": {"failed": 0, "locked_until": 0}})
    return await _session(acc["email"])


async def _account_by_identifier(identifier: str) -> Optional[dict]:
    email = await _resolve(identifier)
    if email:  # members invited before passwords existed get an account on first reset
        await db.portal_accounts.update_one({"email": email}, {"$setOnInsert": {"created_at": now_iso(), "failed": 0}}, upsert=True)
        return await db.portal_accounts.find_one({"email": email})
    return await _account_by_code(identifier)


@router.post("/portal/password-reset/request")
async def reset_request(body: ResetRequest):
    acc = await _account_by_identifier(body.identifier)
    if acc:  # generic response either way: no account enumeration
        sends = [t for t in (acc.get("reset") or {}).get("sends", []) if time.time() - t < 900]
        if len(sends) < 3:
            code = f"{secrets.randbelow(1_000_000):06d}"
            await db.portal_accounts.update_one({"_id": acc["_id"]}, {"$set": {"reset": {"hash": _code_hash(acc["email"], "reset:" + code), "expires": time.time() + CODE_TTL,
                                                                                          "attempts": 0, "sends": sends + [time.time()]}}})
            html = (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
                    f'<p>Your {E(EMAIL_FROM_NAME)} portal password reset code is:</p><p style="font-size:30px;font-weight:bold;letter-spacing:6px">{code}</p>'
                    f'<p>It expires in 10 minutes. If you did not ask to reset your password, ignore this email. Your password has not changed.</p></td></tr></table>')
            try:
                await send_email(to=acc["email"], subject=f"{code} is your {EMAIL_FROM_NAME} password reset code", html=html)
            except EmailError as e:
                logger.warning(f"Portal reset email failed: {e}")
    return {"ok": True, "message": "If that matches a portal account, we've emailed a 6-digit reset code."}


@router.post("/portal/password-reset/confirm")
async def reset_confirm(body: ResetConfirm):
    _check_password_rules(body.new_password)
    acc = await _account_by_identifier(body.identifier)
    rec = (acc or {}).get("reset")
    if not rec or rec.get("expires", 0) < time.time() or rec.get("attempts", 0) >= 5:
        raise HTTPException(401, "Reset code expired. Request a new one")
    if not hmac.compare_digest(rec["hash"], _code_hash(acc["email"], "reset:" + body.reset_code.strip())):
        await db.portal_accounts.update_one({"_id": acc["_id"]}, {"$inc": {"reset.attempts": 1}})
        raise HTTPException(401, "Incorrect reset code")
    # No access code yet (older invite): issue one now and show it once to this verified user.
    code = None if acc.get("code_lookup") else await issue_access_code(acc["email"])
    hashed = await run_in_threadpool(lambda: bcrypt.hashpw(body.new_password.encode(), bcrypt.gensalt()).decode())
    await db.portal_accounts.update_one({"_id": acc["_id"]}, {"$set": {"password_hash": hashed, "failed": 0, "locked_until": 0, "activated_at": acc.get("activated_at") or now_iso()},
                                                              "$unset": {"reset": ""}})
    return {**await _session(acc["email"]), "access_code": code}


async def portal_email(cred: HTTPAuthorizationCredentials = Depends(bearer)) -> str:
    if not cred:
        raise HTTPException(401, "Not signed in")
    try:
        data = jwt.decode(cred.credentials, PORTAL_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired. Sign in again")
    if data.get("typ") != "portal":
        raise HTTPException(401, "Not signed in")
    return data["sub"]


async def _membership(email: str, pid: str) -> dict:
    m = await db.portal_members.find_one({"email": email, "project_id": pid})
    if not m:
        raise HTTPException(404, "Project not shared with you")
    if is_expired(m):
        raise HTTPException(403, f"Your access to this project ended on {m['expires_on']}. Ask the owner to extend it")
    return m


@router.get("/portal/me")
async def portal_me(email: str = Depends(portal_email)):
    h = await db.portal_handles.find_one({"email": email}, {"handle": 1})
    out = []
    async for m in db.portal_members.find({"email": email, **active_q()}):
        p = await db.projects.find_one({"_id": ObjectId(m["project_id"])}, {"name": 1, "address": 1})
        o = await db.users.find_one({"_id": ObjectId(m["owner_id"])}, {"name": 1, "branding": 1})
        if p and o:
            out.append({"project_id": m["project_id"], "name": p["name"], "address": p.get("address", ""), "role": m["role"], "expires_on": m.get("expires_on"),
                        "owner": ((o.get("branding") or {}).get("company_name") or o["name"])})
    return {"email": email, "handle": handle_addr(h["handle"]) if h else None, "projects": out}


@router.get("/portal/projects/{pid}")
async def portal_project(pid: str, week: int = Query(0, ge=0, le=52), email: str = Depends(portal_email)):
    m = await _membership(email, pid)
    last = await db.portal_activity.find_one({"email": email, "project_id": pid, "kind": "view"}, sort=[("at", -1)])
    if not last or (datetime.now(timezone.utc) - datetime.fromisoformat(last["at"])).total_seconds() > 3600:
        await log_activity(m, "view")
    s = await project_summary(Project.from_mongo(await db.projects.find_one({"_id": ObjectId(pid)})))
    docs = await db.documents.find({"_id": {"$in": [oid(i) for i in m["doc_ids"]]}, "project_id": pid}).sort("doc_type", 1).to_list(200)
    return {"name": s["name"], "address": s["address"], "stage": s["current_stage"], "milestones_done": s["milestones_done"],
            "milestones_total": s["milestones_total"], "total_budget": s["total_budget"], "total_spent": s["total_spent"],
            "purchase_price": s["purchase_price"], "estimated_valuation": s["estimated_valuation"], "role": m["role"], "symbol": sym(s["currency"]),
            "company": m.get("company", ""), "is_lead": bool(m.get("is_lead") and m.get("company")), "expires_on": m.get("expires_on"),
            "documents": [{k: v for k, v in doc_out(d).items() if k != "share_url"} for d in docs],
            "digest": await build_digest(pid, week) if m["digest"] else None}


@router.get("/portal/projects/{pid}/documents/{did}")
async def portal_document(pid: str, did: str, email: str = Depends(portal_email)):
    m = await _membership(email, pid)
    if did not in m["doc_ids"]:
        raise HTTPException(404, "Document not shared with you")
    d = await db.documents.find_one({"_id": oid(did), "project_id": pid})
    if not d:
        raise HTTPException(404, "Document not found")
    data, _ = await run_in_threadpool(get_object, d["storage_path"])
    await log_activity(m, "download", d)
    return _attachment(d, data)


@router.get("/portal/projects/{pid}/questions")
async def portal_questions(pid: str, email: str = Depends(portal_email)):
    await _membership(email, pid)
    return [q_out(q) for q in await db.portal_questions.find({"project_id": pid, "email": email}).sort("created_at", -1).to_list(200)]


@router.post("/portal/projects/{pid}/questions")
async def ask_question(pid: str, body: QuestionIn, email: str = Depends(portal_email)):
    m = await _membership(email, pid)
    if await db.portal_questions.count_documents({"email": email, "project_id": pid, "created_at": {"$gte": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}}) >= 10:
        raise HTTPException(429, "Too many questions in the last hour")
    q = {"owner_id": m["owner_id"], "project_id": pid, "email": email, "name": m["name"], "text": body.text.strip(), "created_at": now_iso()}
    q["_id"] = (await db.portal_questions.insert_one(q)).inserted_id
    await log_message(m["owner_id"], pid, name=m["name"], email=email, channel="web", kind="portal_question", direction="in", summary=f"Asked: {q['text'][:200]}")
    owner = await db.users.find_one({"_id": ObjectId(m["owner_id"])}, {"name": 1})
    p = await db.projects.find_one({"_id": ObjectId(pid)}, {"name": 1}) or {}
    to = await owner_reply_to(m["owner_id"])
    if to:
        html = (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
                f'<p style="font-size:12px;letter-spacing:1px;color:#0f766e;font-weight:bold;margin:0">{E(EMAIL_FROM_NAME.upper())} · PORTAL QUESTION</p>'
                f'<p>Hi {E((owner or {}).get("name", ""))}, <b>{E(m["name"])}</b> ({E(m["role"])}) asked about <b>{E(p.get("name", ""))}</b>:</p>'
                f'<p style="border-left:3px solid #0f766e;padding-left:12px">{E(q["text"])}</p><p>Reply from the app: Documents → Stakeholder portal → Questions.</p>'
                f'<p style="font-size:12px;color:#888">Sent by {E(EMAIL_FROM_NAME)} because you manage this project.</p></td></tr></table>')
        try:
            await send_email(to=to, subject=f"{m['name']} asked a question about {p.get('name', 'your project')}", html=html)
        except (EmailError, ValueError) as e:
            logger.warning(f"Portal question email failed: {e}")
    return q_out(q)


# ---------------- Team leads manage their own company's teammates ----------------
async def _lead(email: str, pid: str) -> dict:
    m = await _membership(email, pid)
    if not (m.get("is_lead") and m.get("company")):
        raise HTTPException(403, "Only your team lead can manage teammates")
    return m


def _team_q(lead: dict) -> dict:
    return {"owner_id": lead["owner_id"], "project_id": lead["project_id"], "company": lead["company"]}


@router.get("/portal/projects/{pid}/team")
async def team_list(pid: str, email: str = Depends(portal_email)):
    lead = await _lead(email, pid)
    out = []
    for m in await db.portal_members.find(_team_q(lead)).sort("created_at", 1).to_list(100):
        o = await member_out(m)
        out.append({k: o[k] for k in ("id", "name", "email", "role", "is_lead", "password_set", "last_login", "invited_by", "expires_on", "expired")} | {"is_you": m["email"] == email})
    return out


@router.post("/portal/projects/{pid}/team")
async def team_invite(pid: str, body: TeammateIn, email: str = Depends(portal_email)):
    lead = await _lead(email, pid)
    new = body.email.lower()
    if await db.portal_members.find_one({"project_id": pid, "email": new}):
        raise HTTPException(400, "This person already has access to this project")
    if await db.portal_members.count_documents({"owner_id": lead["owner_id"], "project_id": pid}) >= 25:
        raise HTTPException(400, "This project has reached its stakeholder limit. Ask the owner")
    await ensure_handle(new, body.name)
    code = await issue_access_code(new)
    m = {"owner_id": lead["owner_id"], "project_id": pid, "name": body.name.strip(), "email": new, "role": lead["role"], "company": lead["company"],
         "doc_ids": list(lead["doc_ids"]), "digest": lead["digest"], "origin": lead["origin"], "invited_by": email, "expires_on": lead.get("expires_on"), "created_at": now_iso(), "invited_at": now_iso()}
    m["_id"] = (await db.portal_members.insert_one(m)).inserted_id
    owner = User.from_mongo(await db.users.find_one({"_id": ObjectId(lead["owner_id"])}))
    p = await db.projects.find_one({"_id": ObjectId(pid)}, {"name": 1}) or {}
    await log_activity(lead, "team_invite", detail=f"{m['name']} ({new})")
    await log_message(owner.id, pid, name=m["name"], email=new, channel="email", kind="portal_invite", summary=f"{lead['name']} ({lead['company']}) added them to the stakeholder portal for {p.get('name', '')}")
    try:
        await _invite_email(m, owner, p.get("name", "the project"), code)
        sent = True
    except (EmailError, ValueError) as e:
        logger.warning(f"Team invite email failed: {e}")
        sent = False
    return {"id": str(m["_id"]), "name": m["name"], "email": new, "email_sent": sent}


@router.delete("/portal/projects/{pid}/team/{mid}")
async def team_remove(pid: str, mid: str, email: str = Depends(portal_email)):
    lead = await _lead(email, pid)
    t = await db.portal_members.find_one({"_id": oid(mid), **_team_q(lead)})
    if not t:
        raise HTTPException(404, "Teammate not found")
    if t["email"] == email or t.get("is_lead"):
        raise HTTPException(400, "Team leads can only be removed by the project owner")
    await db.portal_members.delete_one({"_id": t["_id"]})
    await log_activity(lead, "team_remove", detail=f"{t['name']} ({t['email']})")
    return {"ok": True}


# ---------------- Team leads request extra documents from the owner ----------------
class DocRequestIn(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    note: str = Field("", max_length=1000)


class DocRequestAnswer(BaseModel):
    status: str = Field(pattern="^(fulfilled|declined)$")
    reply: str = Field("", max_length=1000)
    doc_ids: List[str] = Field(default_factory=list, max_length=50)


NUDGE_DAYS = 3


def _req_out(r: dict) -> dict:
    days = (datetime.now(timezone.utc) - datetime.fromisoformat(r["created_at"])).days
    last = r.get("reminded_at")
    can = r["status"] == "open" and days >= NUDGE_DAYS and (not last or datetime.fromisoformat(last) < datetime.now(timezone.utc) - timedelta(hours=24))
    return {k: r.get(k) for k in ("title", "note", "status", "reply", "name", "email", "company", "created_at", "answered_at", "doc_titles", "reminded_at")} | {
        "id": str(r["_id"]), "days_waiting": days, "overdue": r["status"] == "open" and days >= NUDGE_DAYS, "can_remind": can, "reminders": r.get("reminders", 0)}


@router.get("/portal/projects/{pid}/doc-requests")
async def lead_doc_requests(pid: str, email: str = Depends(portal_email)):
    lead = await _lead(email, pid)
    return [_req_out(r) for r in await db.portal_doc_requests.find(_team_q(lead)).sort("created_at", -1).to_list(50)]


@router.post("/portal/projects/{pid}/doc-requests")
async def create_doc_request(pid: str, body: DocRequestIn, email: str = Depends(portal_email)):
    lead = await _lead(email, pid)
    if await db.portal_doc_requests.count_documents({**_team_q(lead), "status": "open"}) >= 20:
        raise HTTPException(400, "You have 20 open requests. Wait for the owner to answer some first")
    r = {**_team_q(lead), "member_id": str(lead["_id"]), "email": email, "name": lead["name"], "title": body.title.strip(), "note": body.note.strip(),
         "status": "open", "reply": "", "created_at": now_iso()}
    r["_id"] = (await db.portal_doc_requests.insert_one(r)).inserted_id
    await log_activity(lead, "doc_request", detail=r["title"])
    owner = await db.users.find_one({"_id": ObjectId(lead["owner_id"])}, {"email": 1, "name": 1})
    p = await db.projects.find_one({"_id": ObjectId(pid)}, {"name": 1}) or {}
    if owner:
        note_html = f"<p>{E(r['note'])}</p>" if r["note"] else ""
        html = (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
                f'<p>{E(lead["name"])} ({E(lead["company"])}) has asked for a document on <b>{E(p.get("name", "your project"))}</b>:</p>'
                f'<p style="font-size:17px;font-weight:bold">{E(r["title"])}</p>{note_html}'
                f'<p>Open PropertyPlug → Documents → Stakeholder portal to share it or reply.</p></td></tr></table>')
        try:
            await send_email(to=owner["email"], subject=f"Document request from {lead['name']}: {r['title']}", html=html, reply_to=email)
        except EmailError as e:
            logger.warning(f"Doc request email failed: {e}")
    return _req_out(r)


@router.post("/portal/projects/{pid}/doc-requests/{rid}/remind")
async def remind_doc_request(pid: str, rid: str, email: str = Depends(portal_email)):
    """Lead nudges the owner about a request that has waited 3+ days (at most once a day)."""
    lead = await _lead(email, pid)
    r = await db.portal_doc_requests.find_one({"_id": oid(rid), **_team_q(lead)})
    if not r:
        raise HTTPException(404, "Request not found")
    if not _req_out(r)["can_remind"]:
        raise HTTPException(400, f"You can send a reminder once a request has waited {NUDGE_DAYS} days, and once a day after that")
    owner = await db.users.find_one({"_id": ObjectId(lead["owner_id"])}, {"email": 1})
    p = await db.projects.find_one({"_id": ObjectId(pid)}, {"name": 1}) or {}
    days = _req_out(r)["days_waiting"]
    html = (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
            f'<p>Reminder: {E(lead["name"])} ({E(lead["company"])}) is still waiting for <b>{E(r["title"])}</b> on {E(p.get("name", "your project"))}.</p>'
            f'<p>They asked {days} days ago. Open PropertyPlug → Documents → Stakeholder portal to share it or reply.</p></td></tr></table>')
    try:
        await send_email(to=owner["email"], subject=f"Reminder: {lead['name']} is waiting for {r['title']}", html=html, reply_to=email)
    except EmailError as e:
        raise HTTPException(503, f"Couldn't send the reminder right now: {e}")
    await db.portal_doc_requests.update_one({"_id": r["_id"]}, {"$set": {"reminded_at": now_iso()}, "$inc": {"reminders": 1}})
    await log_activity(lead, "doc_reminder", detail=r["title"])
    return _req_out(await db.portal_doc_requests.find_one({"_id": r["_id"]}))


@router.get("/portal-doc-requests/overdue")
async def overdue_doc_requests(user: User = Depends(current_user)):
    """Dashboard nudge: open requests waiting 3+ days on the active project."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=NUDGE_DAYS)).isoformat()
    docs = await db.portal_doc_requests.find({"owner_id": user.id, "project_id": await active_pid(user), "status": "open", "created_at": {"$lte": cutoff}}).sort("created_at", 1).to_list(50)
    return [_req_out(r) for r in docs]


@router.get("/portal-doc-requests")
async def owner_doc_requests(user: User = Depends(current_user)):
    docs = await db.portal_doc_requests.find({"owner_id": user.id, "project_id": await active_pid(user)}).sort([("status", -1), ("created_at", -1)]).to_list(100)
    return [_req_out(r) for r in docs]


@router.put("/portal-doc-requests/{rid}")
async def answer_doc_request(rid: str, body: DocRequestAnswer, user: User = Depends(current_user)):
    r = await db.portal_doc_requests.find_one({"_id": oid(rid), "owner_id": user.id})
    if not r:
        raise HTTPException(404, "Request not found")
    titles = []
    if body.status == "fulfilled" and body.doc_ids:
        own = await db.documents.find({"_id": {"$in": [oid(i) for i in body.doc_ids]}, "user_id": user.id, "project_id": r["project_id"]}, {"title": 1}).to_list(50)
        ids, titles = [str(d["_id"]) for d in own], [d["title"] for d in own]
        # Share with the requester's whole team on this project.
        await db.portal_members.update_many({"owner_id": user.id, "project_id": r["project_id"], "company": r["company"]}, {"$addToSet": {"doc_ids": {"$each": ids}}})
    await db.portal_doc_requests.update_one({"_id": r["_id"]}, {"$set": {"status": body.status, "reply": body.reply.strip(), "doc_titles": titles, "answered_at": now_iso()}})
    return _req_out(await db.portal_doc_requests.find_one({"_id": r["_id"]}))


PORTAL_JS = """
const $=s=>document.querySelector(s),api=async(p,o={})=>{const t=sessionStorage.getItem('pt');const r=await fetch('/api'+p,{...o,headers:{'Content-Type':'application/json',...(t?{Authorization:'Bearer '+t}:{})}});if(r.status===401&&t){sessionStorage.removeItem('pt');login();throw new Error('Signed out');}if(!r.ok){let m='Something went wrong';try{m=(await r.json()).detail||m}catch(e){}throw new Error(m)}return r};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let sy='£';const gbp=n=>sy+Math.round(n).toLocaleString('en-GB');let ident='',week=0,cur=null;
function done(r){sessionStorage.setItem('pt',r.token);if(r.access_code){$('#app').innerHTML=`<div class='card' id='new-code'><h2>Password saved</h2><p>Your personal access code is:</p><p style='font-size:20px;font-weight:bold;font-family:monospace;letter-spacing:2px' id='new-code-value'>${esc(r.access_code)}</p><p class='cap'>Write it down. You'll sign in with this code and your password.</p><button id='go'>Continue</button></div>`;$('#go').onclick=()=>home();return}home()}
async function run(btn,fn){$('#err').textContent='';btn.disabled=true;try{await fn()}catch(e){$('#err').textContent=e.message;btn.disabled=false}}
const post=async(p,b)=>(await api(p,{method:'POST',body:JSON.stringify(b)})).json();
function login(){$('#app').innerHTML=`<div class='card' id='pw-login'><h2>Stakeholder sign in</h2><p class='cap'>Use the access code from your invite email and your password.</p>
<label>Access code</label><input id='acode' placeholder='BA-XXXX-XXXX-XXXX-XXXX' autocomplete='username' autocapitalize='characters'/><label>Password</label><input id='pw' type='password' autocomplete='current-password'/>
<button id='pw-signin'>Sign in</button><p id='err' class='over'></p>
<p class='cap'><a href='#' id='to-setup'>First time? Set up password</a> · <a href='#' id='to-forgot'>Forgot password?</a></p>
<p class='cap'><a href='#' id='to-otp'>Sign in with an email code instead</a></p></div>`;
$('#pw-signin').onclick=()=>run($('#pw-signin'),async()=>done(await post('/portal/login-password',{access_code:$('#acode').value.trim(),password:$('#pw').value})));
$('#to-setup').onclick=e=>{e.preventDefault();setup()};$('#to-forgot').onclick=e=>{e.preventDefault();forgot()};$('#to-otp').onclick=e=>{e.preventDefault();otpLogin()}}
function setup(){$('#app').innerHTML=`<div class='card' id='pw-setup'><h2>Set up your password</h2><p class='cap'>Enter the access code from your invite email and choose a password (8+ characters, with a letter and a number).</p>
<label>Access code</label><input id='acode' placeholder='BA-XXXX-XXXX-XXXX-XXXX' autocapitalize='characters'/><label>New password</label><input id='pw' type='password' autocomplete='new-password'/><label>Confirm password</label><input id='pw2' type='password' autocomplete='new-password'/>
<button id='pw-activate'>Save password & sign in</button><p id='err' class='over'></p><a href='#' id='back'>Back to sign in</a></div>`;
$('#back').onclick=e=>{e.preventDefault();login()};
$('#pw-activate').onclick=()=>{if($('#pw').value!==$('#pw2').value){$('#err').textContent='Passwords do not match';return}run($('#pw-activate'),async()=>done(await post('/portal/activate',{access_code:$('#acode').value.trim(),password:$('#pw').value})))}}
function forgot(){$('#app').innerHTML=`<div class='card' id='pw-forgot'><h2>Reset your password</h2><p class='cap'>Enter your access code, email or ID ending @buildassist. We'll email you a 6-digit reset code.</p>
<label>Access code, email or ID</label><input id='rid' autocomplete='username'/><button id='reset-send'>Email me a reset code</button><p id='err' class='over'></p><a href='#' id='back'>Back to sign in</a></div>`;
$('#back').onclick=e=>{e.preventDefault();login()};
$('#reset-send').onclick=()=>{ident=$('#rid').value.trim();if(!ident)return;run($('#reset-send'),async()=>{await post('/portal/password-reset/request',{identifier:ident});resetStep()})}}
function resetStep(){$('#app').innerHTML=`<div class='card' id='pw-reset'><h2>Check your email</h2><p class='cap'>If <b>${esc(ident)}</b> matches a portal account, a 6-digit reset code is on its way.</p>
<label>Reset code</label><input id='rcode' inputmode='numeric' maxlength='6' autocomplete='one-time-code'/><label>New password</label><input id='pw' type='password' autocomplete='new-password'/><label>Confirm password</label><input id='pw2' type='password' autocomplete='new-password'/>
<button id='reset-confirm'>Save new password</button><p id='err' class='over'></p><a href='#' id='back'>Back to sign in</a></div>`;
$('#back').onclick=e=>{e.preventDefault();login()};
$('#reset-confirm').onclick=()=>{if($('#pw').value!==$('#pw2').value){$('#err').textContent='Passwords do not match';return}run($('#reset-confirm'),async()=>done(await post('/portal/password-reset/confirm',{identifier:ident,reset_code:$('#rcode').value.trim(),new_password:$('#pw').value})))}}
function otpLogin(){$('#app').innerHTML=`<div class='card' id='otp-login'><h2>Sign in with an email code</h2><p class='cap'>Use your email or your ID ending @buildassist. We'll email you a one-time code.</p>
<label>Email or ID</label><input id='ident' placeholder='dave@buildassist' autocomplete='username'/><button id='send-code'>Email me a code</button><p id='err' class='over'></p><a href='#' id='back'>Use access code & password</a></div>`;
$('#back').onclick=e=>{e.preventDefault();login()};
$('#send-code').onclick=async()=>{ident=$('#ident').value.trim();if(!ident)return;$('#send-code').disabled=true;try{await api('/portal/request-code',{method:'POST',body:JSON.stringify({identifier:ident})});codeStep()}catch(e){$('#err').textContent=e.message;$('#send-code').disabled=false}}}
function codeStep(){$('#app').innerHTML=`<div class='card'><h2>Check your email</h2><p class='cap'>If <b>${esc(ident)}</b> has portal access, a 6-digit code is on its way.</p>
<label>Code</label><input id='code' inputmode='numeric' maxlength='6' autocomplete='one-time-code'/><button id='verify'>Sign in</button><p id='err' class='over'></p><a href='#' id='back'>Use a different ID</a></div>`;
$('#back').onclick=e=>{e.preventDefault();otpLogin()};$('#verify').onclick=async()=>{try{const r=await(await api('/portal/verify',{method:'POST',body:JSON.stringify({identifier:ident,code:$('#code').value.trim()})})).json();sessionStorage.setItem('pt',r.token);home()}catch(e){$('#err').textContent=e.message}}}
async function home(){const me=await(await api('/portal/me')).json();if(me.projects.length===1)return project(me.projects[0].project_id,me);
$('#app').innerHTML=`<div class='card' id='portal-home'><h2>Your shared projects</h2><p class='cap'>Signed in as ${esc(me.handle||me.email)} · <a href='#' id='logout'>Sign out</a></p>${me.projects.map(p=>`<a class='proj' href='#' data-id='${p.project_id}'><b>${esc(p.name)}</b><div class='cap'>${esc(p.address)} · shared by ${esc(p.owner)} · ${esc(p.role)}</div></a>`).join('')||"<p>No projects shared yet.</p>"}</div>`;
document.querySelectorAll('.proj').forEach(a=>a.onclick=e=>{e.preventDefault();project(a.dataset.id,me)});$('#logout').onclick=logout}
function logout(e){e&&e.preventDefault();sessionStorage.removeItem('pt');login()}
async function dl(pid,d){const r=await api(`/portal/projects/${pid}/documents/${d.id}`);const u=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=u;a.download=d.filename;a.click();URL.revokeObjectURL(u)}
async function project(pid,me){cur=pid;const p=await(await api(`/portal/projects/${pid}?week=${week}`)).json();sy=p.symbol||'£';const g=p.digest;
$('#app').innerHTML=`<div class='hdr' id='portal-project'><div class='brand'><i>Property<b>Plug</b></i> · STAKEHOLDER PORTAL</div><h1>${esc(p.name)}</h1><div>${esc(p.address)}</div><div style='font-size:12px;margin-top:6px'>${esc(me.handle||me.email)} · ${esc(p.role)} · ${p.expires_on?`<span id='access-ends'>access until ${esc(p.expires_on)}</span> · `:''}${me.projects.length>1?"<a href='#' id='all' style='color:#fff'>All projects</a> · ":""}<a href='#' id='logout' style='color:#fff'>Sign out</a></div></div>
<div class='kpis' style='margin-top:14px'><div class='kpi'><span>Stage</span><div>${esc(p.stage||'-')}</div></div><div class='kpi'><span>Milestones</span><div>${p.milestones_done}/${p.milestones_total}</div></div><div class='kpi'><span>Budget</span><div>${gbp(p.total_budget)}</div></div><div class='kpi'><span>Spent</span><div>${gbp(p.total_spent)}</div></div></div>
${g?`<div class='card' id='portal-digest'><h2>Weekly update · ${week===0?'This week':week===1?'Last week':week+' weeks ago'}</h2><div class='kpis'><div class='kpi'><span>Spent</span><div>${gbp(g.spend.total)}</div></div><div class='kpi'><span>Snags fixed</span><div>${g.snags_fixed.length}</div></div><div class='kpi'><span>Stages done</span><div>${g.milestones_done.length}</div></div><div class='kpi'><span>Open snags</span><div>${g.snags_open_now}</div></div></div>
${g.milestones_done.map(m=>`<div class='cap'>✓ ${esc(m.name)}</div>`).join('')}<div style='display:flex;justify-content:space-between;margin-top:10px'><a href='#' id='prev'>← Previous week</a>${week>0?"<a href='#' id='next'>Next week →</a>":"<span></span>"}</div></div>`:''}
<div class='card' id='portal-docs'><h2>Documents (${p.documents.length})</h2>${p.documents.length?`<table>${p.documents.map((d,i)=>`<tr><td><b>${esc(d.title)}</b><div class='cap'>${esc(d.doc_type)} · ${esc(d.ext.toUpperCase())}${d.expires_on?' · expires '+esc(d.expires_on):''}</div></td><td class='n'><a href='#' class='dl' data-i='${i}'>Download</a></td></tr>`).join('')}</table>`:"<p class='cap'>No documents shared yet.</p>"}</div>`;
const qs=await(await api(`/portal/projects/${pid}/questions`)).json();
$('#app').insertAdjacentHTML('beforeend',`<div class='card' id='portal-questions'><h2>Questions & comments</h2><p class='cap'>Ask the project owner anything. You'll get an email when they reply.</p>
<textarea id='q-text' rows='3' maxlength='2000' style='width:100%;padding:12px;border:1px solid #cbd5e1;border-radius:10px;font-size:15px' placeholder='e.g. When is the kitchen being fitted?'></textarea><button id='q-send' style='margin-top:8px'>Send question</button><p id='q-err' class='over'></p>
${qs.map(q=>`<div class='q' style='border-top:1px solid #e2e8f0;padding-top:10px;margin-top:10px'><div><b>You</b> <span class='cap'>${new Date(q.created_at).toLocaleString('en-GB')}</span></div><div>${esc(q.text)}</div>${q.reply?`<div style='margin-top:6px;padding:8px 10px;background:#f0fdfa;border-radius:8px' class='q-reply'><b>Reply</b> <span class='cap'>${new Date(q.replied_at).toLocaleString('en-GB')}</span><div>${esc(q.reply)}</div></div>`:"<div class='cap'>Awaiting reply</div>"}</div>`).join('')}</div>`);
if(p.is_lead){const tm=await(await api(`/portal/projects/${pid}/team`)).json();
$('#app').insertAdjacentHTML('beforeend',`<div class='card' id='portal-team'><h2>My team · ${esc(p.company)}</h2><p class='cap'>You're the team lead. Teammates get their own access code and password, and see the same documents and updates as you.</p>
<table>${tm.map(t=>`<tr><td><b>${esc(t.name)}</b>${t.is_lead?" <span class='cap'>· Lead</span>":''}${t.is_you?" <span class='cap'>(you)</span>":''}<div class='cap'>${esc(t.email)} · ${t.password_set?'password set':'invite sent'}</div></td><td class='n'>${t.is_you||t.is_lead?'':`<a href='#' class='t-rm' data-id='${t.id}' data-n='${esc(t.name)}'>Remove</a>`}</td></tr>`).join('')}</table>
<label>Name</label><input id='t-name' placeholder='e.g. Priya Shah'/><label>Email</label><input id='t-email' type='email' placeholder='priya@company.com'/><button id='t-add'>Invite teammate</button><p id='t-err' class='over'></p></div>`);
$('#t-add').onclick=async()=>{const n=$('#t-name').value.trim(),em=$('#t-email').value.trim();if(!n||!em){$('#t-err').textContent='Enter a name and email';return}$('#t-add').disabled=true;try{const r=await(await api(`/portal/projects/${pid}/team`,{method:'POST',body:JSON.stringify({name:n,email:em})})).json();if(!r.email_sent)alert('Added, but the invite email could not be sent. Ask the owner to resend it.');project(pid,me)}catch(e){$('#t-err').textContent=e.message;$('#t-add').disabled=false}};
const rq=await(await api(`/portal/projects/${pid}/doc-requests`)).json();
$('#app').insertAdjacentHTML('beforeend',`<div class='card' id='portal-doc-requests'><h2>Request a document</h2><p class='cap'>Ask the owner for anything you need, e.g. a building control certificate or an updated valuation.</p>
<table>${rq.map(r=>`<tr><td><b>${esc(r.title)}</b><div class='cap'>${esc(r.name)} · ${esc(r.created_at.slice(0,10))}${r.reply?' · Owner: '+esc(r.reply):''}${r.doc_titles&&r.doc_titles.length?' · Shared: '+r.doc_titles.map(esc).join(', '):''}</div></td><td class='n' data-st='${r.status}'>${r.status==='open'?(r.overdue?`<span class='over'>Waiting ${r.days_waiting} days</span>`:'Waiting'):r.status==='fulfilled'?'Done':'Declined'}${r.can_remind?`<div><a href='#' class='rq-remind' data-id='${r.id}'>Send reminder</a></div>`:r.overdue&&r.reminded_at?`<div class='cap'>Reminded</div>`:''}</td></tr>`).join('')}</table>
<label>Document needed</label><input id='rq-title' placeholder='e.g. Electrical certificate'/><label>Note (optional)</label><textarea id='rq-note' rows='2'></textarea><button id='rq-send'>Send request</button><p id='rq-err' class='over'></p></div>`);
document.querySelectorAll('.rq-remind').forEach(a=>a.onclick=async e=>{e.preventDefault();try{await api(`/portal/projects/${pid}/doc-requests/${a.dataset.id}/remind`,{method:'POST'});alert('Reminder sent to the owner');project(pid,me)}catch(err){alert(err.message)}});
$('#rq-send').onclick=async()=>{const t=$('#rq-title').value.trim();if(t.length<2){$('#rq-err').textContent='Say which document you need';return}$('#rq-send').disabled=true;try{await api(`/portal/projects/${pid}/doc-requests`,{method:'POST',body:JSON.stringify({title:t,note:$('#rq-note').value.trim()})});project(pid,me)}catch(e){$('#rq-err').textContent=e.message;$('#rq-send').disabled=false}};
document.querySelectorAll('.t-rm').forEach(a=>a.onclick=async e=>{e.preventDefault();if(!confirm('Remove '+a.dataset.n+' from this project?'))return;try{await api(`/portal/projects/${pid}/team/${a.dataset.id}`,{method:'DELETE'});project(pid,me)}catch(err){alert(err.message)}})}
$('#q-send').onclick=async()=>{const v=$('#q-text').value.trim();if(v.length<2)return;$('#q-send').disabled=true;try{await api(`/portal/projects/${pid}/questions`,{method:'POST',body:JSON.stringify({text:v})});project(pid,me)}catch(e){$('#q-err').textContent=e.message;$('#q-send').disabled=false}};
document.querySelectorAll('.dl').forEach(a=>a.onclick=e=>{e.preventDefault();dl(pid,p.documents[+a.dataset.i]).catch(err=>alert(err.message))});
$('#logout').onclick=logout;$('#all')&&($('#all').onclick=e=>{e.preventDefault();week=0;home()});$('#prev')&&($('#prev').onclick=e=>{e.preventDefault();week++;project(pid,me)});$('#next')&&($('#next').onclick=e=>{e.preventDefault();week--;project(pid,me)})}
sessionStorage.getItem('pt')?home().catch(()=>login()):login();
"""


@router.get("/portal", response_class=HTMLResponse)
async def portal_page():
    css = PAGE_CSS + "input{width:100%;padding:12px;border:1px solid #cbd5e1;border-radius:10px;font-size:16px;margin:6px 0 10px}button{width:100%;padding:14px;border:0;border-radius:10px;background:#0f766e;color:#fff;font-weight:700;font-size:15px}.proj{display:block;padding:12px;border:1px solid #e2e8f0;border-radius:10px;margin-top:8px;color:#0f172a;text-decoration:none}a{color:#0f766e}"
    return HTMLResponse(f"<!DOCTYPE html><html><head><meta charset='utf-8'/><meta name='viewport' content='width=device-width,initial-scale=1'/><title>{E(EMAIL_FROM_NAME)} · Stakeholder portal</title>"
                        f"<style>{css}</style></head><body><div class='wrap'><div class='hdr'><div class='brand'><i>Property<b>Plug</b></i></div><h1>Stakeholder portal</h1>"
                        f"<div>Project updates & documents shared with you</div></div><div id='app'></div><div class='foot'>Powered by {E(EMAIL_FROM_NAME)}</div></div>"
                        f"<script>{PORTAL_JS}</script></body></html>")
