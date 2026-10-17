import csv
import io
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from core import db
from deps import current_user, real_user
from models import User

router = APIRouter()

# collection -> columns exported (in order). Internal ids/paths kept so data can be re-imported.
EXPORTS = {
    "projects": ["_id", "name", "address", "target_type", "finish_type", "purchase_price", "estimated_valuation", "monthly_rent",
                 "refinance_ltv", "refinance_rate", "budget.hard", "budget.soft", "budget.contingency", "currency", "property_type",
                 "plot_size", "plot_unit", "planning_status", "intended_use", "value_without_planning", "value_with_planning", "lat", "lon", "created_at"],
    "line_items": ["_id", "project_id", "name", "category", "supplier", "status", "budgeted", "actual", "created_at"],
    "receipts": ["_id", "project_id", "date", "title", "category", "supplier", "amount", "line_item_id", "storage_path", "created_at"],
    "contacts": ["_id", "project_id", "kind", "name", "role", "phone", "email", "status", "schedule", "cost", "created_at"],
    "milestones": ["_id", "project_id", "order", "name", "status", "target_date", "completed_at", "notes"],
    "snags": ["_id", "project_id", "room", "description", "priority", "status", "assignee", "fixed_by", "fixed_at", "storage_path", "fix_photo_path", "created_at"],
    "shopping_items": ["_id", "project_id", "name", "supplier", "qty", "est_cost", "actual_cost", "checked", "checked_at", "created_at"],
    "stage_payments": ["_id", "project_id", "quote_id", "label", "amount", "due_date", "status", "paid_at", "created_at"],
    "quote_requests": ["_id", "project_id", "title", "trade", "description", "created_at"],
    "documents": ["_id", "project_id", "title", "doc_type", "filename", "size", "notes", "storage_path", "created_at"],
    "planning_apps": ["_id", "project_id", "reference", "authority", "description", "submitted_date", "validated_date", "consultation_end", "target_decision_date", "decision", "decision_date", "notes", "created_at"],
    "media": ["_id", "project_id", "title", "phase", "date", "milestone_id", "storage_path", "url", "created_at"],
}


def _get(doc: dict, path: str):
    for k in path.split("."):
        doc = doc.get(k) if isinstance(doc, dict) else None
    return "" if doc is None else str(doc)


async def _csv(name: str, cols: list, uid: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id" if c == "_id" else c for c in cols])
    async for d in db[name].find({"user_id": uid}).sort("_id", 1):
        w.writerow([_get(d, c) for c in cols])
    return buf.getvalue()


@router.get("/export")
async def export_data(user: User = Depends(real_user)):
    """All of the user's data as a ZIP of CSV spreadsheets (one per data type)."""
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
        acc = io.StringIO()
        csv.writer(acc).writerows([["name", "email", "plan", "created_at"], [user.name, user.email, user.plan, user.created_at]])
        z.writestr("account.csv", "\ufeff" + acc.getvalue())
        for name, cols in EXPORTS.items():
            z.writestr(f"{name}.csv", "\ufeff" + await _csv(name, cols, user.id))  # BOM so Excel opens UTF-8 (e.g. £) correctly
        z.writestr("README.txt", "PropertyPlug data export\n\nEach CSV opens in Excel, Numbers or Google Sheets.\n"
                                 "Photos and receipts are referenced by storage_path.\n"
                                 f"Exported {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')}\n")
    fname = f"propertyplug-export-{datetime.now(timezone.utc).date().isoformat()}.zip"
    return Response(mem.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{fname}"'})
