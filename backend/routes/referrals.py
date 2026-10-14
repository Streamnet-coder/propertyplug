from fastapi import APIRouter, HTTPException, Depends, Form
from fastapi.responses import HTMLResponse
from datetime import datetime, timezone, timedelta
from bson import ObjectId
import re
from core import db, now_iso, E
from models import User
from deps import current_user
from html_utils import page
from seed import create_user

router = APIRouter()


JOIN_FORM = """<div class='hdr'><div class='brand'>MY BUILDER <b>APP</b></div><h1>Start your 30-day free trial</h1>
<div>Track refurb budgets, milestones, trades & BRRR numbers in one app. No card required.</div></div>
<form class='card' method='post' id='join-form'><input type='hidden' name='ref' value='{ref}'/><input type='hidden' name='by' value='{by}'/>{err}
<label>Full name</label><input name='name' required value='{name}'/>
<label>Email</label><input name='email' type='email' required value='{email}'/>
<label>Password (min 6 characters)</label><input name='password' type='password' minlength='6' required/>
<button type='submit' id='join-submit'>Create free account</button></form>"""


@router.get("/join", response_class=HTMLResponse)
async def join_page(ref: str = "direct", by: str = ""):
    return page("Start free trial", JOIN_FORM.format(ref=E(ref), by=E(by), err="", name="", email=""))


REFERRAL_DAYS = 30


async def credit_referrer(by: str, new_user: User, source: str):
    if not by or not ObjectId.is_valid(by) or by == new_user.id:
        return
    ref = await db.users.find_one({"_id": ObjectId(by)}, {"trial_ends": 1})
    if not ref:
        return
    base = max(datetime.now(timezone.utc), datetime.fromisoformat(ref["trial_ends"]))
    await db.users.update_one({"_id": ref["_id"]}, {"$set": {"trial_ends": (base + timedelta(days=REFERRAL_DAYS)).isoformat()},
                                                   "$inc": {"referral_count": 1}})
    await db.users.update_one({"_id": ObjectId(new_user.id)}, {"$set": {"referred_by": by}})
    await db.referrals.insert_one({"referrer_id": by, "new_user_id": new_user.id, "name": new_user.name, "source": source,
                                   "days": REFERRAL_DAYS, "created_at": now_iso()})


@router.get("/referrals")
async def my_referrals(user: User = Depends(current_user)):
    docs = await db.referrals.find({"referrer_id": user.id}).sort("created_at", -1).to_list(100)
    return {"count": len(docs), "months_earned": len(docs), "trial_ends": user.trial_ends,
            "recent": [{"name": d["name"].split(" ")[0], "source": d["source"], "date": d["created_at"][:10]} for d in docs[:20]]}


@router.post("/join", response_class=HTMLResponse)
async def join_submit(name: str = Form(...), email: str = Form(...), password: str = Form(...), ref: str = Form("direct"), by: str = Form("")):
    src = re.sub(r"[^a-z_]", "", ref.lower())[:20] or "direct"
    by = re.sub(r"[^a-f0-9]", "", by.lower())[:24]
    try:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()):
            raise HTTPException(400, "Please enter a valid email")
        nu = await create_user(name, email, password, source=src)
    except HTTPException as e:
        err = f"<p class='over' id='join-error'>{E(str(e.detail))}</p>"
        return page("Start free trial", JOIN_FORM.format(ref=E(src), by=E(by), err=err, name=E(name), email=E(email)))
    await credit_referrer(by, nu, src)
    return page("Welcome", f"""<div class='hdr'><div class='brand'>MY BUILDER <b>APP</b></div><h1>You're in! 🎉</h1>
<div>Your 30-day free trial has started.</div></div><div class='card' id='join-success'><h2>Next steps</h2>
<p>1. Open <b>My Builder App</b> on your phone.</p><p>2. Tap <b>Sign in</b> and use <b>{E(email.strip().lower())}</b>.</p>
<p>3. Your first sample project is already loaded so you can explore straight away.</p></div>""")
