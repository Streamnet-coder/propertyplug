"""Iteration 15 backend tests — Document expiry, folder links, stakeholder portal (owner API + passwordless auth)."""
import io
import os
import time
import uuid
import zipfile
from datetime import date, timedelta
from typing import Dict, Optional

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

# Load backend .env so MONGO_URL/DB_NAME are available without needing shell exports
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


def _db():
    mongo_url = os.environ["MONGO_URL"].strip().strip('"').strip("'")
    db_name = os.environ["DB_NAME"].strip().strip('"').strip("'")
    cli = MongoClient(mongo_url)
    return cli, cli[db_name]


def auth(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def register_test_user(suffix: Optional[str] = None) -> Dict:
    pw = "testpass1234"
    em = f"test_{suffix or uuid.uuid4().hex[:10]}@example.com"
    r = requests.post(f"{API}/auth/register", json={"name": "TEST_ User", "email": em, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    return {"token": data["access_token"], "user": data["user"], "email": em, "password": pw}


def _cleanup(u):
    try:
        requests.delete(f"{API}/auth/account", headers=auth(u["token"]),
                        json={"password": u["password"]}, timeout=20)
    except Exception:
        pass


def upload(tok, filename="TEST_x.pdf", content=b"%PDF-1.4 x", doc_type="Other", title="TEST_doc",
           expires_on: str = "", notes=""):
    files = {"file": (filename, content, "application/pdf")}
    data = {"doc_type": doc_type, "title": title, "notes": notes, "expires_on": expires_on}
    return requests.post(f"{API}/documents", headers=auth(tok), files=files, data=data, timeout=30)


# ==================== Expiry ====================
class TestExpiry:
    def test_valid_date_statuses_and_update_clear(self):
        u = register_test_user("exp")
        try:
            tok = u["token"]
            today = date.today()
            exp_past = (today - timedelta(days=5)).isoformat()
            exp_soon = (today + timedelta(days=10)).isoformat()
            exp_far = (today + timedelta(days=60)).isoformat()

            r1 = upload(tok, filename="TEST_gas.pdf", doc_type="Gas certificate", title="TEST_gas", expires_on=exp_past)
            r2 = upload(tok, filename="TEST_eicr.pdf", doc_type="EICR", title="TEST_eicr", expires_on=exp_soon)
            r3 = upload(tok, filename="TEST_ins.pdf", doc_type="Insurance", title="TEST_ins", expires_on=exp_far)
            assert r1.status_code == r2.status_code == r3.status_code == 200
            d1, d2, d3 = r1.json(), r2.json(), r3.json()
            assert d1["expires_on"] == exp_past and d1["expiry_status"] == "expired" and d1["days_left"] < 0
            assert d2["expires_on"] == exp_soon and d2["expiry_status"] == "soon" and 0 <= d2["days_left"] <= 30
            assert d3["expires_on"] == exp_far and d3["expiry_status"] == "ok" and d3["days_left"] > 30

            # Invalid date -> 400
            bad = upload(tok, filename="TEST_bad.pdf", title="TEST_bad", expires_on="31/03/2027")
            assert bad.status_code == 400
            assert "yyyy-mm-dd" in bad.text.lower() or "format" in bad.text.lower()

            # PUT clear
            cl = requests.put(f"{API}/documents/{d3['id']}", headers=auth(tok), json={"expires_on": ""}, timeout=15)
            assert cl.status_code == 200
            assert cl.json()["expires_on"] is None and cl.json()["expiry_status"] is None

            # PUT set
            s = requests.put(f"{API}/documents/{d3['id']}", headers=auth(tok), json={"expires_on": exp_soon}, timeout=15)
            assert s.status_code == 200
            assert s.json()["expires_on"] == exp_soon and s.json()["expiry_status"] == "soon"

            # PUT invalid date -> 400
            bad2 = requests.put(f"{API}/documents/{d3['id']}", headers=auth(tok), json={"expires_on": "nope"}, timeout=15)
            assert bad2.status_code == 400

            # GET /documents/expiring: only expired+soon, sorted soonest first
            exp_list = requests.get(f"{API}/documents/expiring", headers=auth(tok), timeout=15)
            assert exp_list.status_code == 200
            ids = [d["id"] for d in exp_list.json()]
            # d3 now soon, d2 soon, d1 expired. Sorted by expires_on ascending => d1 (past), d2 (10d), d3 (10d).
            assert d1["id"] in ids and d2["id"] in ids and d3["id"] in ids
            # First must be the expired one
            assert ids[0] == d1["id"]
            # No 'ok' docs
            for d in exp_list.json():
                assert d["expiry_status"] in ("expired", "soon")
        finally:
            _cleanup(u)


# ==================== Folders ====================
class TestFolders:
    def test_folder_crud_filters_foreign_and_public(self):
        a = register_test_user("fa")
        b = register_test_user("fb")
        try:
            ta = a["token"]
            tb = b["token"]
            r1 = upload(ta, filename="TEST_f1.pdf", title="TEST_F1", doc_type="Survey", content=b"AAA")
            r2 = upload(ta, filename="TEST_f2.pdf", title="TEST_F2", doc_type="EPC", content=b"BBB")
            # Foreign doc from user b
            rF = upload(tb, filename="TEST_other.pdf", title="TEST_foreign", content=b"ZZZ")
            assert r1.status_code == r2.status_code == rF.status_code == 200
            d1, d2, dF = r1.json()["id"], r2.json()["id"], rF.json()["id"]

            # None valid -> 400 (foreign-only; filter removes all)
            r_bad = requests.post(f"{API}/doc-folders", headers=auth(ta),
                                   json={"title": "TEST_bad", "doc_ids": [dF], "origin_url": BASE_URL}, timeout=15)
            assert r_bad.status_code == 400, r_bad.text

            # Create with valid + foreign (foreign filtered)
            r_ok = requests.post(f"{API}/doc-folders", headers=auth(ta),
                                  json={"title": "TEST_folder", "doc_ids": [d1, d2, dF], "origin_url": BASE_URL}, timeout=15)
            assert r_ok.status_code == 200, r_ok.text
            f = r_ok.json()
            assert f["doc_count"] == 2  # dF filtered
            assert f["url"].startswith(BASE_URL + "/api/f/")
            token = f["url"].rsplit("/", 1)[-1]

            # List includes it
            lst = requests.get(f"{API}/doc-folders", headers=auth(ta), timeout=15).json()
            assert any(x["id"] == f["id"] for x in lst)

            # Public page HTML
            page = requests.get(f"{API}/f/{token}", timeout=15)
            assert page.status_code == 200
            assert "folder-title" in page.text and "folder-count" in page.text
            assert "folder-doc" in page.text and "folder-zip" in page.text
            assert "TEST_folder" in page.text

            # Public ZIP
            z = requests.get(f"{API}/f/{token}/zip", timeout=20)
            assert z.status_code == 200 and z.headers["Content-Type"].startswith("application/zip")
            with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
                assert len(zf.namelist()) == 2

            # Per-doc public: granted doc works, other 404
            ok = requests.get(f"{API}/f/{token}/d/{d1}", timeout=15)
            assert ok.status_code == 200 and ok.content == b"AAA"
            no = requests.get(f"{API}/f/{token}/d/{dF}", timeout=15)
            assert no.status_code == 404

            # Delete -> page says "no longer active"
            dr = requests.delete(f"{API}/doc-folders/{f['id']}", headers=auth(ta), timeout=15)
            assert dr.status_code == 200
            page2 = requests.get(f"{API}/f/{token}", timeout=15)
            assert "no longer active" in page2.text.lower()
            z2 = requests.get(f"{API}/f/{token}/zip", timeout=15)
            assert z2.status_code == 404
        finally:
            _cleanup(a)
            _cleanup(b)


# ==================== Portal members (owner side) ====================
class TestPortalMembersOwner:
    def test_create_update_resend_delete_handle(self):
        u = register_test_user("pm")
        try:
            tok = u["token"]
            r1 = upload(tok, filename="TEST_pm1.pdf", title="TEST_pm1", content=b"P1")
            r2 = upload(tok, filename="TEST_pm2.pdf", title="TEST_pm2", content=b"P2")
            assert r1.status_code == r2.status_code == 200
            d1, d2 = r1.json()["id"], r2.json()["id"]

            # non-https origin -> 400
            bad = requests.post(f"{API}/portal-members", headers=auth(tok),
                                 json={"name": "TEST Dave", "email": "delivered@resend.dev", "role": "Investor",
                                       "doc_ids": [d1], "digest": True, "origin_url": "http://foo.com"}, timeout=20)
            assert bad.status_code == 400

            # Create (foreign/invalid ids filtered)
            body = {"name": "TEST Dave", "email": "delivered@resend.dev", "role": "Investor",
                    "doc_ids": [d1, d2], "digest": True, "origin_url": BASE_URL}
            r = requests.post(f"{API}/portal-members", headers=auth(tok), json=body, timeout=30)
            assert r.status_code == 200, r.text
            m = r.json()
            assert m["handle"].endswith("@buildassist")
            assert set(m["doc_ids"]) == {d1, d2}
            assert m["digest"] is True

            # Duplicate email same project -> 400
            dup = requests.post(f"{API}/portal-members", headers=auth(tok), json=body, timeout=20)
            assert dup.status_code == 400

            # Handle reused for same email on a different project
            pj = requests.post(f"{API}/projects", headers=auth(tok),
                                json={"name": "TEST_proj2", "address": "TEST_addr"}, timeout=15)
            assert pj.status_code == 200
            r2m = requests.post(f"{API}/portal-members", headers=auth(tok),
                                 json={**body, "name": "TEST Dave 2"}, timeout=20)
            assert r2m.status_code == 200
            assert r2m.json()["handle"] == m["handle"]

            # Suffix number if handle taken (another email + same wanted handle)
            wanted_handle = m["handle"].split("@")[0]
            r3m = requests.post(f"{API}/portal-members", headers=auth(tok),
                                 json={"name": "TEST Other", "email": "delivered+two@resend.dev", "role": "Lender",
                                       "handle": wanted_handle, "doc_ids": [], "digest": False, "origin_url": BASE_URL}, timeout=20)
            assert r3m.status_code == 200
            handle2 = r3m.json()["handle"].split("@")[0]
            assert handle2 != wanted_handle and handle2.startswith(wanted_handle)
            # Clean up second project member
            requests.delete(f"{API}/portal-members/{r3m.json()['id']}", headers=auth(tok), timeout=15)
            # delete 2nd project
            requests.delete(f"{API}/projects/{pj.json()['id']}", headers=auth(tok), timeout=15)

            # PUT update: foreign id filtered, digest, role
            other = register_test_user("pm_other")
            try:
                r_oth = upload(other["token"], filename="TEST_oth.pdf", title="TEST_oth")
                foreign_id = r_oth.json()["id"]
                upd = requests.put(f"{API}/portal-members/{m['id']}", headers=auth(tok),
                                    json={"doc_ids": [d1, foreign_id], "digest": False, "role": "Lender"}, timeout=20)
                assert upd.status_code == 200
                assert upd.json()["doc_ids"] == [d1]
                assert upd.json()["digest"] is False
                assert upd.json()["role"] == "Lender"
            finally:
                _cleanup(other)

            # Resend cooldown — just invited; should 429 within 2 min
            rs = requests.post(f"{API}/portal-members/{m['id']}/resend", headers=auth(tok), timeout=20)
            assert rs.status_code == 429, rs.text

            # DELETE
            dl = requests.delete(f"{API}/portal-members/{m['id']}", headers=auth(tok), timeout=15)
            assert dl.status_code == 200
        finally:
            _cleanup(u)


# ==================== Portal auth + data ====================
class TestPortalAuthData:
    def test_request_code_generic_and_verify_and_data(self):
        u = register_test_user("portal_auth")
        try:
            tok = u["token"]
            # Upload 2 docs
            d1 = upload(tok, filename="TEST_pa1.pdf", title="TEST_PA1", content=b"X1").json()["id"]
            d2 = upload(tok, filename="TEST_pa2.pdf", title="TEST_PA2", content=b"X2").json()["id"]
            pid = u["user"]["active_project_id"] if "active_project_id" in u["user"] else None
            # Determine active project id via /api/project
            proj = requests.get(f"{API}/project", headers=auth(tok), timeout=15)
            assert proj.status_code == 200
            pid = proj.json()["id"]

            # Create portal member sharing only d1
            email = f"delivered+{uuid.uuid4().hex[:6]}@resend.dev"
            r = requests.post(f"{API}/portal-members", headers=auth(tok),
                              json={"name": "TEST Stake", "email": email, "role": "Investor",
                                    "doc_ids": [d1], "digest": True, "origin_url": BASE_URL}, timeout=30)
            assert r.status_code == 200, r.text

            # Unknown identifier -> generic ok, no email
            unk = requests.post(f"{API}/portal/request-code",
                                 json={"identifier": f"unknown_{uuid.uuid4().hex[:8]}@example.com"}, timeout=15)
            assert unk.status_code == 200
            assert "ok" in unk.json() and unk.json()["ok"] is True

            # Known identifier -> generic ok
            kn = requests.post(f"{API}/portal/request-code", json={"identifier": email}, timeout=15)
            assert kn.status_code == 200

            # Overwrite db.portal_codes hash to 123456
            from routes.portal import _code_hash
            cli, dbm = _db()
            try:
                dbm.portal_codes.update_one(
                    {"email": email.lower()},
                    {"$set": {"hash": _code_hash(email.lower(), "123456"),
                              "expires": time.time() + 300, "attempts": 0, "sends": [time.time()]}},
                    upsert=True)

                # Wrong code -> 401 and attempts counted
                bad = requests.post(f"{API}/portal/verify",
                                     json={"identifier": email, "code": "000000"}, timeout=15)
                assert bad.status_code == 401
                rec = dbm.portal_codes.find_one({"email": email.lower()})
                assert rec and rec.get("attempts", 0) >= 1

                # Correct code -> {token}
                ok = requests.post(f"{API}/portal/verify",
                                    json={"identifier": email, "code": "123456"}, timeout=15)
                assert ok.status_code == 200, ok.text
                ptok = ok.json()["token"]
                assert isinstance(ptok, str) and len(ptok) > 20
            finally:
                cli.close()

            # Portal token rejected by owner APIs (GET /api/project -> 401)
            x = requests.get(f"{API}/project", headers=auth(ptok), timeout=15)
            assert x.status_code == 401

            # Owner token rejected by /api/portal/me -> 401
            y = requests.get(f"{API}/portal/me", headers=auth(tok), timeout=15)
            assert y.status_code == 401

            # Portal /me lists shared projects
            me = requests.get(f"{API}/portal/me", headers=auth(ptok), timeout=15)
            assert me.status_code == 200
            data = me.json()
            assert data["email"] == email.lower()
            assert data["handle"] and data["handle"].endswith("@buildassist")
            assert any(p["project_id"] == pid for p in data["projects"])

            # GET /portal/projects/{pid}
            pr = requests.get(f"{API}/portal/projects/{pid}?week=0", headers=auth(ptok), timeout=20)
            assert pr.status_code == 200
            pj = pr.json()
            doc_ids_shown = [d["id"] for d in pj["documents"]]
            assert d1 in doc_ids_shown
            assert d2 not in doc_ids_shown  # not shared
            assert pj["digest"] is not None  # digest=True

            # Granted doc -> 200
            okd = requests.get(f"{API}/portal/projects/{pid}/documents/{d1}", headers=auth(ptok), timeout=15)
            assert okd.status_code == 200 and okd.content == b"X1"
            # Non-granted doc -> 404
            nod = requests.get(f"{API}/portal/projects/{pid}/documents/{d2}", headers=auth(ptok), timeout=15)
            assert nod.status_code == 404

            # Non-member project (random id) -> 404
            fake_pid = "6500000000000000000000aa"
            nmp = requests.get(f"{API}/portal/projects/{fake_pid}", headers=auth(ptok), timeout=15)
            assert nmp.status_code == 404

            # digest=false → digest null
            # Flip digest off via owner
            member = requests.get(f"{API}/portal-members", headers=auth(tok), timeout=15).json()
            mid = [m for m in member if m["email"] == email.lower()][0]["id"]
            requests.put(f"{API}/portal-members/{mid}", headers=auth(tok), json={"digest": False}, timeout=15)
            pr2 = requests.get(f"{API}/portal/projects/{pid}?week=0", headers=auth(ptok), timeout=20)
            assert pr2.json()["digest"] is None
        finally:
            _cleanup(u)


# ==================== Portal web page ====================
class TestPortalPage:
    def test_portal_page_loaded(self):
        r = requests.get(f"{API}/portal", timeout=15)
        assert r.status_code == 200
        for marker in ("ident", "send-code", "code", "verify", "portal-project", "portal-digest", "portal-docs"):
            assert marker in r.text, f"missing {marker}"


# ==================== Cascade deletes ====================
class TestCascade:
    def test_account_delete_removes_members_and_folders(self):
        u = register_test_user("casc_acct")
        tok = u["token"]
        pw = u["password"]
        d1 = upload(tok, filename="TEST_c1.pdf", title="TEST_C1").json()["id"]
        # Folder
        f = requests.post(f"{API}/doc-folders", headers=auth(tok),
                          json={"title": "TEST_cf", "doc_ids": [d1], "origin_url": BASE_URL}, timeout=15).json()
        # Portal member
        pm = requests.post(f"{API}/portal-members", headers=auth(tok),
                            json={"name": "TEST Dave Casc", "email": f"delivered+casc{uuid.uuid4().hex[:5]}@resend.dev",
                                  "role": "Investor", "doc_ids": [d1], "digest": True, "origin_url": BASE_URL}, timeout=20).json()

        # Delete account
        dl = requests.delete(f"{API}/auth/account", headers=auth(tok), json={"password": pw}, timeout=30)
        assert dl.status_code == 200

        # Folder public page -> no longer active
        token = f["url"].rsplit("/", 1)[-1]
        pg = requests.get(f"{API}/f/{token}", timeout=15)
        assert "no longer active" in pg.text.lower()

        # Verify in DB
        cli, dbm = _db()
        try:
            assert dbm.portal_members.find_one({"_id": __import__("bson").ObjectId(pm["id"])}) is None
            assert dbm.doc_folders.find_one({"_id": __import__("bson").ObjectId(f["id"])}) is None
        finally:
            cli.close()

    def test_project_delete_removes_members_folders_documents(self):
        u = register_test_user("casc_proj")
        try:
            tok = u["token"]
            # Create new project (auto-active)
            pj = requests.post(f"{API}/projects", headers=auth(tok),
                                json={"name": "TEST_pdel", "address": "TEST_addr"}, timeout=15)
            assert pj.status_code == 200
            pid = pj.json()["id"]
            d1 = upload(tok, filename="TEST_pd.pdf", title="TEST_PD").json()["id"]
            f = requests.post(f"{API}/doc-folders", headers=auth(tok),
                              json={"title": "TEST_pfold", "doc_ids": [d1], "origin_url": BASE_URL}, timeout=15).json()
            pm = requests.post(f"{API}/portal-members", headers=auth(tok),
                                json={"name": "TEST PD", "email": f"delivered+pd{uuid.uuid4().hex[:5]}@resend.dev",
                                      "role": "Investor", "doc_ids": [d1], "digest": True, "origin_url": BASE_URL}, timeout=20).json()

            # Delete project
            rm = requests.delete(f"{API}/projects/{pid}", headers=auth(tok), timeout=15)
            assert rm.status_code == 200

            cli, dbm = _db()
            try:
                import bson
                assert dbm.documents.find_one({"_id": bson.ObjectId(d1)}) is None
                assert dbm.doc_folders.find_one({"_id": bson.ObjectId(f["id"])}) is None
                assert dbm.portal_members.find_one({"_id": bson.ObjectId(pm["id"])}) is None
            finally:
                cli.close()
        finally:
            _cleanup(u)
