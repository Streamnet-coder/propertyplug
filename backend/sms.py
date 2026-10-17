"""Optional Twilio SMS. Sends only when TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER are set; otherwise a no-op."""
import logging
import os
import re

from fastapi.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)


def sms_enabled() -> bool:
    return all(os.environ.get(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"))


def e164(phone: str) -> str:
    """UK-friendly normalising: 07700 900123 -> +447700900123, 0044... -> +44..., keeps +E.164."""
    p = re.sub(r"[^\d+]", "", phone or "")
    if p.startswith("00"):
        p = "+" + p[2:]
    elif p.startswith("0"):
        p = "+44" + p[1:]
    elif p and not p.startswith("+"):
        p = "+" + p
    return p if re.fullmatch(r"\+\d{8,15}", p) else ""


async def send_sms(to: str, body: str) -> bool:
    num = e164(to)
    if not sms_enabled() or not num:
        return False
    from twilio.rest import Client

    def _send():
        Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"]).messages.create(to=num, from_=os.environ["TWILIO_FROM_NUMBER"], body=body[:640])

    try:
        await run_in_threadpool(_send)
        return True
    except Exception as e:  # never block a report or assignment on SMS problems
        logger.warning(f"SMS failed: {e}")
        return False
