from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import Response, HTMLResponse, RedirectResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from typing import Optional, Literal
from bson import ObjectId
import re, uuid, secrets
from core import db, now_iso, oid, E, APP_NAME
from models import User, Snag
from deps import current_user, active_pid
from storage import put_object, get_object
from html_utils import page, owner_branding, brand_block, serve_logo
from routes.email_settings import notify_owner_signoff
from routes.messages import log_message

router = APIRouter()


class SnagIn(BaseModel):
    room: str
    description: str
    priority: Literal["low", "medium", "high"] = "medium"
    storage_path: Optional[str] = None
    assignee: str = ""


class SnagUpdate(BaseModel):
    room: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[Literal["low", "medium", "high"]] = None
    status: Optional[Literal["open", "fixed"]] = None
    assignee: Optional[str] = None


@router.get("/snags")
async def list_snags(user: User = Depends(current_user)):
    docs = await db.snags.find({"user_id": user.id, "project_id": await active_pid(user)}).sort("created_at", -1).to_list(1000)
    out = [Snag.from_mongo(d).out() for d in docs]
    if user.no_money:
        for o in out:
            o["fix_cost"] = None
    return out


@router.post("/snags")
async def create_snag(body: SnagIn, user: User = Depends(current_user)):
    if not body.room.strip() or not body.description.strip():
        raise HTTPException(400, "Room and description are required")
    s = Snag(user_id=user.id, project_id=await active_pid(user), **{**body.model_dump(), "room": body.room.strip(), "description": body.description.strip()})
    s.id = str((await db.snags.insert_one(s.to_mongo())).inserted_id)
    await clear_signoff(s.project_id, s.assignee)
    return s.out()


async def clear_signoff(pid: str, assignee: str):
    """A sign-off only covers a finished list: new or reopened snags void it."""
    if assignee.strip():
        await db.snag_signoffs.delete_one({"project_id": pid, "assignee_lc": assignee.strip().lower()})


@router.put("/snags/{sid}")
async def update_snag(sid: str, body: SnagUpdate, user: User = Depends(current_user)):
    upd = body.model_dump(exclude_unset=True)
    if "status" in upd:
        upd["fixed_at"] = now_iso() if upd["status"] == "fixed" else None
    if "assignee" in upd:
        prev = await db.snags.find_one({"_id": oid(sid), "user_id": user.id}, {"assigned_to": 1})
        if prev and (prev.get("assigned_to") or {}).get("name", "").lower() != (upd["assignee"] or "").strip().lower():
            upd["assigned_to"] = None  # typed a different name: no longer the emailed team member
    r = await db.snags.update_one({"_id": oid(sid), "user_id": user.id}, {"$set": upd})
    if not r.matched_count:
        raise HTTPException(404, "Snag not found")
    raw = await db.snags.find_one({"_id": oid(sid)})
    s = Snag.from_mongo(raw)
    if s.status == "open":
        await clear_signoff(s.project_id, s.assignee)
    elif upd.get("status") == "fixed":
        from routes.tenant_portal import notify_tenant_repair_fixed
        await notify_tenant_repair_fixed(raw)
    return s.out()


@router.delete("/snags/{sid}")
async def delete_snag(sid: str, user: User = Depends(current_user)):
    await db.snags.delete_one({"_id": oid(sid), "user_id": user.id})
    return {"ok": True}


# ---------------- Snag share links for trades ----------------
class SnagLinkIn(BaseModel):
    assignee: str
    origin_url: str


def snag_link_url(d: dict) -> str:
    return f"{d['origin'].rstrip('/')}/api/s/{d['token']}"


def assignee_query(pid: str, assignee: str) -> dict:
    return {"project_id": pid, "assignee": {"$regex": f"^{re.escape(assignee.strip())}$", "$options": "i"}}


@router.get("/snag-links")
async def list_snag_links(user: User = Depends(current_user)):
    docs = await db.snag_links.find({"user_id": user.id, "project_id": await active_pid(user)}).to_list(100)
    return [{"assignee": d["assignee"], "url": snag_link_url(d)} for d in docs]


@router.post("/snag-links")
async def create_snag_link(body: SnagLinkIn, user: User = Depends(current_user)):
    name = body.assignee.strip()
    if not name:
        raise HTTPException(400, "Choose a trade")
    pid = await active_pid(user)
    if not await db.snags.find_one(assignee_query(pid, name)):
        raise HTTPException(400, f"No snags are assigned to {name}")
    d = await db.snag_links.find_one({"user_id": user.id, "project_id": pid, "assignee_lc": name.lower()})
    if not d:
        d = {"token": secrets.token_urlsafe(14), "user_id": user.id, "project_id": pid, "assignee": name, "assignee_lc": name.lower(),
             "origin": body.origin_url, "created_at": now_iso()}
        await db.snag_links.insert_one(d)
    else:
        await db.snag_links.update_one({"_id": d["_id"]}, {"$set": {"origin": body.origin_url}})
        d["origin"] = body.origin_url
    return {"assignee": d["assignee"], "url": snag_link_url(d)}


# ---------------- Sign-off (owner in app + trade on their link page) ----------------
SIG_PATH = re.compile(r"^[MLml0-9 .,\-]{4,30000}$")


class SignatureIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    path: str = Field(max_length=30000)
    width: float = Field(gt=0, le=4000)
    height: float = Field(gt=0, le=4000)


class OwnerSignIn(SignatureIn):
    assignee: str = Field(min_length=1, max_length=120)


def _sig(name: str, path: str, w: float, h: float) -> dict:
    if not SIG_PATH.match(path.strip()):
        raise HTTPException(400, "Please draw a signature")
    return {"name": name.strip()[:80], "path": path.strip(), "width": w, "height": h, "signed_at": now_iso()}


async def _signoff_ready(pid: str, assignee: str):
    snags = await db.snags.find(assignee_query(pid, assignee), {"status": 1}).to_list(500)
    if not snags:
        raise HTTPException(400, f"No snags are assigned to {assignee}")
    if any(x["status"] == "open" for x in snags):
        raise HTTPException(400, "All snags must be fixed before signing off")
    return len(snags)


async def _upsert_signoff(uid: str, pid: str, assignee: str, role: str, sig: dict, count: int):
    await db.snag_signoffs.update_one({"project_id": pid, "assignee_lc": assignee.strip().lower()},
                                      {"$set": {role: sig, "snag_count": count, "assignee": assignee.strip()},
                                       "$setOnInsert": {"user_id": uid, "created_at": now_iso()}}, upsert=True)


def signoff_out(d: dict) -> dict:
    return {"assignee": d["assignee"], "snag_count": d.get("snag_count", 0), "owner": d.get("owner"), "trade": d.get("trade"),
            "complete": bool(d.get("owner") and d.get("trade"))}


@router.get("/snag-signoffs")
async def list_signoffs(user: User = Depends(current_user)):
    docs = await db.snag_signoffs.find({"user_id": user.id, "project_id": await active_pid(user)}).to_list(200)
    return [signoff_out(d) for d in docs]


@router.post("/snag-signoffs")
async def owner_sign(body: OwnerSignIn, user: User = Depends(current_user)):
    pid = await active_pid(user)
    count = await _signoff_ready(pid, body.assignee)
    await _upsert_signoff(user.id, pid, body.assignee, "owner", _sig(body.name, body.path, body.width, body.height), count)
    return signoff_out(await db.snag_signoffs.find_one({"project_id": pid, "assignee_lc": body.assignee.strip().lower()}))


@router.delete("/snag-signoffs/{assignee}")
async def reset_signoff(assignee: str, user: User = Depends(current_user)):
    await db.snag_signoffs.delete_one({"user_id": user.id, "project_id": await active_pid(user), "assignee_lc": assignee.strip().lower()})
    return {"ok": True}


SIGN_JS = """<script>(function(){var c=document.getElementById('sig'),x=c.getContext('2d'),d=[],on=false,r=window.devicePixelRatio||1;
function fit(){var w=c.clientWidth;c.width=w*r;c.height=160*r;x.scale(r,r);x.lineWidth=2.2;x.lineCap='round';x.strokeStyle='#0f172a';}fit();
function pt(e){var b=c.getBoundingClientRect(),t=e.touches?e.touches[0]:e;return [Math.round((t.clientX-b.left)*10)/10,Math.round((t.clientY-b.top)*10)/10];}
function down(e){e.preventDefault();on=true;var p=pt(e);d.push('M'+p[0]+' '+p[1]);x.beginPath();x.moveTo(p[0],p[1]);}
function move(e){if(!on)return;e.preventDefault();var p=pt(e);d.push('L'+p[0]+' '+p[1]);x.lineTo(p[0],p[1]);x.stroke();}
function up(){on=false;document.getElementById('sig-path').value=d.join(' ');document.getElementById('sig-w').value=c.clientWidth;}
c.addEventListener('mousedown',down);c.addEventListener('mousemove',move);window.addEventListener('mouseup',up);
c.addEventListener('touchstart',down,{passive:false});c.addEventListener('touchmove',move,{passive:false});c.addEventListener('touchend',up);
document.getElementById('sig-clear').onclick=function(){d=[];x.clearRect(0,0,c.width,c.height);document.getElementById('sig-path').value='';};
document.getElementById('sig-form').onsubmit=function(e){if(d.length<2){e.preventDefault();alert('Please sign in the box first');}};})();</script>"""


def sig_svg(s: dict, h: int = 70) -> str:
    return (f"<svg viewBox='0 0 {s['width']:g} {s['height']:g}' style='height:{h}px;max-width:100%' xmlns='http://www.w3.org/2000/svg'>"
            f"<path d='{E(s['path'])}' fill='none' stroke='#0f172a' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'/></svg>")


def signoff_html(token: str, so: Optional[dict], assignee: str) -> str:
    out = "<div class='card' id='signoff'><h2>Sign-off</h2><p class='cap'>All snags are fixed. Sign below to confirm the work is complete.</p>"
    for role, label in (("trade", assignee), ("owner", "Project owner")):
        s = (so or {}).get(role)
        if s:
            out += f"<div style='margin-top:10px' id='signed-{role}'>{sig_svg(s)}<div class='cap'><b>{E(s['name'])}</b> · {E(label)} · signed {E(s['signed_at'][:10])}</div></div>"
    if not (so or {}).get("trade"):
        out += (f"<form id='sig-form' method='post' action='/api/s/{E(token)}/sign'>"
                f"<label>Your name</label><input name='name' required maxlength='80' value='{E(assignee)}'/>"
                "<label>Signature</label><canvas id='sig' style='width:100%;height:160px;border:1px dashed #94a3b8;border-radius:10px;touch-action:none;background:#fff'></canvas>"
                "<input type='hidden' name='path' id='sig-path'/><input type='hidden' name='width' id='sig-w' value='300'/><input type='hidden' name='height' value='160'/>"
                "<div style='display:flex;gap:8px;margin-top:8px'><button type='button' id='sig-clear' style='background:#e2e8f0;color:#0f172a'>Clear</button>"
                "<button type='submit' id='sig-submit'>Sign off work</button></div></form>" + SIGN_JS)
    return out + "</div>"


async def load_snag_link(token: str):
    return await db.snag_links.find_one({"token": token}) if token else None


@router.get("/s/{token}", response_class=HTMLResponse)
async def public_snags(token: str, done: Optional[str] = None, signed: Optional[str] = None):
    link = await load_snag_link(token)
    if not link:
        return page("Not found", "<div class='card'><h2>This snag link is no longer active</h2></div>")
    p = await db.projects.find_one({"_id": ObjectId(link["project_id"])}) or {}
    snags = await db.snags.find(assignee_query(link["project_id"], link["assignee"])).sort("created_at", 1).to_list(500)
    open_s = [x for x in snags if x["status"] == "open"]
    body = brand_block(await owner_branding(link["user_id"]), f"/api/s/{E(token)}/logo")
    body += (f"<div class='hdr'><div class='brand'><i>Property<b>Plug</b></i> · SNAGGING LIST</div><h1>Snags for {E(link['assignee'])}</h1>"
             f"<div>{E(p.get('name', ''))} · {E(p.get('address', ''))}</div>"
             f"<div style='margin-top:6px;font-size:13px' id='snag-count'>{len(open_s)} open · {len(snags) - len(open_s)} fixed</div></div>")
    if signed:
        body += "<div class='card' id='snag-signed-msg'><b class='under'>Thanks! Your sign-off was sent to the project owner.</b></div>"
    if done:
        body += "<div class='card' id='snag-fixed-msg'><b class='under'>Thanks! Marked as fixed and sent to the project owner.</b></div>"
    for x in sorted(snags, key=lambda s: s["status"] != "open"):
        sid = str(x["_id"])
        img = f"<img src='/api/s/{E(token)}/photo/{sid}' style='width:100%;max-height:220px;object-fit:cover;border-radius:10px;margin-top:8px'/>" if x.get("storage_path") else ""
        prio = {"high": "#ef4444", "medium": "#f97316", "low": "#64748b"}[x.get("priority", "medium")]
        head = (f"<div style='display:flex;justify-content:space-between;gap:8px'><b>{E(x['description'])}</b>"
                f"<span class='tag' style='color:{prio}'>{E(x.get('priority', '').upper())}</span></div><div class='cap'>{E(x['room'])}</div>{img}")
        if x["status"] == "open":
            body += (f"<form class='card' id='snag-{sid}' method='post' action='/api/s/{E(token)}/fix/{sid}' enctype='multipart/form-data'>{head}"
                     f"<label>Photo of the fix (recommended)</label><input type='file' name='photo' accept='image/*' capture='environment'/>"
                     f"<label>Note (optional)</label><input name='note' placeholder='What was done'/>"
                     f"<button type='submit' id='fix-{sid}'>Mark as fixed</button></form>")
        else:
            fix = f"<img src='/api/s/{E(token)}/photo/{sid}?kind=fix' style='width:100%;max-height:220px;object-fit:cover;border-radius:10px;margin-top:8px'/>" if x.get("fix_photo_path") else ""
            body += f"<div class='card' style='opacity:.75'>{head}<p class='under'>✓ Fixed {E((x.get('fixed_at') or '')[:10])}</p>{fix}</div>"
    if not snags:
        body += "<div class='card'><h2>No snags assigned right now</h2></div>"
    elif not open_s:
        so = await db.snag_signoffs.find_one({"project_id": link["project_id"], "assignee_lc": link["assignee"].lower()})
        body += signoff_html(token, so, link["assignee"])
    today = now_iso()[:10]
    if link.get("last_viewed") != today:
        await db.snag_links.update_one({"_id": link["_id"]}, {"$set": {"last_viewed": today}})
        await log_message(link["user_id"], link["project_id"], name=link["assignee"], channel="web", kind="snag_link", direction="in",
                          summary=f"Opened their snag list ({len(open_s)} open)")
    return page(f"Snags for {link['assignee']}", body, ref="snag", by=link["user_id"])


@router.post("/s/{token}/sign")
async def public_sign(token: str, name: str = Form(...), path: str = Form(...), width: float = Form(300), height: float = Form(160)):
    link = await load_snag_link(token)
    if not link:
        raise HTTPException(404, "Link not active")
    count = await _signoff_ready(link["project_id"], link["assignee"])
    await _upsert_signoff(link["user_id"], link["project_id"], link["assignee"], "trade", _sig(name, path, min(max(width, 1), 4000), min(max(height, 1), 4000)), count)
    await log_message(link["user_id"], link["project_id"], name=link["assignee"], channel="web", kind="snag_signoff", direction="in",
                      summary=f"Signed off {count} fixed snag{'s' if count != 1 else ''} as {name.strip()[:80]}")
    so = await db.snag_signoffs.find_one({"project_id": link["project_id"], "assignee_lc": link["assignee"].lower()})
    proj = await db.projects.find_one({"_id": ObjectId(link["project_id"])}, {"name": 1}) or {}
    await notify_owner_signoff(link["user_id"], proj.get("name", "your project"), link["assignee"], name.strip()[:80], count,
                               bool(so and so.get("owner")), snag_link_url(link))
    return RedirectResponse(f"/api/s/{token}?signed=1", status_code=303)


@router.post("/s/{token}/fix/{sid}")
async def public_fix_snag(token: str, sid: str, photo: Optional[UploadFile] = File(None), note: str = Form("")):
    link = await load_snag_link(token)
    if not link:
        raise HTTPException(404, "Link not active")
    q = {**assignee_query(link["project_id"], link["assignee"]), "_id": oid(sid)}
    snag = await db.snags.find_one(q)
    if not snag:
        raise HTTPException(404, "Snag not found")
    upd = {"status": "fixed", "fixed_at": now_iso(), "fixed_by": link["assignee"], "fix_note": note.strip()[:500]}
    if photo is not None and photo.filename:
        data = await photo.read()
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(413, "Photo too large (max 10MB)")
        ext = photo.filename.rsplit(".", 1)[-1].lower() if "." in photo.filename else "jpg"
        ctype = photo.content_type or "image/jpeg"
        res = await run_in_threadpool(put_object, f"{APP_NAME}/uploads/{link['user_id']}/{uuid.uuid4()}.{ext}", data, ctype)
        await db.files.insert_one({"storage_path": res["path"], "owner_id": link["user_id"], "content_type": ctype,
                                   "original_filename": photo.filename, "is_deleted": False, "created_at": now_iso()})
        upd["fix_photo_path"] = res["path"]
    await db.snags.update_one({"_id": snag["_id"]}, {"$set": upd})
    from routes.tenant_portal import notify_tenant_repair_fixed
    await notify_tenant_repair_fixed({**snag, **upd})
    await log_message(link["user_id"], link["project_id"], name=link["assignee"], channel="web", kind="snag_fixed", direction="in",
                      summary=f"Marked fixed: {snag['description'][:120]} ({snag['room']})" + (" · photo added" if upd.get("fix_photo_path") else ""))
    return RedirectResponse(f"/api/s/{token}?done=1", status_code=303)


@router.get("/s/{token}/photo/{sid}")
async def public_snag_photo(token: str, sid: str, kind: str = "defect"):
    link = await load_snag_link(token)
    snag = await db.snags.find_one({**assignee_query(link["project_id"], link["assignee"]), "_id": oid(sid)}) if link else None
    path = (snag or {}).get("fix_photo_path" if kind == "fix" else "storage_path")
    if not path:
        raise HTTPException(404, "Not found")
    data, ctype = await run_in_threadpool(get_object, path)
    return Response(content=data, media_type=ctype, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/s/{token}/logo")
async def snag_logo(token: str):
    link = await load_snag_link(token)
    if not link:
        raise HTTPException(404, "Not found")
    return await serve_logo(link["user_id"])


@router.get("/repairs/history")
async def repair_history(user: User = Depends(current_user)):
    """Every snag/repair on the active property: who reported, who fixed, cost and days to fix, with totals."""
    from datetime import datetime
    docs = await db.snags.find({"user_id": user.id, "project_id": await active_pid(user)}).sort("created_at", -1).to_list(2000)
    now = datetime.now().astimezone()
    items = []
    for d in docs:
        start = datetime.fromisoformat(d["created_at"])
        end = datetime.fromisoformat(d["fixed_at"]) if d.get("status") == "fixed" and d.get("fixed_at") else None
        a = d.get("assigned_to") or {}
        items.append({"id": str(d["_id"]), "room": d["room"], "description": d["description"], "priority": d.get("priority", "medium"), "status": d.get("status", "open"),
                      "source": "tenant" if d.get("tenancy_id") or d.get("source") == "report_link" else "snag", "reported_by": d.get("reported_by") or "",
                      "assignee": a.get("name") or d.get("assignee") or "", "fixed_by": d.get("fixed_by") or "", "created_at": d["created_at"], "fixed_at": end and d["fixed_at"],
                      "days": round(((end or now) - start).total_seconds() / 86400, 1), "fix_cost": None if user.no_money else d.get("fix_cost"), "fix_note": d.get("fix_note", "")})
    fixed = [i for i in items if i["status"] == "fixed"]
    costs = [i["fix_cost"] for i in fixed if i["fix_cost"]]
    return {"items": items, "totals": {"count": len(items), "open": len(items) - len(fixed), "fixed": len(fixed),
                                       "avg_days_to_fix": round(sum(i["days"] for i in fixed) / len(fixed), 1) if fixed else None,
                                       "total_cost": None if user.no_money else round(sum(costs), 2), "tenant_reported": sum(i["source"] == "tenant" for i in items)}}
