"""EPC floor areas for sold-price comparables (£ per sq ft). Uses the government 'Get energy performance of buildings data' API.
Postcode searches and certificates are cached in Mongo; each sale is matched to the most recent EPC at the same address."""
import asyncio
import os
import re
from datetime import datetime, timedelta, timezone
from typing import List

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import db, logger
from deps import current_user
from models import User

router = APIRouter()
BASE = "https://api.get-energy-performance-data.communities.gov.uk/api"
SQFT = 10.7639
CACHE_DAYS = 30


def _tokens(s: str) -> set:
    s = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower().replace("apartment", "flat"))
    return {t for t in s.split() if t not in ("the", "road", "rd", "street", "st")}


def _nums(t: set) -> set:
    return {x for x in t if any(ch.isdigit() for ch in x) or len(x) == 1}


def _match(address: str, certs: list):
    """Most recent certificate whose house/flat numbers match exactly and words overlap well."""
    a = _tokens(address)
    best, score = None, 0.0
    for c in certs:
        b = _tokens(" ".join(x for x in [c.get("addressLine1"), c.get("addressLine2"), c.get("addressLine3"), c.get("addressLine4")] if x))
        if not a or not b or _nums(a) != _nums(b):
            continue
        sc = len(a & b) / len(a | b)
        if sc > score or (sc == score and best and c["registrationDate"] > best["registrationDate"]):
            best, score = c, sc
    return best if score >= 0.5 else None


async def _get(c: httpx.AsyncClient, path: str, params: dict):
    for attempt in range(3):
        r = await c.get(f"{BASE}/{path}", params=params)
        if r.status_code == 429:
            await asyncio.sleep(1 + attempt)
            continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    return None


async def _certs_for(c: httpx.AsyncClient, pc: str) -> list:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=CACHE_DAYS)).isoformat()
    hit = await db.epc_postcode_cache.find_one({"postcode": pc})
    if hit and hit["at"] > cutoff:
        return hit["certs"]
    d = await _get(c, "domestic/search", {"postcode": pc, "page_size": 5000})
    certs = [{k: x.get(k) for k in ("certificateNumber", "addressLine1", "addressLine2", "addressLine3", "addressLine4", "registrationDate", "currentEnergyEfficiencyBand")}
             for x in (d or {}).get("data", [])]
    await db.epc_postcode_cache.update_one({"postcode": pc}, {"$set": {"postcode": pc, "at": datetime.now(timezone.utc).isoformat(), "certs": certs}}, upsert=True)
    return certs


async def _area(c: httpx.AsyncClient, num: str):
    hit = await db.epc_cert_cache.find_one({"num": num})
    if hit:
        return hit["sqm"]
    d = await _get(c, "certificate", {"certificate_number": num})
    sqm = float((d or {}).get("data", {}).get("total_floor_area") or 0) or None
    await db.epc_cert_cache.update_one({"num": num}, {"$set": {"num": num, "sqm": sqm}}, upsert=True)
    return sqm


class SaleRef(BaseModel):
    postcode: str = Field(max_length=10)
    address: str = Field(max_length=200)
    price: float = Field(gt=0)


class FloorIn(BaseModel):
    sales: List[SaleRef] = Field(max_length=60)


@router.post("/sold-prices/floor-areas")
async def floor_areas(body: FloorIn, user: User = Depends(current_user)):
    """Per sale (same order): floor area from its EPC and £ per sq ft, or nulls when no EPC matches."""
    token = os.environ.get("EPC_API_KEY")
    if not token:
        raise HTTPException(503, "Floor area data isn't set up yet")
    sem = asyncio.Semaphore(6)
    try:
        async with httpx.AsyncClient(timeout=20, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}) as c:
            pcs = sorted({s.postcode for s in body.sales})

            async def certs(pc):
                async with sem:
                    return pc, await _certs_for(c, pc)
            by_pc = dict(await asyncio.gather(*[certs(pc) for pc in pcs]))

            async def one(s: SaleRef):
                m = _match(s.address, by_pc.get(s.postcode) or [])
                if not m:
                    return {"sqm": None, "sqft": None, "price_per_sqft": None, "epc_band": None}
                async with sem:
                    sqm = await _area(c, m["certificateNumber"])
                sqft = round(sqm * SQFT) if sqm else None
                return {"sqm": sqm, "sqft": sqft, "price_per_sqft": round(s.price / sqft) if sqft else None, "epc_band": m.get("currentEnergyEfficiencyBand")}
            out = await asyncio.gather(*[one(s) for s in body.sales])
    except httpx.HTTPError as e:
        logger.warning(f"EPC lookup failed: {e}")
        raise HTTPException(503, "Floor area data is temporarily unavailable")
    ppsf = sorted(x["price_per_sqft"] for x in out if x["price_per_sqft"])
    return {"items": out, "matched": len(ppsf), "median_ppsf": ppsf[len(ppsf) // 2] if ppsf else None}
