"""Stakeholder portal: owners grant investors/lenders/partners read-only access to chosen projects, documents and
weekly updates. Stakeholders sign in with their email or their name@buildassist handle + a one-time email code."""
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import jwt
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field

from core import E, JWT_SECRET, bearer, db, logger, now_iso, oid
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
    handle: Optional[str] = Field(None, max_length=24)
    doc_ids: List[str] = Field(default_factory=list, max_length=200)
    digest: bool = True
    origin_url: str


class MemberUpdate(BaseModel):
    role: Optional[str] = Field(None, max_length=40)
    doc_ids: Optional[List[str]] = Field(None, max_length=200)
    digest: Optional[bool] = None


async def member_out(m: dict) -> dict:
    h = await db.portal_handles.find_one({"email": m["email"]}, {"handle": 1})
    return {"id": str(m["_id"]), "name": m["name"], "email": m["email"], "role": m["role"], "doc_ids": m["doc_ids"], "digest": m["digest"],
            "handle": handle_addr(h["handle"]) if h else None, "last_login": m.get("last_login"), "invited_at": m.get("invited_at"),
            "portal_url": f"{m['origin'].rstrip('/')}/api/portal" if m.get("origin") else None}


async def _invite_email(m: dict, owner: User, project_name: str):
    url = f"{m['origin'].rstrip('/')}/api/portal"
    h = await db.portal_handles.find_one({"email": m["email"]}, {"handle": 1})
    html = (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
            f'<p style="font-size:12px;letter-spacing:1px;color:#0f766e;font-weight:bold;margin:0">{E(EMAIL_FROM_NAME.upper())} · STAKEHOLDER PORTAL</p>'
            f'<h1 style="font-size:20px;margin:8px 0">You have access to {E(project_name)}</h1>'
            f'<p>Hi {E(m["name"])}, {E(owner.name)} has shared project updates and documents with you.</p>'
            f'<p>Your sign-in ID: <b>{E(handle_addr(h["handle"]))}</b> (or use this email address). Each time you sign in we email you a one-time code.</p>'
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
    own = {str(d["_id"]) for d in await db.documents.find({"_id": {"$in": [oid(i) for i in body.doc_ids]}, "user_id": user.id, "project_id": p.id}, {"_id": 1}).to_list(200)}
    await ensure_handle(email, body.name, body.handle)
    m = {"owner_id": user.id, "project_id": p.id, "name": body.name.strip(), "email": email, "role": body.role.strip() or "Investor",
         "doc_ids": [i for i in body.doc_ids if i in own], "digest": body.digest, "origin": body.origin_url, "created_at": now_iso(), "invited_at": now_iso()}
    m["_id"] = (await db.portal_members.insert_one(m)).inserted_id
    try:
        await _invite_email(m, user, p.name)
        await log_message(user.id, p.id, name=m["name"], email=email, channel="email", kind="portal_invite", summary=f"Invited to the stakeholder portal for {p.name}")
        sent = True
    except (EmailError, ValueError) as e:
        logger.warning(f"Portal invite email failed: {e}")
        sent = False
    return {**await member_out(m), "email_sent": sent}


@router.put("/portal-members/{mid}")
async def update_member(mid: str, body: MemberUpdate, user: User = Depends(current_user)):
    m = await db.portal_members.find_one({"_id": oid(mid), "owner_id": user.id})
    if not m:
        raise HTTPException(404, "Not found")
    upd = body.model_dump(exclude_unset=True)
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
    if m.get("invited_at") and (datetime.now(timezone.utc) - datetime.fromisoformat(m["invited_at"])).total_seconds() < 120:
        raise HTTPException(429, "Invite just sent. Try again in a couple of minutes")
    p = await db.projects.find_one({"_id": ObjectId(m["project_id"])}, {"name": 1}) or {}
    try:
        await _invite_email(m, user, p.get("name", "your project"))
    except EmailError as e:
        raise HTTPException(503, str(e))
    await db.portal_members.update_one({"_id": m["_id"]}, {"$set": {"invited_at": now_iso()}})
    return {"ok": True}


@router.delete("/portal-members/{mid}")
async def remove_member(mid: str, user: User = Depends(current_user)):
    await db.portal_members.delete_one({"_id": oid(mid), "owner_id": user.id})
    return {"ok": True}


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
    return ident if ident and await db.portal_members.find_one({"email": ident}, {"_id": 1}) else None


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
    await db.portal_members.update_many({"email": email}, {"$set": {"last_login": now_iso()}})
    n = datetime.now(timezone.utc)
    return {"token": jwt.encode({"sub": email, "typ": "portal", "iat": n, "exp": n + timedelta(days=7)}, PORTAL_SECRET, algorithm="HS256")}


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
    return m


@router.get("/portal/me")
async def portal_me(email: str = Depends(portal_email)):
    h = await db.portal_handles.find_one({"email": email}, {"handle": 1})
    out = []
    async for m in db.portal_members.find({"email": email}):
        p = await db.projects.find_one({"_id": ObjectId(m["project_id"])}, {"name": 1, "address": 1})
        o = await db.users.find_one({"_id": ObjectId(m["owner_id"])}, {"name": 1, "branding": 1})
        if p and o:
            out.append({"project_id": m["project_id"], "name": p["name"], "address": p.get("address", ""), "role": m["role"],
                        "owner": ((o.get("branding") or {}).get("company_name") or o["name"])})
    return {"email": email, "handle": handle_addr(h["handle"]) if h else None, "projects": out}


@router.get("/portal/projects/{pid}")
async def portal_project(pid: str, week: int = Query(0, ge=0, le=52), email: str = Depends(portal_email)):
    m = await _membership(email, pid)
    s = await project_summary(Project.from_mongo(await db.projects.find_one({"_id": ObjectId(pid)})))
    docs = await db.documents.find({"_id": {"$in": [oid(i) for i in m["doc_ids"]]}, "project_id": pid}).sort("doc_type", 1).to_list(200)
    return {"name": s["name"], "address": s["address"], "stage": s["current_stage"], "milestones_done": s["milestones_done"],
            "milestones_total": s["milestones_total"], "total_budget": s["total_budget"], "total_spent": s["total_spent"],
            "purchase_price": s["purchase_price"], "estimated_valuation": s["estimated_valuation"], "role": m["role"],
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
    return _attachment(d, data)


PORTAL_JS = """
const $=s=>document.querySelector(s),api=async(p,o={})=>{const t=sessionStorage.getItem('pt');const r=await fetch('/api'+p,{...o,headers:{'Content-Type':'application/json',...(t?{Authorization:'Bearer '+t}:{})}});if(r.status===401&&t){sessionStorage.removeItem('pt');login();throw new Error('Signed out');}if(!r.ok){let m='Something went wrong';try{m=(await r.json()).detail||m}catch(e){}throw new Error(m)}return r};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const gbp=n=>'£'+Math.round(n).toLocaleString('en-GB');let ident='',week=0,cur=null;
function login(){$('#app').innerHTML=`<div class='card'><h2>Stakeholder sign in</h2><p class='cap'>Use your email or your ID ending @buildassist. We'll email you a one-time code.</p>
<label>Email or ID</label><input id='ident' placeholder='dave@buildassist' autocomplete='username'/><button id='send-code'>Email me a code</button><p id='err' class='over'></p></div>`;
$('#send-code').onclick=async()=>{ident=$('#ident').value.trim();if(!ident)return;$('#send-code').disabled=true;try{await api('/portal/request-code',{method:'POST',body:JSON.stringify({identifier:ident})});codeStep()}catch(e){$('#err').textContent=e.message;$('#send-code').disabled=false}}}
function codeStep(){$('#app').innerHTML=`<div class='card'><h2>Check your email</h2><p class='cap'>If <b>${esc(ident)}</b> has portal access, a 6-digit code is on its way.</p>
<label>Code</label><input id='code' inputmode='numeric' maxlength='6' autocomplete='one-time-code'/><button id='verify'>Sign in</button><p id='err' class='over'></p><a href='#' id='back'>Use a different ID</a></div>`;
$('#back').onclick=e=>{e.preventDefault();login()};$('#verify').onclick=async()=>{try{const r=await(await api('/portal/verify',{method:'POST',body:JSON.stringify({identifier:ident,code:$('#code').value.trim()})})).json();sessionStorage.setItem('pt',r.token);home()}catch(e){$('#err').textContent=e.message}}}
async function home(){const me=await(await api('/portal/me')).json();if(me.projects.length===1)return project(me.projects[0].project_id,me);
$('#app').innerHTML=`<div class='card' id='portal-home'><h2>Your shared projects</h2><p class='cap'>Signed in as ${esc(me.handle||me.email)} · <a href='#' id='logout'>Sign out</a></p>${me.projects.map(p=>`<a class='proj' href='#' data-id='${p.project_id}'><b>${esc(p.name)}</b><div class='cap'>${esc(p.address)} · shared by ${esc(p.owner)} · ${esc(p.role)}</div></a>`).join('')||"<p>No projects shared yet.</p>"}</div>`;
document.querySelectorAll('.proj').forEach(a=>a.onclick=e=>{e.preventDefault();project(a.dataset.id,me)});$('#logout').onclick=logout}
function logout(e){e&&e.preventDefault();sessionStorage.removeItem('pt');login()}
async function dl(pid,d){const r=await api(`/portal/projects/${pid}/documents/${d.id}`);const u=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=u;a.download=d.filename;a.click();URL.revokeObjectURL(u)}
async function project(pid,me){cur=pid;const p=await(await api(`/portal/projects/${pid}?week=${week}`)).json();const g=p.digest;
$('#app').innerHTML=`<div class='hdr' id='portal-project'><div class='brand'>BUILDER <b>ASSIST</b> · STAKEHOLDER PORTAL</div><h1>${esc(p.name)}</h1><div>${esc(p.address)}</div><div style='font-size:12px;margin-top:6px'>${esc(me.handle||me.email)} · ${esc(p.role)} · ${me.projects.length>1?"<a href='#' id='all' style='color:#fff'>All projects</a> · ":""}<a href='#' id='logout' style='color:#fff'>Sign out</a></div></div>
<div class='kpis' style='margin-top:14px'><div class='kpi'><span>Stage</span><div>${esc(p.stage||'-')}</div></div><div class='kpi'><span>Milestones</span><div>${p.milestones_done}/${p.milestones_total}</div></div><div class='kpi'><span>Budget</span><div>${gbp(p.total_budget)}</div></div><div class='kpi'><span>Spent</span><div>${gbp(p.total_spent)}</div></div></div>
${g?`<div class='card' id='portal-digest'><h2>Weekly update · ${week===0?'This week':week===1?'Last week':week+' weeks ago'}</h2><div class='kpis'><div class='kpi'><span>Spent</span><div>${gbp(g.spend.total)}</div></div><div class='kpi'><span>Snags fixed</span><div>${g.snags_fixed.length}</div></div><div class='kpi'><span>Stages done</span><div>${g.milestones_done.length}</div></div><div class='kpi'><span>Open snags</span><div>${g.snags_open_now}</div></div></div>
${g.milestones_done.map(m=>`<div class='cap'>✓ ${esc(m.name)}</div>`).join('')}<div style='display:flex;justify-content:space-between;margin-top:10px'><a href='#' id='prev'>← Previous week</a>${week>0?"<a href='#' id='next'>Next week →</a>":"<span></span>"}</div></div>`:''}
<div class='card' id='portal-docs'><h2>Documents (${p.documents.length})</h2>${p.documents.length?`<table>${p.documents.map((d,i)=>`<tr><td><b>${esc(d.title)}</b><div class='cap'>${esc(d.doc_type)} · ${esc(d.ext.toUpperCase())}${d.expires_on?' · expires '+esc(d.expires_on):''}</div></td><td class='n'><a href='#' class='dl' data-i='${i}'>Download</a></td></tr>`).join('')}</table>`:"<p class='cap'>No documents shared yet.</p>"}</div>`;
document.querySelectorAll('.dl').forEach(a=>a.onclick=e=>{e.preventDefault();dl(pid,p.documents[+a.dataset.i]).catch(err=>alert(err.message))});
$('#logout').onclick=logout;$('#all')&&($('#all').onclick=e=>{e.preventDefault();week=0;home()});$('#prev')&&($('#prev').onclick=e=>{e.preventDefault();week++;project(pid,me)});$('#next')&&($('#next').onclick=e=>{e.preventDefault();week--;project(pid,me)})}
sessionStorage.getItem('pt')?home().catch(()=>login()):login();
"""


@router.get("/portal", response_class=HTMLResponse)
async def portal_page():
    css = PAGE_CSS + "input{width:100%;padding:12px;border:1px solid #cbd5e1;border-radius:10px;font-size:16px;margin:6px 0 10px}button{width:100%;padding:14px;border:0;border-radius:10px;background:#0f766e;color:#fff;font-weight:700;font-size:15px}.proj{display:block;padding:12px;border:1px solid #e2e8f0;border-radius:10px;margin-top:8px;color:#0f172a;text-decoration:none}a{color:#0f766e}"
    return HTMLResponse(f"<!DOCTYPE html><html><head><meta charset='utf-8'/><meta name='viewport' content='width=device-width,initial-scale=1'/><title>{E(EMAIL_FROM_NAME)} · Stakeholder portal</title>"
                        f"<style>{css}</style></head><body><div class='wrap'><div class='hdr'><div class='brand'>BUILDER <b>ASSIST</b></div><h1>Stakeholder portal</h1>"
                        f"<div>Project updates & documents shared with you</div></div><div id='app'></div><div class='foot'>Powered by {E(EMAIL_FROM_NAME)}</div></div>"
                        f"<script>{PORTAL_JS}</script></body></html>")
