"""Per-project document library (deeds, surveys, certificates, invoices…) with typed uploads and shareable links."""
import io
import re
import secrets
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from core import APP_NAME, E, bearer, db, now_iso, oid
from deps import active_pid, current_user, decode_uid
from html_utils import page
from models import User
from storage import get_object, put_object

router = APIRouter()

DOC_TYPES = ("Title deeds", "Survey", "Planning", "Building control", "Gas certificate", "EICR", "EPC", "Insurance",
             "Mortgage & finance", "Tenancy", "Invoice", "Warranty", "Drawings", "Other")
EXT_TYPES = {"pdf": "application/pdf", "doc": "application/msword", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             "xls": "application/vnd.ms-excel", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             "csv": "text/csv", "txt": "text/plain", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "heic": "image/heic", "webp": "image/webp"}
MAX_BYTES = 20 * 1024 * 1024


def _out(d: dict, origin: Optional[str] = None) -> dict:
    return {"id": str(d["_id"]), "title": d["title"], "doc_type": d["doc_type"], "filename": d["filename"], "ext": d["ext"],
            "size": d["size"], "content_type": d["content_type"], "notes": d.get("notes", ""), "created_at": d["created_at"],
            "share_url": f"{d['share_origin'].rstrip('/')}/api/doc/{d['share_token']}" if d.get("share_token") and d.get("share_origin") else None}


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w.\- ]+", "_", name).strip()[:120] or "document"


async def _own(did: str, uid: str) -> dict:
    d = await db.documents.find_one({"_id": oid(did), "user_id": uid})
    if not d:
        raise HTTPException(404, "Document not found")
    return d


def _attachment(d: dict, data: bytes) -> Response:
    return Response(data, media_type=d["content_type"], headers={"Content-Disposition": f'attachment; filename="{_safe_name(d["filename"])}"',
                                                                 "Cache-Control": "private, max-age=3600"})


@router.get("/documents/types")
async def doc_types():
    return {"types": DOC_TYPES, "extensions": sorted(EXT_TYPES), "max_mb": MAX_BYTES // (1024 * 1024)}


@router.post("/documents")
async def upload_document(file: UploadFile = File(...), title: str = Form(""), doc_type: str = Form("Other"), notes: str = Form(""),
                          user: User = Depends(current_user)):
    if doc_type not in DOC_TYPES:
        raise HTTPException(400, "Choose a document type")
    name = file.filename or "document"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in EXT_TYPES:
        raise HTTPException(400, "Unsupported file. Use PDF, Word, Excel, CSV, text or an image")
    data = await file.read()
    if not data:
        raise HTTPException(400, "The file is empty")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File too large (max 20MB)")
    pid = await active_pid(user)
    path = f"{APP_NAME}/documents/{user.id}/{uuid.uuid4()}.{ext}"
    result = await run_in_threadpool(put_object, path, data, EXT_TYPES[ext])
    doc = {"user_id": user.id, "project_id": pid, "title": (title.strip() or name.rsplit(".", 1)[0])[:120], "doc_type": doc_type,
           "filename": name[:200], "ext": ext, "size": len(data), "content_type": EXT_TYPES[ext], "notes": notes.strip()[:1000],
           "storage_path": result["path"], "share_token": None, "created_at": now_iso()}
    doc["_id"] = (await db.documents.insert_one(doc)).inserted_id
    return _out(doc)


@router.get("/documents")
async def list_documents(doc_type: Optional[str] = Query(None), user: User = Depends(current_user)):
    q = {"user_id": user.id, "project_id": await active_pid(user), **({"doc_type": doc_type} if doc_type else {})}
    return [_out(d) for d in await db.documents.find(q).sort("created_at", -1).to_list(1000)]


class DocUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=120)
    doc_type: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=1000)


@router.put("/documents/{did}")
async def update_document(did: str, body: DocUpdate, user: User = Depends(current_user)):
    upd = body.model_dump(exclude_unset=True)
    if "doc_type" in upd and upd["doc_type"] not in DOC_TYPES:
        raise HTTPException(400, "Choose a document type")
    await _own(did, user.id)
    await db.documents.update_one({"_id": oid(did)}, {"$set": upd})
    return _out(await db.documents.find_one({"_id": oid(did)}))


@router.delete("/documents/{did}")
async def delete_document(did: str, user: User = Depends(current_user)):
    await _own(did, user.id)
    await db.documents.delete_one({"_id": oid(did)})
    return {"ok": True}


@router.get("/documents/zip")
async def download_all(doc_type: Optional[str] = Query(None), token: Optional[str] = None, cred: HTTPAuthorizationCredentials = Depends(bearer)):
    raw = cred.credentials if cred else token
    if not raw:
        raise HTTPException(401, "Not authenticated")
    uid = decode_uid(raw)
    u = await db.users.find_one({"_id": ObjectId(uid)}, {"active_project_id": 1}) or {}
    q = {"user_id": uid, "project_id": u.get("active_project_id"), **({"doc_type": doc_type} if doc_type else {})}
    docs = await db.documents.find(q).sort("doc_type", 1).to_list(500)
    if not docs:
        raise HTTPException(404, "No documents to download")
    mem, seen = io.BytesIO(), set()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
        for d in docs:
            data, _ = await run_in_threadpool(get_object, d["storage_path"])
            base = f"{d['doc_type']}/{_safe_name(d['title'])}.{d['ext']}"
            name, i = base, 2
            while name in seen:
                name, i = base.replace(f".{d['ext']}", f" ({i}).{d['ext']}"), i + 1
            seen.add(name)
            z.writestr(name, data)
    return Response(mem.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="documents-{datetime.now(timezone.utc).date().isoformat()}.zip"'})


@router.get("/documents/{did}/download")
async def download_document(did: str, token: Optional[str] = None, cred: HTTPAuthorizationCredentials = Depends(bearer)):
    raw = cred.credentials if cred else token
    if not raw:
        raise HTTPException(401, "Not authenticated")
    d = await _own(did, decode_uid(raw))
    data, _ = await run_in_threadpool(get_object, d["storage_path"])
    return _attachment(d, data)


# ---------- Sharing with stakeholders (revocable public link) ----------
class ShareIn(BaseModel):
    origin_url: str


@router.post("/documents/{did}/share")
async def share_document(did: str, body: ShareIn, user: User = Depends(current_user)):
    d = await _own(did, user.id)
    token = d.get("share_token") or secrets.token_urlsafe(18)
    await db.documents.update_one({"_id": d["_id"]}, {"$set": {"share_token": token, "share_origin": body.origin_url}})
    return _out(await db.documents.find_one({"_id": d["_id"]}))


@router.delete("/documents/{did}/share")
async def unshare_document(did: str, user: User = Depends(current_user)):
    d = await _own(did, user.id)
    await db.documents.update_one({"_id": d["_id"]}, {"$set": {"share_token": None}})
    return _out(await db.documents.find_one({"_id": d["_id"]}))


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB" if n >= 1024 * 1024 else f"{max(1, n // 1024)} KB"


@router.get("/doc/{token}", response_class=HTMLResponse)
async def public_document(token: str):
    d = await db.documents.find_one({"share_token": token}) if token else None
    if not d:
        return page("Link expired", "<div class='card'><h2>This document link is no longer active</h2><p>Ask the sender for a new link.</p></div>")
    p = await db.projects.find_one({"_id": ObjectId(d["project_id"])}, {"name": 1, "address": 1}) or {}
    body = (f"<div class='hdr'><div class='brand'>BUILDER <b>ASSIST</b> · SHARED DOCUMENT</div><h1 id='doc-title'>{E(d['title'])}</h1>"
            f"<div>{E(p.get('name', ''))}{' · ' + E(p.get('address', '')) if p.get('address') else ''}</div></div>"
            f"<div class='card'><div class='kpis'><div class='kpi'><span>Type</span><div id='doc-type'>{E(d['doc_type'])}</div></div>"
            f"<div class='kpi'><span>File</span><div>{E(d['ext'].upper())} · {_mb(d['size'])}</div></div></div>"
            + (f"<p class='cap'>{E(d['notes'])}</p>" if d.get("notes") else "")
            + f"<a id='doc-download' href='/api/doc/{E(token)}/file' style='display:block;text-align:center;background:#0f766e;color:#fff;padding:14px;border-radius:10px;font-weight:700;text-decoration:none;margin-top:12px'>Download {E(d['filename'])}</a></div>")
    return page(d["title"], body, ref="doc", by=d["user_id"])


@router.get("/doc/{token}/file")
async def public_document_file(token: str):
    d = await db.documents.find_one({"share_token": token}) if token else None
    if not d:
        raise HTTPException(404, "Link not active")
    data, _ = await run_in_threadpool(get_object, d["storage_path"])
    return _attachment(d, data)
