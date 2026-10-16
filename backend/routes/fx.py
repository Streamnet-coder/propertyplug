"""Live FX rates (Frankfurter, no key) cached in Mongo, and a portfolio overview converted to the user's home currency."""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import get_args

import httpx
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import db, logger
from deps import current_user
from models import Currency, Project, User
from routes.projects import project_summaries

router = APIRouter()

CODES = list(get_args(Currency))
CACHE_TTL = timedelta(hours=6)


async def get_rates() -> dict:
    """GBP-based rates {code: rate}; refreshed every 6h, falls back to the last cached copy if the provider is down."""
    cached = await db.fx_rates.find_one({"_id": "GBP"})
    now = datetime.now(timezone.utc)
    if cached and datetime.fromisoformat(cached["fetched_at"]) + CACHE_TTL > now:
        return cached
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get("https://api.frankfurter.dev/v2/rates", params={"base": "GBP", "quotes": ",".join(x for x in CODES if x != "GBP")})
            r.raise_for_status()
            rows = r.json()
        rates = {"GBP": 1.0, **{row["quote"]: float(row["rate"]) for row in rows}}
        if set(CODES) - rates.keys():
            raise ValueError(f"missing {set(CODES) - rates.keys()}")
        doc = {"_id": "GBP", "rates": rates, "rate_date": max(row["date"] for row in rows), "fetched_at": now.isoformat()}
        await db.fx_rates.replace_one({"_id": "GBP"}, doc, upsert=True)
        return doc
    except Exception as e:
        logger.warning(f"FX fetch failed: {e}")
        if cached:
            return {**cached, "stale": True}
        raise HTTPException(503, "Exchange rates are unavailable right now")


@router.get("/fx/rates")
async def fx_rates(_: User = Depends(current_user)):
    d = await get_rates()
    return {"base": "GBP", "rates": d["rates"], "rate_date": d["rate_date"], "stale": d.get("stale", False)}


class HomeIn(BaseModel):
    currency: Currency


@router.put("/portfolio/home-currency")
async def set_home_currency(body: HomeIn, user: User = Depends(current_user)):
    await db.users.update_one({"_id": ObjectId(user.id)}, {"$set": {"home_currency": body.currency}})
    return {"home_currency": body.currency}


@router.get("/portfolio/map")
async def portfolio_map(user: User = Depends(current_user)):
    """Every project with a map pin. Addresses are geocoded once via Nominatim (cached on the project); manual pins win."""
    active = (await db.users.find_one({"_id": ObjectId(user.id)}, {"active_project_id": 1}) or {}).get("active_project_id")
    docs = await db.projects.find({"user_id": user.id}, {"comparables": 0}).sort("_id", 1).to_list(500)
    todo = [d for d in docs if d.get("address", "").strip() and (d.get("geocoded_for") != d["address"] or "country" not in d)]
    if todo:
        async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "builder-assist/1.0 (support@mybuilder.app)"}) as c:
            for i, d in enumerate(todo[:10]):  # Nominatim policy: max 1 req/sec; cap per call
                if i:
                    await asyncio.sleep(1.1)
                lat = lon = country = None
                try:
                    r = await c.get("https://nominatim.openstreetmap.org/search", params={"q": d["address"], "format": "json", "limit": 1, "addressdetails": 1, "accept-language": "en"})
                    r.raise_for_status()
                    hit = r.json()
                    if hit:
                        lat, lon = float(hit[0]["lat"]), float(hit[0]["lon"])
                        country = (hit[0].get("address") or {}).get("country")
                except Exception as e:
                    logger.warning(f"Geocode failed for {d['_id']}: {e}")
                    continue  # retry next time
                upd = {"geocoded_for": d["address"], "country": country}
                if not d.get("pin_manual"):  # manual pins keep their coordinates; we only learn the country
                    upd.update(lat=lat, lon=lon)
                d.update(upd)
                await db.projects.update_one({"_id": d["_id"]}, {"$set": upd})
    summaries = {s["id"]: s for s in await project_summaries([Project.from_mongo(d) for d in docs])}
    countries = {str(d["_id"]): d.get("country") for d in docs}
    return [{"id": s["id"], "name": s["name"], "address": s["address"], "lat": s["lat"], "lon": s["lon"], "pin_manual": s["pin_manual"],
             "country": countries[s["id"]] or None,
             "property_type": s["property_type"], "currency": s["currency"], "total_spent": s["total_spent"], "total_budget": s["total_budget"],
             "purchase_price": s["purchase_price"],
             "estimated_valuation": s["estimated_valuation"], "active": s["id"] == active} for s in summaries.values()]


@router.get("/portfolio")
async def portfolio(user: User = Depends(current_user)):
    home = (await db.users.find_one({"_id": ObjectId(user.id)}, {"home_currency": 1}) or {}).get("home_currency") or "GBP"
    docs = await db.projects.find({"user_id": user.id}, {"comparables": 0}).to_list(500)
    summaries = await project_summaries([Project.from_mongo(d) for d in docs])
    fx = await get_rates()
    rates = fx["rates"]
    keys = ("purchase_price", "estimated_valuation", "total_budget", "total_spent")
    totals = {k: 0.0 for k in keys}
    by_currency: dict = {}
    for s in summaries:
        cur = s.get("currency") or "GBP"
        factor = rates[home] / rates[cur]
        g = by_currency.setdefault(cur, {"currency": cur, "projects": 0, "rate_to_home": round(factor, 6), **{k: 0.0 for k in keys}})
        g["projects"] += 1
        for k in keys:
            g[k] = round(g[k] + s[k], 2)
            totals[k] += s[k] * factor
    return {"home_currency": home, "rate_date": fx["rate_date"], "stale": fx.get("stale", False), "projects": len(summaries),
            "land_count": sum(1 for s in summaries if s.get("property_type") == "land"),
            "totals": {k: round(v, 2) for k, v in totals.items()}, "by_currency": list(by_currency.values())}
