"""Driving distance and time from the profile's address to each listing's area.

Marketplace only gives a place name ("Cherry Hill, NJ"), so each name is turned into a point
(OpenStreetMap Nominatim, remembered in the places table so it is only looked up once) and then
routed over the real road network (OSRM's public server, one batched request). The point is the
middle of that town, not the seller's door.
"""
import httpx

from . import db
from .geocode import geocode
from .log import log

OSRM = "https://router.project-osrm.org/table/v1/driving/"
CHUNK = 90          # the public OSRM server refuses tables much bigger than 100 points
NEW_LOOKUPS = 40    # new place names per export; Nominatim allows one a second
M_PER_MI = 1609.344


async def _point(name):
    row = db.q1("SELECT lat, lng FROM places WHERE name=?", (name.lower(),))
    if row:
        return row["lat"], row["lng"]
    found = await geocode(name, 1)
    if not found:
        return None
    db.ex("INSERT OR REPLACE INTO places (name, lat, lng) VALUES (?,?,?)", (name.lower(), found[0]["lat"], found[0]["lng"]))
    return found[0]["lat"], found[0]["lng"]


async def drives(origin, names):
    """origin: (lat, lng). names: place names. -> {name: (miles, minutes)}; places that can't be found or reached are left out."""
    todo = sorted({n.strip() for n in names if n and n.strip()}, key=str.lower)
    pts, fresh = {}, 0
    for n in todo:
        if not db.q1("SELECT 1 FROM places WHERE name=?", (n.lower(),)):
            if fresh >= NEW_LOOKUPS:
                continue
            fresh += 1
        p = await _point(n)
        if p:
            pts[n] = p
    out, items = {}, list(pts.items())
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "Kindling/1.0 (personal marketplace search)"}) as c:
        for i in range(0, len(items), CHUNK):
            part = items[i:i + CHUNK]
            coords = ";".join(f"{lng},{lat}" for lat, lng in [origin] + [p for _, p in part])
            try:
                r = await c.get(OSRM + coords, params={"sources": 0, "annotations": "duration,distance"})
                r.raise_for_status()
                data = r.json()
                secs, meters = data["durations"][0][1:], data["distances"][0][1:]
            except (httpx.HTTPError, ValueError, KeyError, IndexError) as e:
                log.warning("export: route lookup failed: %s", e)
                continue
            for (n, _), s, m in zip(part, secs, meters):
                if s is not None and m is not None:
                    out[n] = (m / M_PER_MI, s / 60)
    return out
