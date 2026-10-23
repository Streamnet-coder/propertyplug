"""Rent comparables: ONS Price Index of Private Rents average monthly rents for the postcode's local authority, by bedrooms and property type.
Data file backend/data/ons_rents.json is built from the ONS PIPR monthly spreadsheet (Open Government Licence)."""
import json
import re
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from deps import block_money, current_user
from models import User
from routes.credits import charge

router = APIRouter(dependencies=[Depends(block_money)])
RENTS = json.loads((Path(__file__).resolve().parent.parent / "data" / "ons_rents.json").read_text())
PC_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$")


def _area(code: str):
    a = RENTS.get(code)
    return {"code": code, **a} if a and a["prices"].get("all") else None


@router.get("/rent-comparables")
async def rent_comparables(postcode: str = Query(..., max_length=20), user: User = Depends(current_user)):
    pc = re.sub(r"\s+", "", postcode.strip().upper())
    pc = f"{pc[:-3]} {pc[-3:]}"
    if not PC_RE.match(pc):
        raise HTTPException(400, "Enter a full UK postcode, e.g. NG7 1AA")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"https://api.postcodes.io/postcodes/{pc.replace(' ', '')}")
    except httpx.HTTPError:
        raise HTTPException(503, "Postcode lookup is temporarily unavailable")
    if r.status_code == 404:
        raise HTTPException(404, f"{pc} isn't a recognised UK postcode")
    res = r.json()["result"]
    codes = res.get("codes") or {}
    local = _area(codes.get("admin_district", "")) or _area(codes.get("admin_county", ""))
    if not local:
        raise HTTPException(404, f"No ONS rent figures published for {res.get('admin_district') or pc}")
    await charge(user, "rent_comps", local["code"])
    region = next((_area(k) for k, v in RENTS.items() if v["name"] == local["region"]), None)
    return {"postcode": res["postcode"], "district": res.get("admin_district"), "local": local, "region": region, "uk": _area("K02000001"),
            "source": f"ONS Price Index of Private Rents, {local['month']} (Open Government Licence v3.0). Averages of all private rents in the area, not just new lets."}
