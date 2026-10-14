from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import json, re, uuid
from core import db, logger, now_iso, EMERGENT_KEY
from models import User
from deps import current_user

router = APIRouter()


class EstimateIn(BaseModel):
    description: str
    finish_type: str = "Medium Finish"


@router.post("/ai/estimate")
async def ai_estimate(body: EstimateIn, user: User = Depends(current_user)):
    if not body.description.strip():
        raise HTTPException(400, "Please describe the work")
    system = ("You are a UK renovation quantity surveyor. Estimate realistic 2026 UK costs in GBP, referencing suppliers "
              "like B&Q, Wickes, Toolstation, Screwfix, Wren Kitchens, DIY Kitchens, eBay and typical Nottingham/UK trade day rates. "
              "Respond ONLY with compact JSON: {\"items\":[{\"name\":str,\"category\":\"Hard Cost\"|\"Soft Cost\",\"low\":number,\"high\":number,\"supplier\":str}],"
              "\"total_low\":number,\"total_high\":number,\"notes\":str}. 3-8 items. No markdown.")
    chat = LlmChat(api_key=EMERGENT_KEY, session_id=f"est-{uuid.uuid4()}", system_message=system).with_model("anthropic", "claude-sonnet-5-5")
    text = ""
    try:
        async for ev in chat.stream_message(UserMessage(text=f"Finish level: {body.finish_type}. Work: {body.description}")):
            if isinstance(ev, TextDelta):
                text += ev.content
            elif isinstance(ev, StreamDone):
                break
    except Exception as e:
        logger.exception("AI estimate failed")
        raise HTTPException(502, f"AI service error: {e}")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise HTTPException(502, "AI returned an unexpected response")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        raise HTTPException(502, "AI returned an unexpected response")
    await db.estimates.insert_one({"user_id": user.id, "description": body.description, "result": data, "created_at": now_iso()})
    return data
