"""Orbit's JSON API, mounted under /api/o. The signed-in check is the app-wide middleware's."""
import asyncio
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import auth, db, events, orbit, pipeline

router = APIRouter(prefix="/api/o")
_tasks = set()


def me():
    u = auth.current_user.get()
    if not u:
        raise HTTPException(401, "Sign in with an invite code")
    return u


def system(pid=None):
    u = me()
    p = db.q1("SELECT * FROM profiles WHERE id=? AND user_id=?", (pid, u["id"])) if pid else db.active_profile(u["id"])
    if not p:
        raise HTTPException(404, "System not found")
    return p


def guard(fn, *a, **k):
    try:
        return fn(*a, **k)
    except orbit.OrbitError as e:
        raise HTTPException(e.status, str(e))


def after(result):
    """A batch that has just been fully placed gets the same wrap-up the swipe screen used to trigger."""
    if result.get("batch_done"):
        b = db.q1("SELECT id FROM batches WHERE profile_id IN (SELECT id FROM profiles WHERE user_id=?) AND status='done' "
                  "ORDER BY finished_at DESC LIMIT 1", (me()["id"],))
        if b:
            t = asyncio.create_task(pipeline.finish(b["id"]))
            _tasks.add(t)
            t.add_done_callback(_tasks.discard)
    return result


@router.get("/state")
def state():
    return orbit.state(me(), system())


class PlaceIn(BaseModel):
    listing_id: int
    r: float
    theta: float
    sun: int = 0


@router.post("/place")
async def place(body: PlaceIn):
    return after(guard(orbit.place, me(), body.listing_id, body.r, body.theta, body.sun))


class UndoIn(BaseModel):
    placement_id: int


@router.post("/undo")
def undo(body: UndoIn):
    return guard(orbit.undo, me(), body.placement_id)


class RocketIn(BaseModel):
    listing_id: int
    planet_id: int


@router.post("/rocket")
async def rocket(body: RocketIn):
    return after(guard(orbit.rocket, me(), body.listing_id, body.planet_id))


class PlanetIn(BaseModel):
    name: str
    description: str = ""
    orbit: str = "Mid"
    reason: str = "other"
    listing_ids: List[int] = []


@router.post("/planets")
def create_planet(body: PlanetIn):
    u, s = me(), system()
    return guard(orbit.create_planet, u, s, body.name, body.description, body.orbit, body.reason, body.listing_ids)


@router.delete("/planets/{pid}")
def delete_planet(pid: int):
    guard(orbit.delete_planet, me(), pid)
    return {"ok": True}


@router.get("/planets/suggest")
def suggest(name: str = "", description: str = ""):
    return orbit.suggest_moons(me(), system(), name, description)


@router.get("/listing/{lid}")
def listing(lid: int):
    l = guard(orbit.my_listing, me(), lid)
    out = orbit.card(l)
    cur = orbit.current(lid)
    out["placement"] = None if not cur else {"id": cur["id"], "r": cur["r"], "theta": cur["theta"], "kind": cur["kind"],
                                             "origin": cur["origin"], "reasons": cur["reasons"] or None}
    out["planets"] = db.q("SELECT pl.id, pl.name FROM planets pl JOIN planet_members pm ON pm.planet_id=pl.id WHERE pm.listing_id=?", (lid,))
    return out


# --------------------------------------------------------------------------- galaxy

@router.get("/galaxy")
def galaxy():
    return orbit.galaxy(me())


class SystemIn(BaseModel):
    source_id: int
    name: str
    hunt: str
    listing_ids: List[int] = []


@router.post("/systems")
def create_system(body: SystemIn):
    return guard(orbit.create_system, me(), body.source_id, body.name, body.hunt, body.listing_ids)


@router.post("/systems/{pid}/activate")
def activate(pid: int):
    guard(orbit.activate, me(), pid)
    return {"ok": True}


@router.post("/systems/{pid}/found")
def found(pid: int):
    guard(orbit.found_it, me(), pid)
    return {"ok": True}


@router.post("/systems/{pid}/reopen")
def reopen(pid: int):
    guard(orbit.found_it, me(), pid, True)
    return {"ok": True}


# --------------------------------------------------------------------------- binary stars and events

class BinaryIn(BaseModel):
    names: List[str]
    groups: List[List[int]]


@router.post("/systems/{pid}/binary")
def binary(pid: int, body: BinaryIn):
    guard(orbit.make_binary, me(), pid, body.names, body.groups)
    return {"ok": True}


@router.delete("/systems/{pid}/binary")
def unbinary(pid: int):
    guard(orbit.end_binary, me(), pid)
    return {"ok": True}


@router.get("/events/next")
def next_event():
    s = system()
    st = orbit.state(me(), s)
    if not st["events_ready"]:
        return None
    e = events.next_event(s["id"])
    if e["status"] == "queued":
        db.ex("UPDATE events SET status='shown', shown_at=? WHERE id=?", (db.now(), e["id"]))
    ev = e["evidence"] or {}
    photos = {r["id"]: (r["photos"] or [None])[0] for r in db.q("SELECT id, photos FROM listings WHERE profile_id=?", (s["id"],))}
    titles = {r["id"]: r["title"] for r in db.q("SELECT id, title FROM listings WHERE profile_id=?", (s["id"],))}
    pick = lambda ids, n=3: [{"id": i, "photo": photos.get(i), "title": titles.get(i)} for i in ids[:n]]
    view = {"id": e["id"], "kind": e["kind"], "title": e["title"], "body": e["body"], "basis": ev.get("basis"), "system": s["name"]}
    if e["kind"] == "black_hole":
        view["groups"] = [{"name": g["name"], "n": len(g["ids"]), "thumbs": pick(g["ids"])} for g in ev["groups"]]
    elif e["kind"] == "new_star":
        view["n"], view["tag"], view["thumbs"] = ev["n"], ev["tag"], pick(ev["ids"], 4)
    elif e["kind"] == "dwarf_planet":
        view["planet"], view["trait"] = ev["planet"], ev["trait"]
    elif e["kind"] == "asteroid_shower":
        view.update({"belt": ev["belt"], "cap": ev["cap"], "explained": len(ev["explained"]), "unexplained": len(ev["unexplained"]), "why": ev["why"],
                     "burn": pick(ev["explained"], 4), "stay": pick(ev["unexplained"], 4), "group": None if not ev.get("group") else
                     {"tag": ev["group"]["tag"], "n": len(ev["group"]["ids"]), "thumbs": pick(ev["group"]["ids"], 4)}})
    elif e["kind"] == "outlier":
        view.update({"listing": pick([ev["id"]], 1)[0], "predicted": ev["predicted"], "actual": ev["actual"]})
    return view


class ResolveIn(BaseModel):
    action: str
    name: Optional[str] = None
    hunt: Optional[str] = None


@router.post("/events/{eid}/resolve")
def resolve_event(eid: int, body: ResolveIn):
    return guard(events.resolve, me(), eid, body.action, body.name, body.hunt)


@router.get("/recap")
def recap_latest():
    return guard(orbit.recap, me(), None)


@router.get("/recap/{bid}")
def recap(bid: int):
    return guard(orbit.recap, me(), bid)
