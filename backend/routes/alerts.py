"""Owner alert emails: line items going over budget, and documents expiring (30 days before + on expiry)."""
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from core import CURRENCY, E, db, logger, money, now_iso
from email_service import EMAIL_FROM_NAME, EmailError, send_email
from routes.email_settings import owner_reply_to


def _wrap(tag: str, title: str, body: str) -> str:
    return (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">'
            f'<p style="font-size:12px;letter-spacing:1px;color:#0f766e;font-weight:bold;margin:0">{E(EMAIL_FROM_NAME.upper())} · {E(tag)}</p>'
            f'<h1 style="font-size:20px;margin:8px 0">{E(title)}</h1>{body}'
            f'<p style="font-size:12px;color:#888;margin-top:24px">Sent by {E(EMAIL_FROM_NAME)} because you manage this project. Open the app to review.</p></td></tr></table>')


async def _send_owner(uid: str, subject: str, html: str) -> bool:
    to = await owner_reply_to(uid)
    if not to:
        return False
    try:
        await send_email(to=to, subject=subject, html=html)
        return True
    except (EmailError, ValueError) as e:
        logger.warning(f"Owner alert failed for {uid}: {e}")
        return False


async def check_over_budget(line_item_id: str | None):
    """Email the owner the first time a line item's spend (actual + linked receipts) exceeds its budget."""
    if not line_item_id or not ObjectId.is_valid(line_item_id):
        return
    li = await db.line_items.find_one({"_id": ObjectId(line_item_id)})
    if not li:
        return
    linked = sum([r["amount"] async for r in db.receipts.find({"line_item_id": line_item_id}, {"amount": 1})])
    spent = li.get("actual", 0) + linked
    over = li.get("budgeted", 0) > 0 and spent > li["budgeted"]
    if not over:
        if li.get("over_notified"):
            await db.line_items.update_one({"_id": li["_id"]}, {"$set": {"over_notified": False}})
        return
    if li.get("over_notified"):
        return
    await db.line_items.update_one({"_id": li["_id"]}, {"$set": {"over_notified": True, "over_notified_at": now_iso()}})
    proj = await db.projects.find_one({"_id": ObjectId(li["project_id"])}, {"name": 1, "currency": 1}) or {}
    CURRENCY.set(proj.get("currency") or "GBP")
    pct = round(spent / li["budgeted"] * 100)
    body = (f'<p><b>{E(li["name"])}</b> on <b>{E(proj.get("name", "your project"))}</b> has gone over budget.</p>'
            f'<table role="presentation" cellpadding="6"><tr><td>Budget</td><td><b>{money(li["budgeted"])}</b></td></tr>'
            f'<tr><td>Spent</td><td><b>{money(spent, 2)}</b> ({pct}%)</td></tr>'
            f'<tr><td>Over by</td><td style="color:#dc2626"><b>{money(spent - li["budgeted"], 2)}</b></td></tr></table>'
            f'<p>Consider moving funds from contingency or adjusting the estimate.</p>')
    await _send_owner(li["user_id"], f"Over budget: {li['name']} ({proj.get('name', '')})", _wrap("BUDGET ALERT", f"{li['name']} is over budget", body))


async def run_expiry_reminders():
    """Once per document: a reminder when it enters the 30-day window, and another on/after the expiry date."""
    today = datetime.now(timezone.utc).date()
    soon = (today + timedelta(days=30)).isoformat()
    by_user: dict = {}
    async for d in db.documents.find({"expires_on": {"$ne": None, "$lte": soon}}):
        expired = d["expires_on"] < today.isoformat()
        flag = "expiry_notified_expired" if expired else "expiry_notified_soon"
        if d.get(flag) == d["expires_on"]:
            continue
        by_user.setdefault(d["user_id"], []).append((d, expired, flag))
    for uid, items in by_user.items():
        rows = ""
        for d, expired, _ in items:
            days = (datetime.fromisoformat(d["expires_on"]).date() - today).days
            proj = await db.projects.find_one({"_id": ObjectId(d["project_id"])}, {"name": 1}) or {}
            status = f'<span style="color:#dc2626"><b>Expired {abs(days)} day{"s" if abs(days) != 1 else ""} ago</b></span>' if expired else f'<b>Expires in {days} day{"s" if days != 1 else ""}</b>'
            rows += f'<tr><td style="padding:6px 0"><b>{E(d["doc_type"])}</b>: {E(d["title"])}<br/><span style="color:#64748b;font-size:12px">{E(proj.get("name", ""))} · {E(d["expires_on"])}</span></td><td style="padding:6px 0 6px 12px">{status}</td></tr>'
        n = len(items)
        html = _wrap("RENEWAL REMINDER", f"{n} document{'s' if n != 1 else ''} need renewing",
                     f'<p>These certificates or policies are expiring soon or have expired:</p><table role="presentation" width="100%">{rows}</table>'
                     f'<p>Upload the renewed document in the app to clear the reminder.</p>')
        if await _send_owner(uid, f"Renewal reminder: {n} document{'s' if n != 1 else ''} expiring", html):
            for d, _, flag in items:
                await db.documents.update_one({"_id": d["_id"]}, {"$set": {flag: d["expires_on"]}})
