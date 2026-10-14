from fastapi import APIRouter, HTTPException, Depends
from fastapi.concurrency import run_in_threadpool
from datetime import datetime, timezone, timedelta
import re, math, time
import requests
from core import db, logger, now_iso
from models import User
from deps import current_user

router = APIRouter()


TRADE_TERMS = {
    "electrician": ["electrician"],
    "plumber": ["plumber", "heating"],
    "builder": ["builders", "builder"],
    "carpenter": ["carpenter", "joinery"],
    "painter": ["painter", "decorator"],
    "roofer": ["roofer", "roofing"],
}
OSM_UA = {"User-Agent": "builder-assist/1.0 (support@mybuilder.app)"}
POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}$")


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def geocode_postcode(pc: str):
    r = requests.get(f"https://api.postcodes.io/postcodes/{pc.replace(' ', '%20')}", headers=OSM_UA, timeout=10)
    if r.status_code == 404:
        raise HTTPException(404, "Postcode not found")
    r.raise_for_status()
    res = r.json()["result"]
    return float(res["latitude"]), float(res["longitude"]), res["postcode"]


def overpass_search(lat, lon, trade):
    q = f'[out:json][timeout:15];nwr(around:8000,{lat},{lon})[craft="{trade}"];out center tags;'
    try:
        r = requests.post("https://overpass-api.de/api/interpreter", data={"data": q}, headers=OSM_UA, timeout=15)
        r.raise_for_status()
        out = []
        for e in r.json().get("elements", []):
            t = e.get("tags", {})
            pt = e.get("center", e)
            if not t.get("name") or "lat" not in pt:
                continue
            addr = " ".join(x for x in [t.get("addr:housenumber"), t.get("addr:street"), t.get("addr:city"), t.get("addr:postcode")] if x)
            out.append({"osm_id": f"{e['type']}/{e['id']}", "name": t["name"], "lat": float(pt["lat"]), "lon": float(pt["lon"]),
                        "phone": t.get("phone") or t.get("contact:phone") or t.get("mobile"),
                        "email": t.get("email") or t.get("contact:email"),
                        "website": t.get("website") or t.get("contact:website"), "address": addr})
        return out
    except Exception as e:
        logger.info(f"Overpass unavailable, falling back to Nominatim: {e}")
        return None


def nominatim_search(lat, lon, trade):
    out = []
    viewbox = f"{lon - 0.09},{lat + 0.055},{lon + 0.09},{lat - 0.055}"
    for i, term in enumerate(TRADE_TERMS[trade]):
        if i:
            time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec
        r = requests.get("https://nominatim.openstreetmap.org/search", headers=OSM_UA, timeout=15, params={
            "q": term, "format": "jsonv2", "limit": 25, "extratags": 1, "addressdetails": 1, "bounded": 1, "viewbox": viewbox})
        if r.status_code != 200:
            continue
        for e in r.json():
            if e.get("category") not in ("craft", "office", "building") or not e.get("name"):
                continue
            t = e.get("extratags") or {}
            a = e.get("address") or {}
            addr = " ".join(x for x in [a.get("house_number"), a.get("road"), a.get("city") or a.get("town") or a.get("suburb"), a.get("postcode")] if x)
            out.append({"osm_id": f"{e.get('osm_type')}/{e.get('osm_id')}", "name": e["name"], "lat": float(e["lat"]), "lon": float(e["lon"]),
                        "phone": t.get("phone") or t.get("contact:phone") or t.get("mobile"),
                        "email": t.get("email") or t.get("contact:email"),
                        "website": t.get("website") or t.get("contact:website"), "address": addr})
    return out


def find_trades(lat, lon, trade):
    found = overpass_search(lat, lon, trade)
    if found is None:
        found = nominatim_search(lat, lon, trade)
    seen, results = set(), []
    for f in found:
        if f["osm_id"] in seen:
            continue
        seen.add(f["osm_id"])
        f["trade"] = trade
        f["distance_km"] = round(haversine_km(lat, lon, f["lat"], f["lon"]), 2)
        results.append(f)
    return sorted(results, key=lambda x: x["distance_km"])[:30]


@router.get("/trades/search")
async def trades_search(postcode: str, trade: str = "electrician", user: User = Depends(current_user)):
    pc = " ".join(postcode.upper().split())
    if not POSTCODE_RE.match(pc):
        raise HTTPException(400, "Please enter a valid UK postcode")
    if trade not in TRADE_TERMS:
        raise HTTPException(400, "Unknown trade")
    key = f"{pc.replace(' ', '')}|{trade}"
    cached = await db.trade_cache.find_one({"key": key})
    if cached and datetime.fromisoformat(cached["fetched_at"]) > datetime.now(timezone.utc) - timedelta(hours=24):
        return {"postcode": cached["postcode"], "trade": trade, "results": cached["results"], "attribution": "© OpenStreetMap contributors"}
    try:
        lat, lon, norm = await run_in_threadpool(geocode_postcode, pc)
        results = await run_in_threadpool(find_trades, lat, lon, trade)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Trades search failed")
        raise HTTPException(503, f"Trades search is temporarily unavailable: {e}")
    await db.trade_cache.update_one({"key": key}, {"$set": {"key": key, "postcode": norm, "results": results, "fetched_at": now_iso()}}, upsert=True)
    return {"postcode": norm, "trade": trade, "results": results, "attribution": "© OpenStreetMap contributors"}
