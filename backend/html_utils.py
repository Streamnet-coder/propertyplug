from fastapi import HTTPException
from fastapi.responses import Response, HTMLResponse
from fastapi.concurrency import run_in_threadpool
from typing import Optional
from bson import ObjectId
from core import db, E
from models import Branding
from storage import get_object


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
