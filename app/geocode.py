"""Street-address lookup (OpenStreetMap Nominatim).

The marketplace sources only know city names, so an address typed into the
profile's location box finds nothing there. This turns it into coordinates,
which only the coordinate-based source (ScrapeCreators) can use. Nominatim's
policy allows one request a second, so calls are spaced and repeats cached.
"""
import asyncio
import time

import httpx

NOMINATIM = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "Kindling/1.0 (personal marketplace search)"}

_lock = asyncio.Lock()
_last = 0.0
_cache = {}


async def geocode(text: str, limit: int = 4) -> list:
    global _last
    text = " ".join(text.split())
    if not text:
        return []
    key = text.lower()
    if key in _cache:
        return _cache[key]
    async with _lock:
        wait = 1.1 - (time.monotonic() - _last)
        if wait > 0:
            await asyncio.sleep(wait)
        _last = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=10, headers=HEADERS) as c:
                r = await c.get(NOMINATIM, params={
                    "q": text, "format": "jsonv2", "limit": limit, "addressdetails": 0})
                r.raise_for_status()
                rows = r.json()
        except (httpx.HTTPError, ValueError):
            return []
    found = [{"name": row["display_name"], "subtitle": "Address match",
              "lat": float(row["lat"]), "lng": float(row["lon"])}
             for row in rows if row.get("lat") and row.get("lon")]
    if len(_cache) > 200:
        _cache.clear()
    _cache[key] = found
    return found
