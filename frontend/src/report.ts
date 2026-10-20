import * as Print from "expo-print";
import * as Sharing from "expo-sharing";
import { Platform } from "react-native";

import { api, Branding, Comparable, fileUrl, FloorAreas, gbp, LineItem, MediaItem, Milestone, Project, Receipt, Rentals, Signature, Snag, SnagSignoff, SoldPrices } from "@/src/api";
import { colors } from "@/src/theme";
import type { Split } from "@/src/components/ownership-split-card";

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);

async function toDataUri(url: string): Promise<string | null> {
  try {
    const blob = await (await fetch(url)).blob();
    return await new Promise((resolve) => {
      const r = new FileReader();
      r.onloadend = () => resolve(typeof r.result === "string" ? r.result : null);
      r.onerror = () => resolve(null);
      r.readAsDataURL(blob);
    });
  } catch {
    return null;
  }
}

const CSS = `*{box-sizing:border-box} body{font-family:-apple-system,Helvetica,Arial,sans-serif;color:${colors.onSurface};margin:0;padding:28px;font-size:12px}
.hdr{background:${colors.brand};color:${colors.onBrand};padding:22px;border-radius:14px}
.bb{display:flex;gap:14px;align-items:center;border:1px solid ${colors.border};border-radius:14px;padding:14px;margin-bottom:12px}
.bb img{width:56px;height:56px;object-fit:contain} .bc{font-size:16px;font-weight:800} .bd{font-size:11px;color:${colors.muted};margin-top:2px}
.hdr .brand{font-size:11px;letter-spacing:1.5px;font-weight:700;opacity:.85} .hdr .brand b{color:${colors.brandPrimary}}
.hdr h1{margin:8px 0 4px;font-size:24px} .hdr p{margin:0;opacity:.9}
.kpis{display:flex;gap:10px;margin:18px 0} .kpi{flex:1;border:1px solid ${colors.border};border-radius:10px;padding:12px}
.kpi span{color:${colors.muted};font-size:10px;text-transform:uppercase;letter-spacing:.6px} .kpi div{font-size:17px;font-weight:800;margin-top:4px}
h2{font-size:15px;margin:22px 0 8px;color:${colors.brand}} h3{font-size:13px;margin:14px 0 6px}
table{width:100%;border-collapse:collapse} th,td{text-align:left;padding:7px 8px;border-bottom:1px solid ${colors.divider}}
th{background:${colors.surfaceSecondary};font-size:10px;text-transform:uppercase;color:${colors.muted}} td.n,th.n{text-align:right}
.over{color:${colors.error};font-weight:700} .under{color:${colors.success};font-weight:700}
.bar{height:8px;background:${colors.surfaceTertiary};border-radius:4px;overflow:hidden;margin-top:6px} .bar i{display:block;height:8px;background:${colors.brandPrimary}}
.grid{display:flex;flex-wrap:wrap;gap:10px} figure{margin:0;width:31%;page-break-inside:avoid} figure img{width:100%;height:120px;object-fit:cover;border-radius:8px}
figcaption{font-size:10px;color:${colors.muted};margin-top:4px}
.foot{margin-top:28px;color:${colors.muted};font-size:10px;text-align:center;border-top:1px solid ${colors.border};padding-top:10px}
`;

function buildHtml(
  p: Project,
  items: LineItem[],
  receipts: Receipt[],
  photos: { m: MediaItem; src: string | null }[],
  milestones: Milestone[],
  brand: { b: Branding; logo: string | null },
  split: Split | null = null,
) {
  const stageName = Object.fromEntries(milestones.map((m) => [m.id, m.name]));
  const { b, logo } = brand;
  const contacts = [b.contact_name, b.phone, b.email, b.website].filter(Boolean).map((x) => esc(x)).join(" · ");
  const brandHtml =
    b.company_name || logo
      ? `<div class="bb">${logo ? `<img src="${logo}"/>` : ""}<div><div class="bc">${esc(b.company_name)}</div>${b.tagline ? `<div class="bd">${esc(b.tagline)}</div>` : ""}<div class="bd">${contacts}</div></div></div>`
      : "";
  const msHtml = milestones.length
    ? `<h2>Milestones (${milestones.filter((m) => m.status === "done").length}/${milestones.length} complete)</h2><table>${milestones
        .map(
          (m) =>
            `<tr><td>${esc(m.name)}</td><td class="n ${m.status === "done" ? "under" : ""}">${m.status === "done" ? "Done" : m.status === "in_progress" ? "In progress" : m.target_date ?? "To do"}</td></tr>`,
        )
        .join("")}</table>`
    : "";
  const remaining = p.total_budget - p.total_spent;
  const pct = p.total_budget > 0 ? Math.round((p.total_spent / p.total_budget) * 100) : 0;
  const receiptsTotal = receipts.reduce((a, r) => a + r.amount, 0);
  const cats = [
    ["Hard costs", p.budget.hard, p.spent.hard],
    ["Soft costs", p.budget.soft, p.spent.soft],
    ["Contingency", p.budget.contingency, p.spent.contingency],
  ] as const;
  const phases = [
    ["before", "Before"],
    ["progress", "In progress"],
    ["after", "After"],
  ] as const;
  const photoSection = phases
    .map(([k, label]) => {
      const list = photos.filter((x) => x.m.phase === k && x.src);
      if (!list.length) return "";
      return `<h3>${label}</h3><div class="grid">${list
        .map((x) => `<figure><img src="${x.src}" /><figcaption>${x.m.milestone_id && stageName[x.m.milestone_id] ? `<b>${esc(stageName[x.m.milestone_id])}</b> · ` : ""}${esc(x.m.title)} · ${x.m.date}</figcaption></figure>`)
        .join("")}</div>`;
    })
    .join("");

  return `${brandHtml}
<div class="hdr"><div class="brand"><i>Property<b>Plug</b></i> · PROGRESS REPORT</div><h1>${esc(p.name)}</h1><p>${esc(p.address)}</p>
<p style="margin-top:6px;font-size:11px">${esc(p.target_type)} · ${esc(p.finish_type)} · ${new Date().toLocaleDateString("en-GB")}</p></div>
<div class="kpis">
<div class="kpi"><span>Purchase</span><div>${gbp(p.purchase_price)}</div></div>
<div class="kpi"><span>Est. valuation</span><div>${gbp(p.estimated_valuation)}</div></div>
<div class="kpi"><span>Budget</span><div>${gbp(p.total_budget)}</div></div>
<div class="kpi"><span>Spent</span><div>${gbp(p.total_spent)}</div></div>
</div>
<div><b>${pct}% of budget used</b> · ${remaining >= 0 ? `${gbp(remaining)} remaining` : `<span class="over">${gbp(-remaining)} over budget</span>`}<div class="bar"><i style="width:${Math.min(100, pct)}%"></i></div></div>
${msHtml}
${splitHtml(split)}
<h2>Budget breakdown</h2>
<table><tr><th>Category</th><th class="n">Budget</th><th class="n">Spent</th><th class="n">Variance</th></tr>
${cats.map(([l, b, s]) => `<tr><td>${l}</td><td class="n">${gbp(b)}</td><td class="n">${gbp(s)}</td><td class="n ${b - s < 0 ? "over" : "under"}">${gbp(b - s)}</td></tr>`).join("")}
</table>
<h2>Line items (${items.length})</h2>
<table><tr><th>Item</th><th>Category</th><th>Supplier</th><th>Status</th><th class="n">Budget</th><th class="n">Actual</th></tr>
${items.map((i) => `<tr><td>${esc(i.name)}</td><td>${i.category}</td><td>${esc(i.supplier)}</td><td>${esc(i.status)}</td><td class="n">${gbp(i.budgeted)}</td><td class="n ${i.actual > i.budgeted ? "over" : ""}">${gbp(i.actual)}</td></tr>`).join("")}
</table>
<h2>Receipts (${receipts.length}) · ${gbp(receiptsTotal, 2)}</h2>
<table><tr><th>Date</th><th>Description</th><th>Supplier</th><th class="n">Amount</th></tr>
${receipts.map((r) => `<tr><td>${r.date}</td><td>${esc(r.title)}</td><td>${esc(r.supplier)}</td><td class="n">${gbp(r.amount, 2)}</td></tr>`).join("")}
</table>
${photoSection ? `<h2>Before &amp; after photos</h2>${photoSection}` : ""}
`;
}

export async function shareProgressReport() {
  const p = await api<Project>("/project");
  await printPdf(doc(await progressBody()), `${p.name} progress report`);
}

async function progressBody() {
  const [p, items, receipts, media, milestones] = await Promise.all([
    api<Project>("/project"),
    api<LineItem[]>("/line-items"),
    api<Receipt[]>("/receipts"),
    api<MediaItem[]>("/media"),
    api<Milestone[]>("/milestones"),
  ]);
  const b = await api<Branding>("/branding");
  const split = await api<Split>("/project/split").catch(() => null);
  const logo = b.logo_path ? await toDataUri(fileUrl(b.logo_path)) : null;
  const photos = await Promise.all(
    media.slice(0, 12).map(async (m) => {
      const url = m.storage_path ? fileUrl(m.storage_path) : m.url;
      return { m, src: url ? await toDataUri(url) : null };
    }),
  );
  return buildHtml(p, items, receipts, photos, milestones, { b, logo }, split);
}

function splitHtml(split: Split | null) {
  if (!split || !split.has_split) return "";
  const prof = split.figures.profit !== null;
  return `<h2>Ownership split</h2>
<table><tr><th>Owner</th><th class="n">Share</th>${prof ? `<th class="n">Profit</th>` : ""}<th class="n">Rent / mo</th><th class="n">Cashflow / mo</th><th class="n">Cashflow / yr</th></tr>
${split.rows.map((r) => `<tr><td>${esc(r.name)}</td><td class="n">${r.pct}%</td>${prof ? `<td class="n">${gbp(r.profit ?? 0)}</td>` : ""}<td class="n">${gbp(r.monthly_rent)}</td><td class="n ${r.monthly_cashflow < 0 ? "over" : ""}">${gbp(r.monthly_cashflow)}</td><td class="n ${r.annual_cashflow < 0 ? "over" : ""}">${gbp(r.annual_cashflow)}</td></tr>`).join("")}
</table>
<p style="font-size:11px;color:#64748b">${prof ? `Profit ${gbp(split.figures.profit!)} = valuation minus purchase and budget. ` : ""}Cashflow = rent minus mortgage.</p>`;
}

export async function printPdf(html: string, title: string) {
  if (Platform.OS === "web") {
    await Print.printAsync({ html });
    return;
  }
  const { uri } = await Print.printToFileAsync({ html });
  if (await Sharing.isAvailableAsync()) {
    await Sharing.shareAsync(uri, { mimeType: "application/pdf", UTI: "com.adobe.pdf", dialogTitle: title });
  }
}

async function brandHeader(kind: string, p: Project) {
  const b = await api<Branding>("/branding");
  const logo = b.logo_path ? await toDataUri(fileUrl(b.logo_path)) : null;
  const contacts = [b.contact_name, b.phone, b.email, b.website].filter(Boolean).map((x) => esc(x)).join(" · ");
  const bb = b.company_name || logo
    ? `<div class="bb">${logo ? `<img src="${logo}"/>` : ""}<div><div class="bc">${esc(b.company_name)}</div>${b.tagline ? `<div class="bd">${esc(b.tagline)}</div>` : ""}<div class="bd">${contacts}</div></div></div>`
    : "";
  return `${bb}<div class="hdr"><div class="brand"><i>Property<b>Plug</b></i> · ${kind}</div><h1>${esc(p.name)}</h1><p>${esc(p.address)}</p>
<p style="margin-top:6px;font-size:11px">${new Date().toLocaleDateString("en-GB")}</p></div>`;
}

export async function shareCoownerStatement(d: { project_name: string; address: string; owner_name: string; label: string; whole: { rent_received: number; expenses: number; net: number }; mine: { pct: number; rent_received: number; expenses: number; net: number; profit: number | null; contribution: number } }) {
  const m = d.mine;
  const row = (k: string, v: string, b = false) => `<tr><td>${b ? `<b>${k}</b>` : k}</td><td class="n">${b ? `<b>${v}</b>` : v}</td></tr>`;
  const body = `<div class="hdr"><div class="brand"><i>Property<b>Plug</b></i> · CO-OWNER STATEMENT</div><h1>${esc(d.project_name)}</h1><p>${esc(d.address)}</p>
<p style="margin-top:6px;font-size:11px">Tax year ${esc(d.label)} · owner ${esc(d.owner_name)}</p></div>
<h2>Your share (${m.pct}%)</h2><table>
${row("Rent received", gbp(m.rent_received, 2))}${row("Property expenses", gbp(m.expenses, 2))}${row("Net income", gbp(m.net, 2), true)}
${m.profit !== null ? row("Share of estimated profit", gbp(m.profit, 2)) : ""}${m.contribution ? row("Capital contribution", gbp(m.contribution, 2)) : ""}
</table>
<h2>Whole property</h2><table>${row("Rent received", gbp(d.whole.rent_received, 2))}${row("Property expenses", gbp(d.whole.expenses, 2))}${row("Net income", gbp(d.whole.net, 2), true)}</table>
<p style="font-size:11px;color:#64748b">Grouped by month (April to March), at current ownership shares. Profit is an estimate (valuation minus purchase and budget). Please check with your accountant before filing.</p>`;
  await printPdf(doc(body), `${d.project_name} statement ${d.label}`);
}

export async function shareRepairHistory(h: { repeats?: { room: string; count: number; open: number; keywords: string[]; last: string; cost: number }[]; items: { room: string; description: string; priority: string; status: string; source: string; reported_by: string; assignee: string; fixed_by: string; created_at: string; fixed_at: string | null; days: number; fix_cost: number | null }[]; totals: { count: number; open: number; fixed: number; avg_days_to_fix: number | null; total_cost: number | null } }, name: string, money: boolean) {
  const p = await api<Project>("/project");
  const days = (d: number) => (d < 1 ? "&lt;1" : String(Math.round(d)));
  const t = h.totals;
  const body = `${await brandHeader("REPAIR HISTORY", p)}
<div class="kpis">
<div class="kpi"><span>Repairs</span><div>${t.count}</div></div>
<div class="kpi"><span>Open</span><div>${t.open}</div></div>
<div class="kpi"><span>Avg days to fix</span><div>${t.avg_days_to_fix === null ? "–" : days(t.avg_days_to_fix)}</div></div>
${money && t.total_cost !== null ? `<div class="kpi"><span>Spent</span><div>${gbp(t.total_cost, 2)}</div></div>` : ""}
</div>
${h.repeats?.length ? `<h2>Keeps coming back</h2><table><tr><th>Room</th><th class="n">Repairs</th><th class="n">Open</th><th>Common words</th><th>Last</th>${money ? `<th class="n">Spent</th>` : ""}</tr>${h.repeats.map((r) => `<tr><td><b>${esc(r.room)}</b></td><td class="n">${r.count}</td><td class="n">${r.open}</td><td>${esc(r.keywords.join(", "))}</td><td>${r.last}</td>${money ? `<td class="n">${gbp(r.cost, 2)}</td>` : ""}</tr>`).join("")}</table>` : ""}
<h2>All repairs</h2>
<table><tr><th>Reported</th><th>Issue</th><th>Reported by</th><th>Fixed by</th><th>Status</th><th class="n">Days</th>${money ? `<th class="n">Cost</th>` : ""}</tr>
${h.items.map((i) => `<tr><td>${i.created_at.slice(0, 10)}</td><td><b>${esc(i.room)}</b> · ${esc(i.description)}</td><td>${esc(i.reported_by.replace("Tenant: ", "Tenant "))}</td><td>${esc(i.fixed_by || i.assignee)}</td><td class="${i.status === "fixed" ? "under" : "warn"}">${i.status === "fixed" ? `Fixed ${i.fixed_at?.slice(0, 10) ?? ""}` : "Open"}</td><td class="n">${days(i.days)}</td>${money ? `<td class="n">${i.fix_cost ? gbp(i.fix_cost, 2) : "–"}</td>` : ""}</tr>`).join("")}
</table>`;
  await printPdf(doc(body), `${name} repair history`);
}

const doc = (body: string) =>
  `<!DOCTYPE html><html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/><style>${CSS}
.warn{color:${colors.brandPrimary};font-weight:700} .pill{display:inline-block;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700}
.alerts{border:1px solid ${colors.border};border-radius:10px;padding:12px;margin-top:14px}</style></head><body>${body}
<div class="foot">Generated with PropertyPlug · ${new Date().toLocaleString("en-GB")} · Figures are owner-reported</div></body></html>`;

const kpis = (rows: [string, string][]) => `<div class="kpis">${rows.map(([l, v]) => `<div class="kpi"><span>${l}</span><div>${v}</div></div>`).join("")}</div>`;

export async function shareBudgetPdf() {
  const p = await api<Project>("/project");
  await printPdf(doc(await budgetBody()), `${p.name} budget estimate`);
}

async function budgetBody() {
  const [p, items] = await Promise.all([api<Project>("/project"), api<LineItem[]>("/line-items")]);
  const cats = ["Hard Cost", "Soft Cost", "Contingency"] as const;
  const key = { "Hard Cost": "hard", "Soft Cost": "soft", Contingency: "contingency" } as const;
  const flagged = items.filter((i) => i.alert);
  const alerts = flagged.length
    ? `<div class="alerts"><b>Variance alerts</b><table>${flagged.map((i) => `<tr><td>${esc(i.name)}</td><td class="n ${i.alert === "over" ? "over" : "warn"}">${i.alert === "over" ? `Over by ${gbp(i.spent - i.budgeted)}` : `${Math.round((i.spent / i.budgeted) * 100)}% used`}</td></tr>`).join("")}</table></div>`
    : "";
  const sections = cats
    .map((c) => {
      const list = items.filter((i) => i.category === c);
      const b = list.reduce((a, i) => a + i.budgeted, 0);
      const sp = list.reduce((a, i) => a + i.spent, 0);
      return `<h2>${c} · allowance ${gbp(p.budget[key[c]])}</h2><table><tr><th>Item</th><th>Supplier</th><th>Status</th><th class="n">Estimate</th><th class="n">Spent</th><th class="n">Variance</th></tr>
${list.map((i) => `<tr><td>${esc(i.name)}</td><td>${esc(i.supplier)}</td><td>${esc(i.status)}</td><td class="n">${gbp(i.budgeted)}</td><td class="n">${gbp(i.spent)}</td><td class="n ${i.alert === "over" ? "over" : i.alert === "near" ? "warn" : "under"}">${gbp(i.budgeted - i.spent)}</td></tr>`).join("") || `<tr><td colspan="6">No items</td></tr>`}
<tr><th>Total</th><th></th><th></th><th class="n">${gbp(b)}</th><th class="n">${gbp(sp)}</th><th class="n">${gbp(b - sp)}</th></tr></table>`;
    })
    .join("");
  const est = items.reduce((a, i) => a + i.budgeted, 0);
  return `${await brandHeader("BUDGET ESTIMATE", p)}
${kpis([["Total budget", gbp(p.total_budget)], ["Itemised estimate", gbp(est)], ["Spent to date", gbp(p.total_spent)], ["Remaining", gbp(p.total_budget - p.total_spent)]])}
${alerts}${sections}`;
}

export async function shareSnagPdf() {
  const [p, snags, signoffs] = await Promise.all([api<Project>("/project"), api<Snag[]>("/snags"), api<SnagSignoff[]>("/snag-signoffs")]);
  const photos = await Promise.all(snags.map(async (x) => {
    const path = x.fix_photo_path || x.storage_path;
    return path ? await toDataUri(fileUrl(path)) : null;
  }));
  const open = snags.filter((x) => x.status === "open").length;
  const rooms = Array.from(new Set(snags.map((x) => x.room)));
  const rows = rooms
    .map((r) => `<h2>${esc(r)}</h2><table><tr><th>Defect</th><th>Priority</th><th>Assigned</th><th>Status</th><th>Photo</th></tr>${snags
      .map((x, i) => [x, i] as const)
      .filter(([x]) => x.room === r)
      .map(([x, i]) => `<tr><td>${esc(x.description)}${x.fix_note ? `<div class="bd">${esc(x.fix_note)}</div>` : ""}</td><td>${x.priority}</td><td>${esc(x.assignee || "-")}</td><td class="${x.status === "fixed" ? "under" : "over"}">${x.status === "fixed" ? `Fixed${x.fixed_by ? ` by ${esc(x.fixed_by)}` : ""}` : "Open"}</td><td>${photos[i] ? `<img src="${photos[i]}" style="width:70px;height:52px;object-fit:cover;border-radius:6px"/>` : ""}</td></tr>`)
      .join("")}</table>`)
    .join("");
  const trades = Array.from(new Set(snags.map((x) => x.assignee.trim()).filter(Boolean)));
  const soFor = (n: string) => signoffs.find((x) => x.assignee.toLowerCase() === n.toLowerCase());
  const allSigned = !open && trades.length > 0 && trades.every((n) => soFor(n)?.complete);
  const svg = (g: Signature) => `<svg viewBox="0 0 ${g.width} ${g.height}" style="height:54px;max-width:100%" xmlns="http://www.w3.org/2000/svg"><path d="${esc(g.path)}" fill="none" stroke="#0f172a" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  const cell = (g: Signature | null | undefined, label: string) =>
    g ? `<td style="width:50%">${svg(g)}<div><b>${esc(g.name)}</b> · ${label}</div><div class="bd">Signed ${new Date(g.signed_at).toLocaleString("en-GB")}</div></td>` : `<td style="width:50%" class="bd">${label}: not signed</td>`;
  const signSection = trades.length
    ? `<h2>Sign-off</h2><table>${trades.map((n) => { const so = soFor(n); return `<tr><td colspan="2"><b>${esc(n)}</b> · ${so?.complete ? `<span class="under">Signed off · ${so.snag_count} snags</span>` : "<span class=\"warn\">Awaiting sign-off</span>"}</td></tr><tr>${cell(so?.trade, `Trade (${esc(n)})`)}${cell(so?.owner, "Project owner")}</tr>`; }).join("")}</table>`
    : "";
  const html = doc(`${await brandHeader(allSigned ? "SIGNED-OFF SNAGGING REPORT" : "SNAGGING REPORT", p)}
${kpis([["Total snags", String(snags.length)], ["Open", String(open)], ["Fixed", String(snags.length - open)], [allSigned ? "Status" : "Rooms", allSigned ? "Signed off" : String(rooms.length)]])}
${rows || "<p>No snags logged.</p>"}${signSection}`);
  await printPdf(html, `${p.name} snagging report`);
}

type BrrrBase = { purchase: number; fees: number; refurb: number; valuation: number; ltv: number; rate: number; rent: number; costs: number };
/** Optional bridging/timing: months to refinance, bridging loan as % of purchase, bridging interest % per month, arrangement fee %, holding costs per month. */
type BrrrBridge = { months?: number; bridge_pct?: number; bridge_rate?: number; bridge_fee?: number; holding?: number };
export type BrrrFigures = BrrrBase & BrrrBridge & { bridgeLoan: number; financeCost: number; holdingTotal: number; cashNeeded: number;
  invested: number; refi: number; leftIn: number; mortgage: number; cashflow: number; roi: number; yieldPct: number; equity: number };

export async function shareBrrrPdf(f: BrrrFigures, comps: Comparable[]) {
  const p = await api<Project>("/project");
  await printPdf(doc(await brrrBody(p, f, comps)), `${p.name} BRRR analysis`);
}

async function brrrBody(p: Project, f: BrrrFigures, comps: Comparable[]) {
  const row = (l: string, v: string) => `<tr><td>${l}</td><td class="n">${v}</td></tr>`;
  const avg = comps.length ? comps.reduce((a, c) => a + c.price, 0) / comps.length : 0;
  return `${await brandHeader("BRRR ANALYSIS", p)}
${kpis([["Money left in", f.leftIn <= 0 ? `${gbp(-f.leftIn)} out` : gbp(f.leftIn)], ["Cash-on-cash ROI", Number.isFinite(f.roi) ? `${f.roi.toFixed(1)}%` : "Infinite"], ["Cashflow / mo", gbp(f.cashflow)], ["Gross yield", `${f.yieldPct.toFixed(1)}%`]])}
<h2>Buy &amp; refurbish</h2><table>${row("Purchase price", gbp(f.purchase))}${row("Fees &amp; SDLT", gbp(f.fees))}${row("Refurb budget", gbp(f.refurb))}${f.financeCost ? row(`Bridging (${gbp(f.bridgeLoan)} over ${f.months} mo)`, gbp(f.financeCost)) : ""}${f.holdingTotal ? row("Holding costs until refinance", gbp(f.holdingTotal)) : ""}${row("<b>Total invested</b>", `<b>${gbp(f.invested)}</b>`)}</table>
<h2>Refinance</h2><table>${row("End valuation (GDV)", gbp(f.valuation))}${row(`Refinance at ${f.ltv}% LTV`, gbp(f.refi))}${row("Equity retained", gbp(f.equity))}${row(`Mortgage (${f.rate}% interest-only)`, `${gbp(f.mortgage)}/mo`)}</table>
<h2>Rent</h2><table>${row("Monthly rent", gbp(f.rent))}${row("Monthly costs", gbp(f.costs))}${row("<b>Monthly cashflow</b>", `<b class="${f.cashflow < 0 ? "over" : "under"}">${gbp(f.cashflow)}</b>`)}${row("Annual cashflow", gbp(f.cashflow * 12))}</table>
${comps.length ? `<h2>1/4 mile comparables · average ${gbp(avg)}</h2><table><tr><th>Address</th><th>Beds</th><th>Date</th><th class="n">Sold</th></tr>${comps.map((c) => `<tr><td>${esc(c.address)}</td><td>${c.beds}</td><td>${esc(c.date)}</td><td class="n">${gbp(c.price)}</td></tr>`).join("")}</table>` : ""}`;
}

export type BrrrInputs = BrrrBase & BrrrBridge;
export const BRRR_DEFAULT_FEES = 6000;
export const BRRR_DEFAULT_COSTS = 200;

export function calcBrrr(i: BrrrInputs): BrrrFigures {
  const months = i.months ?? 0;
  const bridgeLoan = i.purchase * ((i.bridge_pct ?? 0) / 100);
  const financeCost = bridgeLoan * ((i.bridge_rate ?? 0) / 100) * months + bridgeLoan * ((i.bridge_fee ?? 0) / 100);
  const holdingTotal = (i.holding ?? 0) * months;
  const invested = i.purchase + i.fees + i.refurb + financeCost + holdingTotal;
  const cashNeeded = invested - bridgeLoan;
  const refi = i.valuation * (i.ltv / 100);
  const leftIn = invested - refi;
  const mortgage = (refi * (i.rate / 100)) / 12;
  const cashflow = i.rent - mortgage - i.costs;
  const roi = leftIn <= 0 ? Infinity : ((cashflow * 12) / leftIn) * 100;
  const yieldPct = i.valuation > 0 ? ((i.rent * 12) / i.valuation) * 100 : 0;
  return { ...i, bridgeLoan, financeCost, holdingTotal, cashNeeded, invested, refi, leftIn, mortgage, cashflow, roi, yieldPct, equity: i.valuation - refi };
}

/** One combined PDF for refinance applications: cover + progress + budget estimate (+ BRRR analysis for Pro). */
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Rental income proof for lenders: tenancies, rent received vs due, letting costs and net cashflow (year to date). */
/** Local sold prices (HM Land Registry, ½ mile, 3 years) with a dot plot around the property and recent sales with £/sq ft. */
async function soldBody(p: Project): Promise<string> {
  const pc = p.address.match(/\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b/i)?.[1];
  if (!pc) return "";
  const d = await api<SoldPrices>(`/sold-prices?postcode=${encodeURIComponent(pc)}&miles=0.5&years=3`).catch(() => null);
  if (!d || !d.sales.length) return "";
  const recent = d.sales.slice(0, 15);
  const fa = await api<FloorAreas>("/sold-prices/floor-areas", { body: { sales: recent.map((x) => ({ postcode: x.postcode, address: x.address || x.postcode, price: x.price })) } }).catch(() => null);
  const W = 420, R = 190, k = R / d.radius_m, cos = Math.cos((d.lat * Math.PI) / 180), med = d.stats.median || 1;
  const dots = d.sales.slice(0, 600).map((x) => {
    const cx = W / 2 + (x.lon - d.lon) * cos * 111320 * k, cy = W / 2 - (x.lat - d.lat) * 111320 * k;
    const col = x.price < med * 0.85 ? "#10b981" : x.price > med * 1.15 ? "#f97316" : "#0f766e";
    return `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="4" fill="${col}" fill-opacity="0.8" stroke="#fff" stroke-width="1"/>`;
  }).join("");
  const svg = `<svg width="${W}" height="${W}" viewBox="0 0 ${W} ${W}" style="display:block;margin:8px auto;background:#f1f5f9;border-radius:12px">
<circle cx="${W / 2}" cy="${W / 2}" r="${R}" fill="#ffffff" stroke="#0f766e" stroke-width="2"/>${dots}
<circle cx="${W / 2}" cy="${W / 2}" r="8" fill="#0f172a" stroke="#fff" stroke-width="3"/><text x="${W / 2 + 12}" y="${W / 2 + 4}" font-size="11" font-weight="bold" fill="#0f172a">${esc(d.postcode)}</text>
<text x="8" y="${W - 10}" font-size="10" fill="#475569">● green below median · teal around · orange above · ring = ½ mile</text></svg>`;
  const types = Object.entries(d.stats.by_type).filter(([t]) => t !== "Other").map(([t, v]) => `<tr><td>${t}</td><td class="n">${v.count}</td><td class="n">${gbp(v.median)}</td><td class="n">${gbp(v.avg)}</td></tr>`).join("");
  const rows = recent.map((x, i) => { const a = fa?.items[i]; return `<tr><td>${esc(x.address || x.postcode)}<div class="bd">${esc(x.postcode)} · ${esc(x.type)}${x.tenure ? ` · ${esc(x.tenure)}` : ""}</div></td><td class="n">${esc(x.date)}</td><td class="n">${a?.sqft ? a.sqft.toLocaleString() : "–"}</td><td class="n">${a?.price_per_sqft ? `£${a.price_per_sqft}` : "–"}</td><td class="n"><b>${gbp(x.price)}</b></td></tr>`; }).join("");
  const gdvVs = p.estimated_valuation ? `<p class="bd">End valuation ${gbp(p.estimated_valuation)} is ${Math.abs(Math.round((p.estimated_valuation / med - 1) * 100))}% ${p.estimated_valuation >= med ? "above" : "below"} the local median sold price.</p>` : "";
  return `<h1>Local sold prices</h1><p class="bd">Sales within ½ mile of ${esc(d.postcode)} since ${esc(d.since)}.</p>
${kpis([["Median sold", gbp(d.stats.median)], ["Average sold", gbp(d.stats.avg)], ["Sales", d.stats.count.toLocaleString()], ["Median £/sq ft", fa?.median_ppsf ? `£${fa.median_ppsf}` : "–"]])}
${gdvVs}${svg}
<h2>By property type</h2><table><tr><th>Type</th><th class="n">Sales</th><th class="n">Median</th><th class="n">Average</th></tr>${types}</table>
<h2>Most recent sales</h2><table><tr><th>Address</th><th class="n">Sold</th><th class="n">Sq ft</th><th class="n">£/sq ft</th><th class="n">Price</th></tr>${rows}</table>
<p class="bd">Source: HM Land Registry Price Paid Data (Open Government Licence v3.0); floor areas from EPC register where available. Medians exclude commercial and bulk sales.</p>`;
}

function rentalBody(r: Rentals) {
  const sm = r.summary;
  const nowM = new Date().toISOString().slice(0, 7);
  const months = sm.monthly.filter((m) => m.month <= nowM && (m.due || m.received || m.expenses));
  const onTime = r.tenancies.flatMap((t) => t.schedule.filter((m) => m.month <= nowM));
  const paidPct = onTime.length ? Math.round((onTime.filter((m) => m.status === "paid").length / onTime.length) * 100) : 0;
  return `<h2>Rental income ${r.year} (year to date)</h2>
${kpis([["Rent received", gbp(sm.received)], ["Letting costs", gbp(sm.expenses)], ["Net cashflow", gbp(sm.net)], ["Arrears", gbp(sm.arrears)]])}
<p style="font-size:11px">${onTime.length ? `${paidPct}% of rent months paid in full` : "No rent due yet this year"} · current contracted rent ${gbp(sm.active_rent)} / month</p>
<h2>Tenancies</h2><table><tr><th>Tenant</th><th>Term</th><th class="n">Rent / mo</th><th class="n">Deposit</th><th class="n">Arrears</th></tr>
${r.tenancies.map((t) => `<tr><td>${esc(t.tenant_name)}<div class="bd">${t.status}</div></td><td>${t.start_date} – ${t.end_date ?? "rolling"}</td><td class="n">${gbp(t.rent)}</td><td class="n">${gbp(t.deposit)}${t.deposit ? `<div class="bd">${t.deposit_protected ? `Protected${t.deposit_scheme ? " · " + esc(t.deposit_scheme) : ""}` : "Not protected"}</div>` : ""}</td><td class="n">${gbp(t.arrears)}</td></tr>`).join("")}</table>
${months.length ? `<h2>Monthly cashflow</h2><table><tr><th>Month</th><th class="n">Rent due</th><th class="n">Received</th><th class="n">Costs</th><th class="n">Net</th></tr>
${months.map((m) => `<tr><td>${MON[Number(m.month.slice(5)) - 1]} ${m.month.slice(0, 4)}</td><td class="n">${gbp(m.due)}</td><td class="n">${gbp(m.received)}</td><td class="n">${gbp(m.expenses)}</td><td class="n">${gbp(m.net)}</td></tr>`).join("")}
<tr><td><b>Total</b></td><td class="n"><b>${gbp(months.reduce((a, m) => a + m.due, 0))}</b></td><td class="n"><b>${gbp(sm.received)}</b></td><td class="n"><b>${gbp(sm.expenses)}</b></td><td class="n"><b>${gbp(sm.net)}</b></td></tr></table>` : ""}
${Object.keys(sm.by_category).length ? `<h2>Letting costs by category</h2><table>${Object.entries(sm.by_category).map(([k, v]) => `<tr><td>${esc(k.replace(/_/g, " "))}</td><td class="n">${gbp(v)}</td></tr>`).join("")}</table>` : ""}`;
}

function homeKpis(p: Project) {
  const h = p.home_finance;
  const r = h.remortgage;
  return `${kpis([["Purchase price", gbp(p.purchase_price)], ["Value after refurb", gbp(p.estimated_valuation)], ["Mortgage balance", gbp(h.loan)], ["Monthly payment", gbp(h.monthly_payment)]])}
${kpis([["LTV now / after", `${h.ltv_now.toFixed(0)}% / ${h.ltv_after.toFixed(0)}%`], ["Equity after refurb", gbp(h.equity_after)], ["Refurb budget", gbp(p.total_budget)], ["Value added (net)", gbp(h.net_value_added)]])}
<h2>Remortgage to fund the refurb</h2>
${kpis([["Borrow for refurb", gbp(r.borrow_for_refurb)], ["New mortgage", gbp(r.new_loan)], ["New monthly payment", `${gbp(r.new_payment)} (+${gbp(r.payment_increase)})`], ["New LTV", `${r.new_ltv.toFixed(0)}%`]])}
<p style="font-size:11px">${r.covers_refurb ? "Remortgaging covers the full refurb budget." : `Remortgage covers ${gbp(r.borrow_for_refurb)}; ${gbp(r.shortfall)} still to fund from savings.`}</p>`;
}

export async function shareLenderPack(includeBrrr: boolean) {
  const p = await api<Project>("/project");
  const f = calcBrrr({ purchase: p.purchase_price, fees: BRRR_DEFAULT_FEES, refurb: p.total_budget, valuation: p.estimated_valuation,
    ltv: p.refinance_ltv, rate: p.refinance_rate, rent: p.monthly_rent, costs: BRRR_DEFAULT_COSTS });
  const comps = includeBrrr ? await api<Comparable[]>("/project/comparables").catch(() => [] as Comparable[]) : [];
  const rentals = await api<Rentals>(`/rentals?year=${new Date().getFullYear()}`).catch(() => null);
  const hasRent = !!rentals?.tenancies.length;
  const [progress, budget, brrr, sold] = await Promise.all([progressBody(), budgetBody(), includeBrrr ? brrrBody(p, f, comps) : Promise.resolve(""), p.property_type === "land" ? Promise.resolve("") : soldBody(p)]);
  const sections = [["Progress report", "Milestones, budget usage, receipts and before & after photos"], ["Budget estimate", "Itemised costs by category with variance"],
    ...(hasRent ? [["Rental income", "Rent received, tenancies, letting costs and net cashflow"]] : []),
    ...(includeBrrr ? [["BRRR analysis", "Refinance, money left in, cashflow and local comparables"]] : []),
    ...(sold ? [["Local sold prices", "Land Registry sales within ½ mile, map, £ per sq ft and median vs valuation"]] : [])].map(([t, d], i) => [String(i + 1), t, d]);
  const cover = `${await brandHeader("LENDER REPORT PACK", p)}
<p style="margin:18px 0 6px;font-size:13px">Prepared for ${p.purpose === "personal" ? "remortgage" : "refinance"} application · ${esc(p.target_type)} · ${esc(p.finish_type)}</p>
${p.purpose === "personal" ? homeKpis(p) : `${kpis([["Purchase price", gbp(p.purchase_price)], ["End valuation (GDV)", gbp(p.estimated_valuation)], [`Refinance at ${p.refinance_ltv}% LTV`, gbp(f.refi)], [f.leftIn > 0 ? "Money left in" : "Cash pulled out", gbp(Math.abs(f.leftIn))]])}
${kpis([["Refurb budget", gbp(p.total_budget)], ["Spent to date", gbp(p.total_spent)], ["Monthly rent", gbp(p.monthly_rent)], ["Gross yield", `${f.yieldPct.toFixed(1)}%`]])}`}
${hasRent ? kpis([["Rent received (YTD)", gbp(rentals!.summary.received)], ["Letting costs (YTD)", gbp(rentals!.summary.expenses)], ["Net cashflow (YTD)", gbp(rentals!.summary.net)], ["Arrears", gbp(rentals!.summary.arrears)]]) : ""}
<p style="font-size:11px">Stage: <b>${esc(p.current_stage ?? "Not started")}</b> · ${p.milestones_done}/${p.milestones_total} milestones complete</p>
<h2>Contents</h2><table>${sections.map(([n, t, d]) => `<tr><td style="width:24px"><b>${n}</b></td><td><b>${t}</b><div class="bd">${d}</div></td></tr>`).join("")}</table>
${p.purpose === "personal" ? `<p class="bd" style="margin-top:14px">Mortgage: ${p.mortgage_type === "repayment" ? "repayment" : "interest-only"} over ${p.mortgage_term} years at ${p.mortgage_rate}%. Remortgage assumes up to ${p.remortgage_ltv}% LTV on the end valuation.` : `<p class="bd" style="margin-top:14px">Money left in assumes ${gbp(BRRR_DEFAULT_FEES)} purchase fees and the full refurb budget. Mortgage is interest-only at ${p.refinance_rate}%.`}</p>`;
  const brk = (h: string) => `<div style="page-break-before:always"></div>${h}`;
  await printPdf(doc(cover + brk(progress) + brk(budget) + (hasRent ? brk(rentalBody(rentals!)) : "") + (brrr ? brk(brrr) : "") + (sold ? brk(sold) : "")), `${p.name} lender report pack`);
}
