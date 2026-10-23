"""Sold prices map: HM Land Registry Price Paid Data for postcodes within 1/4 mile to 5 miles of a UK postcode.
Postcodes and their centres come from postcodes.io; sales come from the Land Registry SPARQL endpoint. Both are free, open data."""
import asyncio
import math
import re
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from core import db, logger
from deps import block_money, current_user
from models import User
from routes.credits import charge

router = APIRouter(dependencies=[Depends(block_money)])
MILE_M = 1609.34
MAX_SALES = 1500  # most recent sales returned for the map/list; stats use everything found
PC_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$")
SPARQL = "https://landregistry.data.gov.uk/landregistry/query"
TYPES = {"detached": "Detached", "semi-detached": "Semi-detached", "terraced": "Terraced", "flat-maisonette": "Flat", "other": "Other"}
CACHE_HOURS = 24


def _norm(pc: str) -> str:
    pc = re.sub(r"\s+", "", pc.upper())
    return f"{pc[:-3]} {pc[-3:]}"


def _dist(lat1, lon1, lat2, lon2) -> float:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


async def _postcodes(c: httpx.AsyncClient, pc: str, radius_m: float):
    r = await c.get(f"https://api.postcodes.io/postcodes/{pc.replace(' ', '')}")
    if r.status_code == 404:
        raise HTTPException(404, f"{pc} isn't a recognised UK postcode")
    r.raise_for_status()
    centre = r.json()["result"]
    if centre.get("country") not in ("England", "Wales"):
        raise HTTPException(400, "Sold prices are only available for England and Wales (HM Land Registry)")
    lat0, lon0 = centre["latitude"], centre["longitude"]
    # postcodes.io returns at most 100 postcodes per point, so cover the circle with a grid of lookups.
    step = 300 if radius_m <= 500 else 450 if radius_m <= 1700 else 1000
    n = int(radius_m // step) + 1
    pts = [{"latitude": lat0 + i * step / 111320, "longitude": lon0 + j * step / (111320 * math.cos(math.radians(lat0))), "radius": int(step * 0.72), "limit": 100}
           for i in range(-n, n + 1) for j in range(-n, n + 1) if math.hypot(i * step, j * step) <= radius_m + step]
    pcs = {centre["postcode"]: (lat0, lon0)}
    for i in range(0, len(pts), 100):
        r = await c.post("https://api.postcodes.io/postcodes", json={"geolocations": pts[i:i + 100]})
        r.raise_for_status()
        for q in r.json()["result"]:
            for x in q["result"] or []:
                if _dist(lat0, lon0, x["latitude"], x["longitude"]) <= radius_m:
                    pcs[x["postcode"]] = (x["latitude"], x["longitude"])
    return centre, pcs


async def _sales(c: httpx.AsyncClient, pcs: list, since: str) -> list:
    """Land Registry rate-limits bursts, so query in chunks two at a time and back off on 429."""
    sem = asyncio.Semaphore(2)

    async def one(part):
        async with sem:
            for attempt in range(5):
                try:
                    return await _sales_chunk(c, part, since)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code != 429 or attempt == 4:
                        raise
                    await asyncio.sleep(1.5 * (attempt + 1))
    parts = await asyncio.gather(*[one(pcs[i:i + 400]) for i in range(0, len(pcs), 400)])
    return [b for p in parts for b in p]


async def _sales_chunk(c: httpx.AsyncClient, pcs: list, since: str) -> list:
    values = " ".join('"' + p.replace('"', "") + '"' for p in pcs)
    q = f"""PREFIX lrppi: <http://landregistry.data.gov.uk/def/ppi/>
PREFIX lrcommon: <http://landregistry.data.gov.uk/def/common/>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?pc ?paon ?saon ?street ?amount ?date ?type ?newBuild ?estate WHERE {{
  VALUES ?pc {{ {values} }}
  ?addr lrcommon:postcode ?pc .
  ?tx lrppi:propertyAddress ?addr ; lrppi:pricePaid ?amount ; lrppi:transactionDate ?date ; lrppi:propertyType/skos:prefLabel ?type .
  OPTIONAL {{ ?addr lrcommon:paon ?paon }} OPTIONAL {{ ?addr lrcommon:saon ?saon }} OPTIONAL {{ ?addr lrcommon:street ?street }}
  OPTIONAL {{ ?tx lrppi:newBuild ?newBuild }} OPTIONAL {{ ?tx lrppi:estateType/skos:prefLabel ?estate }}
  FILTER(?date >= "{since}"^^xsd:date)
}} LIMIT 5000"""
    r = await c.post(SPARQL, data={"query": q}, headers={"Accept": "application/sparql-results+json"})
    r.raise_for_status()
    return r.json()["results"]["bindings"]


@router.get("/sold-prices")
async def sold_prices(postcode: str = Query(..., max_length=20), years: Literal["1", "2", "3", "5"] = "3",
                      miles: Literal["0.25", "0.5", "1", "2", "3", "5"] = "0.25", user: User = Depends(current_user)):
    pc = _norm(postcode.strip())
    if not PC_RE.match(pc):
        raise HTTPException(400, "Enter a full UK postcode, e.g. NG7 1AA")
    radius_m = round(float(miles) * MILE_M)
    key = f"{pc}|{years}|{miles}"
    await charge(user, "sold_prices", key)
    hit = await db.sold_price_cache.find_one({"key": key})
    if hit and hit["at"] > (datetime.now(timezone.utc) - timedelta(hours=CACHE_HOURS)).isoformat():
        return hit["data"]
    years = int(years)
    since = (date.today() - timedelta(days=365 * years)).isoformat()
    try:
        async with httpx.AsyncClient(timeout=40, headers={"User-Agent": "propertyplug/1.0 (support@mybuilder.app)"}) as c:
            centre, pcs = await _postcodes(c, pc, radius_m)
            rows = await _sales(c, list(pcs), since)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Sold prices lookup failed for {pc}: {e}")
        raise HTTPException(503, "Sold price data is temporarily unavailable. Please try again shortly")
    clat, clon = centre["latitude"], centre["longitude"]
    sales = []
    for b in rows:
        v = lambda k: b.get(k, {}).get("value", "")  # noqa: E731
        lat, lon = pcs[v("pc")]
        sales.append({"price": int(v("amount")), "date": v("date"), "type": TYPES.get(v("type"), "Other"), "postcode": v("pc"),
                      "address": ", ".join(x for x in [v("saon").title(), " ".join(x for x in [v("paon").title(), v("street").title()] if x)] if x),
                      "new_build": v("newBuild") == "true", "tenure": v("estate").title(), "lat": lat, "lon": lon,
                      "distance_m": round(_dist(clat, clon, lat, lon))})
    sales.sort(key=lambda s: s["date"], reverse=True)
    prices = [s["price"] for s in sales if s["type"] != "Other"]  # "Other" is commercial/bulk sales that skew the averages
    by_type = {}
    for t in TYPES.values():
        tp = [s["price"] for s in sales if s["type"] == t]
        if tp:
            by_type[t] = {"count": len(tp), "median": int(statistics.median(tp)), "avg": int(sum(tp) / len(tp))}
    data = {"postcode": centre["postcode"], "lat": clat, "lon": clon, "radius_m": radius_m, "miles": float(miles), "years": years, "since": since,
            "postcodes_searched": len(pcs), "sales": sales[:MAX_SALES], "truncated": len(sales) > MAX_SALES,
            "stats": {"count": len(prices), "median": int(statistics.median(prices)) if prices else 0, "avg": int(sum(prices) / len(prices)) if prices else 0,
                      "min": min(prices, default=0), "max": max(prices, default=0), "by_type": by_type},
            "source": "HM Land Registry Price Paid Data (Open Government Licence v3.0). Postcode locations: postcodes.io / ONS."}
    await db.sold_price_cache.update_one({"key": key}, {"$set": {"key": key, "at": datetime.now(timezone.utc).isoformat(), "data": data}}, upsert=True)
    return data
