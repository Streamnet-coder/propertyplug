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
import os, json, re, uuid, logging
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


class User(BaseDocument):
    name: str
    email: str
    password_hash: str
    plan: Literal["basic", "pro"] = "basic"
    paid_pro: bool = False
    trial_ends: str
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


class LineItem(BaseDocument):
    user_id: str
    category: Literal["Hard Cost", "Soft Cost", "Contingency"]
    name: str
    budgeted: float = 0
    actual: float = 0
    supplier: str = ""
    status: str = "Planned"
    created_at: str = Field(default_factory=now_iso)


class Contact(BaseDocument):
    user_id: str
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
    title: str
    amount: float
    date: str
    category: str = "Hard Cost"
    supplier: str = ""
    storage_path: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)


class Media(BaseDocument):
    user_id: str
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
    return {"id": u.id, "name": u.name, "email": u.email, "plan": u.plan, "paid_pro": u.paid_pro, "trial_ends": u.trial_ends}


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
    await db.projects.insert_one(p.to_mongo())
    items = [
        ("Hard Cost", "Kitchen Units & Worktop", 6500, 6200, "DIY Kitchens", "Purchased"),
        ("Hard Cost", "Bathroom Suite & Tiles", 3200, 3450, "B&Q", "Purchased"),
        ("Hard Cost", "Rewiring & Consumer Unit", 4500, 4500, "Toolstation", "In Progress"),
        ("Soft Cost", "Planning Permission & Building Regs", 1200, 1150, "Nottingham City Council", "Paid"),
        ("Soft Cost", "Architectural Drawings", 1800, 1800, "Local Surveyor", "Paid"),
        ("Contingency", "Damp proofing (unexpected)", 1500, 1200, "Wickes", "Paid"),
    ]
    await db.line_items.insert_many([LineItem(user_id=uid, category=c, name=n, budgeted=b, actual=a, supplier=s, status=st).to_mongo() for c, n, b, a, s, st in items])
    contacts = [
        Contact(user_id=uid, kind="trade", name="Dave Miller", role="Master Electrician", phone="+447700900077", email="dave@millerelectrical.co.uk", status="Assigned"),
        Contact(user_id=uid, kind="trade", name="Sajid Khan", role="Plumber & Heating Engineer", phone="+447700900123", email="sajid@nottsplumbing.co.uk", status="Assigned"),
        Contact(user_id=uid, kind="trade", name="Apex Builders Ltd", role="General Builders & Bricklayers", phone="+447700900888", email="quotes@apexbuilders.co.uk", status="Invited"),
        Contact(user_id=uid, kind="subcontractor", name="Dave Miller", role="Electrician", phone="+447700900077", email="dave@miller.co.uk", schedule="First fix complete, second fix starting Monday", status="Today, 10:45 AM"),
        Contact(user_id=uid, kind="subcontractor", name="Sajid Khan", role="Plumber", phone="+447700900123", email="sajid@plumbing.co.uk", schedule="Boiler installation & bathroom piping", status="Yesterday, 4:15 PM"),
        Contact(user_id=uid, kind="stakeholder", name="NatWest Buy-to-Let Mortgage", role="Financing", email="mortgages@natwest.co.uk", cost="£1,450 fee"),
        Contact(user_id=uid, kind="stakeholder", name="Belvoir Estate Agents Nottingham", role="Brokerage & Valuation", email="nottingham@belvoir.co.uk", cost="1.2% commission"),
        Contact(user_id=uid, kind="stakeholder", name="Browne Jacobson Solicitors", role="Legal & Conveyancing", email="conveyancing@brownejacobson.com", cost="£1,250 fixed"),
    ]
    await db.contacts.insert_many([c.to_mongo() for c in contacts])
    receipts = [
        Receipt(user_id=uid, title="B&Q Timber & Plasterboard", amount=480.50, date="2026-06-12", supplier="B&Q"),
        Receipt(user_id=uid, title="Toolstation Cable & Sockets", amount=215.20, date="2026-06-14", supplier="Toolstation"),
        Receipt(user_id=uid, title="Wren Kitchen Deposit", amount=1500.00, date="2026-06-18", supplier="Wren Kitchens"),
    ]
    await db.receipts.insert_many([r.to_mongo() for r in receipts])
    media = [
        Media(user_id=uid, title="Kitchen Strip-Out Before", phase="before", url="https://placehold.co/600x400/0f766e/ffffff.png?text=Kitchen+Before", date="2026-06-01"),
        Media(user_id=uid, title="New First Fix Electrics", phase="progress", url="https://placehold.co/600x400/06b6d4/ffffff.png?text=First+Fix+Electrics", date="2026-06-15"),
        Media(user_id=uid, title="Bathroom Plumbing Installed", phase="after", url="https://placehold.co/600x400/f97316/ffffff.png?text=Bathroom+Plumbing", date="2026-06-20"),
    ]
    await db.media.insert_many([m.to_mongo() for m in media])


@api.post("/auth/register")
async def register(body: RegisterIn):
    email = body.email.lower()
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    if await db.users.find_one({"email": email}):
        raise HTTPException(409, "Email already registered")
    u = User(name=body.name.strip() or "Builder", email=email,
             password_hash=bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode(),
             trial_ends=(datetime.now(timezone.utc) + timedelta(days=30)).isoformat())
    res = await db.users.insert_one(u.to_mongo())
    u.id = str(res.inserted_id)
    await seed_user_data(u.id)
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
async def get_project_doc(uid: str) -> Project:
    p = Project.from_mongo(await db.projects.find_one({"user_id": uid}))
    if not p:
        raise HTTPException(404, "Project not found")
    return p


@api.get("/project")
async def get_project(user: User = Depends(current_user)):
    p = await get_project_doc(user.id)
    items = await db.line_items.find({"user_id": user.id}).to_list(1000)
    receipts = await db.receipts.find({"user_id": user.id}).to_list(1000)
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
    out.update({"spent": spent, "total_budget": total_budget, "total_spent": round(total_spent, 2),
                "line_item_count": len(items), "receipt_count": len(receipts)})
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
    if upd:
        await db.projects.update_one({"user_id": user.id}, {"$set": upd})
    return await get_project(user)


@api.get("/project/comparables")
async def comparables(user: User = Depends(pro_user)):
    p = await get_project_doc(user.id)
    return [c.model_dump() for c in p.comparables]


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
    docs = await db.line_items.find({"user_id": user.id}).sort("created_at", -1).to_list(1000)
    return [LineItem.from_mongo(d).out() for d in docs]


@api.post("/line-items")
async def create_item(body: LineItemIn, user: User = Depends(current_user)):
    li = LineItem(user_id=user.id, **body.model_dump())
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
    docs = await db.contacts.find({"user_id": user.id, "kind": kind}).sort("created_at", 1).to_list(500)
    return [Contact.from_mongo(d).out() for d in docs]


@api.post("/contacts")
async def create_contact(body: ContactIn, user: User = Depends(current_user)):
    if body.kind != "trade" and user.plan != "pro":
        raise HTTPException(403, "Pro plan required")
    c = Contact(user_id=user.id, **body.model_dump())
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
    docs = await db.receipts.find({"user_id": user.id}).sort("date", -1).to_list(1000)
    return [Receipt.from_mongo(d).out() for d in docs]


@api.post("/receipts")
async def create_receipt(body: ReceiptIn, user: User = Depends(current_user)):
    r = Receipt(user_id=user.id, **body.model_dump())
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


@api.get("/media")
async def list_media(user: User = Depends(current_user)):
    docs = await db.media.find({"user_id": user.id}).sort("created_at", -1).to_list(1000)
    return [Media.from_mongo(d).out() for d in docs]


@api.post("/media")
async def create_media(body: MediaIn, user: User = Depends(current_user)):
    m = Media(user_id=user.id, title=body.title, phase=body.phase, storage_path=body.storage_path, url=body.url,
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


@api.get("/")
async def root():
    return {"message": "My Builder App API"}


app.include_router(api)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    try:
        init_storage()
    except Exception as e:
        logger.error(f"Storage init failed: {e}")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
