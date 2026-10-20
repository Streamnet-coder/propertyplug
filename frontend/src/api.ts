export const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL as string;

let token: string | null = null;
export const setApiToken = (t: string | null) => {
  token = t;
};
export const getApiToken = () => token;

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

type Opts = { method?: string; body?: unknown; form?: FormData };

export async function api<T = any>(path: string, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`${BACKEND_URL}/api${path}`, {
    method: opts.method ?? (opts.body !== undefined || opts.form ? "POST" : "GET"),
    headers,
    body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
  });
  const text = await res.text();
  let data: any = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    const d = data?.detail;
    throw new ApiError(typeof d === "string" ? d : Array.isArray(d) ? d[0]?.msg ?? "Request failed" : `Error ${res.status}`, res.status);
  }
  return data as T;
}

export const fileUrl = (path: string) => `${BACKEND_URL}/api/files/${path}?token=${encodeURIComponent(token ?? "")}`;
export const receiptUrl = (sessionId: string) => `${BACKEND_URL}/api/payments/receipt/${sessionId}?t=${encodeURIComponent(token ?? "")}`;
export type BillingItem = { id: string; date: string; description: string; amount: number; currency: string; status: "paid" | "due" | "failed"; receipt: "local" | "stripe"; url: string | null };

export const CURRENCIES = { GBP: "£", EUR: "€", USD: "$", CAD: "C$", AUD: "A$", NZD: "NZ$", ZAR: "R", AED: "AED ", NGN: "₦", INR: "₹" } as const;
export type CurrencyCode = keyof typeof CURRENCIES;
let currency: CurrencyCode = "GBP";
/** Active project's currency; set whenever the active project is loaded or switched. */
export const setCurrency = (c?: string | null) => { currency = (c && c in CURRENCIES ? c : "GBP") as CurrencyCode; };
export const sym = (c: CurrencyCode = currency) => CURRENCIES[c].trim();

export function gbp(n: number, decimals = 0, cur: CurrencyCode = currency) {
  const neg = n < 0;
  const fixed = Math.abs(n).toFixed(decimals);
  const [int, dec] = fixed.split(".");
  const withCommas = int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${neg ? "-" : ""}${CURRENCIES[cur]}${withCommas}${dec ? "." + dec : ""}`;
}

export type User = { id: string; name: string; email: string; plan: "basic" | "pro"; own_plan: "basic" | "pro"; paid_pro: boolean; trial_ends: string; active_project_id?: string | null;
  pro_tier: "monthly" | "yearly" | "lifetime" | null; pro_until: string | null; acting_as: { owner_id: string; owner_name: string; money?: boolean } | null;
  auto_renew: boolean; has_subscription: boolean; sub_status: string | null };
export type Category = "Hard Cost" | "Soft Cost" | "Contingency";
export type Project = {
  id: string;
  name: string;
  cover_path?: string | null;
  cover_history?: { path: string; at: string }[];
  address: string;
  target_type: string;
  finish_type: string;
  purchase_price: number;
  estimated_valuation: number;
  monthly_rent: number;
  refinance_ltv: number;
  refinance_rate: number;
  rent_yield: RentYield;
  budget: { hard: number; soft: number; contingency: number };
  spent: { hard: number; soft: number; contingency: number };
  total_budget: number;
  total_spent: number;
  line_item_count: number;
  receipt_count: number;
  milestones_total: number;
  milestones_done: number;
  current_stage: string | null;
  currency: CurrencyCode;
  property_type: "residential" | "land";
  purpose: "investment" | "personal";
  money_hidden?: boolean;
  deposit: number;
  mortgage_rate: number;
  mortgage_term: number;
  mortgage_type: "repayment" | "interest_only";
  remortgage_ltv: number;
  fixed_rate_end: string | null;
  remortgage_scenarios: { label: string; rate: number; fee: number }[];
  home_finance: HomeFinance;
  plot_size: number;
  plot_unit: "acres" | "hectares";
  planning_status: "none" | "applied" | "granted";
  intended_use: string;
  value_without_planning: number;
  value_with_planning: number;
  lat: number | null;
  lon: number | null;
  pin_manual: boolean;
};
export type PlanningApp = {
  id: string;
  authority: string;
  reference: string;
  description: string;
  submitted_date: string | null;
  validated_date: string | null;
  consultation_end: string | null;
  target_decision_date: string | null;
  decision: "pending" | "approved" | "refused" | "withdrawn";
  decision_date: string | null;
  notes: string;
  days_to_decision: number | null;
};
export type MapPin = Pick<Project, "id" | "name" | "address" | "lat" | "lon" | "pin_manual" | "property_type" | "currency" | "total_spent" | "total_budget" | "estimated_valuation" | "purchase_price"> & { active: boolean; country: string | null };
type PortfolioSums = { purchase_price: number; estimated_valuation: number; total_budget: number; total_spent: number };
export type Portfolio = {
  home_currency: CurrencyCode;
  rate_date: string;
  stale: boolean;
  projects: number;
  land_count: number;
  totals: PortfolioSums;
  by_currency: (PortfolioSums & { currency: CurrencyCode; projects: number; rate_to_home: number })[];
};
export type Milestone = { id: string; name: string; status: "todo" | "in_progress" | "done"; target_date?: string | null; notes: string; order: number; completed_at?: string | null };
export type QuoteEntry = {
  id: string;
  token: string;
  link: string;
  contact_id?: string | null;
  name: string;
  role: string;
  phone: string;
  email: string;
  status: "requested" | "received" | "accepted" | "declined";
  sent: boolean;
  amount?: number | null;
  days?: number | null;
  notes: string;
  responded_at?: string | null;
};
export type QuoteRequest = { id: string; title: string; description: string; trade: string; quotes: QuoteEntry[]; created_at: string; added_line_item_id?: string | null };
export type StagePayment = { id: string; quote_id: string; label: string; amount: number; due_date?: string | null; status: "due" | "paid"; paid_at?: string | null };
export type Contract = {
  quote_id: string;
  title: string;
  payee: string;
  phone: string;
  contract_amount: number;
  paid: number;
  scheduled: number;
  remaining: number;
  unscheduled: number;
  payments: StagePayment[];
};
export type Snag = { id: string; room: string; description: string; priority: "low" | "medium" | "high"; status: "open" | "fixed"; storage_path?: string | null; assignee: string; created_at: string; fix_photo_path?: string | null; fixed_by?: string | null; fix_note?: string; reported_by?: string;
  reporter_name?: string; reporter_email?: string; reporter_phone?: string; source?: string; fix_cost?: number | null; assigned_to?: { kind: "team" | "trade"; id: string; name: string; email: string } | null };
export type Referrals = { count: number; months_earned: number; trial_ends: string; recent: { name: string; source: string; date: string }[] };
export type VarianceAlert = "over" | "near" | null;
export type LineItem = { id: string; category: Category; name: string; budgeted: number; actual: number; supplier: string; status: string; linked_spend: number; spent: number; alert: VarianceAlert };
export type SpendTrend = { budget: number; points: { date: string; spent: number }[] };
export type ContactKind = "trade" | "subcontractor" | "stakeholder";
export type Contact = { id: string; kind: ContactKind; name: string; role: string; phone: string; email: string; status: string; schedule: string; cost: string };
export type Receipt = { id: string; title: string; amount: number; date: string; category: string; supplier: string; storage_path?: string | null };
export type MediaItem = { id: string; title: string; phase: "before" | "progress" | "after"; url?: string | null; storage_path?: string | null; date: string; milestone_id?: string | null };
export type Branding = { company_name: string; contact_name: string; phone: string; email: string; website: string; tagline: string; logo_path?: string | null };
export type Comparable = { address: string; beds: number; price: number; distance: string; date: string };
export type SoldSale = { price: number; date: string; type: string; postcode: string; address: string; new_build: boolean; tenure: string; lat: number; lon: number; distance_m: number };
export type SoldPrices = { postcode: string; lat: number; lon: number; radius_m: number; miles: number; years: number; since: string; postcodes_searched: number; truncated: boolean;
  sales: SoldSale[]; stats: { count: number; median: number; avg: number; min: number; max: number; by_type: Record<string, { count: number; median: number; avg: number }> }; source: string };
export type Estimate = { items: { name: string; spec?: string; category: string; low: number; high: number; supplier: string; visible?: boolean }[]; total_low: number; total_high: number; notes: string };
export type RentYield = { gross_yield: number; yield_on_cost: number; invested: number; refinance_amount: number; cash_left_in: number; monthly_mortgage: number; monthly_cashflow: number };
export type ShoppingItem = { id: string; line_item_id?: string | null; name: string; supplier: string; qty: string; est_cost: number; checked: boolean; actual_cost?: number | null; receipt_id?: string | null };
export type Digest = {
  week: number;
  week_start: string;
  week_end: string;
  spend: { total: number; receipts_total: number; receipts_count: number; payments_total: number; payments_count: number; top: { title: string; supplier: string; amount: number; date: string }[] };
  prev_spend: number;
  snags_fixed: { id: string; room: string; description: string; fixed_by?: string | null }[];
  snags_opened: number;
  snags_open_now: number;
  milestones_done: { id: string; name: string; completed_at: string }[];
  next_milestone: { name: string; target_date?: string | null; status: string } | null;
};
export type DigestSettings = { recipients: { name: string; email: string }[]; auto: boolean; last_sent_at: string | null; url: string | null };
export type Signature = { name: string; path: string; width: number; height: number; signed_at: string };
export type SnagSignoff = { assignee: string; snag_count: number; owner: Signature | null; trade: Signature | null; complete: boolean };
export type Message = { id: string; name: string; email: string; channel: string; kind: string; direction: "in" | "out"; status: string; summary: string; url?: string | null; created_at: string };
export type Stakeholder = { key: string; name: string; email: string; phone: string; role: string; source: string; contact_id?: string | null; count?: number; last_at?: string; last_summary?: string; last_direction?: "in" | "out" };

/** Record an outbound message in the stakeholder log (fire-and-forget). */
export const logMessage = (b: { name: string; email?: string; phone?: string; channel: "email" | "whatsapp" | "call" | "link" | "share"; kind: string; summary: string; url?: string }) =>
  api("/messages", { body: b }).catch(() => undefined);
export type EmailSettings = { company_email: string | null; verified: boolean; sender_name: string; company_name: string; account_email: string };
export type TradeRating = { id: string; assignee: string; stars: number; tags: string[]; comment: string; project_id: string; project_name: string; contact_id?: string | null; updated_at: string };
export type TrustedTrade = { name: string; avg: number; count: number; top_tags: string[]; last_comment: string; role: string; phone: string; email: string; contact_id?: string | null };
export const DOC_TYPES = ["Title deeds", "Survey", "Planning", "Building control", "Gas certificate", "EICR", "EPC", "Insurance", "Mortgage & finance", "Tenancy", "Invoice", "Warranty", "Drawings", "Other"] as const;
export type DocItem = { id: string; title: string; doc_type: string; filename: string; ext: string; size: number; content_type: string; notes: string; created_at: string; share_url: string | null; expires_on: string | null; expiry_status: "expired" | "soon" | "ok" | null; days_left: number | null };
export const fileSize = (n: number) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
export type DocFolder = { id: string; title: string; doc_count: number; created_at: string; url: string };
export type PortalMember = { id: string; name: string; email: string; role: string; company: string; password_set: boolean; is_lead: boolean; invited_by: string | null; expires_on: string | null; expired: boolean; doc_ids: string[]; digest: boolean; handle: string | null; last_login: string | null; invited_at: string | null; portal_url: string | null };
export const expiryLabel = (d: { expiry_status: string | null; days_left: number | null }) =>
  d.expiry_status === "expired" ? `Expired ${Math.abs(d.days_left ?? 0)} day${Math.abs(d.days_left ?? 0) === 1 ? "" : "s"} ago` : d.expiry_status === "soon" ? (d.days_left === 0 ? "Expires today" : `Expires in ${d.days_left} day${d.days_left === 1 ? "" : "s"}`) : null;
export type PortalActivity = { id: string; email: string; name: string; kind: "login" | "view" | "download" | "team_invite" | "team_remove" | "doc_request" | "doc_reminder"; doc_id: string | null; doc_title: string | null; doc_type: string | null; detail?: string | null; at: string };
export type PortalQuestion = { id: string; name: string; email: string; text: string; created_at: string; reply: string | null; replied_at: string | null };
export type RentStatus = "paid" | "partial" | "late" | "due";
export type RentMonth = { month: string; due_on: string; due: number; paid: number; paid_on: string | null; status: RentStatus; reminded_at: string | null };
export type Tenancy = { id: string; tenant_name: string; tenant_email: string; tenant_phone: string; rent: number; deposit: number; deposit_scheme: string; deposit_protected: boolean; start_date: string; end_date: string | null; rent_day: number; notes: string;
  status: "active" | "upcoming" | "ended"; schedule: RentMonth[]; arrears: number; late_count: number; days_to_end: number | null;
  receipts_auto: boolean; statements_auto: boolean; arrears_auto?: boolean; portal_url: string | null; shared_doc_ids: string[]; current_rent: number; rent_changes: { from_month: string; rent: number }[]; renewals: { at: string; end_date: string | null; new_rent: number | null; rent_from: string | null }[] };
export type PlanInstalment = { n: number; due_on: string; amount: number; status: "paid" | "missed" | "due" };
export type PaymentPlan = { id: string; tenancy_id: string; status: "active" | "broken" | "completed" | "cancelled"; amount: number; paid: number; remaining: number; instalment: number;
  frequency: "weekly" | "monthly"; start_date: string; months: string[]; on_track: boolean; behind: number; next: PlanInstalment | null; schedule: PlanInstalment[];
  payments: { amount: number; paid_on: string; at: string }[]; created_at: string };
export type ArrearsMonth = { month: string; due_on: string; due: number; paid: number; owed: number; days_late: number };
export type ArrearsTenancy = { tenancy_id: string; project_id: string; project_name: string; address: string; currency: CurrencyCode; tenant_name: string; tenant_email: string; tenant_phone: string;
  owed: number; owed_home: number; months: ArrearsMonth[]; oldest_days: number; arrears_auto: boolean; last_reminder_at: string | null; next_auto_on: string | null; can_manage: boolean; shared: boolean; plan: PaymentPlan | null };
export type ArrearsList = { home_currency: CurrencyCode; total: number; count: number; auto_on: number; tenancies: ArrearsTenancy[] };
export type BrrrDealInputs = { purchase: number; fees: number; refurb: number; valuation: number; ltv: number; rate: number; rent: number; costs: number; months: number; bridge_pct: number; bridge_rate: number; bridge_fee: number; holding: number };
export type BrrrDeal = { id: string; name: string; inputs: BrrrDealInputs; created_at: string; updated_at: string };
export type RentalExpense = { id: string; category: string; amount: number; date: string; description: string };
export type Rentals = { year: number; tenancies: Tenancy[]; expenses: RentalExpense[];
  summary: { rent_due: number; received: number; arrears: number; expenses: number; net: number; active_rent: number; by_category: Record<string, number>; monthly: { month: string; due: number; received: number; expenses: number; net: number }[] } };
export type CompareLink = { id: string; token: string; url: string; before_id: string; after_id: string; title: string; created_at: string };
export type RemortgageScenario = { label: string; rate: number; fee: number; monthly_payment: number; vs_current: number; two_year_cost: number; best_monthly: boolean; best_two_year: boolean };
export type HomeFinance = { fixed_rate_end: string | null; fixed_days_left: number | null; scenarios: RemortgageScenario[]; loan: number; ltv_now: number; ltv_after: number; monthly_payment: number; total_interest: number; equity_now: number; equity_after: number; value_added: number; net_value_added: number;
  remortgage: { max_loan: number; headroom: number; borrow_for_refurb: number; covers_refurb: boolean; shortfall: number; new_loan: number; new_payment: number; payment_increase: number; new_ltv: number; equity_after: number } };
export type RentRollRow = { id: string; name: string; address: string; currency: CurrencyCode; rate_to_home: number; shared: boolean; tenancies: number; active_tenancies: number; late_months: number;
  rent_due: number; received: number; arrears: number; expenses: number; net: number; active_rent: number; home: Record<"rent_due" | "received" | "arrears" | "expenses" | "net" | "active_rent", number>;
  tenants: { name: string; status: string; rent: number; arrears: number; end_date: string | null }[] };
export type RentRoll = { year: number; home_currency: CurrencyCode; rate_date: string; stale: boolean; properties: RentRollRow[];
  totals: Record<"rent_due" | "received" | "arrears" | "expenses" | "net" | "active_rent", number>; counts: { properties: number; tenancies: number; active: number; in_arrears: number } };
