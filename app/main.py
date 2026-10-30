"""Kindling: Tinder-style swiping for Facebook Marketplace. FastAPI app + JSON API."""
import asyncio
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, config, costs, crystal, db, learn, pipeline, spending, xlsx
from .log import log, recent as recent_logs
from .sources import SourceError, get_source

app = FastAPI(title="Kindling")
db.init()


@app.on_event("startup")
def _on_startup():
    db.recover_interrupted()
    log.info("Kindling started: source=%s brain=%s", config.source_mode(), config.brain_mode())


app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


class _ImmutableFiles(StaticFiles):
    """Cached listing photos never change, so let the phone keep them."""

    async def get_response(self, path, scope):
        res = await super().get_response(path, scope)
        if res.status_code == 200:
            res.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return res


app.mount("/img", _ImmutableFiles(directory=config.IMG_DIR), name="img")

OPEN_PATHS = ("/api/auth/",)  # everything else under /api and /img needs a signed-in device


@app.middleware("http")
async def signed_in(request: Request, call_next):
    path = request.url.path
    if (path.startswith("/api/") or path.startswith("/img/")) and not path.startswith(OPEN_PATHS):
        user = auth.user_for_token(request.cookies.get(auth.COOKIE))
        if not user:
            return JSONResponse({"detail": "Sign in with an invite code", "auth": True}, status_code=401)
        auth.current_user.set(user)
    return await call_next(request)


@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


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


@app.get("/api/auth/invite/{code}")
def invite_info(code: str):
    info = auth.peek_invite(code)
    if not info:
        raise HTTPException(404, "That code isn't valid anymore. Ask for a new one.")
    return info


@app.post("/api/auth/redeem")
def redeem(body: RedeemIn, request: Request):
    ip = request.client.host if request.client else "?"
    try:
        auth.throttle(ip)
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
    auth.end_session(request.cookies.get(auth.COOKIE))
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
    if "batch_size" in data and data["batch_size"]:
        data["batch_size"] = max(3, min(40, int(data["batch_size"])))
    if "criteria" in data:
        data["criteria"] = db.dumps([c.strip() for c in data["criteria"] or [] if c.strip()])
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
        raise HTTPException(502, str(e))
    return locs[:6]


# --------------------------------------------------------------------------- batches

class BatchIn(BaseModel):
    size: Optional[int] = None
    weirdness: Optional[int] = None
    modifiers: Optional[List[str]] = None  # extras for this batch only, never saved to the hunt


@app.post("/api/batches")
async def new_batch(body: BatchIn):
    me = _me()
    p = _profile()
    cur = _current_batch(p["id"])
    if cur and cur["status"] != "error":
        return _batch_full(cur["id"])
    in_web = learn.web_count(p["id"])
    if in_web >= learn.WEB_LIMIT:
        raise HTTPException(409, f"Your web is full ({in_web}/{learn.WEB_LIMIT}). Crystallize it to keep going.")
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


@app.post("/api/batches/{bid}/finish")
async def finish_batch(bid: int):
    b = _batch_full(bid)
    if b["status"] not in ("ready", "done"):
        raise HTTPException(409, "Batch isn't ready")
    db.ex("UPDATE batches SET status='done', finished_at=? WHERE id=?", (db.now(), bid))
    asyncio.create_task(pipeline.finish(bid))
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
               "Claude's expected approval (%)"]


def _export_rows(batch_id=None, keepers=False):
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
    out, photos = [], []
    for r in src:
        photos.append((r["photos"] or [None])[0])
        quals = [t for t in (r["tags"] or []) if not t.startswith("shape:")]
        quals.sort(key=lambda t: -sway.get(t, 0))
        out.append([
            r["title"] or "", r["url"] or "", r["price_text"] or ("" if r["price"] is None else f"${r['price']:.0f}"),
            ", ".join(t.split(":", 1)[1] for t in quals[:5]),
            "" if r["rank"] is None else round(r["rank"] * 100),
            {"like": "Like", "dislike": "Pass"}.get(r["verdict"], ""),
            "" if r["claude_score"] is None else round(r["claude_score"]),
        ])
    return p, out, photos


@app.get("/api/export")
def export(batch_id: Optional[int] = None, fmt: str = "csv", keepers: bool = False):
    import csv
    import io
    import time as _t
    p, rows, photos = _export_rows(batch_id, keepers)
    name = "".join(ch for ch in p["name"] if ch.isalnum() or ch in " -_").strip().replace(" ", "-") or "web"
    base = f"kindling-{name.lower()}{'-keepers' if keepers else '-batch' if batch_id else ''}-{_t.strftime('%Y-%m-%d')}"
    if fmt == "xlsx":
        try:
            data = xlsx.build(EXPORT_COLS, rows, photos, f"{p['name']} {'keepers' if keepers else 'web'}")
        except xlsx.XlsxUnavailable as e:
            log.error("%s", e)
            raise HTTPException(503, str(e))
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{base}.xlsx"'})
    if fmt == "tsv":  # for pasting into Google Sheets: tabs split cells
        clean = lambda v: " ".join(str(v).split())
        return Response("\n".join("\t".join(clean(v) for v in row) for row in [EXPORT_COLS] + rows),
                        media_type="text/plain; charset=utf-8")
    buf = io.StringIO()
    csv.writer(buf).writerows([EXPORT_COLS] + rows)
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{base}.csv"'})


@app.get("/api/spending")
def my_spending():
    return spending.summary(_me())


@app.get("/api/logs")
def logs(n: int = 30, level: str = "WARNING"):
    _admin()  # the log covers everyone's batches
    return {"path": str(config.DATA_DIR / "kindling.log"), "entries": recent_logs(min(n, 200), level.upper())}


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
