from fastapi import FastAPI, APIRouter, HTTPException, Depends, UploadFile, File, Request, Query
from fastapi.responses import Response, HTMLResponse
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr, BeforeValidator, ConfigDict
from typing import Annotated, Optional, List, Literal
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from pathlib import Path
import os, json, re, uuid, logging, math, time, secrets, html
from fastapi import Form
from fastapi.responses import RedirectResponse
import bcrypt, jwt, requests

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone  # noqa: E402
from emergentintegrations.payments.stripe.checkout import StripeCheckout, CheckoutSessionRequest  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

client = AsyncIOMotorClient(os.environ['MONGO_URL'])
db = client[os.environ['DB_NAME']]

JWT_SECRET = os.environ['JWT_SECRET']
EMERGENT_KEY = os.environ['EMERGENT_LLM_KEY']
STRIPE_API_KEY = os.environ['STRIPE_API_KEY']
PRO_PRICE_GBP = 19.0
APP_NAME = "my-builder-app"

app = FastAPI()
api = APIRouter(prefix="/api")
bearer = HTTPBearer(auto_error=False)


# ---------------- Mongo models ----------------
PyObjectId = Annotated[str, BeforeValidator(lambda v: str(v) if isinstance(v, ObjectId) else v)]


class BaseDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: Optional[PyObjectId] = Field(default=None, alias="_id")

    @classmethod
    def from_mongo(cls, doc):
        return cls.model_validate(doc) if doc else None

    def to_mongo(self):
        d = self.model_dump(by_alias=True, exclude={"id"})
        if self.id:
            d["_id"] = ObjectId(self.id)
        return d

    def out(self):
        return self.model_dump(exclude={"user_id", "password_hash"})


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class Branding(BaseModel):
    company_name: str = ""
    contact_name: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    tagline: str = ""
    logo_path: Optional[str] = None


class User(BaseDocument):
    name: str
    email: str
    password_hash: str
    plan: Literal["basic", "pro"] = "basic"
    paid_pro: bool = False
    trial_ends: str
    active_project_id: Optional[str] = None
    branding: Branding = Branding()
    signup_source: Optional[str] = None
    referred_by: Optional[str] = None
    referral_count: int = 0
    created_at: str = Field(default_factory=now_iso)


class Budget(BaseModel):
    hard: float = 0
    soft: float = 0
    contingency: float = 0


class Comparable(BaseModel):
    address: str
    beds: int
    price: float
    distance: str
    date: str


class Project(BaseDocument):
    user_id: str
    name: str
    address: str
    target_type: str = "BRRR Refurbishment"
    finish_type: str = "Medium Finish"
    purchase_price: float = 0
    estimated_valuation: float = 0
    monthly_rent: float = 0
    budget: Budget = Budget()
    comparables: List[Comparable] = []
    share_token: Optional[str] = None
    share_origin: Optional[str] = None


class LineItem(BaseDocument):
    user_id: str
    project_id: Optional[str] = None
    category: Literal["Hard Cost", "Soft Cost", "Contingency"]
    name: str
    budgeted: float = 0
    actual: float = 0
    supplier: str = ""
    status: str = "Planned"
    created_at: str = Field(default_factory=now_iso)


class Contact(BaseDocument):
    user_id: str
    project_id: Optional[str] = None
    kind: Literal["trade", "subcontractor", "stakeholder"]
    name: str
    role: str = ""
    phone: str = ""
    email: str = ""
    status: str = ""
    schedule: str = ""
    cost: str = ""
    created_at: str = Field(default_factory=now_iso)


class Receipt(BaseDocument):
    user_id: str
    project_id: Optional[str] = None
    title: str
    amount: float
    date: str
    category: str = "Hard Cost"
    supplier: str = ""
    storage_path: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)


class Media(BaseDocument):
    user_id: str
    project_id: Optional[str] = None
    milestone_id: Optional[str] = None
    title: str
    phase: Literal["before", "progress", "after"] = "progress"
    url: Optional[str] = None
    storage_path: Optional[str] = None
    date: str
    created_at: str = Field(default_factory=now_iso)


# ---------------- Auth ----------------
def make_token(uid: str, minutes: int = 60 * 24 * 7) -> str:
    n = datetime.now(timezone.utc)
    return jwt.encode({"sub": uid, "iat": n, "exp": n + timedelta(minutes=minutes)}, JWT_SECRET, algorithm="HS256")


def decode_uid(token: str) -> str:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")


async def load_user(uid: str) -> User:
    try:
        doc = await db.users.find_one({"_id": ObjectId(uid)})
    except Exception:
        doc = None
    if not doc:
        raise HTTPException(401, "User not found")
    return User.from_mongo(doc)


async def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer)) -> User:
    if not cred:
        raise HTTPException(401, "Not authenticated")
    return await load_user(decode_uid(cred.credentials))


async def pro_user(user: User = Depends(current_user)) -> User:
    if user.plan != "pro":
        raise HTTPException(403, "Pro plan required")
    return user


def user_out(u: User):
    return {"id": u.id, "name": u.name, "email": u.email, "plan": u.plan, "paid_pro": u.paid_pro, "trial_ends": u.trial_ends,
            "active_project_id": u.active_project_id}


class RegisterIn(BaseModel):
    name: str
    email: EmailStr
    password: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str


async def seed_user_data(uid: str):
    p = Project(
        user_id=uid, name="Nottingham Victorian Refurb", address="14 Mapperley Road, Nottingham, NG3 5AP",
        purchase_price=185000, estimated_valuation=265000, monthly_rent=1350,
        budget=Budget(hard=35000, soft=8500, contingency=5000),
        comparables=[
            Comparable(address="12 Mapperley Road", beds=3, price=260000, distance="0.05 miles", date="May 2026"),
            Comparable(address="45 Woodborough Road", beds=3, price=272000, distance="0.12 miles", date="Apr 2026"),
            Comparable(address="8 Sherwood Rise", beds=3, price=258000, distance="0.21 miles", date="Jun 2026"),
        ])
    pid = str((await db.projects.insert_one(p.to_mongo())).inserted_id)
    await db.users.update_one({"_id": ObjectId(uid)}, {"$set": {"active_project_id": pid}})
    items = [
        ("Hard Cost", "Kitchen Units & Worktop", 6500, 6200, "DIY Kitchens", "Purchased"),
        ("Hard Cost", "Bathroom Suite & Tiles", 3200, 3450, "B&Q", "Purchased"),
        ("Hard Cost", "Rewiring & Consumer Unit", 4500, 4500, "Toolstation", "In Progress"),
        ("Soft Cost", "Planning Permission & Building Regs", 1200, 1150, "Nottingham City Council", "Paid"),
        ("Soft Cost", "Architectural Drawings", 1800, 1800, "Local Surveyor", "Paid"),
        ("Contingency", "Damp proofing (unexpected)", 1500, 1200, "Wickes", "Paid"),
    ]
    await db.line_items.insert_many([LineItem(user_id=uid, project_id=pid, category=c, name=n, budgeted=b, actual=a, supplier=s, status=st).to_mongo() for c, n, b, a, s, st in items])
    contacts = [
        Contact(user_id=uid, project_id=pid, kind="trade", name="Dave Miller", role="Master Electrician", phone="+447700900077", email="dave@millerelectrical.co.uk", status="Assigned"),
        Contact(user_id=uid, project_id=pid, kind="trade", name="Sajid Khan", role="Plumber & Heating Engineer", phone="+447700900123", email="sajid@nottsplumbing.co.uk", status="Assigned"),
        Contact(user_id=uid, project_id=pid, kind="trade", name="Apex Builders Ltd", role="General Builders & Bricklayers", phone="+447700900888", email="quotes@apexbuilders.co.uk", status="Invited"),
        Contact(user_id=uid, project_id=pid, kind="subcontractor", name="Dave Miller", role="Electrician", phone="+447700900077", email="dave@miller.co.uk", schedule="First fix complete, second fix starting Monday", status="Today, 10:45 AM"),
        Contact(user_id=uid, project_id=pid, kind="subcontractor", name="Sajid Khan", role="Plumber", phone="+447700900123", email="sajid@plumbing.co.uk", schedule="Boiler installation & bathroom piping", status="Yesterday, 4:15 PM"),
        Contact(user_id=uid, project_id=pid, kind="stakeholder", name="NatWest Buy-to-Let Mortgage", role="Financing", email="mortgages@natwest.co.uk", cost="£1,450 fee"),
        Contact(user_id=uid, project_id=pid, kind="stakeholder", name="Belvoir Estate Agents Nottingham", role="Brokerage & Valuation", email="nottingham@belvoir.co.uk", cost="1.2% commission"),
        Contact(user_id=uid, project_id=pid, kind="stakeholder", name="Browne Jacobson Solicitors", role="Legal & Conveyancing", email="conveyancing@brownejacobson.com", cost="£1,250 fixed"),
    ]
    await db.contacts.insert_many([c.to_mongo() for c in contacts])
    receipts = [
        Receipt(user_id=uid, project_id=pid, title="B&Q Timber & Plasterboard", amount=480.50, date="2026-06-12", supplier="B&Q"),
        Receipt(user_id=uid, project_id=pid, title="Toolstation Cable & Sockets", amount=215.20, date="2026-06-14", supplier="Toolstation"),
        Receipt(user_id=uid, project_id=pid, title="Wren Kitchen Deposit", amount=1500.00, date="2026-06-18", supplier="Wren Kitchens"),
    ]
    await db.receipts.insert_many([r.to_mongo() for r in receipts])
    media = [
        Media(user_id=uid, project_id=pid, title="Kitchen Strip-Out Before", phase="before", url="https://placehold.co/600x400/0f766e/ffffff.png?text=Kitchen+Before", date="2026-06-01"),
        Media(user_id=uid, project_id=pid, title="New First Fix Electrics", phase="progress", url="https://placehold.co/600x400/06b6d4/ffffff.png?text=First+Fix+Electrics", date="2026-06-15"),
        Media(user_id=uid, project_id=pid, title="Bathroom Plumbing Installed", phase="after", url="https://placehold.co/600x400/f97316/ffffff.png?text=Bathroom+Plumbing", date="2026-06-20"),
    ]
    await db.media.insert_many([m.to_mongo() for m in media])
    await seed_milestones(uid, pid, demo=True)


async def create_user(name: str, email: str, password: str, source: Optional[str] = None) -> User:
    email = email.lower().strip()
    if len(password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    if await db.users.find_one({"email": email}):
        raise HTTPException(409, "Email already registered")
    u = User(name=name.strip() or "Builder", email=email, signup_source=source,
             password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
             trial_ends=(datetime.now(timezone.utc) + timedelta(days=30)).isoformat())
    res = await db.users.insert_one(u.to_mongo())
    u.id = str(res.inserted_id)
    await seed_user_data(u.id)
    return u


@api.post("/auth/register")
async def register(body: RegisterIn):
    u = await create_user(body.name, body.email, body.password)
    return {"access_token": make_token(u.id), "user": user_out(u)}


@api.post("/auth/login")
async def login(body: LoginIn):
    u = User.from_mongo(await db.users.find_one({"email": body.email.lower()}))
    if not u or not bcrypt.checkpw(body.password.encode(), u.password_hash.encode()):
        raise HTTPException(401, "Incorrect email or password")
    return {"access_token": make_token(u.id), "user": user_out(u)}


@api.get("/auth/me")
async def me(user: User = Depends(current_user)):
    return user_out(user)


class PlanIn(BaseModel):
    plan: Literal["basic", "pro"]


@api.post("/auth/plan")
async def set_plan(body: PlanIn, user: User = Depends(current_user)):
    await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"plan": body.plan}})
    user.plan = body.plan
    return user_out(user)


# ---------------- Project ----------------
async def active_pid(user: User) -> str:
    if user.active_project_id and ObjectId.is_valid(user.active_project_id) and await db.projects.find_one(
            {"_id": ObjectId(user.active_project_id), "user_id": user.id}, {"_id": 1}):
        return user.active_project_id
    doc = await db.projects.find_one({"user_id": user.id}, sort=[("_id", 1)])
    if not doc:
        raise HTTPException(404, "Project not found")
    pid = str(doc["_id"])
    await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"active_project_id": pid}})
    user.active_project_id = pid
    return pid


async def get_project_doc(user: User) -> Project:
    pid = await active_pid(user)
    return Project.from_mongo(await db.projects.find_one({"_id": ObjectId(pid)}))


@api.get("/project")
async def get_project(user: User = Depends(current_user)):
    return await project_summary(await get_project_doc(user))


async def project_summary(p: Project) -> dict:
    items = await db.line_items.find({"project_id": p.id}).to_list(1000)
    receipts = await db.receipts.find({"project_id": p.id}).to_list(1000)
    spent = {"hard": 0.0, "soft": 0.0, "contingency": 0.0}
    key = {"Hard Cost": "hard", "Soft Cost": "soft", "Contingency": "contingency"}
    for i in items:
        spent[key[i["category"]]] += i.get("actual", 0)
    for r in receipts:
        spent[key.get(r.get("category"), "hard")] += r.get("amount", 0)
    out = p.out()
    out.pop("comparables", None)
    total_budget = p.budget.hard + p.budget.soft + p.budget.contingency
    total_spent = sum(spent.values())
    ms = await db.milestones.find({"project_id": p.id}).sort("order", 1).to_list(200)
    current = next((m for m in ms if m["status"] == "in_progress"), None) or next((m for m in ms if m["status"] == "todo"), None)
    out.update({"spent": spent, "total_budget": total_budget, "total_spent": round(total_spent, 2),
                "line_item_count": len(items), "receipt_count": len(receipts),
                "milestones_total": len(ms), "milestones_done": sum(1 for m in ms if m["status"] == "done"),
                "current_stage": current["name"] if current else ("Complete" if ms else None)})
    return out


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    finish_type: Optional[str] = None
    purchase_price: Optional[float] = None
    estimated_valuation: Optional[float] = None
    monthly_rent: Optional[float] = None
    budget: Optional[Budget] = None


@api.put("/project")
async def update_project(body: ProjectUpdate, user: User = Depends(current_user)):
    upd = body.model_dump(exclude_none=True)
    pid = await active_pid(user)
    if upd:
        await db.projects.update_one({"_id": ObjectId(pid)}, {"$set": upd})
    return await get_project(user)


@api.get("/project/comparables")
async def comparables(user: User = Depends(pro_user)):
    p = await get_project_doc(user)
    return [c.model_dump() for c in p.comparables]


class ProjectCreate(BaseModel):
    name: str
    address: str = ""
    target_type: str = "BRRR Refurbishment"
    finish_type: str = "Medium Finish"
    purchase_price: float = 0
    estimated_valuation: float = 0
    monthly_rent: float = 0
    budget: Budget = Budget()


@api.get("/projects")
async def list_projects(user: User = Depends(current_user)):
    pid = await active_pid(user)
    docs = await db.projects.find({"user_id": user.id}).sort("_id", 1).to_list(200)
    out = []
    for d in docs:
        s = await project_summary(Project.from_mongo(d))
        s["active"] = s["id"] == pid
        out.append(s)
    return out


@api.post("/projects")
async def create_project(body: ProjectCreate, user: User = Depends(current_user)):
    if not body.name.strip():
        raise HTTPException(400, "Project name is required")
    p = Project(user_id=user.id, **body.model_dump())
    p.id = str((await db.projects.insert_one(p.to_mongo())).inserted_id)
    await seed_milestones(user.id, p.id)
    await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"active_project_id": p.id}})
    return await project_summary(p)


@api.post("/projects/{pid}/activate")
async def activate_project(pid: str, user: User = Depends(current_user)):
    doc = await db.projects.find_one({"_id": oid(pid), "user_id": user.id})
    if not doc:
        raise HTTPException(404, "Project not found")
    await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"active_project_id": pid}})
    return await project_summary(Project.from_mongo(doc))


@api.delete("/projects/{pid}")
async def delete_project(pid: str, user: User = Depends(current_user)):
    if await db.projects.count_documents({"user_id": user.id}) <= 1:
        raise HTTPException(400, "You need at least one project")
    r = await db.projects.delete_one({"_id": oid(pid), "user_id": user.id})
    if not r.deleted_count:
        raise HTTPException(404, "Project not found")
    for coll in (db.line_items, db.contacts, db.receipts, db.media, db.milestones, db.quote_requests, db.stage_payments, db.snags):
        await coll.delete_many({"user_id": user.id, "project_id": pid})
    if user.active_project_id == pid:
        await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"active_project_id": None}})
    return {"ok": True}


# ---------------- Line items ----------------
class LineItemIn(BaseModel):
    category: Literal["Hard Cost", "Soft Cost", "Contingency"]
    name: str
    budgeted: float = 0
    actual: float = 0
    supplier: str = ""
    status: str = "Planned"


@api.get("/line-items")
async def list_items(user: User = Depends(current_user)):
    docs = await db.line_items.find({"user_id": user.id, "project_id": await active_pid(user)}).sort("created_at", -1).to_list(1000)
    return [LineItem.from_mongo(d).out() for d in docs]


@api.post("/line-items")
async def create_item(body: LineItemIn, user: User = Depends(current_user)):
    li = LineItem(user_id=user.id, project_id=await active_pid(user), **body.model_dump())
    res = await db.line_items.insert_one(li.to_mongo())
    li.id = str(res.inserted_id)
    return li.out()


def oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(404, "Not found")


@api.put("/line-items/{item_id}")
async def update_item(item_id: str, body: LineItemIn, user: User = Depends(current_user)):
    r = await db.line_items.update_one({"_id": oid(item_id), "user_id": user.id}, {"$set": body.model_dump()})
    if not r.matched_count:
        raise HTTPException(404, "Not found")
    return LineItem.from_mongo(await db.line_items.find_one({"_id": oid(item_id)})).out()


@api.delete("/line-items/{item_id}")
async def delete_item(item_id: str, user: User = Depends(current_user)):
    await db.line_items.delete_one({"_id": oid(item_id), "user_id": user.id})
    return {"ok": True}


# ---------------- Contacts ----------------
class ContactIn(BaseModel):
    kind: Literal["trade", "subcontractor", "stakeholder"]
    name: str
    role: str = ""
    phone: str = ""
    email: str = ""
    status: str = ""
    schedule: str = ""
    cost: str = ""


@api.get("/contacts")
async def list_contacts(kind: str = Query("trade"), user: User = Depends(current_user)):
    if kind != "trade" and user.plan != "pro":
        raise HTTPException(403, "Pro plan required")
    docs = await db.contacts.find({"user_id": user.id, "project_id": await active_pid(user), "kind": kind}).sort("created_at", 1).to_list(500)
    return [Contact.from_mongo(d).out() for d in docs]


@api.post("/contacts")
async def create_contact(body: ContactIn, user: User = Depends(current_user)):
    if body.kind != "trade" and user.plan != "pro":
        raise HTTPException(403, "Pro plan required")
    c = Contact(user_id=user.id, project_id=await active_pid(user), **body.model_dump())
    res = await db.contacts.insert_one(c.to_mongo())
    c.id = str(res.inserted_id)
    return c.out()


@api.delete("/contacts/{cid}")
async def delete_contact(cid: str, user: User = Depends(current_user)):
    await db.contacts.delete_one({"_id": oid(cid), "user_id": user.id})
    return {"ok": True}


# ---------------- Object storage ----------------
STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
storage_key = None


def init_storage():
    global storage_key
    if storage_key:
        return storage_key
    resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30)
    resp.raise_for_status()
    storage_key = resp.json()["storage_key"]
    return storage_key


def put_object(path: str, data: bytes, content_type: str) -> dict:
    global storage_key
    key = init_storage()
    resp = requests.put(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key, "Content-Type": content_type}, data=data, timeout=120)
    if resp.status_code == 503:
        storage_key = None
        key = init_storage()
        resp = requests.put(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key, "Content-Type": content_type}, data=data, timeout=120)
    if resp.status_code == 402:
        raise HTTPException(402, "Storage credits exhausted")
    resp.raise_for_status()
    return resp.json()


def get_object(path: str):
    key = init_storage()
    resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


@api.post("/upload")
async def upload(file: UploadFile = File(...), user: User = Depends(current_user)):
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 10MB)")
    ext = (file.filename or "img.jpg").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "jpg"
    path = f"{APP_NAME}/uploads/{user.id}/{uuid.uuid4()}.{ext}"
    ctype = file.content_type or "image/jpeg"
    result = await run_in_threadpool(put_object, path, data, ctype)
    await db.files.insert_one({"storage_path": result["path"], "owner_id": user.id, "content_type": ctype,
                               "original_filename": file.filename, "is_deleted": False, "created_at": now_iso()})
    return {"path": result["path"]}


@api.get("/files/{path:path}")
async def download(path: str, token: Optional[str] = None, cred: HTTPAuthorizationCredentials = Depends(bearer)):
    raw = cred.credentials if cred else token
    if not raw:
        raise HTTPException(401, "Not authenticated")
    uid = decode_uid(raw)
    rec = await db.files.find_one({"storage_path": path, "owner_id": uid, "is_deleted": False})
    if not rec:
        raise HTTPException(404, "File not found")
    data, ctype = await run_in_threadpool(get_object, path)
    return Response(content=data, media_type=rec.get("content_type", ctype), headers={"Cache-Control": "private, max-age=86400"})


# ---------------- Receipts ----------------
class ReceiptIn(BaseModel):
    title: str
    amount: float
    date: str
    category: str = "Hard Cost"
    supplier: str = ""
    storage_path: Optional[str] = None


@api.get("/receipts")
async def list_receipts(user: User = Depends(current_user)):
    docs = await db.receipts.find({"user_id": user.id, "project_id": await active_pid(user)}).sort("date", -1).to_list(1000)
    return [Receipt.from_mongo(d).out() for d in docs]


@api.post("/receipts")
async def create_receipt(body: ReceiptIn, user: User = Depends(current_user)):
    r = Receipt(user_id=user.id, project_id=await active_pid(user), **body.model_dump())
    res = await db.receipts.insert_one(r.to_mongo())
    r.id = str(res.inserted_id)
    return r.out()


@api.delete("/receipts/{rid}")
async def delete_receipt(rid: str, user: User = Depends(current_user)):
    await db.receipts.delete_one({"_id": oid(rid), "user_id": user.id})
    return {"ok": True}


# ---------------- Media ----------------
class MediaIn(BaseModel):
    title: str
    phase: Literal["before", "progress", "after"] = "progress"
    storage_path: Optional[str] = None
    url: Optional[str] = None
    date: Optional[str] = None
    milestone_id: Optional[str] = None


@api.get("/media")
async def list_media(user: User = Depends(current_user)):
    docs = await db.media.find({"user_id": user.id, "project_id": await active_pid(user)}).sort("created_at", -1).to_list(1000)
    return [Media.from_mongo(d).out() for d in docs]


@api.post("/media")
async def create_media(body: MediaIn, user: User = Depends(current_user)):
    m = Media(user_id=user.id, project_id=await active_pid(user), title=body.title, phase=body.phase, storage_path=body.storage_path, url=body.url,
              milestone_id=body.milestone_id or None,
              date=body.date or datetime.now(timezone.utc).date().isoformat())
    res = await db.media.insert_one(m.to_mongo())
    m.id = str(res.inserted_id)
    return m.out()


@api.delete("/media/{mid}")
async def delete_media(mid: str, user: User = Depends(current_user)):
    await db.media.delete_one({"_id": oid(mid), "user_id": user.id})
    return {"ok": True}


# ---------------- AI estimate ----------------
class EstimateIn(BaseModel):
    description: str
    finish_type: str = "Medium Finish"


@api.post("/ai/estimate")
async def ai_estimate(body: EstimateIn, user: User = Depends(current_user)):
    if not body.description.strip():
        raise HTTPException(400, "Please describe the work")
    system = ("You are a UK renovation quantity surveyor. Estimate realistic 2026 UK costs in GBP, referencing suppliers "
              "like B&Q, Wickes, Toolstation, Screwfix, Wren Kitchens, DIY Kitchens, eBay and typical Nottingham/UK trade day rates. "
              "Respond ONLY with compact JSON: {\"items\":[{\"name\":str,\"category\":\"Hard Cost\"|\"Soft Cost\",\"low\":number,\"high\":number,\"supplier\":str}],"
              "\"total_low\":number,\"total_high\":number,\"notes\":str}. 3-8 items. No markdown.")
    chat = LlmChat(api_key=EMERGENT_KEY, session_id=f"est-{uuid.uuid4()}", system_message=system).with_model("anthropic", "claude-sonnet-5-5")
    text = ""
    try:
        async for ev in chat.stream_message(UserMessage(text=f"Finish level: {body.finish_type}. Work: {body.description}")):
            if isinstance(ev, TextDelta):
                text += ev.content
            elif isinstance(ev, StreamDone):
                break
    except Exception as e:
        logger.exception("AI estimate failed")
        raise HTTPException(502, f"AI service error: {e}")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise HTTPException(502, "AI returned an unexpected response")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        raise HTTPException(502, "AI returned an unexpected response")
    await db.estimates.insert_one({"user_id": user.id, "description": body.description, "result": data, "created_at": now_iso()})
    return data


# ---------------- Payments (Stripe) ----------------
class CheckoutIn(BaseModel):
    origin_url: str


def stripe_client(request: Request):
    host = str(request.base_url).rstrip("/")
    return StripeCheckout(api_key=STRIPE_API_KEY, webhook_url=f"{host}/api/webhook/stripe")


@api.post("/payments/checkout")
async def create_checkout(body: CheckoutIn, request: Request, user: User = Depends(current_user)):
    sc = stripe_client(request)
    origin = body.origin_url.rstrip("/")
    req = CheckoutSessionRequest(amount=PRO_PRICE_GBP, currency="gbp",
                                 success_url=f"{origin}/api/payments/done?session_id={{CHECKOUT_SESSION_ID}}",
                                 cancel_url=f"{origin}/api/payments/done?cancelled=1",
                                 metadata={"user_id": user.id, "plan": "pro"})
    s = await sc.create_checkout_session(req)
    await db.payment_transactions.insert_one({"session_id": s.session_id, "user_id": user.id, "amount": PRO_PRICE_GBP,
                                              "currency": "gbp", "metadata": {"plan": "pro"}, "payment_status": "initiated",
                                              "created_at": now_iso()})
    return {"url": s.url, "session_id": s.session_id}


async def mark_paid(session_id: str):
    tx = await db.payment_transactions.find_one({"session_id": session_id})
    if not tx or tx.get("payment_status") == "paid":
        return
    await db.payment_transactions.update_one({"session_id": session_id}, {"$set": {"payment_status": "paid", "paid_at": now_iso()}})
    await db.users.update_one({"_id": ObjectId(tx["user_id"])}, {"$set": {"plan": "pro", "paid_pro": True}})


@api.get("/payments/status/{session_id}")
async def payment_status(session_id: str, request: Request, user: User = Depends(current_user)):
    tx = await db.payment_transactions.find_one({"session_id": session_id, "user_id": user.id})
    if not tx:
        raise HTTPException(404, "Payment not found")
    st = await stripe_client(request).get_checkout_status(session_id)
    if st.payment_status == "paid":
        await mark_paid(session_id)
    elif st.status == "expired":
        await db.payment_transactions.update_one({"session_id": session_id}, {"$set": {"payment_status": "expired"}})
    return {"status": st.status, "payment_status": st.payment_status}


@api.get("/payments/done", response_class=HTMLResponse)
async def payment_done(session_id: Optional[str] = None, cancelled: Optional[str] = None):
    msg = "Payment cancelled." if cancelled else "Payment received! You can now return to My Builder App."
    return f"<html><body style='font-family:sans-serif;text-align:center;padding:60px'><h2>{msg}</h2></body></html>"


@api.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    body = await request.body()
    try:
        ev = await stripe_client(request).handle_webhook(body, request.headers.get("Stripe-Signature"))
        if ev.payment_status == "paid" and ev.session_id:
            await mark_paid(ev.session_id)
    except Exception as e:
        logger.warning(f"Webhook error: {e}")
    return {"received": True}


# ---------------- Trades finder (postcodes.io + OpenStreetMap) ----------------
TRADE_TERMS = {
    "electrician": ["electrician"],
    "plumber": ["plumber", "heating"],
    "builder": ["builders", "builder"],
    "carpenter": ["carpenter", "joinery"],
    "painter": ["painter", "decorator"],
    "roofer": ["roofer", "roofing"],
}
OSM_UA = {"User-Agent": "my-builder-app/1.0 (support@mybuilder.app)"}
POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}$")


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def geocode_postcode(pc: str):
    r = requests.get(f"https://api.postcodes.io/postcodes/{pc.replace(' ', '%20')}", headers=OSM_UA, timeout=10)
    if r.status_code == 404:
        raise HTTPException(404, "Postcode not found")
    r.raise_for_status()
    res = r.json()["result"]
    return float(res["latitude"]), float(res["longitude"]), res["postcode"]


def overpass_search(lat, lon, trade):
    q = f'[out:json][timeout:15];nwr(around:8000,{lat},{lon})[craft="{trade}"];out center tags;'
    try:
        r = requests.post("https://overpass-api.de/api/interpreter", data={"data": q}, headers=OSM_UA, timeout=15)
        r.raise_for_status()
        out = []
        for e in r.json().get("elements", []):
            t = e.get("tags", {})
            pt = e.get("center", e)
            if not t.get("name") or "lat" not in pt:
                continue
            addr = " ".join(x for x in [t.get("addr:housenumber"), t.get("addr:street"), t.get("addr:city"), t.get("addr:postcode")] if x)
            out.append({"osm_id": f"{e['type']}/{e['id']}", "name": t["name"], "lat": float(pt["lat"]), "lon": float(pt["lon"]),
                        "phone": t.get("phone") or t.get("contact:phone") or t.get("mobile"),
                        "email": t.get("email") or t.get("contact:email"),
                        "website": t.get("website") or t.get("contact:website"), "address": addr})
        return out
    except Exception as e:
        logger.info(f"Overpass unavailable, falling back to Nominatim: {e}")
        return None


def nominatim_search(lat, lon, trade):
    out = []
    viewbox = f"{lon - 0.09},{lat + 0.055},{lon + 0.09},{lat - 0.055}"
    for i, term in enumerate(TRADE_TERMS[trade]):
        if i:
            time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec
        r = requests.get("https://nominatim.openstreetmap.org/search", headers=OSM_UA, timeout=15, params={
            "q": term, "format": "jsonv2", "limit": 25, "extratags": 1, "addressdetails": 1, "bounded": 1, "viewbox": viewbox})
        if r.status_code != 200:
            continue
        for e in r.json():
            if e.get("category") not in ("craft", "office", "building") or not e.get("name"):
                continue
            t = e.get("extratags") or {}
            a = e.get("address") or {}
            addr = " ".join(x for x in [a.get("house_number"), a.get("road"), a.get("city") or a.get("town") or a.get("suburb"), a.get("postcode")] if x)
            out.append({"osm_id": f"{e.get('osm_type')}/{e.get('osm_id')}", "name": e["name"], "lat": float(e["lat"]), "lon": float(e["lon"]),
                        "phone": t.get("phone") or t.get("contact:phone") or t.get("mobile"),
                        "email": t.get("email") or t.get("contact:email"),
                        "website": t.get("website") or t.get("contact:website"), "address": addr})
    return out


def find_trades(lat, lon, trade):
    found = overpass_search(lat, lon, trade)
    if found is None:
        found = nominatim_search(lat, lon, trade)
    seen, results = set(), []
    for f in found:
        if f["osm_id"] in seen:
            continue
        seen.add(f["osm_id"])
        f["trade"] = trade
        f["distance_km"] = round(haversine_km(lat, lon, f["lat"], f["lon"]), 2)
        results.append(f)
    return sorted(results, key=lambda x: x["distance_km"])[:30]


@api.get("/trades/search")
async def trades_search(postcode: str, trade: str = "electrician", user: User = Depends(current_user)):
    pc = " ".join(postcode.upper().split())
    if not POSTCODE_RE.match(pc):
        raise HTTPException(400, "Please enter a valid UK postcode")
    if trade not in TRADE_TERMS:
        raise HTTPException(400, "Unknown trade")
    key = f"{pc.replace(' ', '')}|{trade}"
    cached = await db.trade_cache.find_one({"key": key})
    if cached and datetime.fromisoformat(cached["fetched_at"]) > datetime.now(timezone.utc) - timedelta(hours=24):
        return {"postcode": cached["postcode"], "trade": trade, "results": cached["results"], "attribution": "© OpenStreetMap contributors"}
    try:
        lat, lon, norm = await run_in_threadpool(geocode_postcode, pc)
        results = await run_in_threadpool(find_trades, lat, lon, trade)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Trades search failed")
        raise HTTPException(503, f"Trades search is temporarily unavailable: {e}")
    await db.trade_cache.update_one({"key": key}, {"$set": {"key": key, "postcode": norm, "results": results, "fetched_at": now_iso()}}, upsert=True)
    return {"postcode": norm, "trade": trade, "results": results, "attribution": "© OpenStreetMap contributors"}


# ---------------- Milestones ----------------
DEFAULT_MILESTONES = ["Purchase complete", "Strip-out", "Structural & roofing", "First fix (electrics & plumbing)",
                      "Plastering", "Second fix", "Kitchen & bathroom install", "Decoration & flooring",
                      "Final inspection & sign-off", "Refinance / let"]


class Milestone(BaseDocument):
    user_id: str
    project_id: str
    name: str
    status: Literal["todo", "in_progress", "done"] = "todo"
    target_date: Optional[str] = None
    notes: str = ""
    order: int = 0
    completed_at: Optional[str] = None


async def seed_milestones(uid: str, pid: str, demo: bool = False):
    start = datetime(2026, 5, 18, tzinfo=timezone.utc)
    docs = []
    for i, n in enumerate(DEFAULT_MILESTONES):
        st = ("done" if i < 3 else "in_progress" if i == 3 else "todo") if demo else "todo"
        docs.append(Milestone(user_id=uid, project_id=pid, name=n, status=st, order=i,
                              target_date=(start + timedelta(days=14 * i)).date().isoformat() if demo else None,
                              completed_at=now_iso() if st == "done" else None).to_mongo())
    await db.milestones.insert_many(docs)


class MilestoneIn(BaseModel):
    name: str
    target_date: Optional[str] = None


class MilestoneUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[Literal["todo", "in_progress", "done"]] = None
    target_date: Optional[str] = None
    notes: Optional[str] = None


@api.get("/milestones")
async def list_milestones(user: User = Depends(current_user)):
    docs = await db.milestones.find({"user_id": user.id, "project_id": await active_pid(user)}).sort("order", 1).to_list(200)
    return [Milestone.from_mongo(d).out() for d in docs]


@api.post("/milestones")
async def create_milestone(body: MilestoneIn, user: User = Depends(current_user)):
    if not body.name.strip():
        raise HTTPException(400, "Stage name is required")
    pid = await active_pid(user)
    last = await db.milestones.find_one({"project_id": pid}, sort=[("order", -1)])
    m = Milestone(user_id=user.id, project_id=pid, name=body.name.strip(), target_date=body.target_date or None,
                  order=(last["order"] + 1) if last else 0)
    m.id = str((await db.milestones.insert_one(m.to_mongo())).inserted_id)
    return m.out()


@api.put("/milestones/{mid}")
async def update_milestone(mid: str, body: MilestoneUpdate, user: User = Depends(current_user)):
    upd = body.model_dump(exclude_unset=True)
    if "status" in upd:
        upd["completed_at"] = now_iso() if upd["status"] == "done" else None
    if "target_date" in upd and not upd["target_date"]:
        upd["target_date"] = None
    r = await db.milestones.update_one({"_id": oid(mid), "user_id": user.id}, {"$set": upd})
    if not r.matched_count:
        raise HTTPException(404, "Not found")
    return Milestone.from_mongo(await db.milestones.find_one({"_id": oid(mid)})).out()


@api.delete("/milestones/{mid}")
async def delete_milestone(mid: str, user: User = Depends(current_user)):
    await db.milestones.delete_one({"_id": oid(mid), "user_id": user.id})
    return {"ok": True}


# ---------------- Public HTML helpers ----------------
E = html.escape
PAGE_CSS = """*{box-sizing:border-box}body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;margin:0;background:#f8fafc;color:#0f172a}
.wrap{max-width:820px;margin:0 auto;padding:20px}.hdr{background:#0f766e;color:#fff;border-radius:16px;padding:22px}
.brand{font-size:11px;letter-spacing:1.5px;font-weight:700;opacity:.85}.brand b{color:#f97316}h1{margin:8px 0 4px;font-size:24px}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:16px;margin-top:14px}h2{font-size:15px;color:#0f766e;margin:0 0 10px}
.kpis{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}@media(min-width:600px){.kpis{grid-template-columns:repeat(4,1fr)}}
.kpi{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px}.kpi span{font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.6px}
.kpi div{font-size:18px;font-weight:800;margin-top:4px}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:8px 6px;border-bottom:1px solid #f1f5f9}
th{font-size:10px;color:#64748b;text-transform:uppercase}.n{text-align:right}.over{color:#ef4444;font-weight:700}.under{color:#10b981;font-weight:700}
.bar{height:8px;background:#f1f5f9;border-radius:4px;overflow:hidden;margin-top:8px}.bar i{display:block;height:8px;background:#f97316}
.ms{display:flex;gap:10px;align-items:center;padding:7px 0}.dot{width:14px;height:14px;border-radius:7px;border:2px solid #cbd5e1;flex-shrink:0}
.dot.done{background:#10b981;border-color:#10b981}.dot.in_progress{background:#f97316;border-color:#f97316}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}@media(min-width:600px){.grid{grid-template-columns:repeat(3,1fr)}}
.grid img{width:100%;height:140px;object-fit:cover;border-radius:10px;background:#f1f5f9}.cap{font-size:11px;color:#64748b;margin-top:4px}
.tag{display:inline-block;font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px;background:#f0fdf4;color:#0f766e}
.foot{text-align:center;color:#64748b;font-size:11px;margin:24px 0}
.msph{display:flex;gap:8px;margin:0 0 8px 24px;overflow-x:auto}.msph figure{margin:0;flex-shrink:0}.msph img{width:96px;height:72px;object-fit:cover;border-radius:8px;background:#f1f5f9}
.msph figcaption{margin-top:2px}label{display:block;font-size:13px;font-weight:600;margin:12px 0 6px;color:#334155}
input,textarea{width:100%;padding:12px;border:1px solid #e2e8f0;border-radius:10px;font-size:15px;background:#f8fafc}
button{margin-top:16px;width:100%;padding:14px;border:0;border-radius:12px;background:#f97316;color:#fff;font-size:16px;font-weight:700}"""


CTA_CSS = """.cta{background:#1e293b;color:#f8fafc;border-radius:16px;padding:20px;margin-top:18px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
.cta h3{margin:0 0 4px;font-size:17px}.cta p{margin:0;font-size:13px;opacity:.85}.cta a{display:inline-block;background:#f97316;color:#fff;text-decoration:none;
font-weight:700;padding:12px 18px;border-radius:12px;white-space:nowrap}.cta .t{flex:1;min-width:200px}
.bb{display:flex;gap:14px;align-items:center;background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:14px;margin-bottom:12px}
.bb img{width:56px;height:56px;object-fit:contain;border-radius:10px;background:#f8fafc}.bb .c{font-weight:800;font-size:16px}.bb .d{font-size:12px;color:#64748b;margin-top:2px}
.bb a{color:#0f766e;text-decoration:none}"""


def page(title: str, body: str, ref: Optional[str] = None, by: Optional[str] = None) -> HTMLResponse:
    cta = (f"<div class='cta' id='trial-cta'><div class='t'><h3>Run your own renovation like this</h3><p>Budgets, milestones, quotes & lender reports in one app. "
           f"30 days free, no card needed.</p></div><a href='/api/join?ref={E(ref)}&by={E(by or '')}' id='start-trial-link'>Start free trial</a></div>") if ref else ""
    return HTMLResponse(f"<!DOCTYPE html><html><head><meta charset='utf-8'/><meta name='viewport' content='width=device-width,initial-scale=1'/>"
                        f"<title>{E(title)}</title><style>{PAGE_CSS}{CTA_CSS}</style></head><body><div class='wrap'>{body}{cta}"
                        f"<div class='foot'>Powered by My Builder App</div></div></body></html>")


async def owner_branding(uid: str) -> Branding:
    doc = await db.users.find_one({"_id": ObjectId(uid)}, {"branding": 1})
    return Branding(**((doc or {}).get("branding") or {}))


def brand_block(b: Branding, logo_src: str) -> str:
    if not (b.company_name or b.logo_path):
        return ""
    contacts = " · ".join(x for x in [
        E(b.contact_name) if b.contact_name else "",
        f"<a href='tel:{E(b.phone)}'>{E(b.phone)}</a>" if b.phone else "",
        f"<a href='mailto:{E(b.email)}'>{E(b.email)}</a>" if b.email else "",
        f"<a href='{E(b.website if b.website.startswith('http') else 'https://' + b.website)}'>{E(b.website)}</a>" if b.website else ""] if x)
    logo = f"<img src='{logo_src}' alt='logo'/>" if b.logo_path else ""
    return (f"<div class='bb' id='brand-block'>{logo}<div><div class='c'>{E(b.company_name)}</div>"
            f"{f'<div class=d>{E(b.tagline)}</div>' if b.tagline else ''}<div class='d'>{contacts}</div></div></div>")


async def serve_logo(uid: str):
    b = await owner_branding(uid)
    if not b.logo_path:
        raise HTTPException(404, "No logo")
    data, ctype = await run_in_threadpool(get_object, b.logo_path)
    return Response(content=data, media_type=ctype, headers={"Cache-Control": "public, max-age=3600"})


# ---------------- Branding ----------------
@api.get("/branding")
async def get_branding(user: User = Depends(current_user)):
    return user.branding.model_dump()


@api.put("/branding")
async def put_branding(body: Branding, user: User = Depends(current_user)):
    if body.logo_path and not await db.files.find_one({"storage_path": body.logo_path, "owner_id": user.id}):
        raise HTTPException(400, "Invalid logo")
    await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"branding": body.model_dump()}})
    return body.model_dump()


@api.get("/share/{token}/logo")
async def share_logo(token: str):
    doc = await db.projects.find_one({"share_token": token}) if token else None
    if not doc:
        raise HTTPException(404, "Not found")
    return await serve_logo(doc["user_id"])


# ---------------- Public trial signup ----------------
JOIN_FORM = """<div class='hdr'><div class='brand'>MY BUILDER <b>APP</b></div><h1>Start your 30-day free trial</h1>
<div>Track refurb budgets, milestones, trades & BRRR numbers in one app. No card required.</div></div>
<form class='card' method='post' id='join-form'><input type='hidden' name='ref' value='{ref}'/><input type='hidden' name='by' value='{by}'/>{err}
<label>Full name</label><input name='name' required value='{name}'/>
<label>Email</label><input name='email' type='email' required value='{email}'/>
<label>Password (min 6 characters)</label><input name='password' type='password' minlength='6' required/>
<button type='submit' id='join-submit'>Create free account</button></form>"""


@api.get("/join", response_class=HTMLResponse)
async def join_page(ref: str = "direct", by: str = ""):
    return page("Start free trial", JOIN_FORM.format(ref=E(ref), by=E(by), err="", name="", email=""))


REFERRAL_DAYS = 30


async def credit_referrer(by: str, new_user: User, source: str):
    if not by or not ObjectId.is_valid(by) or by == new_user.id:
        return
    ref = await db.users.find_one({"_id": ObjectId(by)}, {"trial_ends": 1})
    if not ref:
        return
    base = max(datetime.now(timezone.utc), datetime.fromisoformat(ref["trial_ends"]))
    await db.users.update_one({"_id": ref["_id"]}, {"$set": {"trial_ends": (base + timedelta(days=REFERRAL_DAYS)).isoformat()},
                                                   "$inc": {"referral_count": 1}})
    await db.users.update_one({"_id": ObjectId(new_user.id)}, {"$set": {"referred_by": by}})
    await db.referrals.insert_one({"referrer_id": by, "new_user_id": new_user.id, "name": new_user.name, "source": source,
                                   "days": REFERRAL_DAYS, "created_at": now_iso()})


@api.get("/referrals")
async def my_referrals(user: User = Depends(current_user)):
    docs = await db.referrals.find({"referrer_id": user.id}).sort("created_at", -1).to_list(100)
    return {"count": len(docs), "months_earned": len(docs), "trial_ends": user.trial_ends,
            "recent": [{"name": d["name"].split(" ")[0], "source": d["source"], "date": d["created_at"][:10]} for d in docs[:20]]}


@api.post("/join", response_class=HTMLResponse)
async def join_submit(name: str = Form(...), email: str = Form(...), password: str = Form(...), ref: str = Form("direct"), by: str = Form("")):
    src = re.sub(r"[^a-z_]", "", ref.lower())[:20] or "direct"
    by = re.sub(r"[^a-f0-9]", "", by.lower())[:24]
    try:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()):
            raise HTTPException(400, "Please enter a valid email")
        nu = await create_user(name, email, password, source=src)
    except HTTPException as e:
        err = f"<p class='over' id='join-error'>{E(str(e.detail))}</p>"
        return page("Start free trial", JOIN_FORM.format(ref=E(src), by=E(by), err=err, name=E(name), email=E(email)))
    await credit_referrer(by, nu, src)
    return page("Welcome", f"""<div class='hdr'><div class='brand'>MY BUILDER <b>APP</b></div><h1>You're in! 🎉</h1>
<div>Your 30-day free trial has started.</div></div><div class='card' id='join-success'><h2>Next steps</h2>
<p>1. Open <b>My Builder App</b> on your phone.</p><p>2. Tap <b>Sign in</b> and use <b>{E(email.strip().lower())}</b>.</p>
<p>3. Your first sample project is already loaded so you can explore straight away.</p></div>""")


def money(n, d=0):
    return f"£{n:,.{d}f}"


# ---------------- Lender share link ----------------
class ShareIn(BaseModel):
    origin_url: str


def share_url(p: Project):
    return f"{p.share_origin.rstrip('/')}/api/share/{p.share_token}" if p.share_token and p.share_origin else None


@api.get("/project/share")
async def get_share(user: User = Depends(current_user)):
    return {"url": share_url(await get_project_doc(user))}


@api.post("/project/share")
async def create_share(body: ShareIn, user: User = Depends(current_user)):
    p = await get_project_doc(user)
    token = p.share_token or secrets.token_urlsafe(16)
    await db.projects.update_one({"_id": ObjectId(p.id)}, {"$set": {"share_token": token, "share_origin": body.origin_url}})
    p.share_token, p.share_origin = token, body.origin_url
    return {"url": share_url(p)}


@api.delete("/project/share")
async def revoke_share(user: User = Depends(current_user)):
    p = await get_project_doc(user)
    await db.projects.update_one({"_id": ObjectId(p.id)}, {"$set": {"share_token": None}})
    return {"url": None}


@api.get("/share/{token}", response_class=HTMLResponse)
async def public_report(token: str):
    doc = await db.projects.find_one({"share_token": token}) if token else None
    if not doc:
        return page("Link expired", "<div class='card'><h2>This report link is no longer active</h2><p>Ask the project owner for a new link.</p></div>")
    p = Project.from_mongo(doc)
    s = await project_summary(p)
    items = await db.line_items.find({"project_id": p.id}).sort("created_at", -1).to_list(500)
    receipts = await db.receipts.find({"project_id": p.id}).sort("date", -1).to_list(500)
    media = await db.media.find({"project_id": p.id}).sort("created_at", 1).to_list(60)
    ms = await db.milestones.find({"project_id": p.id}).sort("order", 1).to_list(200)
    pct = round(s["total_spent"] / s["total_budget"] * 100) if s["total_budget"] else 0
    rem = s["total_budget"] - s["total_spent"]
    brand = brand_block(await owner_branding(p.user_id), f"/api/share/{E(token)}/logo")
    by_ms: dict = {}
    for m in media:
        if m.get("milestone_id"):
            by_ms.setdefault(m["milestone_id"], []).append(m)
    cats = [("Hard costs", p.budget.hard, s["spent"]["hard"]), ("Soft costs", p.budget.soft, s["spent"]["soft"]),
            ("Contingency", p.budget.contingency, s["spent"]["contingency"])]
    body = brand + f"""<div class='hdr'><div class='brand'>MY BUILDER <b>APP</b> · LIVE PROJECT REPORT</div><h1>{E(p.name)}</h1>
<div>{E(p.address)}</div><div style='font-size:12px;opacity:.85;margin-top:6px'>{E(p.target_type)} · {E(p.finish_type)} · Updated {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M')} UTC</div></div>
<div class='kpis' style='margin-top:14px'><div class='kpi'><span>Purchase</span><div>{money(p.purchase_price)}</div></div>
<div class='kpi'><span>Est. valuation</span><div>{money(p.estimated_valuation)}</div></div><div class='kpi'><span>Budget</span><div>{money(s['total_budget'])}</div></div>
<div class='kpi'><span>Spent</span><div>{money(s['total_spent'])}</div></div></div>
<div class='card'><b>{pct}% of budget used</b> · {money(rem) + ' remaining' if rem >= 0 else "<span class='over'>" + money(-rem) + ' over budget</span>'}
<div class='bar'><i style='width:{min(100, pct)}%'></i></div></div>"""
    if ms:
        body += f"<div class='card'><h2>Milestones · {s['milestones_done']}/{s['milestones_total']} complete</h2>" + "".join(
            f"<div class='ms'><div class='dot {m['status']}'></div><div style='flex:1'>{E(m['name'])}</div>"
            f"<div class='cap'>{'Done' if m['status'] == 'done' else 'In progress' if m['status'] == 'in_progress' else (m.get('target_date') or '')}</div></div>"
            + ("<div class='msph'>" + "".join(
                f"<figure><img loading='lazy' src='/api/share/{E(token)}/photo/{ph['_id']}'/><figcaption><span class='tag'>{E(ph['phase'].upper())}</span></figcaption></figure>"
                for ph in by_ms.get(str(m["_id"]), [])) + "</div>" if by_ms.get(str(m["_id"])) else "")
            for m in ms) + "</div>"
    snags = await db.snags.find({"project_id": p.id}).to_list(500)
    if snags:
        open_n = sum(1 for x in snags if x["status"] == "open")
        body += (f"<div class='card' id='snag-summary'><h2>Snagging · {len(snags) - open_n}/{len(snags)} fixed</h2>"
                 f"<div class='cap'>{open_n} open item{'s' if open_n != 1 else ''} before sign-off</div></div>")
    body += "<div class='card'><h2>Budget breakdown</h2><table><tr><th>Category</th><th class='n'>Budget</th><th class='n'>Spent</th><th class='n'>Variance</th></tr>" + "".join(
        f"<tr><td>{l}</td><td class='n'>{money(b)}</td><td class='n'>{money(sp)}</td><td class='n {'over' if b - sp < 0 else 'under'}'>{money(b - sp)}</td></tr>"
        for l, b, sp in cats) + "</table></div>"
    body += f"<div class='card'><h2>Line items ({len(items)})</h2><table><tr><th>Item</th><th>Status</th><th class='n'>Budget</th><th class='n'>Actual</th></tr>" + "".join(
        f"<tr><td>{E(i['name'])}<div class='cap'>{E(i.get('supplier', ''))}</div></td><td><span class='tag'>{E(i.get('status', ''))}</span></td>"
        f"<td class='n'>{money(i.get('budgeted', 0))}</td><td class='n'>{money(i.get('actual', 0))}</td></tr>" for i in items) + "</table></div>"
    body += f"<div class='card'><h2>Receipts ({len(receipts)}) · {money(sum(r['amount'] for r in receipts), 2)}</h2><table>" + "".join(
        f"<tr><td>{E(r['date'])}</td><td>{E(r['title'])}</td><td class='n'>{money(r['amount'], 2)}</td></tr>" for r in receipts) + "</table></div>"
    if media:
        body += "<div class='card'><h2>Site photos</h2><div class='grid'>" + "".join(
            f"<div><img loading='lazy' src='/api/share/{E(token)}/photo/{m['_id']}'/><div class='cap'><span class='tag'>{E(m['phase'].upper())}</span> {E(m['title'])}</div></div>"
            for m in media) + "</div></div>"
    return page(f"{p.name} · Project report", body, ref="share", by=p.user_id)


@api.get("/share/{token}/photo/{mid}")
async def public_photo(token: str, mid: str):
    doc = await db.projects.find_one({"share_token": token}) if token else None
    if not doc:
        raise HTTPException(404, "Not found")
    m = await db.media.find_one({"_id": oid(mid), "project_id": str(doc["_id"])})
    if not m:
        raise HTTPException(404, "Not found")
    if m.get("storage_path"):
        data, ctype = await run_in_threadpool(get_object, m["storage_path"])
        return Response(content=data, media_type=ctype, headers={"Cache-Control": "public, max-age=3600"})
    return RedirectResponse(m["url"])


# ---------------- Quote requests ----------------
class QuoteEntry(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    token: str = Field(default_factory=lambda: secrets.token_urlsafe(12))
    contact_id: Optional[str] = None
    name: str
    role: str = ""
    phone: str = ""
    email: str = ""
    status: Literal["requested", "received", "accepted", "declined"] = "requested"
    sent: bool = False
    amount: Optional[float] = None
    days: Optional[int] = None
    notes: str = ""
    responded_at: Optional[str] = None


class QuoteRequest(BaseDocument):
    user_id: str
    project_id: str
    title: str
    description: str
    trade: str = ""
    origin: str = ""
    quotes: List[QuoteEntry] = []
    added_line_item_id: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)


def quote_out(q: QuoteRequest):
    d = q.out()
    for e in d["quotes"]:
        e["link"] = f"{q.origin.rstrip('/')}/api/q/{e['token']}"
    return d


class QuoteCreate(BaseModel):
    title: str
    description: str
    trade: str = ""
    contact_ids: List[str]
    origin_url: str


class EntryUpdate(BaseModel):
    amount: Optional[float] = None
    days: Optional[int] = None
    notes: Optional[str] = None
    sent: Optional[bool] = None
    status: Optional[Literal["requested", "received", "declined"]] = None


async def load_quote(qid: str, user: User) -> QuoteRequest:
    q = QuoteRequest.from_mongo(await db.quote_requests.find_one({"_id": oid(qid), "user_id": user.id}))
    if not q:
        raise HTTPException(404, "Quote request not found")
    return q


@api.get("/quotes")
async def list_quotes(user: User = Depends(current_user)):
    docs = await db.quote_requests.find({"user_id": user.id, "project_id": await active_pid(user)}).sort("created_at", -1).to_list(200)
    return [quote_out(QuoteRequest.from_mongo(d)) for d in docs]


@api.post("/quotes")
async def create_quote(body: QuoteCreate, user: User = Depends(current_user)):
    if not body.title.strip() or not body.description.strip():
        raise HTTPException(400, "Title and job description are required")
    ids = [oid(c) for c in body.contact_ids]
    contacts = await db.contacts.find({"_id": {"$in": ids}, "user_id": user.id}).to_list(50)
    if not contacts:
        raise HTTPException(400, "Choose at least one tradesperson")
    q = QuoteRequest(user_id=user.id, project_id=await active_pid(user), title=body.title.strip(), description=body.description.strip(),
                     trade=body.trade, origin=body.origin_url,
                     quotes=[QuoteEntry(contact_id=str(c["_id"]), name=c["name"], role=c.get("role", ""), phone=c.get("phone", ""),
                                        email=c.get("email", "")) for c in contacts])
    q.id = str((await db.quote_requests.insert_one(q.to_mongo())).inserted_id)
    return quote_out(q)


@api.get("/quotes/{qid}")
async def get_quote(qid: str, user: User = Depends(current_user)):
    return quote_out(await load_quote(qid, user))


@api.put("/quotes/{qid}/entries/{eid}")
async def update_entry(qid: str, eid: str, body: EntryUpdate, user: User = Depends(current_user)):
    q = await load_quote(qid, user)
    e = next((x for x in q.quotes if x.id == eid), None)
    if not e:
        raise HTTPException(404, "Quote not found")
    upd = body.model_dump(exclude_unset=True)
    for k, v in upd.items():
        setattr(e, k, v)
    if body.amount is not None and e.status == "requested":
        e.status, e.responded_at = "received", now_iso()
    await db.quote_requests.update_one({"_id": ObjectId(q.id)}, {"$set": {"quotes": [x.model_dump() for x in q.quotes]}})
    return quote_out(q)


class AcceptIn(BaseModel):
    add_to_budget: bool = True


@api.post("/quotes/{qid}/entries/{eid}/accept")
async def accept_entry(qid: str, eid: str, body: AcceptIn, user: User = Depends(current_user)):
    q = await load_quote(qid, user)
    e = next((x for x in q.quotes if x.id == eid), None)
    if not e:
        raise HTTPException(404, "Quote not found")
    if e.amount is None:
        raise HTTPException(400, "This quote has no price yet")
    for x in q.quotes:
        x.status = "accepted" if x.id == eid else ("declined" if x.status in ("received", "accepted", "requested") else x.status)
    upd = {"quotes": [x.model_dump() for x in q.quotes]}
    if body.add_to_budget:
        if q.added_line_item_id:
            await db.line_items.delete_one({"_id": oid(q.added_line_item_id), "user_id": user.id})
        li = LineItem(user_id=user.id, project_id=q.project_id, category="Hard Cost", name=q.title, budgeted=e.amount,
                      actual=0, supplier=e.name, status="Quoted")
        upd["added_line_item_id"] = q.added_line_item_id = str((await db.line_items.insert_one(li.to_mongo())).inserted_id)
    await db.quote_requests.update_one({"_id": ObjectId(q.id)}, {"$set": upd})
    return quote_out(q)


@api.delete("/quotes/{qid}")
async def delete_quote(qid: str, user: User = Depends(current_user)):
    await db.stage_payments.delete_many({"quote_id": qid, "user_id": user.id})
    await db.quote_requests.delete_one({"_id": oid(qid), "user_id": user.id})
    return {"ok": True}


async def find_entry(token: str):
    doc = await db.quote_requests.find_one({"quotes.token": token})
    if not doc:
        return None, None
    q = QuoteRequest.from_mongo(doc)
    return q, next(x for x in q.quotes if x.token == token)


@api.get("/q/{token}", response_class=HTMLResponse)
async def public_quote_form(token: str):
    q, e = await find_entry(token)
    if not q:
        return page("Not found", "<div class='card'><h2>This quote link is no longer active</h2></div>")
    p = await db.projects.find_one({"_id": ObjectId(q.project_id)}) or {}
    closed = e.status in ("accepted", "declined")
    body = brand_block(await owner_branding(q.user_id), f"/api/q/{E(token)}/logo") + f"""<div class='hdr'><div class='brand'>MY BUILDER <b>APP</b> · QUOTE REQUEST</div><h1>{E(q.title)}</h1>
<div>For {E(e.name)} · {E(p.get('address', ''))}</div></div>
<div class='card'><h2>Job description</h2><div style='white-space:pre-wrap;line-height:1.5'>{E(q.description)}</div></div>"""
    if closed:
        body += f"<div class='card'><h2>This job has been {'awarded to you 🎉' if e.status == 'accepted' else 'awarded to another trade'}</h2><p>Thanks for quoting.</p></div>"
    else:
        body += f"""<form class='card' method='post'><h2>{'Update your quote' if e.amount is not None else 'Submit your quote'}</h2>
<label>Total price (£, inc. materials)</label><input name='amount' type='number' step='0.01' min='1' required value='{e.amount if e.amount is not None else ''}'/>
<label>Time to complete (working days)</label><input name='days' type='number' min='0' value='{e.days if e.days is not None else ''}'/>
<label>Notes (what's included, availability)</label><textarea name='notes' rows='4'>{E(e.notes)}</textarea>
<button type='submit'>Send quote</button></form>"""
    return page(f"Quote: {q.title}", body, ref="quote", by=q.user_id)


@api.get("/q/{token}/logo")
async def quote_logo(token: str):
    q, _ = await find_entry(token)
    if not q:
        raise HTTPException(404, "Not found")
    return await serve_logo(q.user_id)


@api.post("/q/{token}", response_class=HTMLResponse)
async def public_quote_submit(token: str, amount: float = Form(...), days: Optional[str] = Form(None), notes: str = Form("")):
    q, e = await find_entry(token)
    if not q:
        return page("Not found", "<div class='card'><h2>This quote link is no longer active</h2></div>")
    if e.status in ("accepted", "declined"):
        return page("Closed", "<div class='card'><h2>This job is already closed</h2></div>")
    if amount <= 0:
        return page("Invalid", "<div class='card'><h2>Please enter a valid price</h2></div>")
    e.amount, e.notes, e.status, e.responded_at = float(amount), notes.strip()[:2000], "received", now_iso()
    e.days = int(days) if days and days.strip().isdigit() else None
    await db.quote_requests.update_one({"_id": ObjectId(q.id)}, {"$set": {"quotes": [x.model_dump() for x in q.quotes]}})
    return page("Quote sent", f"<div class='card'><h2>Thanks {E(e.name)} — your quote of {money(e.amount, 2)} was sent</h2><p>The project owner will be in touch. You can reopen this link to update your quote.</p></div>", ref="quote", by=q.user_id)


# ---------------- Stage payments (against accepted quotes) ----------------
class StagePayment(BaseDocument):
    user_id: str
    project_id: str
    quote_id: str
    label: str
    amount: float
    due_date: Optional[str] = None
    status: Literal["due", "paid"] = "due"
    paid_at: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)


class StagePaymentIn(BaseModel):
    quote_id: str
    label: str
    amount: float
    due_date: Optional[str] = None


async def sync_line_item_actual(q: dict, user_id: str):
    if not q.get("added_line_item_id"):
        return
    paid = sum(p["amount"] for p in await db.stage_payments.find({"quote_id": str(q["_id"]), "status": "paid"}).to_list(500))
    await db.line_items.update_one({"_id": oid(q["added_line_item_id"]), "user_id": user_id},
                                   {"$set": {"actual": round(paid, 2), "status": "Paid" if paid else "Quoted"}})


@api.get("/stage-payments")
async def list_contracts(user: User = Depends(current_user)):
    pid = await active_pid(user)
    out = []
    async for q in db.quote_requests.find({"user_id": user.id, "project_id": pid}).sort("created_at", -1):
        acc = next((e for e in q["quotes"] if e["status"] == "accepted"), None)
        if not acc:
            continue
        pays = [StagePayment.from_mongo(d).out() for d in await db.stage_payments.find({"quote_id": str(q["_id"])}).sort("created_at", 1).to_list(200)]
        paid = sum(p["amount"] for p in pays if p["status"] == "paid")
        sched = sum(p["amount"] for p in pays)
        out.append({"quote_id": str(q["_id"]), "title": q["title"], "payee": acc["name"], "phone": acc.get("phone", ""),
                    "contract_amount": acc["amount"], "paid": round(paid, 2), "scheduled": round(sched, 2),
                    "remaining": round(acc["amount"] - paid, 2), "unscheduled": round(acc["amount"] - sched, 2), "payments": pays})
    return out


@api.post("/stage-payments")
async def add_stage_payment(body: StagePaymentIn, user: User = Depends(current_user)):
    q = await db.quote_requests.find_one({"_id": oid(body.quote_id), "user_id": user.id})
    acc = next((e for e in (q or {}).get("quotes", []) if e["status"] == "accepted"), None)
    if not acc:
        raise HTTPException(404, "Accepted quote not found")
    if body.amount <= 0 or not body.label.strip():
        raise HTTPException(400, "Enter a label and an amount above £0")
    sched = sum(p["amount"] for p in await db.stage_payments.find({"quote_id": body.quote_id}).to_list(500))
    if sched + body.amount > acc["amount"] + 0.009:
        raise HTTPException(400, f"This would exceed the agreed quote by {money(sched + body.amount - acc['amount'], 2)}. "
                                 f"Only {money(acc['amount'] - sched, 2)} is left to schedule.")
    sp = StagePayment(user_id=user.id, project_id=q["project_id"], quote_id=body.quote_id, label=body.label.strip(),
                      amount=round(body.amount, 2), due_date=body.due_date or None)
    sp.id = str((await db.stage_payments.insert_one(sp.to_mongo())).inserted_id)
    return sp.out()


class PayStatusIn(BaseModel):
    status: Literal["due", "paid"]


@api.put("/stage-payments/{sid}")
async def set_payment_status(sid: str, body: PayStatusIn, user: User = Depends(current_user)):
    d = await db.stage_payments.find_one({"_id": oid(sid), "user_id": user.id})
    if not d:
        raise HTTPException(404, "Payment not found")
    await db.stage_payments.update_one({"_id": d["_id"]}, {"$set": {"status": body.status, "paid_at": now_iso() if body.status == "paid" else None}})
    await sync_line_item_actual(await db.quote_requests.find_one({"_id": oid(d["quote_id"])}) or {}, user.id)
    return StagePayment.from_mongo(await db.stage_payments.find_one({"_id": d["_id"]})).out()


@api.delete("/stage-payments/{sid}")
async def delete_stage_payment(sid: str, user: User = Depends(current_user)):
    d = await db.stage_payments.find_one({"_id": oid(sid), "user_id": user.id})
    if d:
        await db.stage_payments.delete_one({"_id": d["_id"]})
        await sync_line_item_actual(await db.quote_requests.find_one({"_id": oid(d["quote_id"])}) or {}, user.id)
    return {"ok": True}


# ---------------- Snagging ----------------
class Snag(BaseDocument):
    user_id: str
    project_id: str
    room: str
    description: str
    priority: Literal["low", "medium", "high"] = "medium"
    status: Literal["open", "fixed"] = "open"
    storage_path: Optional[str] = None
    assignee: str = ""
    fixed_at: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)


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


@api.get("/snags")
async def list_snags(user: User = Depends(current_user)):
    docs = await db.snags.find({"user_id": user.id, "project_id": await active_pid(user)}).sort("created_at", -1).to_list(1000)
    return [Snag.from_mongo(d).out() for d in docs]


@api.post("/snags")
async def create_snag(body: SnagIn, user: User = Depends(current_user)):
    if not body.room.strip() or not body.description.strip():
        raise HTTPException(400, "Room and description are required")
    s = Snag(user_id=user.id, project_id=await active_pid(user), **{**body.model_dump(), "room": body.room.strip(), "description": body.description.strip()})
    s.id = str((await db.snags.insert_one(s.to_mongo())).inserted_id)
    return s.out()


@api.put("/snags/{sid}")
async def update_snag(sid: str, body: SnagUpdate, user: User = Depends(current_user)):
    upd = body.model_dump(exclude_unset=True)
    if "status" in upd:
        upd["fixed_at"] = now_iso() if upd["status"] == "fixed" else None
    r = await db.snags.update_one({"_id": oid(sid), "user_id": user.id}, {"$set": upd})
    if not r.matched_count:
        raise HTTPException(404, "Snag not found")
    return Snag.from_mongo(await db.snags.find_one({"_id": oid(sid)})).out()


@api.delete("/snags/{sid}")
async def delete_snag(sid: str, user: User = Depends(current_user)):
    await db.snags.delete_one({"_id": oid(sid), "user_id": user.id})
    return {"ok": True}


@api.get("/")
async def root():
    return {"message": "My Builder App API"}


app.include_router(api)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    # Migrate single-project data to multi-project: attach orphan docs to each user's first project
    async for u in db.users.find({}, {"_id": 1, "active_project_id": 1}):
        uid = str(u["_id"])
        first = await db.projects.find_one({"user_id": uid}, sort=[("_id", 1)])
        if not first:
            continue
        fpid = str(first["_id"])
        for coll in (db.line_items, db.contacts, db.receipts, db.media):
            await coll.update_many({"user_id": uid, "$or": [{"project_id": {"$exists": False}}, {"project_id": None}]}, {"$set": {"project_id": fpid}})
        if not u.get("active_project_id"):
            await db.users.update_one({"_id": u["_id"]}, {"$set": {"active_project_id": fpid}})
    async for pr in db.projects.find({}, {"_id": 1, "user_id": 1}):
        if not await db.milestones.find_one({"project_id": str(pr["_id"])}, {"_id": 1}):
            await seed_milestones(pr["user_id"], str(pr["_id"]))
    await db.quote_requests.create_index("quotes.token")
    try:
        init_storage()
    except Exception as e:
        logger.error(f"Storage init failed: {e}")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
