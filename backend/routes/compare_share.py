"""Shareable before/after transformation links: a public page with a draggable wipe slider, owner branding and trial CTA."""
import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from core import E, db, now_iso, oid
from deps import active_pid, current_user
from html_utils import brand_block, owner_branding, page, serve_logo
from models import User
from storage import get_object

router = APIRouter()


class CompareShareIn(BaseModel):
    before_id: str
    after_id: str
    title: str = Field("", max_length=120)
    origin_url: str


def _url(d: dict) -> str:
    return f"{d['origin'].rstrip('/')}/api/c/{d['token']}"


def _out(d: dict) -> dict:
    return {"id": str(d["_id"]), "token": d["token"], "url": _url(d), "before_id": d["before_id"], "after_id": d["after_id"], "title": d.get("title", ""), "created_at": d["created_at"]}


@router.get("/compare-links")
async def list_links(user: User = Depends(current_user)):
    docs = await db.compare_links.find({"user_id": user.id, "project_id": await active_pid(user)}).sort("created_at", -1).to_list(100)
    return [_out(d) for d in docs]


@router.post("/compare-links")
async def create_link(body: CompareShareIn, user: User = Depends(current_user)):
    pid = await active_pid(user)
    for mid in (body.before_id, body.after_id):
        if not await db.media.find_one({"_id": oid(mid), "project_id": pid}, {"_id": 1}):
            raise HTTPException(404, "Photo not found")
    q = {"user_id": user.id, "project_id": pid, "before_id": body.before_id, "after_id": body.after_id}
    existing = await db.compare_links.find_one(q)
    if existing:
        await db.compare_links.update_one({"_id": existing["_id"]}, {"$set": {"title": body.title.strip(), "origin": body.origin_url}})
        return _out({**existing, "title": body.title.strip(), "origin": body.origin_url})
    doc = {**q, "title": body.title.strip(), "origin": body.origin_url, "token": secrets.token_urlsafe(16), "created_at": now_iso()}
    doc["_id"] = (await db.compare_links.insert_one(doc)).inserted_id
    return _out(doc)


@router.delete("/compare-links/{lid}")
async def revoke_link(lid: str, user: User = Depends(current_user)):
    await db.compare_links.delete_one({"_id": oid(lid), "user_id": user.id})
    return {"ok": True}


SLIDER_CSS = """.ba{position:relative;width:100%;aspect-ratio:4/3;border-radius:16px;overflow:hidden;background:#f1f5f9;touch-action:none;user-select:none;-webkit-user-select:none;cursor:ew-resize}
.ba img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;pointer-events:none}.ba .b{clip-path:inset(0 50% 0 0)}
.ba .ln{position:absolute;top:0;bottom:0;left:50%;width:3px;margin-left:-1.5px;background:#fff}
.ba .h{position:absolute;top:50%;left:50%;width:46px;height:46px;margin:-23px 0 0 -23px;border-radius:23px;background:#fff;box-shadow:0 2px 10px rgba(0,0,0,.3);display:flex;align-items:center;justify-content:center;color:#0f766e;font-weight:800;font-size:18px}
.ba .t{position:absolute;top:10px;font-size:10px;font-weight:700;letter-spacing:.6px;color:#fff;padding:3px 9px;border-radius:99px}
.ba .tb{left:10px;background:#1e293b}.ba .ta{right:10px;background:#10b981}"""

SLIDER_JS = """<script>(function(){var el=document.getElementById('ba');var b=el.querySelector('.b'),l=el.querySelector('.ln'),h=el.querySelector('.h');
function set(x){var r=el.getBoundingClientRect();var p=Math.max(0,Math.min(100,(x-r.left)/r.width*100));b.style.clipPath='inset(0 '+(100-p)+'% 0 0)';l.style.left=p+'%';h.style.left=p+'%';}
var down=false;el.addEventListener('pointerdown',function(e){down=true;el.setPointerCapture(e.pointerId);set(e.clientX);});
el.addEventListener('pointermove',function(e){if(down)set(e.clientX);});el.addEventListener('pointerup',function(){down=false;});el.addEventListener('pointercancel',function(){down=false;});})();</script>"""


@router.get("/c/{token}", response_class=HTMLResponse)
async def public_compare(token: str):
    d = await db.compare_links.find_one({"token": token}) if token else None
    if not d:
        return page("Link expired", "<div class='card'><h2>This before &amp; after link is no longer active</h2><p>Ask the project owner for a new link.</p></div>")
    proj = await db.projects.find_one({"_id": oid(d["project_id"])}, {"name": 1, "address": 1}) or {}
    before = await db.media.find_one({"_id": oid(d["before_id"])}, {"title": 1, "date": 1}) or {}
    after = await db.media.find_one({"_id": oid(d["after_id"])}, {"title": 1, "date": 1}) or {}
    t = E(token)
    body = brand_block(await owner_branding(d["user_id"]), f"/api/c/{t}/logo")
    body += (f"<div class='hdr'><div class='brand'>BUILDER <b>ASSIST</b> · BEFORE &amp; AFTER</div><h1>{E(d.get('title') or proj.get('name', 'Transformation'))}</h1>"
             f"<div>{E(proj.get('address', ''))}</div></div>")
    body += (f"<style>{SLIDER_CSS}</style><div class='card'><div class='ba' id='ba'><img src='/api/c/{t}/photo/after' alt='after'/>"
             f"<img class='b' src='/api/c/{t}/photo/before' alt='before'/><div class='ln'></div><div class='h'>&#8596;</div>"
             f"<span class='t tb'>BEFORE</span><span class='t ta'>AFTER</span></div>"
             f"<div class='cap' style='text-align:center;margin-top:10px'>Drag across the photo to reveal the transformation</div>"
             f"<table style='margin-top:10px'><tr><td><span class='tag'>BEFORE</span> {E(before.get('title', ''))}</td><td class='n cap'>{E(before.get('date', ''))}</td></tr>"
             f"<tr><td><span class='tag'>AFTER</span> {E(after.get('title', ''))}</td><td class='n cap'>{E(after.get('date', ''))}</td></tr></table></div>{SLIDER_JS}")
    return page(f"{proj.get('name', 'Project')} · Before & after", body, ref="compare", by=d["user_id"])


@router.get("/c/{token}/photo/{which}")
async def compare_photo(token: str, which: str):
    d = await db.compare_links.find_one({"token": token}) if token else None
    if not d or which not in ("before", "after"):
        raise HTTPException(404, "Not found")
    m = await db.media.find_one({"_id": oid(d[f"{which}_id"]), "project_id": d["project_id"]})
    if not m:
        raise HTTPException(404, "Not found")
    if m.get("storage_path"):
        data, ctype = await run_in_threadpool(get_object, m["storage_path"])
        return Response(content=data, media_type=ctype, headers={"Cache-Control": "public, max-age=3600"})
    return RedirectResponse(m["url"])


@router.get("/c/{token}/logo")
async def compare_logo(token: str):
    d = await db.compare_links.find_one({"token": token}, {"user_id": 1}) if token else None
    if not d:
        raise HTTPException(404, "Not found")
    return await serve_logo(d["user_id"])
