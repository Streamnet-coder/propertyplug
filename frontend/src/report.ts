import * as Print from "expo-print";
import * as Sharing from "expo-sharing";
import { Platform } from "react-native";

import { api, Branding, fileUrl, gbp, LineItem, MediaItem, Milestone, Project, Receipt } from "@/src/api";
import { colors } from "@/src/theme";

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

function buildHtml(
  p: Project,
  items: LineItem[],
  receipts: Receipt[],
  photos: { m: MediaItem; src: string | null }[],
  milestones: Milestone[],
  brand: { b: Branding; logo: string | null },
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

  return `<!DOCTYPE html><html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
*{box-sizing:border-box} body{font-family:-apple-system,Helvetica,Arial,sans-serif;color:${colors.onSurface};margin:0;padding:28px;font-size:12px}
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
</style></head><body>
${brandHtml}
<div class="hdr"><div class="brand">BUILDER <b>ASSIST</b> · PROGRESS REPORT</div><h1>${esc(p.name)}</h1><p>${esc(p.address)}</p>
<p style="margin-top:6px;font-size:11px">${esc(p.target_type)} · ${esc(p.finish_type)} · ${new Date().toLocaleDateString("en-GB")}</p></div>
<div class="kpis">
<div class="kpi"><span>Purchase</span><div>${gbp(p.purchase_price)}</div></div>
<div class="kpi"><span>Est. valuation</span><div>${gbp(p.estimated_valuation)}</div></div>
<div class="kpi"><span>Budget</span><div>${gbp(p.total_budget)}</div></div>
<div class="kpi"><span>Spent</span><div>${gbp(p.total_spent)}</div></div>
</div>
<div><b>${pct}% of budget used</b> · ${remaining >= 0 ? `${gbp(remaining)} remaining` : `<span class="over">${gbp(-remaining)} over budget</span>`}<div class="bar"><i style="width:${Math.min(100, pct)}%"></i></div></div>
${msHtml}
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
<div class="foot">Generated with Builder Assist · ${new Date().toLocaleString("en-GB")} · Figures are owner-reported</div>
</body></html>`;
}

export async function shareProgressReport() {
  const [p, items, receipts, media, milestones] = await Promise.all([
    api<Project>("/project"),
    api<LineItem[]>("/line-items"),
    api<Receipt[]>("/receipts"),
    api<MediaItem[]>("/media"),
    api<Milestone[]>("/milestones"),
  ]);
  const b = await api<Branding>("/branding");
  const logo = b.logo_path ? await toDataUri(fileUrl(b.logo_path)) : null;
  const photos = await Promise.all(
    media.slice(0, 12).map(async (m) => {
      const url = m.storage_path ? fileUrl(m.storage_path) : m.url;
      return { m, src: url ? await toDataUri(url) : null };
    }),
  );
  const html = buildHtml(p, items, receipts, photos, milestones, { b, logo });
  if (Platform.OS === "web") {
    await Print.printAsync({ html });
    return;
  }
  const { uri } = await Print.printToFileAsync({ html });
  if (await Sharing.isAvailableAsync()) {
    await Sharing.shareAsync(uri, { mimeType: "application/pdf", UTI: "com.adobe.pdf", dialogTitle: `${p.name} progress report` });
  }
}
