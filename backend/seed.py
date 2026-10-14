from fastapi import HTTPException
from typing import Optional
from datetime import datetime, timezone, timedelta
from bson import ObjectId
import bcrypt
from core import db, now_iso
from models import User, Budget, Comparable, Project, LineItem, Contact, Receipt, Media, Milestone


DEFAULT_MILESTONES = ["Purchase complete", "Strip-out", "Structural & roofing", "First fix (electrics & plumbing)",
                      "Plastering", "Second fix", "Kitchen & bathroom install", "Decoration & flooring",
                      "Final inspection & sign-off", "Refinance / let"]



async def seed_milestones(uid: str, pid: str, demo: bool = False):
    start = datetime(2026, 5, 18, tzinfo=timezone.utc)
    docs = []
    for i, n in enumerate(DEFAULT_MILESTONES):
        st = ("done" if i < 3 else "in_progress" if i == 3 else "todo") if demo else "todo"
        docs.append(Milestone(user_id=uid, project_id=pid, name=n, status=st, order=i,
                              target_date=(start + timedelta(days=14 * i)).date().isoformat() if demo else None,
                              completed_at=now_iso() if st == "done" else None).to_mongo())
    await db.milestones.insert_many(docs)


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
