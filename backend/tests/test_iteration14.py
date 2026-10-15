"""Iteration 14 backend tests — per-project Documents library (upload, list/filter, update, delete, download,
   ZIP, revocable share links, public page/file, inclusion in export, deletion cascade).
"""
import io
import os
import re
import uuid
import zipfile
from typing import Dict, Optional

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


def auth(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def register_test_user(suffix: Optional[str] = None) -> Dict:
    pw = "testpass1234"
    em = f"test_{suffix or uuid.uuid4().hex[:10]}@example.com"
    r = requests.post(f"{API}/auth/register", json={"name": "TEST_ User", "email": em, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    return {"token": data["access_token"], "user": data["user"], "email": em, "password": pw}


def _cleanup_test_user(u):
    try:
        requests.delete(f"{API}/auth/account", headers=auth(u["token"]),
                        json={"password": u["password"]}, timeout=20)
    except Exception:
        pass


def upload_doc(tok: str, filename="TEST_hello.pdf", content=b"%PDF-1.4\n1 0 obj<<>>endobj\n", doc_type="Other",
               title: Optional[str] = None, notes: str = "", content_type="application/pdf"):
    files = {"file": (filename, content, content_type)}
    data = {"doc_type": doc_type, "notes": notes}
    if title is not None:
        data["title"] = title
    return requests.post(f"{API}/documents", headers=auth(tok), files=files, data=data, timeout=30)


# ==================== Types endpoint ====================
class TestDocTypes:
    def test_types_and_extensions(self):
        r = requests.get(f"{API}/documents/types", timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert "Survey" in d["types"] and "Title deeds" in d["types"] and "Other" in d["types"]
        assert len(d["types"]) == 14
        assert "pdf" in d["extensions"] and "xlsx" in d["extensions"] and "csv" in d["extensions"] and "png" in d["extensions"]
        assert d["max_mb"] == 20


# ==================== Upload validation ====================
class TestUploadValidation:
    def test_unsupported_extension_400(self):
        u = register_test_user("doc_ext")
        try:
            r = upload_doc(u["token"], filename="TEST_bad.exe", content=b"MZ junk", content_type="application/octet-stream")
            assert r.status_code == 400, r.text
            assert "unsupported" in r.text.lower() or "pdf" in r.text.lower()
        finally:
            _cleanup_test_user(u)

    def test_invalid_doc_type_400(self):
        u = register_test_user("doc_type")
        try:
            r = upload_doc(u["token"], doc_type="NotAType")
            assert r.status_code == 400, r.text
        finally:
            _cleanup_test_user(u)

    def test_empty_file_400(self):
        u = register_test_user("doc_empty")
        try:
            r = upload_doc(u["token"], content=b"")
            assert r.status_code == 400, r.text
            assert "empty" in r.text.lower()
        finally:
            _cleanup_test_user(u)

    def test_too_large_413(self):
        u = register_test_user("doc_big")
        try:
            # 20MB + 1 byte
            big = b"X" * (20 * 1024 * 1024 + 1)
            r = upload_doc(u["token"], filename="TEST_big.pdf", content=big)
            assert r.status_code == 413, f"{r.status_code} {r.text[:200]}"
        finally:
            _cleanup_test_user(u)


# ==================== CRUD, filter, title default ====================
class TestDocumentCRUD:
    def test_create_default_title_from_filename(self):
        u = register_test_user("doc_crud")
        try:
            tok = u["token"]
            # title omitted -> default = filename without extension
            r = upload_doc(tok, filename="TEST_Survey Report.pdf", doc_type="Survey", title="")
            assert r.status_code == 200, r.text
            d = r.json()
            # response shape
            for k in ("id", "title", "doc_type", "filename", "ext", "size", "content_type", "notes", "created_at", "share_url"):
                assert k in d, f"missing {k}: {d}"
            assert d["title"] == "TEST_Survey Report"
            assert d["filename"] == "TEST_Survey Report.pdf"
            assert d["ext"] == "pdf"
            assert d["doc_type"] == "Survey"
            assert d["share_url"] is None
            assert d["content_type"] == "application/pdf"
            assert d["size"] > 0

            # List
            lst = requests.get(f"{API}/documents", headers=auth(tok), timeout=15)
            assert lst.status_code == 200
            assert any(x["id"] == d["id"] for x in lst.json())

            # Filter by doc_type
            flt = requests.get(f"{API}/documents?doc_type=Survey", headers=auth(tok), timeout=15)
            assert flt.status_code == 200
            assert any(x["id"] == d["id"] for x in flt.json())
            flt2 = requests.get(f"{API}/documents?doc_type=EPC", headers=auth(tok), timeout=15)
            assert flt2.status_code == 200
            assert not any(x["id"] == d["id"] for x in flt2.json())

            # Update
            put_r = requests.put(f"{API}/documents/{d['id']}", headers=auth(tok),
                                 json={"title": "TEST_renamed", "doc_type": "EPC", "notes": "TEST_note"}, timeout=15)
            assert put_r.status_code == 200, put_r.text
            upd = put_r.json()
            assert upd["title"] == "TEST_renamed"
            assert upd["doc_type"] == "EPC"
            assert upd["notes"] == "TEST_note"

            # Update invalid type -> 400
            bad = requests.put(f"{API}/documents/{d['id']}", headers=auth(tok),
                               json={"doc_type": "Nope"}, timeout=15)
            assert bad.status_code == 400

            # Delete
            dr = requests.delete(f"{API}/documents/{d['id']}", headers=auth(tok), timeout=15)
            assert dr.status_code == 200
            # Download after delete -> 404
            miss = requests.get(f"{API}/documents/{d['id']}/download", headers=auth(tok), timeout=15)
            assert miss.status_code == 404
        finally:
            _cleanup_test_user(u)

    def test_other_user_doc_returns_404(self):
        a = register_test_user("doc_u1")
        b = register_test_user("doc_u2")
        try:
            ra = upload_doc(a["token"], filename="TEST_a.pdf", doc_type="Other")
            assert ra.status_code == 200
            did = ra.json()["id"]
            # user b hitting other user's doc id -> 404
            r = requests.get(f"{API}/documents/{did}/download", headers=auth(b["token"]), timeout=15)
            assert r.status_code == 404
            r2 = requests.put(f"{API}/documents/{did}", headers=auth(b["token"]), json={"title": "steal"}, timeout=15)
            assert r2.status_code == 404
            r3 = requests.delete(f"{API}/documents/{did}", headers=auth(b["token"]), timeout=15)
            assert r3.status_code == 404
        finally:
            _cleanup_test_user(a)
            _cleanup_test_user(b)


# ==================== Download: bearer and token= ====================
class TestDownload:
    def test_download_bearer_and_query_token(self):
        u = register_test_user("doc_dl")
        try:
            tok = u["token"]
            payload = b"hello document bytes " + uuid.uuid4().hex.encode()
            r = upload_doc(tok, filename="TEST_bytes.txt", content=payload, content_type="text/plain", doc_type="Other")
            assert r.status_code == 200, r.text
            d = r.json()

            # Bearer
            dl = requests.get(f"{API}/documents/{d['id']}/download", headers=auth(tok), timeout=15)
            assert dl.status_code == 200
            assert dl.content == payload
            cd = dl.headers.get("Content-Disposition", "")
            assert "attachment" in cd and "TEST_bytes.txt" in cd

            # ?token=
            dl2 = requests.get(f"{API}/documents/{d['id']}/download", params={"token": tok}, timeout=15)
            assert dl2.status_code == 200
            assert dl2.content == payload
        finally:
            _cleanup_test_user(u)


# ==================== ZIP ====================
class TestZip:
    def test_zip_folders_per_type_and_duplicate_titles(self):
        u = register_test_user("doc_zip")
        try:
            tok = u["token"]
            # Two docs same type + same title -> expect (2) suffix in zip
            r1 = upload_doc(tok, filename="TEST_a.pdf", title="TEST_Same", doc_type="Survey", content=b"AAA")
            r2 = upload_doc(tok, filename="TEST_b.pdf", title="TEST_Same", doc_type="Survey", content=b"BBB")
            r3 = upload_doc(tok, filename="TEST_c.pdf", title="TEST_Other", doc_type="EPC", content=b"CCC")
            assert r1.status_code == r2.status_code == r3.status_code == 200
            z = requests.get(f"{API}/documents/zip", headers=auth(tok), timeout=30)
            assert z.status_code == 200
            assert z.headers["Content-Type"].startswith("application/zip")
            with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
                names = zf.namelist()
                assert "Survey/TEST_Same.pdf" in names, names
                assert "Survey/TEST_Same (2).pdf" in names, names
                assert "EPC/TEST_Other.pdf" in names, names
                # content preserved
                data_a = zf.read("Survey/TEST_Same.pdf")
                data_b = zf.read("Survey/TEST_Same (2).pdf")
                assert {data_a, data_b} == {b"AAA", b"BBB"}

            # Filter
            z2 = requests.get(f"{API}/documents/zip", params={"doc_type": "EPC"}, headers=auth(tok), timeout=30)
            assert z2.status_code == 200
            with zipfile.ZipFile(io.BytesIO(z2.content)) as zf:
                assert all(n.startswith("EPC/") for n in zf.namelist())
        finally:
            _cleanup_test_user(u)

    def test_zip_404_when_no_documents(self):
        u = register_test_user("doc_zip_empty")
        try:
            z = requests.get(f"{API}/documents/zip", headers=auth(u["token"]), timeout=15)
            assert z.status_code == 404
        finally:
            _cleanup_test_user(u)


# ==================== Share links ====================
class TestShareLinks:
    def test_create_idempotent_public_page_file_and_revoke(self):
        u = register_test_user("doc_share")
        try:
            tok = u["token"]
            payload = b"share me " + uuid.uuid4().hex.encode()
            r = upload_doc(tok, filename="TEST_share.pdf", title="TEST_Shared", doc_type="Invoice", content=payload,
                           notes="TEST_notes_visible")
            assert r.status_code == 200, r.text
            d = r.json()

            # Create share
            s1 = requests.post(f"{API}/documents/{d['id']}/share", headers=auth(tok),
                               json={"origin_url": BASE_URL}, timeout=15)
            assert s1.status_code == 200, s1.text
            url1 = s1.json()["share_url"]
            assert url1 and f"{BASE_URL}/api/doc/" in url1
            token = url1.rsplit("/", 1)[-1]
            # Idempotent token
            s2 = requests.post(f"{API}/documents/{d['id']}/share", headers=auth(tok),
                               json={"origin_url": BASE_URL}, timeout=15)
            assert s2.status_code == 200
            assert s2.json()["share_url"] == url1

            # Public page
            page = requests.get(f"{API}/doc/{token}", timeout=15)
            assert page.status_code == 200
            assert "doc-title" in page.text
            assert "doc-type" in page.text
            assert "doc-download" in page.text
            assert "TEST_Shared" in page.text
            assert "Invoice" in page.text

            # Public file bytes
            f_r = requests.get(f"{API}/doc/{token}/file", timeout=15)
            assert f_r.status_code == 200
            assert f_r.content == payload
            cd = f_r.headers.get("Content-Disposition", "")
            assert "TEST_share.pdf" in cd and "attachment" in cd

            # Revoke
            rev = requests.delete(f"{API}/documents/{d['id']}/share", headers=auth(tok), timeout=15)
            assert rev.status_code == 200
            assert rev.json()["share_url"] is None
            # file now 404
            after = requests.get(f"{API}/doc/{token}/file", timeout=15)
            assert after.status_code == 404
            # page now shows 'no longer active'
            page2 = requests.get(f"{API}/doc/{token}", timeout=15)
            assert page2.status_code == 200
            assert "no longer active" in page2.text.lower()
        finally:
            _cleanup_test_user(u)


# ==================== Export + cascading deletes ====================
class TestExportAndCascade:
    def test_documents_included_in_export(self):
        u = register_test_user("doc_export")
        try:
            tok = u["token"]
            r = upload_doc(tok, filename="TEST_exp.pdf", title="TEST_ExportMe", doc_type="Planning")
            assert r.status_code == 200
            z = requests.get(f"{API}/export", headers=auth(tok), timeout=30)
            assert z.status_code == 200
            with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
                assert "documents.csv" in zf.namelist(), zf.namelist()
                content = zf.read("documents.csv").decode("utf-8-sig")
                assert "TEST_ExportMe" in content
                assert "Planning" in content
        finally:
            _cleanup_test_user(u)

    def test_account_delete_removes_documents(self):
        u = register_test_user("doc_delacct")
        tok = u["token"]
        pw = u["password"]
        r = upload_doc(tok, filename="TEST_rm.pdf", title="TEST_RemoveMe", doc_type="Other")
        assert r.status_code == 200
        did = r.json()["id"]
        # Delete account
        d = requests.delete(f"{API}/auth/account", headers=auth(tok), json={"password": pw}, timeout=30)
        assert d.status_code == 200, d.text
        # Document gone
        m = requests.get(f"{API}/documents/{did}/download", headers=auth(tok), timeout=15)
        assert m.status_code in (401, 404)

    def test_project_delete_removes_documents(self):
        u = register_test_user("doc_delproj")
        try:
            tok = u["token"]
            # Need >1 project (seed creates one; create a second & delete it after uploading there)
            pj = requests.post(f"{API}/projects", headers=auth(tok),
                               json={"name": "TEST_tempProj", "address": "TEST_addr"}, timeout=15)
            assert pj.status_code == 200, pj.text
            pid = pj.json()["id"]
            # creating a project auto-activates it
            r = upload_doc(tok, filename="TEST_proj.pdf", title="TEST_InTempProj", doc_type="Other")
            assert r.status_code == 200, r.text
            did = r.json()["id"]
            # Delete the project
            rm = requests.delete(f"{API}/projects/{pid}", headers=auth(tok), timeout=15)
            assert rm.status_code == 200, rm.text
            # The doc should no longer be visible (filtered to active project) nor directly fetchable
            dl = requests.get(f"{API}/documents/{did}/download", headers=auth(tok), timeout=15)
            assert dl.status_code == 404
        finally:
            _cleanup_test_user(u)
