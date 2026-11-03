"""Orbit's service layer: placing, undo, the rocket, planets and the state the Place screen draws.

A listing's current position is its latest placement that is not undone. Only a listing's FIRST placement is
scored against Claude's locked prediction; moves, rocketed listings and migrated swipes never are. Every placement
also keeps the older `swipes` row in step (rank = rating, weight = learning weight), so the existing taste model
(learn.py) reads Orbit placements without being rewritten.
"""
import math
import re

from . import costs, db, events, learn, orbit_math as m, scores

ROCKET_WEIGHT = 0.25        # a rocketed listing teaches taste a quarter as much as one placed by hand
CALLED_IT, CLOSE = 0.06, 0.16   # rating gap thresholds for Claude's verdict
ZONE_EDGES = {"Inner": (m.SUN_R, m.INNER_R), "Mid": (m.INNER_R, m.FROST), "Outer": (m.FROST, m.OUTER_R), "Belt": (m.OUTER_R, 1.0)}
REASON_THETA = dict(m.AXES, other=None)


class OrbitError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def verdict(gap):
    return "Called it" if gap < CALLED_IT else "Close" if gap < CLOSE else "Claude missed"


# --------------------------------------------------------------------------- reading

def my_listing(user, listing_id):
    l = db.q1("SELECT l.* FROM listings l JOIN profiles p ON p.id=l.profile_id WHERE l.id=? AND p.user_id=?", (listing_id, user["id"]))
    if not l:
        raise OrbitError("Listing not found", 404)
    return l


def current(listing_id):
    return db.q1("SELECT * FROM placements WHERE listing_id=? AND undone=0 ORDER BY id DESC LIMIT 1", (listing_id,))


def active_placements(profile_id):
    return db.q(
        "SELECT p.*, l.title, l.photos, l.price, l.price_text, l.explore, l.avail, l.keeper, l.batch_id FROM placements p "
        "JOIN listings l ON l.id=p.listing_id WHERE p.profile_id=? AND p.undone=0 AND p.id="
        "(SELECT MAX(id) FROM placements q WHERE q.listing_id=p.listing_id AND q.undone=0) ORDER BY p.id", (profile_id,))


def card(l, pred=None):
    pred = pred or db.q1("SELECT * FROM predictions WHERE listing_id=?", (l["id"],)) or {}
    return {"id": l["id"], "title": l["title"], "price": l["price"], "price_text": l["price_text"],
            "location_text": l["location_text"], "photos": l["photos"] or [], "url": l["url"], "condition": l["condition"],
            "description": l["description"], "take": l["take"], "checklist": l["checklist"], "tags": l["tags"],
            "comet": bool(l["explore"]), "guess": pred.get("guess_text") or "Hard to judge from photos",
            "predicted": pred.get("predicted"), "claude_score": l["claude_score"], "avail": l["avail"], "batch_id": l["batch_id"]}


def current_batch(profile_id):
    return db.q1("SELECT * FROM batches WHERE profile_id=? AND status!='done' ORDER BY id DESC LIMIT 1", (profile_id,))


def queue(batch):
    if not batch or batch["status"] != "ready":
        return []
    rows = db.q("SELECT l.* FROM listings l WHERE l.batch_id=? AND NOT EXISTS (SELECT 1 FROM placements p WHERE p.listing_id=l.id "
                "AND p.undone=0) AND NOT EXISTS (SELECT 1 FROM swipes s WHERE s.listing_id=l.id) ORDER BY l.position", (batch["id"],))
    out = []
    prof = db.q1("SELECT * FROM profiles WHERE id=?", (batch["profile_id"],))
    for r in rows:
        c = card(r)
        if prof.get("binary"):
            pred = db.q1("SELECT sun_guess FROM predictions WHERE listing_id=?", (r["id"],))
            g = pred["sun_guess"] if pred and pred["sun_guess"] is not None else guess_sun(prof, r["tags"])
            if pred and pred["sun_guess"] is None:
                db.ex("UPDATE predictions SET sun_guess=? WHERE listing_id=?", (g, r["id"]))   # locked before the person sees it
            c["sun_guess"] = g
        out.append(c)
    return out


def rocket_use(profile_id):
    row = db.q1("SELECT SUM(kind='rocket') rockets, COUNT(*) n FROM placements WHERE profile_id=? AND undone=0 "
                "AND origin='placed' AND kind IN ('first','rocket')", (profile_id,))
    n = row["n"] or 0
    return {"rocketed": row["rockets"] or 0, "placements": n, "share": (row["rockets"] or 0) / n if n else None}


def planet_rows(profile_id):
    ps = db.q("SELECT * FROM planets WHERE profile_id=? ORDER BY id", (profile_id,))
    for p in ps:
        mem = db.q("SELECT l.id, l.photos FROM planet_members pm JOIN listings l ON l.id=pm.listing_id WHERE pm.planet_id=? LIMIT 4", (p["id"],))
        p["moons"] = db.q1("SELECT COUNT(*) n FROM planet_members WHERE planet_id=?", (p["id"],))["n"]
        p["thumbs"] = [(x["photos"] or [None])[0] for x in mem]
        p["zone"] = m.zone(p["r"])
    return ps


def placed_view(profile_id):
    out = []
    for p in active_placements(profile_id):
        out.append({"id": p["listing_id"], "placement_id": p["id"], "title": p["title"], "photo": (p["photos"] or [None])[0],
                    "price_text": p["price_text"], "r": p["r"], "theta": p["theta"], "zone": m.zone(p["r"]), "kind": p["kind"],
                    "origin": p["origin"], "planet_id": p["planet_id"], "sun": p["sun"], "gone": p["avail"] == "gone",
                    "comet": bool(p["explore"]), "rating": p["rating"], "reasons": p["reasons"] or None})
    return out


def events_ready(profile, batch, q):
    """Events wait while a batch is building or still has listings to place; then one is offered at a time."""
    if (batch and batch["status"] in ("queued", "searching", "screening", "scoring")) or q:
        return None
    try:
        events.refresh_if_due(profile)
    except Exception:
        from .log import log
        log.exception("event refresh failed")
        return None
    e = events.next_event(profile["id"])
    return None if not e else {"id": e["id"], "kind": e["kind"], "title": e["title"]}


def state(user, profile):
    b = current_batch(profile["id"])
    q = queue(b)
    last = db.q1("SELECT p.id, p.listing_id, l.title FROM placements p JOIN listings l ON l.id=p.listing_id "
                 "WHERE p.profile_id=? AND p.undone=0 AND p.origin='placed' ORDER BY p.id DESC LIMIT 1", (profile["id"],))
    return {
        "system": {"id": profile["id"], "name": profile["name"], "state": profile.get("state") or "active", "hunt": profile["hunt"],
                   "binary": ({"names": [s["name"] for s in profile["suns"]]} if profile.get("binary") and len(profile.get("suns") or []) == 2 else None),
                   "batch_size": profile["batch_size"], "comet_rate": profile["weirdness"]},
        "me": {"id": user["id"], "name": user["name"], "role": user["role"], "budget": costs.budget(user)},
        "scores": {"confidence": scores.confidence(profile["id"]), "wild_card": scores.wild_card_rate(profile["id"]),
                   "rocket": rocket_use(profile["id"]), "sun_pick": scores.sun_pick(profile["id"])},
        "batch": None if not b else {"id": b["id"], "number": b["number"], "status": b["status"], "progress": b["progress"],
                                     "error": b["error"], "size": b["size"]},
        "queue": q,
        "placed": placed_view(profile["id"]),
        "planets": planet_rows(profile["id"]),
        "last_placement": last,
        "events_ready": events_ready(profile, b, q),
        "last_modifiers": (db.q1("SELECT modifiers FROM batches WHERE profile_id=? ORDER BY id DESC LIMIT 1", (profile["id"],)) or {}).get("modifiers") or [],
        "batch_total": db.q1("SELECT COUNT(*) n FROM listings WHERE batch_id=?", (b["id"],))["n"] if b else 0,
    }


# --------------------------------------------------------------------------- writing

def _sync_swipe(listing_id, rating, r, weight, manual):
    db.ex("INSERT INTO swipes (listing_id, verdict, rank, manual, swiped_at, weight) VALUES (?,?,?,?,?,?) "
          "ON CONFLICT(listing_id) DO UPDATE SET verdict=excluded.verdict, rank=excluded.rank, manual=excluded.manual, "
          "swiped_at=excluded.swiped_at, weight=excluded.weight",
          (listing_id, "like" if m.is_like(r) else "dislike", rating, manual, db.now(), weight))


def _insert(l, kind, r, theta, rating, reasons, weight, planet_id=None, sun=0):
    return db.ex("INSERT INTO placements (listing_id, profile_id, kind, origin, r, theta, rating, reasons, reason_known, weight, "
                 "planet_id, sun, created_at) VALUES (?,?,?,'placed',?,?,?,?,1,?,?,?,?)",
                 (l["id"], l["profile_id"], kind, r, theta, rating, db.dumps(reasons) if reasons else None, weight, planet_id, sun, db.now()))


def place(user, listing_id, r, theta, sun=0):
    """Place here. Returns {placement, compare (first placements only), scores}."""
    l = my_listing(user, listing_id)
    require_open(db.q1("SELECT * FROM profiles WHERE id=?", (l["profile_id"],)))
    if not (isinstance(r, (int, float)) and math.isfinite(r)) or not (isinstance(theta, (int, float)) and math.isfinite(theta)):
        raise OrbitError("That isn't a position")
    r = m.clamp(float(r), 0.0, 1.0)
    b = m.blend(r, float(theta))
    prof = db.q1("SELECT * FROM profiles WHERE id=?", (l["profile_id"],))
    sun = int(sun) if prof.get("binary") and int(sun) in (0, 1) else 0
    prev = current(listing_id)
    kind = "move" if prev else "first"
    rating = b["rating"]
    pid = _insert(l, kind, r, float(theta) if b["reasons"] else None, rating, b["reasons"], 1.0, None, int(sun))
    compare = None
    if kind == "first":
        pred = db.q1("SELECT * FROM predictions WHERE listing_id=?", (listing_id,))
        if pred and pred["checked_at"] is None and pred["predicted"] is not None:
            gap = abs(pred["predicted"] - rating)
            db.ex("UPDATE predictions SET checked_at=?, actual_rating=?, gap=?, sun_actual=? WHERE listing_id=?",
                  (db.now(), rating, gap, sun if prof.get("binary") else None, listing_id))
            compare = {"predicted": pred["predicted"], "predicted_r": m.r_from_rating(pred["predicted"]), "actual": rating,
                       "gap": gap, "verdict": verdict(gap), "guess": pred["guess_text"]}
    _sync_swipe(listing_id, rating, r, 1.0, 0 if kind == "first" else 1)
    done = _maybe_finish_batch(l["batch_id"])
    return {"placement": {"id": pid, "kind": kind, "r": r, "zone": b["zone"], "like": b["like"], "percents": b["percents"]},
            "compare": compare, "scores": {"confidence": scores.confidence(l["profile_id"]),
                                           "wild_card": scores.wild_card_rate(l["profile_id"]), "rocket": rocket_use(l["profile_id"])},
            "batch_done": done}


def _maybe_finish_batch(batch_id):
    b = db.q1("SELECT * FROM batches WHERE id=?", (batch_id,))
    if not b or b["status"] != "ready":
        return False
    left = db.q1("SELECT COUNT(*) n FROM listings l WHERE l.batch_id=? AND NOT EXISTS (SELECT 1 FROM placements p WHERE "
                 "p.listing_id=l.id AND p.undone=0) AND NOT EXISTS (SELECT 1 FROM swipes s WHERE s.listing_id=l.id)", (batch_id,))["n"]
    if left:
        return False
    db.ex("UPDATE batches SET status='done', finished_at=? WHERE id=?", (db.now(), batch_id))
    return True


def undo(user, placement_id):
    p = db.q1("SELECT p.* FROM placements p JOIN profiles pr ON pr.id=p.profile_id WHERE p.id=? AND pr.user_id=?", (placement_id, user["id"]))
    if not p or p["undone"]:
        raise OrbitError("Nothing to undo", 404)
    cur = current(p["listing_id"])
    if not cur or cur["id"] != p["id"]:
        raise OrbitError("That placement is no longer the latest one", 409)
    db.ex("UPDATE placements SET undone=1 WHERE id=?", (p["id"],))
    if p["kind"] == "first":  # the check goes with it, so an undone placement can't move Confidence
        db.ex("UPDATE predictions SET checked_at=NULL, actual_rating=NULL, gap=NULL, sun_actual=NULL WHERE listing_id=?", (p["listing_id"],))
    if p["kind"] == "rocket" and p["planet_id"] and not db.q1(
            "SELECT 1 FROM placements WHERE listing_id=? AND planet_id=? AND kind='rocket' AND undone=0", (p["listing_id"], p["planet_id"])):
        db.ex("DELETE FROM planet_members WHERE planet_id=? AND listing_id=?", (p["planet_id"], p["listing_id"]))
    prev = current(p["listing_id"])
    if prev:
        _sync_swipe(p["listing_id"], prev["rating"], prev["r"], prev["weight"], 0 if prev["kind"] == "first" else 1)
    else:
        db.ex("DELETE FROM swipes WHERE listing_id=?", (p["listing_id"],))
    l = db.q1("SELECT batch_id FROM listings WHERE id=?", (p["listing_id"],))
    b = db.q1("SELECT * FROM batches WHERE id=?", (l["batch_id"],))
    if b and b["status"] == "done" and not db.q1("SELECT 1 FROM batches WHERE profile_id=? AND status!='done'", (b["profile_id"],)):
        db.ex("UPDATE batches SET status='ready', finished_at=NULL WHERE id=?", (b["id"],))   # reopened so the listing is placeable again
    return {"ok": True, "listing_id": p["listing_id"], "restored": bool(prev)}


# --------------------------------------------------------------------------- planets and the rocket

def create_planet(user, profile, name, description="", orbit="Mid", reason="other", listing_ids=()):
    name = " ".join((name or "").split())[:40]
    if not name:
        raise OrbitError("Give the planet a name")
    if orbit not in ZONE_EDGES:
        raise OrbitError("Orbit must be Inner, Mid, Outer or Belt")
    if reason not in REASON_THETA:
        raise OrbitError("Unknown reason")
    if db.q1("SELECT 1 FROM planets WHERE profile_id=? AND lower(name)=lower(?)", (profile["id"], name)):
        raise OrbitError("You already have a planet with that name", 409)
    lo, hi = ZONE_EDGES[orbit]
    theta = REASON_THETA[reason]
    reasons = {k: (1.0 if k == reason else 0.0) for k in m.AXIS_NAMES} if theta is not None else None
    pid = db.ex("INSERT INTO planets (profile_id, name, description, r, theta, reasons, created_at) VALUES (?,?,?,?,?,?,?)",
                (profile["id"], name, (description or "").strip()[:200], (lo + hi) / 2, theta, db.dumps(reasons) if reasons else None, db.now()))
    for lid in listing_ids:
        l = my_listing(user, lid)
        if l["profile_id"] == profile["id"]:
            db.ex("INSERT OR IGNORE INTO planet_members (planet_id, listing_id) VALUES (?,?)", (pid, lid))
    return db.q1("SELECT * FROM planets WHERE id=?", (pid,))


def my_planet(user, planet_id):
    p = db.q1("SELECT pl.* FROM planets pl JOIN profiles pr ON pr.id=pl.profile_id WHERE pl.id=? AND pr.user_id=?", (planet_id, user["id"]))
    if not p:
        raise OrbitError("Planet not found", 404)
    return p


def delete_planet(user, planet_id):
    my_planet(user, planet_id)
    db.ex("DELETE FROM planet_members WHERE planet_id=?", (planet_id,))
    db.ex("DELETE FROM planets WHERE id=?", (planet_id,))


STOP = set("a an the and or of for with in on to my is it this that very from at be are as by".split())


def _words(s):
    return {w for w in re.findall(r"[a-z]{3,}", (s or "").lower()) if w not in STOP}


def suggest_moons(user, profile, name, description):
    """Listings in this system whose title, tags or Claude's take share words with the planet. A plain word match, not a model."""
    want = _words(name) | _words(description)
    if not want:
        return []
    out = []
    for p in active_placements(profile["id"]):
        l = db.q1("SELECT title, tags, take FROM listings WHERE id=?", (p["listing_id"],))
        hay = _words(l["title"]) | _words(" ".join(t.split(":", 1)[-1] for t in l["tags"] or []))
        n = len(want & hay)
        if n:
            out.append((n, p["listing_id"], p["title"], (p["photos"] or [None])[0]))
    out.sort(key=lambda x: (-x[0], x[1]))
    return [{"id": i, "title": t, "photo": ph} for _, i, t, ph in out[:8]]


def rocket(user, listing_id, planet_id):
    l = my_listing(user, listing_id)
    require_open(db.q1("SELECT * FROM profiles WHERE id=?", (l["profile_id"],)))
    pl = my_planet(user, planet_id)
    if pl["profile_id"] != l["profile_id"]:
        raise OrbitError("That planet belongs to another system", 409)
    reasons = pl["reasons"] or None
    rating = m.rating(pl["r"])
    pid = _insert(l, "rocket", pl["r"], pl["theta"], rating, reasons, ROCKET_WEIGHT, planet_id)
    db.ex("INSERT OR IGNORE INTO planet_members (planet_id, listing_id) VALUES (?,?)", (planet_id, listing_id))
    _sync_swipe(listing_id, rating, pl["r"], ROCKET_WEIGHT, 1)
    done = _maybe_finish_batch(l["batch_id"])
    return {"placement": {"id": pid, "kind": "rocket", "r": pl["r"], "zone": m.zone(pl["r"])}, "planet": pl["name"], "batch_done": done,
            "scores": {"confidence": scores.confidence(l["profile_id"]), "rocket": rocket_use(l["profile_id"])}}


# --------------------------------------------------------------------------- galaxy: systems

def system_row(user, pid):
    p = db.q1("SELECT * FROM profiles WHERE id=? AND user_id=?", (pid, user["id"]))
    if not p:
        raise OrbitError("System not found", 404)
    return p


def zone_counts(profile_id):
    c = {z: 0 for z in ("Sun", "Inner", "Mid", "Outer", "Belt")}
    for p in active_placements(profile_id):
        c[m.zone(p["r"])] += 1
    return c


def galaxy(user):
    active = db.active_profile(user["id"])
    out = []
    for p in db.q("SELECT * FROM profiles WHERE user_id=? ORDER BY id", (user["id"],)):
        b = current_batch(p["id"])
        out.append({"id": p["id"], "name": p["name"], "hunt": p["hunt"], "state": p.get("state") or "active", "found_at": p.get("found_at"),
                    "active": p["id"] == active["id"], "binary": bool(p.get("binary")), "counts": zone_counts(p["id"]),
                    "batch": None if not b else {"status": b["status"], "number": b["number"]},
                    "confidence": scores.confidence(p["id"]),
                    "batches": db.q1("SELECT COUNT(*) n FROM batches WHERE profile_id=? AND status='done'", (p["id"],))["n"]})
    return out


def activate(user, pid):
    system_row(user, pid)
    with db.tx() as c:
        c.execute("UPDATE profiles SET active=0 WHERE user_id=?", (user["id"],))
        c.execute("UPDATE profiles SET active=1 WHERE id=?", (pid,))


def create_system(user, source_id, name, hunt, listing_ids):
    """A second sun: a new hunt with its own search terms. The listings the person picks leave the old system and
    follow it, taking their placements, predictions and 'seen' marks with them."""
    src = system_row(user, source_id)
    name = " ".join((name or "").split())[:40]
    hunt = (hunt or "").strip()
    if not name:
        raise OrbitError("Give the new system a name")
    if not hunt:
        raise OrbitError("Say what you're hunting, in a sentence. That's what Claude searches with.")
    mine = [my_listing(user, i) for i in listing_ids]
    if any(l["profile_id"] != src["id"] for l in mine):
        raise OrbitError("Those listings aren't all in that system", 409)
    with db.tx() as c:
        c.execute("UPDATE profiles SET active=0 WHERE user_id=?", (user["id"],))
        cur = c.execute(
            "INSERT INTO profiles (name, hunt, criteria, min_price, max_price, location_name, location_slug, lat, lng, radius_km, "
            "batch_size, weirdness, active, user_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
            (name, hunt, "[]", src["min_price"], src["max_price"], src["location_name"], src["location_slug"], src["lat"], src["lng"],
             src["radius_km"], src["batch_size"], src["weirdness"], user["id"], db.now()))
        new = cur.lastrowid
        for l in mine:
            c.execute("UPDATE listings SET profile_id=? WHERE id=?", (new, l["id"]))
            c.execute("UPDATE placements SET profile_id=?, planet_id=NULL WHERE listing_id=?", (new, l["id"]))
            c.execute("UPDATE predictions SET profile_id=? WHERE listing_id=?", (new, l["id"]))
            c.execute("DELETE FROM planet_members WHERE listing_id=?", (l["id"],))
            c.execute("INSERT OR IGNORE INTO seen (profile_id, fb_id, phash, tkey, price, loc, state, at) "
                      "SELECT ?, fb_id, phash, tkey, price, loc, state, at FROM seen WHERE profile_id=? AND fb_id=?", (new, src["id"], l["fb_id"]))
    return db.q1("SELECT * FROM profiles WHERE id=?", (new,))


def found_it(user, pid, reopen=False):
    p = system_row(user, pid)
    if reopen:
        db.ex("UPDATE profiles SET state='active', found_at=NULL WHERE id=?", (pid,))
        return
    if current_batch(pid) and current_batch(pid)["status"] in ("queued", "searching", "screening", "scoring"):
        raise OrbitError("A batch is still being built. Wait for it to finish first.", 409)
    db.ex("UPDATE profiles SET state='finished', found_at=? WHERE id=?", (db.now(), pid))
    if p.get("active"):
        other = db.q1("SELECT id FROM profiles WHERE user_id=? AND id!=? AND COALESCE(state,'active')='active' ORDER BY id LIMIT 1", (user["id"], pid))
        if other:
            activate(user, other["id"])


def require_open(profile):
    if (profile.get("state") or "active") == "finished":
        raise OrbitError("This hunt is finished. Reopen it from the Galaxy to keep going.", 409)


# --------------------------------------------------------------------------- binary stars

def _distinct_tags(groups_tags):
    """For two groups of tag-lists, the tags that tell group 0 from group 1."""
    out = []
    for gi in (0, 1):
        mine, other = groups_tags[gi], groups_tags[1 - gi]
        cnt, oc = {}, {}
        for tags in mine:
            for t in set(tags) - {x for x in tags if x.startswith(("price:", "size:", "condition:", "shape:"))}:
                cnt[t] = cnt.get(t, 0) + 1
        for tags in other:
            for t in set(tags):
                oc[t] = oc.get(t, 0) + 1
        score = lambda t: cnt[t] / max(1, len(mine)) - oc.get(t, 0) / max(1, len(other))
        out.append([t for t in sorted(cnt, key=lambda t: -score(t)) if score(t) > 0][:8])
    return out


def make_binary(user, pid, names, groups):
    """A second sun inside one hunt. Both suns share its search terms; each has its own taste, and Claude guesses which
    sun a new listing starts on. Two suns is the most this screen holds."""
    p = system_row(user, pid)
    require_open(p)
    if p.get("binary"):
        raise OrbitError("This system already has two suns. That's the most a screen can hold.", 409)
    if len(groups) != 2 or len(names) != 2:
        raise OrbitError("A binary star has exactly two suns")
    names = [" ".join(str(n).split())[:40] for n in names]
    if not all(names) or names[0].lower() == names[1].lower():
        raise OrbitError("Give the two suns different names")
    tags = []
    for g in groups:
        rows = [db.q1("SELECT id, tags, profile_id FROM listings WHERE id=?", (i,)) for i in g]
        if any(r is None or r["profile_id"] != pid for r in rows):
            raise OrbitError("Those listings aren't all in this system", 409)
        tags.append([r["tags"] or [] for r in rows])
    dist = _distinct_tags(tags)
    with db.tx() as c:
        c.execute("UPDATE profiles SET binary=1, suns=? WHERE id=?", (db.dumps([{"name": names[i], "tags": dist[i]} for i in (0, 1)]), pid))
        for si, g in enumerate(groups):
            for lid in g:
                c.execute("UPDATE placements SET sun=? WHERE listing_id=? AND undone=0", (si, lid))
    return db.q1("SELECT * FROM profiles WHERE id=?", (pid,))


def end_binary(user, pid):
    system_row(user, pid)
    with db.tx() as c:
        c.execute("UPDATE profiles SET binary=0, suns='[]' WHERE id=?", (pid,))
        c.execute("UPDATE placements SET sun=0 WHERE profile_id=?", (pid,))


def guess_sun(profile, tags):
    """Which sun a listing starts on: the one whose distinctive tags it shares most (ties go to sun 0). Local, not an LLM."""
    suns = profile.get("suns") or []
    if len(suns) != 2:
        return 0
    s = [len(set(tags or []) & set(x["tags"])) / max(1, len(x["tags"])) for x in suns]
    return 1 if s[1] > s[0] else 0


# --------------------------------------------------------------------------- batch recap

def recap(user, batch_id=None):
    """How a finished batch went: where each listing landed, how close Claude got, and what the batch did to Confidence."""
    if batch_id:
        b = db.q1("SELECT b.* FROM batches b JOIN profiles p ON p.id=b.profile_id WHERE b.id=? AND p.user_id=?", (batch_id, user["id"]))
    else:
        b = db.q1("SELECT b.* FROM batches b JOIN profiles p ON p.id=b.profile_id WHERE p.user_id=? AND b.status='done' ORDER BY b.id DESC LIMIT 1", (user["id"],))
    if not b:
        raise OrbitError("Batch not found", 404)
    pid = b["profile_id"]
    items = []
    for l in db.q("SELECT * FROM listings WHERE batch_id=? ORDER BY position", (b["id"],)):
        p = current(l["id"])
        if not p:
            continue
        pr = db.q1("SELECT * FROM predictions WHERE listing_id=?", (l["id"],)) or {}
        gap = pr.get("gap")
        items.append({"id": l["id"], "title": l["title"], "photo": (l["photos"] or [None])[0], "comet": bool(l["explore"]), "kind": p["kind"],
                      "zone": m.zone(p["r"]), "r": p["r"], "theta": p["theta"], "like": m.is_like(p["r"]), "rating": p["rating"],
                      "predicted": pr.get("predicted"), "predicted_r": None if pr.get("predicted") is None else m.r_from_rating(pr["predicted"]),
                      "gap": gap, "verdict": None if gap is None else verdict(gap), "reasons": p["reasons"] or None})
    counts = {"called": sum(1 for i in items if i["verdict"] == "Called it"), "close": sum(1 for i in items if i["verdict"] == "Close"),
              "missed": sum(1 for i in items if i["verdict"] == "Claude missed"), "rocketed": sum(1 for i in items if i["kind"] == "rocket"),
              "unscored": sum(1 for i in items if i["verdict"] is None)}
    comets = [i for i in items if i["comet"]]
    comet_liked = sum(1 for i in comets if i["like"])
    gaps = [r["gap"] for r in db.q("SELECT gap FROM predictions WHERE profile_id=? AND checked_at IS NOT NULL AND batch_id!=? ORDER BY checked_at DESC LIMIT ?",
                                    (pid, b["id"], scores.WINDOW))]
    before = None
    if len(gaps) >= scores.MIN_CHECKED:
        mean, half, _ = scores._weighted_mean_interval(gaps)
        if half <= scores.MAX_HALF_WIDTH:
            before = {"state": "ready", "value": round(1 - mean, 4)}
    return {"batch": {"id": b["id"], "number": b["number"], "status": b["status"]}, "system": db.q1("SELECT name FROM profiles WHERE id=?", (pid,))["name"],
            "items": items, "counts": counts, "comets": {"n": len(comets), "liked": comet_liked},
            "confidence": scores.confidence(pid), "confidence_before": before or {"state": "learning"}}
