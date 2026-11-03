"""Kindling: Tinder-style swiping for Facebook Marketplace. FastAPI app + JSON API."""
import asyncio
import re
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, config, costs, crystal, db, learn, migrate_orbit, orbit, orbit_api, orbit_math, pipeline, route, spending, vibe, xlsx
from .geocode import geocode
from .log import log, recent as recent_logs
from .sources import SourceError, get_source

app = FastAPI(title="Orbit")
db.init()


@app.on_event("startup")
def _on_startup():
    db.recover_interrupted()
    if migrate_orbit.is_migrated():  # swipes made in the old screen since the last run become placements
        migrate_orbit.sync()
    log.info("Orbit started: source=%s brain=%s", config.source_mode(), config.brain_mode())


app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


class _ImmutableFiles(StaticFiles):
    """Cached listing photos never change, so let the phone keep them."""

    async def get_response(self, path, scope):
        res = await super().get_response(path, scope)
        if res.status_code == 200:
            res.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return res


app.mount("/img", _ImmutableFiles(directory=config.IMG_DIR), name="img")

app.include_router(orbit_api.router)

OPEN_PATHS = ("/api/auth/",)  # everything else under /api and /img needs a signed-in device


CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "connect-src 'self'; font-src 'self'; manifest-src 'self'; worker-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """The client never talks to anything but this app: no outside fonts, scripts, images or beacons."""
    res = await call_next(request)
    res.headers.setdefault("Content-Security-Policy", CSP)
    res.headers.setdefault("X-Content-Type-Options", "nosniff")
    res.headers.setdefault("Referrer-Policy", "same-origin")
    return res


@app.middleware("http")
async def signed_in(request: Request, call_next):
    path = request.url.path
    if (path.startswith("/api/") or path.startswith("/img/")) and not path.startswith(OPEN_PATHS):
        user = auth.user_for_token(auth.token_from(request.cookies))
        if not user:
            return JSONResponse({"detail": "Sign in with an invite code", "auth": True}, status_code=401)
        auth.current_user.set(user)
        res = await call_next(request)
        legacy = request.cookies.get(auth.LEGACY_COOKIE)
        if legacy and not request.cookies.get(auth.COOKIE):   # signed in before the rename: carry the same session over
            res.set_cookie(auth.COOKIE, legacy, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                           secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https")
            # the old cookie is left alone: browsers share cookies across ports on one host, so Kindling may still need it
        return res
    return await call_next(request)


@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/legacy")
def legacy():
    """The Kindling-era screens Orbit hasn't replaced (profile, people, spending, vibe hunts, export)."""
    return FileResponse(config.STATIC_DIR / "legacy.html", headers={"Cache-Control": "no-cache"})


@app.get("/sw.js")
def service_worker():
    return FileResponse(config.STATIC_DIR / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(config.STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


# --------------------------------------------------------------------------- helpers

def _me():
    u = auth.current_user.get()
    if not u:
        raise HTTPException(401, "Sign in with an invite code")
    return u


def _admin():
    u = _me()
    if u["role"] != "admin":
        raise HTTPException(403, "Only the admin can do that")
    return u


def _my_profile_ids():
    return {r["id"] for r in db.q("SELECT id FROM profiles WHERE user_id=?", (_me()["id"],))}


def _profile(pid=None):
    me = _me()
    p = db.q1("SELECT * FROM profiles WHERE id=? AND user_id=?", (pid, me["id"])) if pid else db.active_profile(me["id"])
    if not p:
        raise HTTPException(404, "Hunt not found")
    return p


def _listing(lid):
    l = db.q1("SELECT l.*, s.verdict, s.rank, s.manual FROM listings l LEFT JOIN swipes s ON s.listing_id=l.id "
              "WHERE l.id=?", (lid,))
    if not l or l["profile_id"] not in _my_profile_ids():
        raise HTTPException(404, "Listing not found")
    l["groups"] = db.q("SELECT g.id, g.label FROM groups g JOIN group_members gm ON gm.group_id=g.id "
                       "WHERE gm.listing_id=?", (lid,))
    return l


def _batch_full(bid):
    b = db.q1("SELECT * FROM batches WHERE id=?", (bid,))
    if not b or b["profile_id"] not in _my_profile_ids():
        raise HTTPException(404, "Batch not found")
    b["listings"] = db.q(
        "SELECT l.*, s.verdict, s.rank, s.manual FROM listings l LEFT JOIN swipes s ON s.listing_id=l.id "
        "WHERE l.batch_id=? ORDER BY l.position", (bid,))
    b["swiped"] = sum(1 for l in b["listings"] if l["verdict"])
    return b


def _group(gid):
    g = db.q1("SELECT * FROM groups WHERE id=?", (gid,))
    if not g or g["profile_id"] not in _my_profile_ids():
        raise HTTPException(404, "Category not found")
    return g


def _current_batch(pid):
    return db.q1("SELECT * FROM batches WHERE profile_id=? AND status!='done' ORDER BY id DESC LIMIT 1", (pid,))


def _me_public(u):
    return {"id": u["id"], "name": u["name"], "role": u["role"], "budget": costs.budget(u)}


# --------------------------------------------------------------------------- accounts

class RedeemIn(BaseModel):
    code: str
    name: Optional[str] = None


def _client_ip(request: Request):
    host = request.client.host if request.client else "?"
    fwd = request.headers.get("x-forwarded-for", "")
    if host in ("127.0.0.1", "::1") and fwd:  # behind our own proxy: the last hop it added is the real client
        return fwd.split(",")[-1].strip() or host
    return host


@app.get("/api/auth/invite/{code}")
def invite_info(code: str, request: Request):
    ip = _client_ip(request)
    try:
        auth.throttle(ip)
    except auth.AuthError as e:
        raise HTTPException(429, str(e))
    info = auth.peek_invite(code)
    if not info:
        auth.failed(ip)
        raise HTTPException(404, "That code isn't valid anymore. Ask for a new one.")
    return info


@app.post("/api/auth/redeem")
def redeem(body: RedeemIn, request: Request):
    ip = _client_ip(request)
    try:
        auth.throttle(ip)
    except auth.AuthError as e:
        raise HTTPException(429, str(e))  # a locked-out client doesn't extend its own lockout
    try:
        user, token = auth.redeem(body.code, body.name, request.headers.get("user-agent", ""))
    except auth.AuthError as e:
        auth.failed(ip)
        raise HTTPException(400, str(e))
    log.info("user %s (%s) signed in a device with an invite", user["id"], user["name"])
    resp = JSONResponse({"ok": True, "name": user["name"]})
    resp.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                    secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https")
    return resp


@app.post("/api/auth/logout")
def logout(request: Request):
    auth.end_session(auth.token_from(request.cookies))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE)
    return resp


@app.get("/api/me")
def me():
    return _me_public(_me())


class InviteIn(BaseModel):
    for_me: bool = False             # sign another of my own devices in
    claude_cap: Optional[float] = auth.DEFAULT_FRIEND_CAP


@app.post("/api/admin/invites")
def make_invite(body: InviteIn):
    a = _admin()
    if body.for_me:
        code = auth.create_invite(role="admin", claude_cap=None, for_user_id=a["id"], created_by=a["id"])
    else:
        cap = None if body.claude_cap is None else max(0.0, float(body.claude_cap))
        code = auth.create_invite(role="user", claude_cap=cap, created_by=a["id"])
    return {"code": code, "expires_days": auth.INVITE_DAYS}


@app.get("/api/admin/users")
def list_users():
    _admin()
    out = []
    week = costs.week_start().timestamp()
    for u in db.q("SELECT * FROM users ORDER BY id"):
        pids = [r["id"] for r in db.q("SELECT id FROM profiles WHERE user_id=?", (u["id"],))]
        marks = ",".join("?" * len(pids)) or "NULL"
        credits_week = db.q1(f"SELECT COALESCE(SUM(credits_used),0) c FROM batches WHERE profile_id IN ({marks}) "
                             f"AND created_at>=?", (*pids, week))["c"] if pids else 0
        out.append({"id": u["id"], "name": u["name"], "role": u["role"], "disabled": bool(u["disabled"]),
                    "last_seen": u["last_seen"], "budget": costs.budget(u),
                    "claude_total": round(costs.spent(u["id"], since=costs.week_start().replace(year=2000)), 4),
                    "scrape_credits_week": credits_week,
                    "devices": db.q1("SELECT COUNT(*) n FROM sessions WHERE user_id=?", (u["id"],))["n"]})
    return out


class UserAdminIn(BaseModel):
    claude_cap: Optional[float] = None
    no_cap: bool = False
    disabled: Optional[bool] = None
    sign_out: bool = False


@app.put("/api/admin/users/{uid}")
def admin_user(uid: int, body: UserAdminIn):
    a = _admin()
    u = db.q1("SELECT * FROM users WHERE id=?", (uid,))
    if not u:
        raise HTTPException(404, "No such person")
    if uid == a["id"] and (body.disabled or body.sign_out):
        raise HTTPException(400, "You can't lock yourself out")
    if body.no_cap:
        db.ex("UPDATE users SET claude_cap=NULL WHERE id=?", (uid,))
    elif body.claude_cap is not None:
        db.ex("UPDATE users SET claude_cap=? WHERE id=?", (max(0.0, body.claude_cap), uid))
    if body.disabled is not None:
        db.ex("UPDATE users SET disabled=? WHERE id=?", (int(body.disabled), uid))
        if body.disabled:
            auth.end_all_sessions(uid)
    if body.sign_out:
        auth.end_all_sessions(uid)
    return {"ok": True}


# --------------------------------------------------------------------------- state

@app.get("/api/state")
def state():
    u = _me()
    p = _profile()
    cur = _current_batch(p["id"])
    totals = db.q1(
        "SELECT COUNT(*) swipes, SUM(CASE WHEN s.verdict='like' THEN 1 ELSE 0 END) likes FROM swipes s "
        "JOIN listings l ON l.id=s.listing_id WHERE l.profile_id=? AND l.state='web'", (p["id"],))
    recent_likes = db.q(
        "SELECT l.id, l.photos FROM listings l JOIN swipes s ON s.listing_id=l.id WHERE l.profile_id=? "
        "AND s.verdict='like' AND l.state='web' ORDER BY s.swiped_at DESC LIMIT 8", (p["id"],))
    in_web = learn.web_count(p["id"])
    last = db.q1("SELECT modifiers FROM batches WHERE profile_id=? ORDER BY id DESC LIMIT 1", (p["id"],))
    return {
        "last_modifiers": (last or {}).get("modifiers") or [],
        "me": _me_public(u),
        "profile": p,
        "mode": {"source": config.source_mode(), "brain": config.brain_mode()},
        "current": _batch_full(cur["id"]) if cur else None,
        "batches_done": db.q1("SELECT COUNT(*) n FROM batches WHERE profile_id=? AND status='done'", (p["id"],))["n"],
        "totals": {"swipes": totals["swipes"] or 0, "likes": totals["likes"] or 0},
        "recent_likes": [{"id": r["id"], "thumb": (r["photos"] or [None])[0]} for r in recent_likes],
        "web": {"count": in_web, "limit": learn.WEB_LIMIT, "locked": in_web >= learn.WEB_LIMIT},
        "crystals": db.q1("SELECT COUNT(*) n FROM crystals WHERE profile_id=?", (p["id"],))["n"],
        "keepers": db.q1("SELECT COUNT(*) n FROM listings WHERE profile_id=? AND keeper=1", (p["id"],))["n"],
    }


# --------------------------------------------------------------------------- profiles (hunts)

class ProfileIn(BaseModel):
    name: Optional[str] = None
    hunt: Optional[str] = None
    criteria: Optional[List[str]] = None
    must_have: Optional[List[str]] = None  # checklist items where an answer of "no" removes the listing
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    location_name: Optional[str] = None
    location_slug: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    radius_km: Optional[float] = None
    batch_size: Optional[int] = None


@app.get("/api/profiles")
def profiles():
    return db.q("SELECT id, name, hunt, active FROM profiles WHERE user_id=? ORDER BY id", (_me()["id"],))


@app.post("/api/profiles")
def create_profile(body: ProfileIn):
    me = _me()
    cur = _profile()
    pid = db.ex(
        "INSERT INTO profiles (name, hunt, criteria, min_price, max_price, location_name, location_slug, lat, lng, "
        "radius_km, batch_size, user_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (body.name or "New hunt", body.hunt or "", db.dumps(body.criteria or []), body.min_price, body.max_price,
         body.location_name or cur["location_name"], body.location_slug or cur["location_slug"],
         body.lat if body.lat is not None else cur["lat"], body.lng if body.lng is not None else cur["lng"],
         body.radius_km or cur["radius_km"], body.batch_size or cur["batch_size"], me["id"], db.now()))
    activate(pid)
    return _profile(pid)


@app.put("/api/profiles/{pid}")
def update_profile(pid: int, body: ProfileIn):
    _profile(pid)
    data = body.model_dump(exclude_unset=True)
    for k in ("name", "hunt", "criteria", "must_have", "location_name", "location_slug", "lat", "lng", "radius_km", "batch_size"):
        if k in data and data[k] is None:
            del data[k]  # these columns can't be empty; null means "leave it"
    if "name" in data:
        data["name"] = data["name"].strip() or _profile(pid)["name"]
    if "lat" in data and not -90 <= data["lat"] <= 90:
        raise HTTPException(400, "Latitude must be between -90 and 90")
    if "lng" in data and not -180 <= data["lng"] <= 180:
        raise HTTPException(400, "Longitude must be between -180 and 180")
    if "radius_km" in data:
        data["radius_km"] = max(1.0, min(500.0, data["radius_km"]))
    if "batch_size" in data and data["batch_size"]:
        data["batch_size"] = max(3, min(40, int(data["batch_size"])))
    if "criteria" in data:
        data["criteria"] = [c.strip() for c in data["criteria"] or [] if c.strip()]
    if "criteria" in data or "must_have" in data:  # must-haves are always a subset of the checklist
        current = _profile(pid)
        crit = data.get("criteria", current["criteria"])
        wanted = data["must_have"] if "must_have" in data else current["must_have"]
        want = {m.strip().lower() for m in wanted or []}
        data["must_have"] = db.dumps([c for c in crit if c.lower() in want])
        data["criteria"] = db.dumps(crit)
    if data:
        db.ex(f"UPDATE profiles SET {', '.join(f'{k}=?' for k in data)} WHERE id=?", [*data.values(), pid])
    return _profile(pid)


@app.post("/api/profiles/{pid}/activate")
def activate(pid: int):
    _profile(pid)
    me = _me()
    with db.tx() as c:
        c.execute("UPDATE profiles SET active=0 WHERE user_id=?", (me["id"],))
        c.execute("UPDATE profiles SET active=1 WHERE id=?", (pid,))
    return {"ok": True}


class LocateIn(BaseModel):
    text: str


@app.post("/api/locate")
async def locate(body: LocateIn):
    try:
        locs, _ = await get_source().locate(body.text)
    except SourceError as e:
        # still let a street address through when the source lookup is down
        found = await geocode(body.text) if config.source_mode() != "apify" else []
        if not found:
            raise HTTPException(502, str(e))
        return found
    if config.source_mode() == "apify":
        return locs[:6]  # Apify searches by Facebook city slug, which a street address can't give it
    return (locs[:4] + await geocode(body.text))[:8]


# --------------------------------------------------------------------------- vibe hunts

class VibeText(BaseModel):
    text: str = ""


class VibeImage(BaseModel):
    data: str


class VibeLink(BaseModel):
    url: str


class VibeDraft(BaseModel):
    hunt: str = ""
    criteria: List[str] = []
    min_price: Optional[float] = None
    max_price: Optional[float] = None


class VibeReact(BaseModel):
    id: str
    reaction: Optional[str] = None
    why: List[str] = []
    note: str = ""


def _vibe(pid):
    _profile(pid)  # ownership check
    return vibe.ensure(pid)


def _vibe_call(fn, *a):
    try:
        return fn(*a)
    except vibe.VibeError as e:
        raise HTTPException(409, str(e))


def _claude_ok():
    b = costs.budget(_me())
    if config.brain_mode() == "claude" and b["over"]:
        raise HTTPException(409, f"You've used this week's ${b['cap']:.2f} of Claude. It resets {b['resets_label']}.")


@app.get("/api/vibe/{pid}")
def get_vibe(pid: int):
    _profile(pid)  # ownership check; asking never creates a vibe
    v = vibe.get(pid)
    return vibe.view(v) if v else {"status": "none"}


@app.put("/api/vibe/{pid}")
def save_vibe_text(pid: int, body: VibeText):
    v = _vibe(pid)
    if v["status"] in ("inputs", "drafted"):
        vibe._set(pid, text=body.text[:2000])
    return vibe.view(vibe.get(pid))


@app.post("/api/vibe/{pid}/image")
def vibe_image(pid: int, body: VibeImage):
    _vibe(pid)
    _vibe_call(vibe.add_image, pid, body.data)
    return vibe.view(vibe.get(pid))


@app.post("/api/vibe/{pid}/link")
async def vibe_link(pid: int, body: VibeLink):
    _vibe(pid)
    try:
        await vibe.add_link(pid, body.url)
    except vibe.VibeError as e:
        raise HTTPException(409, str(e))
    return vibe.view(vibe.get(pid))


@app.delete("/api/vibe/{pid}/source/{sid}")
def vibe_remove(pid: int, sid: str):
    _vibe(pid)
    _vibe_call(vibe.remove_source, pid, sid)
    return vibe.view(vibe.get(pid))


@app.post("/api/vibe/{pid}/analyze")
async def vibe_analyze(pid: int, body: VibeText):
    v = _vibe(pid)
    if v["status"] not in ("inputs", "drafted"):
        raise HTTPException(409, "This vibe is already past that step.")
    text = body.text.strip()
    if not text and not any(s["images"] or s["text"] for s in v["sources"]):
        raise HTTPException(400, "Describe the vibe, or add a photo or link, so there's something to go on.")
    _claude_ok()
    vibe._set(pid, status="analyzing", progress="Reading your references", error=None, text=text[:2000],
              draft={}, readings=[])
    vibe.start(pid, vibe.analyze)
    return vibe.view(vibe.get(pid))


@app.put("/api/vibe/{pid}/draft")
def vibe_draft(pid: int, body: VibeDraft):
    v = _vibe(pid)
    _vibe_call(vibe._need, v, "drafted")
    d = {**v["draft"], "hunt": body.hunt.strip()[:1200], "criteria": [c.strip()[:80] for c in body.criteria if c.strip()][:10],
         "min_price": body.min_price, "max_price": body.max_price}
    vibe._set(pid, draft=d)
    return vibe.view(vibe.get(pid))


@app.delete("/api/vibe/{pid}/reading/{rid}")
def vibe_drop_reading(pid: int, rid: str):
    _vibe(pid)
    _vibe_call(vibe.remove_reading, pid, rid)
    return vibe.view(vibe.get(pid))


@app.post("/api/vibe/{pid}/hone")
async def vibe_hone(pid: int):
    v = _vibe(pid)
    _vibe_call(vibe._need, v, "drafted")
    if v["honed"]:
        raise HTTPException(409, "This hunt has already been honed. You get one hone per hunt.")
    _claude_ok()
    vibe._set(pid, status="fetching", progress="Starting", error=None)
    vibe.start(pid, vibe.build_hone)
    return vibe.view(vibe.get(pid))


@app.post("/api/vibe/{pid}/react")
def vibe_react(pid: int, body: VibeReact):
    _vibe(pid)
    _vibe_call(vibe.react, pid, body.id, body.reaction, body.why, body.note)
    return vibe.view(vibe.get(pid))


@app.post("/api/vibe/{pid}/refine")
async def vibe_refine(pid: int):
    v = _vibe(pid)
    _vibe_call(vibe._need, v, "hone")
    rated = [i for i in v["items"] if i.get("reaction")]
    if not rated:
        raise HTTPException(400, "React to at least one listing first.")
    if any(not i["why"] and not i["note"] for i in rated):
        raise HTTPException(400, "Say why for each reaction: pick a reason, \"Not sure\", or write a note.")
    _claude_ok()
    vibe._set(pid, status="refining", progress="Sharpening your hunt", error=None)
    vibe.start(pid, vibe.refine)
    return vibe.view(vibe.get(pid))


@app.post("/api/vibe/{pid}/apply")
def vibe_apply(pid: int, body: VibeDraft):
    _vibe(pid)
    _vibe_call(vibe.apply, pid, body.hunt, body.criteria, body.min_price, body.max_price)
    return {"profile": _profile(pid), "vibe": vibe.view(vibe.get(pid))}


@app.post("/api/vibe/{pid}/web")
def vibe_to_web(pid: int):
    _vibe(pid)
    n = _vibe_call(vibe.add_to_web, pid)
    return {"added": n, "vibe": vibe.view(vibe.get(pid))}


# --------------------------------------------------------------------------- batches

class BatchIn(BaseModel):
    size: Optional[int] = None
    weirdness: Optional[int] = None
    modifiers: Optional[List[str]] = None  # extras for this batch only, never saved to the hunt


@app.post("/api/batches")
async def new_batch(body: BatchIn):
    me = _me()
    p = _profile()
    if (p.get("state") or "active") == "finished":
        raise HTTPException(409, "This hunt is finished. Reopen it from the Galaxy to keep going.")
    cur = _current_batch(p["id"])
    if cur and cur["status"] != "error":
        return _batch_full(cur["id"])
    b = costs.budget(me)
    if config.brain_mode() == "claude" and b["over"]:
        raise HTTPException(409, f"You've used this week's ${b['cap']:.2f} of Claude. It resets {b['resets_label']}.")
    if cur:  # retire a failed batch so a fresh one can start
        db.ex("UPDATE batches SET status='done', finished_at=? WHERE id=?", (db.now(), cur["id"]))
    size = max(3, min(40, body.size or p["batch_size"]))
    weird = max(0, min(100, body.weirdness if body.weirdness is not None else p["weirdness"]))
    db.ex("UPDATE profiles SET batch_size=?, weirdness=? WHERE id=?", (size, weird, p["id"]))
    number = (db.q1("SELECT MAX(number) n FROM batches WHERE profile_id=?", (p["id"],))["n"] or 0) + 1
    mods, seen_mods = [], set()
    for m in body.modifiers or []:
        m = " ".join(str(m).split())[:60]
        if m and m.lower() not in seen_mods:
            seen_mods.add(m.lower())
            mods.append(m)
    bid = db.ex("INSERT INTO batches (profile_id, number, status, size, weirdness, modifiers, created_at) "
                "VALUES (?,?,?,?,?,?,?)", (p["id"], number, "queued", size, weird, db.dumps(mods[:8]), db.now()))
    pipeline.start(bid)
    return _batch_full(bid)


@app.get("/api/batches")
def batches():
    p = _profile()
    rows = db.q("SELECT * FROM batches WHERE profile_id=? ORDER BY number DESC", (p["id"],))
    for b in rows:
        if b["stats"]:  # listings were crystallized away; use the numbers frozen at that moment
            b["shown"], b["likes"], b["per_query"] = b["stats"]["shown"], b["stats"]["likes"], b["stats"]["per_query"]
            continue
        s = db.q1("SELECT COUNT(s.listing_id) shown, SUM(CASE WHEN s.verdict='like' THEN 1 ELSE 0 END) likes "
                  "FROM listings l LEFT JOIN swipes s ON s.listing_id=l.id WHERE l.batch_id=?", (b["id"],))
        b["shown"], b["likes"] = s["shown"] or 0, s["likes"] or 0
        b["per_query"] = db.q(
            "SELECT l.query, COUNT(*) n, SUM(CASE WHEN s.verdict='like' THEN 1 ELSE 0 END) likes FROM listings l "
            "LEFT JOIN swipes s ON s.listing_id=l.id WHERE l.batch_id=? GROUP BY l.query", (b["id"],))
        b["claude_cost"] = round(db.q1("SELECT COALESCE(SUM(cost),0) c FROM usage WHERE batch_id=?", (b["id"],))["c"], 4)
    return rows


@app.get("/api/batches/{bid}")
def get_batch(bid: int):
    return _batch_full(bid)


_tasks = set()


@app.post("/api/batches/{bid}/finish")
async def finish_batch(bid: int):
    b = _batch_full(bid)
    if b["status"] == "done":
        return {"ok": True}  # already finished; don't pay for the taste summary again
    if b["status"] != "ready":
        raise HTTPException(409, "Batch isn't ready")
    db.ex("UPDATE batches SET status='done', finished_at=? WHERE id=?", (db.now(), bid))
    task = asyncio.create_task(pipeline.finish(bid))
    _tasks.add(task)  # a bare task can be garbage-collected mid-run
    task.add_done_callback(_tasks.discard)
    return {"ok": True}


# --------------------------------------------------------------------------- swipes & ranks

class SwipeIn(BaseModel):
    listing_id: int
    verdict: str


@app.post("/api/swipe")
def swipe(body: SwipeIn):
    if body.verdict not in ("like", "dislike"):
        raise HTTPException(400, "verdict must be like or dislike")
    _listing(body.listing_id)
    rank = 0.75 if body.verdict == "like" else 0.25
    db.ex("INSERT INTO swipes (listing_id, verdict, rank, manual, swiped_at) VALUES (?,?,?,0,?) "
          "ON CONFLICT(listing_id) DO UPDATE SET verdict=excluded.verdict, rank=excluded.rank, manual=0, "
          "swiped_at=excluded.swiped_at", (body.listing_id, body.verdict, rank, db.now()))
    return _listing(body.listing_id)


@app.delete("/api/swipe/{lid}")
def unswipe(lid: int):
    _listing(lid)
    db.ex("DELETE FROM swipes WHERE listing_id=?", (lid,))
    return {"ok": True}


class RankIn(BaseModel):
    listing_id: int
    rank: float


@app.post("/api/rank")
def rank(body: RankIn):
    _listing(body.listing_id)
    r = max(0.0, min(1.0, body.rank))
    verdict = "like" if r >= 0.5 else "dislike"
    db.ex("INSERT INTO swipes (listing_id, verdict, rank, manual, swiped_at) VALUES (?,?,?,1,?) "
          "ON CONFLICT(listing_id) DO UPDATE SET verdict=excluded.verdict, rank=excluded.rank, manual=1",
          (body.listing_id, verdict, r, db.now()))
    return _listing(body.listing_id)


# --------------------------------------------------------------------------- groups

class GroupIn(BaseModel):
    label: str
    listing_ids: List[int] = []


class MembersIn(BaseModel):
    listing_ids: List[int]


@app.get("/api/groups")
def list_groups():
    return learn.groups(_profile()["id"])


@app.post("/api/groups")
def create_group(body: GroupIn):
    p = _profile()
    label = body.label.strip()[:60] or "Untitled"
    existing = db.q1("SELECT id FROM groups WHERE profile_id=? AND lower(label)=lower(?)", (p["id"], label))
    gid = existing["id"] if existing else db.ex(
        "INSERT INTO groups (profile_id, label, created_at) VALUES (?,?,?)", (p["id"], label, db.now()))
    add_members(gid, MembersIn(listing_ids=body.listing_ids))
    return {"id": gid, "label": label}


@app.post("/api/groups/{gid}/members")
def add_members(gid: int, body: MembersIn):
    _group(gid)
    for lid in body.listing_ids:
        _listing(lid)
    with db.tx() as c:
        c.executemany("INSERT OR IGNORE INTO group_members (group_id, listing_id) VALUES (?,?)",
                      [(gid, lid) for lid in body.listing_ids])
    return {"ok": True}


@app.delete("/api/groups/{gid}/members/{lid}")
def remove_member(gid: int, lid: int):
    _group(gid)
    with db.tx() as c:
        c.execute("DELETE FROM group_members WHERE group_id=? AND listing_id=?", (gid, lid))
        # a category with one or no listings left isn't a category anymore
        left = c.execute("SELECT COUNT(*) FROM group_members WHERE group_id=?", (gid,)).fetchone()[0]
        if left < 2:
            c.execute("DELETE FROM group_members WHERE group_id=?", (gid,))
            c.execute("DELETE FROM groups WHERE id=?", (gid,))
    return {"ok": True, "group_removed": left < 2}


@app.put("/api/groups/{gid}")
def rename_group(gid: int, body: GroupIn):
    _group(gid)
    db.ex("UPDATE groups SET label=? WHERE id=?", (body.label.strip()[:60], gid))
    return {"ok": True}


@app.delete("/api/groups/{gid}")
def delete_group(gid: int):
    _group(gid)
    with db.tx() as c:
        c.execute("DELETE FROM group_members WHERE group_id=?", (gid,))
        c.execute("DELETE FROM groups WHERE id=?", (gid,))
    return {"ok": True}


# --------------------------------------------------------------------------- views

@app.get("/api/graph")
def graph(batch_id: Optional[int] = None):
    if batch_id:
        _batch_full(batch_id)
    return learn.graph(_profile()["id"], batch_id)


@app.get("/api/listing/{lid}")
def listing(lid: int):
    return _listing(lid)


# --------------------------------------------------------------------------- crystals & keepers

class CrystallizeIn(BaseModel):
    keepers: List[int] = []
    keep_in_web: List[int] = []
    landmarks: Optional[List[dict]] = None


@app.get("/api/crystallize/preview")
def crystallize_preview():
    return crystal.preview(_profile())


@app.post("/api/crystallize")
def crystallize(body: CrystallizeIn):
    try:
        return crystal.crystallize(_profile(), body.keepers, body.keep_in_web, body.landmarks)
    except crystal.CrystalError as e:
        raise HTTPException(409, str(e))


@app.get("/api/keepers")
def list_keepers():
    return crystal.keepers(_profile()["id"])


@app.post("/api/keepers/check")
async def check_keepers():
    """Re-fetch every keeper from the source and record whether it's still for sale (and any price change).
    One batched source call; a keeper the source can't answer for stays 'unknown' rather than 'gone'."""
    ks = crystal.keepers(_profile()["id"])
    if not ks:
        return {"checked": 0, "live": 0, "gone": 0, "unknown": 0, "changed": 0, "credits": 0}
    by_fb = {k["fb_id"]: k for k in ks}
    try:
        details, credits = await get_source().items(list(by_fb))
    except SourceError as e:
        raise HTTPException(502, str(e))
    t = db.now()
    out = {"checked": len(ks), "live": 0, "gone": 0, "unknown": 0, "changed": 0, "credits": credits}
    for fb_id, k in by_fb.items():
        d = details.get(fb_id)
        if not d:
            out["unknown"] += 1
            continue
        state = "live" if d.get("is_live", True) else "gone"
        out[state] += 1
        new_price = d.get("price")
        if state == "live" and new_price is not None and k["price"] is not None and float(new_price) != float(k["price"]):
            out["changed"] += 1
            db.ex("UPDATE listings SET avail=?, avail_at=?, price_prev=?, price=?, price_text=? WHERE id=?",
                  (state, t, k["price"], new_price, d.get("price_text") or f"${new_price:g}", k["id"]))
        else:
            db.ex("UPDATE listings SET avail=?, avail_at=? WHERE id=?", (state, t, k["id"]))
    log.info("keeper check for profile %s: %s", _profile()["id"], out)
    return out


@app.delete("/api/keepers/{lid}")
def drop_keeper(lid: int):
    l = _listing(lid)
    if l["state"] == "out":  # only alive as a keeper: let it go entirely
        with db.tx() as c:
            c.execute("DELETE FROM swipes WHERE listing_id=?", (lid,))
            c.execute("DELETE FROM listings WHERE id=?", (lid,))
    else:
        db.ex("UPDATE listings SET keeper=0 WHERE id=?", (lid,))
    return {"ok": True}


# --------------------------------------------------------------------------- export

EXPORT_COLS = ["Name", "Link", "Price", "Top 5 qualities", "Your ranking (0-100)", "Your call",
               "Claude's expected approval (%)", "Orbit", "Reasons", "Planet", "Claude's predicted rating (0-100)",
               "Gap (points)", "Status"]


DRIVE_COLS = ["Listing area", "Drive (mi)", "Drive (min)"]


def _price_num(r):
    """Price as a bare number for numeric columns (250, not "$250"); blank when unknown."""
    v = r["price"]
    if v is None:
        m = re.search(r"\d[\d,]*(?:\.\d+)?", r["price_text"] or "")
        v = float(m.group().replace(",", "")) if m else None
    return "" if v is None else int(v) if float(v).is_integer() else round(float(v), 2)


def _norm_name(s):
    return " ".join((s or "").casefold().split())


def _export_rows(batch_id=None, keepers=False, exclude=None):
    """Listings as rows, using numbers the app already keeps. Best-ranked first.
    Default is the web (or one batch of it); keepers=True is the Keepers tab instead."""
    p = _profile()
    if batch_id:
        _batch_full(batch_id)
    w, _ = learn.weights(p["id"])
    sway = {x["tag"]: abs(x["weight"]) for x in w}
    if keepers:
        src = sorted(crystal.keepers(p["id"]), key=lambda r: -(r["rank"] if r["rank"] is not None else 0.5))
    else:
        src = learn.swiped(p["id"], batch_id)
    skip = {_norm_name(n) for n in (exclude or []) if _norm_name(n)}
    place = {x["listing_id"]: x for x in orbit.active_placements(p["id"])}
    preds = {x["listing_id"]: x for x in db.q("SELECT * FROM predictions WHERE profile_id=?", (p["id"],))}
    planets = {x["id"]: x["name"] for x in db.q("SELECT id, name FROM planets WHERE profile_id=?", (p["id"],))}
    out, photos, areas = [], [], []
    skipped = 0
    for r in src:
        if skip and _norm_name(r["title"]) in skip:
            skipped += 1
            continue
        photos.append((r["photos"] or [None])[0])
        areas.append((r["location_text"] or "").strip())
        quals = [t for t in (r["tags"] or []) if not t.startswith("shape:")]
        quals.sort(key=lambda t: -sway.get(t, 0))
        out.append([
            r["title"] or "", r["url"] or "", _price_num(r),
            ", ".join(t.split(":", 1)[1] for t in quals[:5]),
            "" if r["rank"] is None else round(r["rank"] * 100),
            {"like": "Like", "dislike": "Pass"}.get(r["verdict"], ""),
            "" if r["claude_score"] is None else round(r["claude_score"]),
            *_orbit_cols(r, place.get(r["id"]), preds.get(r["id"]), planets),
        ])
    return p, out, photos, areas, skipped


def _orbit_cols(r, pl, pred, planets):
    """Where the listing sits now: zone, reason split, planet, Claude's predicted rating and gap, sold or live."""
    if not pl:
        return ["", "", "", "", "", ""]
    z = orbit_math.zone(pl["r"])
    rs = pl["reasons"]
    split = ", ".join(f"{round(v * 100)}% {orbit_math.AXIS_NAMES_PRETTY[k]}" for k, v in sorted(rs.items(), key=lambda kv: -kv[1]) if v >= 0.05) if rs else ("no complaints" if z == "Sun" else "")
    pr = pred["predicted"] if pred and pred["predicted"] is not None else None
    gap = pred["gap"] if pred and pred["gap"] is not None else None
    status = {"gone": "Sold", "live": "Live"}.get(r.get("avail"), "Not checked")
    return [z, split, planets.get(pl["planet_id"], ""), "" if pr is None else round(pr * 100), "" if gap is None else round(gap * 100), status]


class ExportIn(BaseModel):
    exclude: List[str] = []


@app.get("/api/export")
async def export(batch_id: Optional[int] = None, fmt: str = "csv", keepers: bool = False, like: str = "", bare: bool = False):
    return await _export(batch_id, fmt, keepers, None, like, bare)


@app.post("/api/export")
async def export_excluding(body: ExportIn, batch_id: Optional[int] = None, fmt: str = "csv", keepers: bool = False,
                           like: str = "", bare: bool = False):
    """Same as the GET, minus any listing whose name is in the uploaded "don't export" list."""
    return await _export(batch_id, fmt, keepers, body.exclude[:20000], like, bare)


@app.post("/api/export/names")
async def export_names(request: Request):
    """Listing names from an earlier Excel export (raw .xlsx bytes in the body): the Name column."""
    import xml.etree.ElementTree as ET
    import zipfile
    import io as _io
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    data = await request.body()
    if len(data) > 25_000_000:
        raise HTTPException(413, "That file is too big.")
    try:
        z = zipfile.ZipFile(_io.BytesIO(data))
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(ns + "si"):
                shared.append("".join(t.text or "" for t in si.iter(ns + "t")))
        sheet = sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))[0]
        cells = {}  # (row, column letters) -> text
        for c in ET.fromstring(z.read(sheet)).iter(ns + "c"):
            m = re.fullmatch(r"([A-Z]+)(\d+)", c.get("r", ""))
            if not m:
                continue
            v = c.find(ns + "v")
            if c.get("t") == "s":
                val = shared[int(v.text)] if v is not None and v.text else ""
            elif c.get("t") == "inlineStr":
                val = "".join(t.text or "" for t in c.iter(ns + "t"))
            else:
                val = v.text if v is not None and v.text else ""
            cells[(int(m.group(2)), m.group(1))] = val.strip()
        col = next((k[1] for k, v in sorted(cells.items()) if k[0] == 1 and v.casefold() in ("name", "title")), None)
        names = [v for k, v in sorted(cells.items()) if col and k[1] == col and k[0] > 1]
    except Exception:
        raise HTTPException(400, "That doesn't look like an Excel (.xlsx) file.")
    return {"names": list(dict.fromkeys(n for n in names if n))}


class AvailIn(BaseModel):
    lines: List[str] = []


@app.post("/api/export/availability")
async def export_availability(body: AvailIn):
    """Is each pasted listing still for sale? One answer per pasted line, in the same order.
    A line is a listing link (best: the link holds the listing's id) or a listing name the app knows.
    Answers: Available, Unavailable, Failed to find. One batched source call, which costs credits."""
    lines = body.lines[:500]
    pid = _profile()["id"]
    known = {}  # normalized title -> fb_id, keepers first and newest first so a repeated title picks the likeliest
    for r in db.q("SELECT fb_id, title FROM listings WHERE profile_id=? ORDER BY keeper ASC, created_at ASC", (pid,)):
        known[_norm_name(r["title"])] = r["fb_id"]
    ids = []
    for i, raw in enumerate(lines):
        t = raw.strip().strip('"').strip()
        m = re.search(r"/item/(\d+)", t) or re.fullmatch(r"(\d{6,})", t)
        ids.append(None if i == 0 and t.casefold() in ("name", "link", "title", "availability") else
                   m.group(1) if m else known.get(_norm_name(t)) if t else None)
    want = list(dict.fromkeys(i for i in ids if i))
    details, credits = {}, 0
    if want:
        try:
            details, credits = await get_source().items(want)
        except SourceError as e:
            raise HTTPException(502, str(e))
    t = db.now()
    for fb_id, d in details.items():
        db.ex("UPDATE listings SET avail=?, avail_at=? WHERE profile_id=? AND fb_id=?",
              ("live" if d.get("is_live", True) else "gone", t, pid, fb_id))
    out = []
    for i, (raw, fb_id) in enumerate(zip(lines, ids)):
        if i == 0 and raw.strip().strip('"').strip().casefold() in ("name", "link", "title", "availability"):
            out.append("Availability")  # the pasted header row keeps its place
        elif not raw.strip():
            out.append("")
        elif fb_id and fb_id in details:
            out.append("Available" if details[fb_id].get("is_live", True) else "Unavailable")
        else:
            out.append("Failed to find")
    log.info("availability check for profile %s: %s lines, %s credits", pid, len(lines), credits)
    return {"results": out, "credits": credits}


async def _export(batch_id, fmt, keepers, exclude, like="", bare=False):
    import csv
    import io
    import time as _t
    p, rows, photos, areas, skipped = _export_rows(batch_id, keepers, exclude)
    extra = {"X-Excluded": str(skipped), "Access-Control-Expose-Headers": "X-Excluded"}
    name = "".join(ch for ch in p["name"] if ch.isalnum() or ch in " -_").strip().replace(" ", "-") or "web"
    base = f"orbit-{name.lower()}{'-keepers' if keepers else '-batch' if batch_id else ''}-{_t.strftime('%Y-%m-%d')}"
    cols = EXPORT_COLS
    if fmt == "xlsx" or (fmt == "tsv" and like == "xlsx"):
        # the picture export also says how far each listing is by road from the profile's address
        trips = await route.drives((p["lat"], p["lng"]), areas)
        for row, area in zip(rows, areas):
            mi, mins = trips.get(area, (None, None))
            row += [area, "" if mi is None else round(mi, 1), "" if mins is None else round(mins)]
    if fmt == "tsv" and like == "xlsx":
        # pasted under an Excel export: same columns in the same order, with the Photo column left empty
        cols = ["Photo"] + EXPORT_COLS + DRIVE_COLS
        rows = [[""] + row for row in rows]
    if fmt == "xlsx":
        try:
            data = xlsx.build(EXPORT_COLS + DRIVE_COLS, rows, photos, f"{p['name']} {'keepers' if keepers else 'web'}")
        except xlsx.XlsxUnavailable as e:
            log.error("%s", e)
            raise HTTPException(503, str(e))
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{base}.xlsx"', **extra})
    rows = [[xlsx.formula_safe(v) for v in row] for row in rows]
    if fmt == "tsv":  # for pasting into Google Sheets: tabs split cells
        clean = lambda v: " ".join(str(v).split())
        return Response("\n".join("\t".join(clean(v) for v in row) for row in ([] if bare else [cols]) + rows),
                        media_type="text/plain; charset=utf-8", headers=extra)
    buf = io.StringIO()
    csv.writer(buf).writerows([EXPORT_COLS] + rows)
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{base}.csv"', **extra})


@app.get("/api/spending")
def my_spending():
    return spending.summary(_me())


@app.get("/api/logs")
def logs(n: int = 30, level: str = "WARNING"):
    _admin()  # the log covers everyone's batches
    return {"path": str(config.DATA_DIR / "orbit.log"), "entries": recent_logs(min(n, 200), level.upper())}


@app.get("/api/insights")
def insights():
    p = _profile()
    w, mean = learn.weights(p["id"])
    credits = db.q1("SELECT SUM(credits_used) c FROM batches WHERE profile_id=?", (p["id"],))["c"] or 0
    return {
        "taste_summary": p["taste_summary"],
        "weights": w,
        "mean": mean,
        "accuracy": learn.batch_accuracy(p["id"]),
        "queries": learn.query_stats(p["id"]),
        "credits_used": credits,
        "groups": learn.groups(p["id"]),
        "concepts": learn.concepts(p["id"]),
        "crystals": [{"number": c["number"], "created_at": c["created_at"], "n_listings": c["n_listings"],
                      "kept": c["kept"], "kept_in_web": c["kept_in_web"], "forgotten": c["forgotten"],
                      "factor": c["factor"],
                      "pulls": [e["tag"].split(":", 1)[1] for e in sorted(c["weights"], key=lambda e: -e["sum"] / (e["n"] + 2))
                                if e["n"] >= 2 and e["sum"] > 0 and not e["tag"].startswith(("shape:", "condition:"))][:4]}
                     for c in learn.crystals(p["id"])],
    }
