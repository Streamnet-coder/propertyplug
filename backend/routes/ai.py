from emergentintegrations.llm.chat import ImageContent, LlmChat, UserMessage
from fastapi import APIRouter, HTTPException, Depends
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from typing import Optional
import base64, json, re, uuid
from datetime import datetime, timezone
from bson import ObjectId
from core import db, logger, now_iso, oid, EMERGENT_KEY, APP_NAME
from models import Media, User
from deps import active_pid, current_user
from storage import get_object, put_object

router = APIRouter()
IMAGE_MODEL = "gemini-3.1-flash-image-preview"


class EstimateIn(BaseModel):
    description: str = Field(max_length=2000)
    finish_type: str = "Medium Finish"
    photo_path: Optional[str] = None


def _json(text: str):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise HTTPException(502, "AI returned an unexpected response")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        raise HTTPException(502, "AI returned an unexpected response")


async def _photo_b64(path: str, user: User) -> str:
    if not await db.files.find_one({"storage_path": path, "owner_id": user.id, "is_deleted": False}):
        raise HTTPException(404, "Photo not found")
    data, _ = await run_in_threadpool(get_object, path)
    return base64.b64encode(data).decode()


@router.post("/ai/estimate")
async def ai_estimate(body: EstimateIn, user: User = Depends(current_user)):
    if not body.description.strip():
        raise HTTPException(400, "Please describe the work")
    from routes.credits import charge
    await charge(user, "ai_estimate", body.description.strip()[:200])
    system = ("You are a UK renovation quantity surveyor. Estimate realistic 2026 UK costs in GBP, referencing suppliers "
              "like B&Q, Wickes, Toolstation, Screwfix, Wren Kitchens, DIY Kitchens, eBay and typical UK trade day rates. "
              "If a photo of the space is provided, use it to judge size, condition and what needs replacing. "
              "Respond ONLY with compact JSON: {\"items\":[{\"name\":str,\"spec\":str (short material/finish spec, e.g. 'Oak-effect LVT, 5mm'),"
              "\"category\":\"Hard Cost\"|\"Soft Cost\",\"low\":number,\"high\":number,\"supplier\":str,\"visible\":bool (true if it is a material/finish you could point to in a photo of the finished room)}],"
              "\"total_low\":number,\"total_high\":number,\"notes\":str}. 3-8 items. No markdown.")
    chat = LlmChat(api_key=EMERGENT_KEY, session_id=f"est-{uuid.uuid4()}", system_message=system).with_model("anthropic", "claude-sonnet-5-5")
    files = [ImageContent(await _photo_b64(body.photo_path, user))] if body.photo_path else None
    try:
        text = await chat.send_message(UserMessage(text=f"Finish level: {body.finish_type}. Work: {body.description}", file_contents=files))
    except Exception as e:
        logger.exception("AI estimate failed")
        raise HTTPException(502, f"AI service error: {e}")
    data = _json(text)
    res = await db.estimates.insert_one({"user_id": user.id, "project_id": await active_pid(user), "description": body.description, "finish_type": body.finish_type,
                                         "photo_path": body.photo_path, "result": data, "created_at": now_iso()})
    return {**data, "id": str(res.inserted_id)}


@router.post("/ai/estimate/{eid}/design")
async def design_finished(eid: str, user: User = Depends(current_user)):
    """Nano Banana designs the finished space (editing the user's photo when given), then a vision pass places a dot
    on each visible material so the app can overlay name + cost. The image is saved to the project's photos."""
    est = await db.estimates.find_one({"_id": oid(eid), "user_id": user.id})
    if not est:
        raise HTTPException(404, "Estimate not found")
    items = est["result"].get("items", [])
    mats = "; ".join(f"{i['name']} ({i.get('spec', '')})" for i in items if i.get("visible", True))
    prompt = (f"Photorealistic interior photo of the FINISHED renovation, {est.get('finish_type', 'Medium Finish').lower()} level, UK home. "
              f"Work: {est['description']}. Clearly show these materials and finishes: {mats}. Natural daylight, tidy, no people, no text or labels.")
    photo = est.get("photo_path")
    if photo:
        prompt = "Renovate the room in this photo, keeping the same layout, walls, windows and camera angle. " + prompt
    chat = LlmChat(api_key=EMERGENT_KEY, session_id=f"design-{uuid.uuid4()}", system_message="You are an interior visualisation artist.")
    chat.with_model("gemini", IMAGE_MODEL).with_params(modalities=["image", "text"])
    try:
        _, images = await chat.send_message_multimodal_response(
            UserMessage(text=prompt, file_contents=[ImageContent(await _photo_b64(photo, user))] if photo else None))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Design image failed")
        raise HTTPException(502, f"Image service error: {e}")
    if not images:
        raise HTTPException(502, "The AI didn't return an image. Try again")
    img_b64, mime = images[0]["data"], images[0].get("mime_type", "image/png")

    # Locate each visible item in the generated image (percent coordinates).
    listing = "\n".join(f"{n}: {i['name']} - {i.get('spec', '')}" for n, i in enumerate(items) if i.get("visible", True))
    pins = []
    try:
        loc = LlmChat(api_key=EMERGENT_KEY, session_id=f"pins-{uuid.uuid4()}",
                      system_message="You locate objects in images. Reply ONLY with JSON.").with_model("anthropic", "claude-sonnet-5-5")
        out = await loc.send_message(UserMessage(
            text=("For each numbered item below, give the point in the image where that material/finish is most clearly visible, as percentages "
                  "of image width (x) and height (y) from the top-left. Skip items that are not visible. Keep points at least 8% apart. "
                  f"Reply as {{\"pins\":[{{\"i\":number,\"x\":number,\"y\":number}}]}}.\n{listing}"),
            file_contents=[ImageContent(img_b64)]))
        for p in _json(out).get("pins", []):
            i, x, y = int(p["i"]), float(p["x"]), float(p["y"])
            if 0 <= i < len(items) and 0 <= x <= 100 and 0 <= y <= 100:
                it = items[i]
                pins.append({"i": i, "x": round(min(max(x, 4), 96), 1), "y": round(min(max(y, 4), 96), 1), "name": it["name"], "spec": it.get("spec", ""),
                             "low": it["low"], "high": it["high"], "supplier": it.get("supplier", "")})
    except Exception as e:
        logger.warning(f"Pin placement failed: {e}")  # still return the image without dots

    ext = "png" if "png" in mime else "jpg"
    path = f"{APP_NAME}/uploads/{user.id}/design-{uuid.uuid4()}.{ext}"
    result = await run_in_threadpool(put_object, path, base64.b64decode(img_b64), mime)
    await db.files.insert_one({"storage_path": result["path"], "owner_id": user.id, "content_type": mime, "original_filename": f"ai-design.{ext}",
                               "is_deleted": False, "created_at": now_iso()})
    m = Media(user_id=user.id, project_id=await active_pid(user), title=f"AI design: {est['description'][:60]}", phase="after",
              storage_path=result["path"], date=datetime.now(timezone.utc).date().isoformat())
    await db.media.insert_one(m.to_mongo())
    await db.estimates.update_one({"_id": est["_id"]}, {"$set": {"design_path": result["path"], "pins": pins}})
    return {"image_path": result["path"], "pins": pins}


# ---------- Saved estimates (with their AI design images) for later review ----------

def _est_out(d: dict) -> dict:
    r = d.get("result") or {}
    return {"id": str(d["_id"]), "description": d["description"], "finish_type": d.get("finish_type", ""), "created_at": d["created_at"],
            "photo_path": d.get("photo_path"), "design_path": d.get("design_path"), "pins": d.get("pins") or [], "title": d.get("title") or "",
            "total_low": r.get("total_low", 0), "total_high": r.get("total_high", 0), "items": r.get("items", []), "notes": r.get("notes", ""),
            "chosen": bool(d.get("chosen")), "chosen_at": d.get("chosen_at"), "added_items": d.get("added_items") or []}


@router.get("/ai/estimates")
async def list_estimates(user: User = Depends(current_user)):
    pid = await active_pid(user)
    q = {"user_id": user.id, "$or": [{"project_id": pid}, {"project_id": {"$exists": False}}]}
    return [_est_out(d) async for d in db.estimates.find(q).sort("created_at", -1).limit(200)]


@router.get("/ai/estimates/{eid}")
async def get_estimate(eid: str, user: User = Depends(current_user)):
    d = await db.estimates.find_one({"_id": oid(eid), "user_id": user.id})
    if not d:
        raise HTTPException(404, "Estimate not found")
    return _est_out(d)


class EstimateRename(BaseModel):
    title: str = Field(max_length=80)


@router.put("/ai/estimates/{eid}")
async def rename_estimate(eid: str, body: EstimateRename, user: User = Depends(current_user)):
    r = await db.estimates.update_one({"_id": oid(eid), "user_id": user.id}, {"$set": {"title": body.title.strip()}})
    if not r.matched_count:
        raise HTTPException(404, "Estimate not found")
    return await get_estimate(eid, user)


@router.delete("/ai/estimates/{eid}")
async def delete_estimate(eid: str, user: User = Depends(current_user)):
    await db.estimates.delete_one({"_id": oid(eid), "user_id": user.id})
    return {"ok": True}


@router.post("/ai/estimates/{eid}/choose")
async def choose_estimate(eid: str, user: User = Depends(current_user)):
    """Mark this estimate as the winning option for the project and add all its items to the budget (once each)."""
    d = await db.estimates.find_one({"_id": oid(eid), "user_id": user.id})
    if not d:
        raise HTTPException(404, "Estimate not found")
    pid = await active_pid(user)
    from models import LineItem
    items = (d.get("result") or {}).get("items", [])
    done = set(d.get("added_items") or [])
    added = 0
    for i, it in enumerate(items):
        if i in done:
            continue
        li = LineItem(user_id=user.id, project_id=pid, category="Soft Cost" if it.get("category") == "Soft Cost" else "Hard Cost", name=it.get("name", "Item")[:120],
                      budgeted=round((float(it.get("low", 0)) + float(it.get("high", 0))) / 2), supplier=it.get("supplier", "")[:120], status="Planned")
        await db.line_items.insert_one(li.to_mongo())
        done.add(i)
        added += 1
    await db.estimates.update_many({"user_id": user.id, "project_id": pid, "_id": {"$ne": d["_id"]}}, {"$set": {"chosen": False}})
    await db.estimates.update_one({"_id": d["_id"]}, {"$set": {"chosen": True, "chosen_at": now_iso(), "project_id": d.get("project_id") or pid, "added_items": sorted(done)}})
    return {"added": added, "estimate": await get_estimate(eid, user)}


class AddedIn(BaseModel):
    index: int = Field(ge=0, le=500)


@router.post("/ai/estimates/{eid}/added")
async def mark_added(eid: str, body: AddedIn, user: User = Depends(current_user)):
    """Remember a single item was added to the budget so "add all" skips it."""
    await db.estimates.update_one({"_id": oid(eid), "user_id": user.id}, {"$addToSet": {"added_items": body.index}})
    return {"ok": True}
