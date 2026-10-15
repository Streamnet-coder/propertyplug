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

export function gbp(n: number, decimals = 0) {
  const neg = n < 0;
  const fixed = Math.abs(n).toFixed(decimals);
  const [int, dec] = fixed.split(".");
  const withCommas = int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${neg ? "-" : ""}£${withCommas}${dec ? "." + dec : ""}`;
}

export type User = { id: string; name: string; email: string; plan: "basic" | "pro"; paid_pro: boolean; trial_ends: string; active_project_id?: string | null };
export type Category = "Hard Cost" | "Soft Cost" | "Contingency";
export type Project = {
  id: string;
  name: string;
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
export type Snag = { id: string; room: string; description: string; priority: "low" | "medium" | "high"; status: "open" | "fixed"; storage_path?: string | null; assignee: string; created_at: string; fix_photo_path?: string | null; fixed_by?: string | null; fix_note?: string };
export type Referrals = { count: number; months_earned: number; trial_ends: string; recent: { name: string; source: string; date: string }[] };
export type VarianceAlert = "over" | "near" | null;
export type LineItem = { id: string; category: Category; name: string; budgeted: number; actual: number; supplier: string; status: string; linked_spend: number; spent: number; alert: VarianceAlert };
export type ContactKind = "trade" | "subcontractor" | "stakeholder";
export type Contact = { id: string; kind: ContactKind; name: string; role: string; phone: string; email: string; status: string; schedule: string; cost: string };
export type Receipt = { id: string; title: string; amount: number; date: string; category: string; supplier: string; storage_path?: string | null };
export type MediaItem = { id: string; title: string; phase: "before" | "progress" | "after"; url?: string | null; storage_path?: string | null; date: string; milestone_id?: string | null };
export type Branding = { company_name: string; contact_name: string; phone: string; email: string; website: string; tagline: string; logo_path?: string | null };
export type Comparable = { address: string; beds: number; price: number; distance: string; date: string };
export type Estimate = { items: { name: string; category: string; low: number; high: number; supplier: string }[]; total_low: number; total_high: number; notes: string };
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
export type DocItem = { id: string; title: string; doc_type: string; filename: string; ext: string; size: number; content_type: string; notes: string; created_at: string; share_url: string | null };
export const fileSize = (n: number) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
