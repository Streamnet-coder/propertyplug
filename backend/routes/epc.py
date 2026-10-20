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


# ---------- EPC upgrade planner for the active project ----------
from bson import ObjectId  # noqa: E402
from typing import Optional  # noqa: E402

from core import now_iso  # noqa: E402
from deps import active_pid, block_money, get_project_doc  # noqa: E402
from models import LineItem  # noqa: E402

PC_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)
# RdSAP Appendix T improvement letters (first letter decides; a few variants named explicitly)
IMPROVEMENTS = {"A": "Loft insulation", "A2": "Flat roof insulation", "A3": "Room-in-roof insulation", "B": "Cavity wall insulation", "C": "Hot water cylinder insulation",
                "D": "Draught proofing", "E": "Low energy lighting", "F": "Hot water cylinder thermostat", "G": "Heating controls (programmer, thermostat, TRVs)",
                "H": "Heat recovery / heating improvement", "I": "Condensing boiler", "J": "Biomass boiler", "K": "Biomass room heater", "L": "High heat retention storage heaters",
                "M": "Replacement warm-air unit", "N": "Solar water heating", "O": "Double glazing", "O3": "Replacement glazing", "P": "Secondary glazing",
                "Q": "Solid wall insulation (internal or external)", "Q2": "External wall insulation", "R": "Condensing oil boiler", "S": "Gas condensing boiler",
                "T": "Fan-assisted storage heaters", "U": "Solar photovoltaic (PV) panels", "V": "Wind turbine", "W": "Floor insulation", "W1": "Suspended floor insulation",
                "W2": "Solid floor insulation", "X": "Insulated external doors", "Y": "Waste water heat recovery", "Z": "Heat pump", "Z1": "Air source heat pump", "Z3": "Ground source heat pump"}


def _imp_name(code: str) -> str:
    code = (code or "").upper()
    return IMPROVEMENTS.get(code) or IMPROVEMENTS.get(code[:1]) or f"Energy improvement ({code})"


def _costs(text: str):
    nums = [float(x.replace(",", "")) for x in re.findall(r"[\d,]+(?:\.\d+)?", text or "") if x.replace(",", "")]
    return (nums[0], nums[-1]) if nums else (0.0, 0.0)


def _band(rating) -> str:
    r = int(rating or 0)
    return "A" if r >= 92 else "B" if r >= 81 else "C" if r >= 69 else "D" if r >= 55 else "E" if r >= 39 else "F" if r >= 21 else "G"


async def _cert_detail(c: httpx.AsyncClient, num: str) -> Optional[dict]:
    hit = await db.epc_detail_cache.find_one({"num": num})
    if hit:
        return hit["d"]
    d = (await _get(c, "certificate", {"certificate_number": num}) or {}).get("data")
    if d:
        await db.epc_detail_cache.update_one({"num": num}, {"$set": {"num": num, "d": d}}, upsert=True)
    return d


def _client():
    token = os.environ.get("EPC_API_KEY")
    if not token:
        raise HTTPException(503, "EPC data isn't set up yet")
    return httpx.AsyncClient(timeout=20, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})


@router.get("/project/epc", dependencies=[Depends(block_money)])
async def project_epc(user: User = Depends(current_user)):
    p = await get_project_doc(user)
    m = PC_RE.search(p.address or "")
    if not m:
        return {"status": "no_postcode"}
    pc = m.group(1).upper().replace(" ", "")
    pc = f"{pc[:-3]} {pc[-3:]}"
    doc = await db.projects.find_one({"_id": ObjectId(p.id)}, {"epc_certificate": 1}) or {}
    try:
        async with _client() as c:
            certs = await _certs_for(c, pc)
            pinned = doc.get("epc_certificate")
            cert = next((x for x in certs if x["certificateNumber"] == pinned), None) if pinned else _match(PC_RE.sub("", p.address), certs)
            cands = [{"certificate_number": x["certificateNumber"], "address": ", ".join(y for y in [x.get("addressLine1"), x.get("addressLine2"), x.get("addressLine3")] if y),
                      "band": x.get("currentEnergyEfficiencyBand"), "date": x.get("registrationDate")} for x in sorted(certs, key=lambda x: x["registrationDate"], reverse=True)][:60]
            if not cert:
                return {"status": "pick", "postcode": pc, "candidates": cands}
            d = await _cert_detail(c, cert["certificateNumber"])
    except httpx.HTTPError as e:
        logger.warning(f"EPC project lookup failed: {e}")
        raise HTTPException(503, "EPC data is temporarily unavailable")
    if not d:
        return {"status": "pick", "postcode": pc, "candidates": cands}
    names = {x["name"] async for x in db.line_items.find({"project_id": p.id, "supplier": "EPC recommendation"}, {"name": 1})}
    imps = []
    for x in sorted(d.get("suggested_improvements") or [], key=lambda x: x.get("sequence", 0)):
        lo, hi = _costs(x.get("indicative_cost"))
        name = _imp_name(x.get("improvement_type"))
        imps.append({"sequence": x.get("sequence"), "code": x.get("improvement_type"), "name": name, "cost_text": x.get("indicative_cost") or "",
                     "cost_low": lo, "cost_high": hi, "saving": (x.get("typical_saving") or {}).get("value"), "rating_after": x.get("energy_performance_rating"),
                     "band_after": _band(x.get("energy_performance_rating")), "in_budget": f"EPC: {name}" in names})
    sqm = float(d.get("total_floor_area") or 0) or None
    return {"status": "ok", "postcode": pc, "certificate_number": cert["certificateNumber"], "pinned": bool(pinned),
            "address": ", ".join(y for y in [d.get("address_line_1"), d.get("address_line_2"), d.get("address_line_3")] if y),
            "registration_date": d.get("registration_date"), "band": d.get("current_energy_efficiency_band"), "rating": d.get("energy_rating_current"),
            "potential_band": d.get("potential_energy_efficiency_band"), "potential_rating": d.get("energy_rating_potential"),
            "sqm": sqm, "sqft": round(sqm * SQFT) if sqm else None, "property_type": d.get("property_type"), "built_form": d.get("built_form"),
            "heating_cost": d.get("heating_cost_current"), "improvements": imps, "candidates": cands}


class PinIn(BaseModel):
    certificate_number: Optional[str] = Field(None, max_length=40)


@router.put("/project/epc", dependencies=[Depends(block_money)])
async def pin_epc(body: PinIn, user: User = Depends(current_user)):
    await db.projects.update_one({"_id": ObjectId(await active_pid(user))}, {"$set": {"epc_certificate": body.certificate_number or None}})
    return await project_epc(user)


class AddIn(BaseModel):
    sequences: List[int] = Field(min_length=1, max_length=30)


@router.post("/project/epc/add-to-budget", dependencies=[Depends(block_money)])
async def add_to_budget(body: AddIn, user: User = Depends(current_user)):
    e = await project_epc(user)
    if e.get("status") != "ok":
        raise HTTPException(400, "Link an EPC certificate first")
    pid = await active_pid(user)
    added = []
    for x in e["improvements"]:
        if x["sequence"] in body.sequences and not x["in_budget"]:
            li = LineItem(user_id=user.id, project_id=pid, category="Hard Cost", name=f"EPC: {x['name']}", budgeted=round((x["cost_low"] + x["cost_high"]) / 2),
                          supplier="EPC recommendation", status="Planned")
            await db.line_items.insert_one(li.to_mongo())
            added.append(x["name"])
    return {"added": added, "count": len(added), "at": now_iso()}
