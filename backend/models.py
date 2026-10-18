from pydantic import BaseModel, Field
from typing import Optional, List, Literal
import uuid, secrets
from core import now_iso, BaseDocument


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
    pro_tier: Optional[Literal["monthly", "yearly", "lifetime"]] = None
    pro_until: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    sub_status: Optional[str] = None
    cancel_at_period_end: bool = False
    acting_owner_id: Optional[str] = None  # set while a co-owner has one of this owner's projects open
    real_id: Optional[str] = Field(None, exclude=True)  # runtime only: the co-owner actually signed in
    real_name: Optional[str] = Field(None, exclude=True)
    no_money: bool = Field(False, exclude=True)  # runtime only: shared access without money (tasks-only)
    created_at: str = Field(default_factory=now_iso)


Currency = Literal["GBP", "EUR", "USD", "CAD", "AUD", "NZD", "ZAR", "AED", "NGN", "INR"]


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
    refinance_ltv: float = 75
    refinance_rate: float = 5.5
    budget: Budget = Budget()
    cover_path: Optional[str] = None  # preferred project photo (shown on project list / home)
    cover_history: List[dict] = []  # every photo ever set as cover: {path, at} -> before & now timeline
    currency: Currency = "GBP"
    property_type: Literal["residential", "land"] = "residential"
    purpose: Literal["investment", "personal"] = "investment"
    deposit: float = 0
    mortgage_rate: float = 4.5
    mortgage_term: int = 25
    mortgage_type: Literal["repayment", "interest_only"] = "repayment"
    remortgage_ltv: float = 85
    fixed_rate_end: Optional[str] = None
    remortgage_scenarios: List[dict] = []
    plot_size: float = 0
    plot_unit: Literal["acres", "hectares"] = "acres"
    planning_status: Literal["none", "applied", "granted"] = "none"
    intended_use: str = ""
    value_without_planning: float = 0
    value_with_planning: float = 0
    lat: Optional[float] = None
    lon: Optional[float] = None
    pin_manual: bool = False
    geocoded_for: Optional[str] = None
    comparables: List[Comparable] = []
    share_token: Optional[str] = None
    share_origin: Optional[str] = None
    digest_token: Optional[str] = None
    digest_origin: Optional[str] = None
    digest_recipients: List[dict] = []
    digest_auto: bool = False
    digest_last_sent_week: Optional[str] = None
    digest_last_sent_at: Optional[str] = None


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
    shopping_item_id: Optional[str] = None
    line_item_id: Optional[str] = None
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


class Milestone(BaseDocument):
    user_id: str
    project_id: str
    name: str
    status: Literal["todo", "in_progress", "done"] = "todo"
    target_date: Optional[str] = None
    notes: str = ""
    order: int = 0
    completed_at: Optional[str] = None


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
    fix_photo_path: Optional[str] = None
    fixed_by: Optional[str] = None
    fix_note: str = ""
    reported_by: str = ""
    tenancy_id: Optional[str] = None
    tenant_notified_at: Optional[str] = None
    reporter_name: str = ""
    reporter_email: str = ""
    reporter_phone: str = ""
    source: str = ""
    assigned_to: Optional[dict] = None
    job_token: Optional[str] = None
    fix_cost: Optional[float] = None
    created_at: str = Field(default_factory=now_iso)
