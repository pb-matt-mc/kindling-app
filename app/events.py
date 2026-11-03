"""Events: a black hole, a new star, a dwarf planet, an asteroid shower, an outlier.

Each is detected by a measured rule over the person's placements and the local model (model.py), never by an LLM,
stored with the numbers that triggered it, and only PROPOSED: nothing changes until the person confirms. They queue
while a batch is building or still has unplaced listings, and are shown one at a time afterwards. A rejected event is
muted for a week, and returns only if its evidence has grown by half again. Answers also calibrate trust: after two
rejections in the last three of a kind, that kind needs half again as much evidence.
"""
import math
import time

from . import db, lessons, model, orbit_math as m
from .log import log

BELT_CAP = 30                 # from the handoff: "Belt 34/30"
BLACK_HOLE_MIN = 12
NEW_STAR_MIN = 6
EXPLAIN_TOL = 0.12
OUTLIER_MIN_ROWS, OUTLIER_RESIDUAL, OUTLIER_MAX_MAE = 20, 0.35, 0.15
MUTE_DAYS = 7
DWARF_BATCHES = 4
GENERIC = ("price:", "size:", "condition:", "shape:")
KINDS = ("black_hole", "new_star", "dwarf_planet", "asteroid_shower", "outlier")


def _style_tags(tags):
    return {t for t in tags or [] if not t.startswith(GENERIC)}


def _trust(profile_id, kind):
    """1.0 normally; 1.5 when two of the last three of this kind were rejected."""
    last = db.q("SELECT status FROM events WHERE profile_id=? AND kind=? AND status IN ('confirmed','rejected') ORDER BY id DESC LIMIT 3", (profile_id, kind))
    return 1.5 if sum(1 for e in last if e["status"] == "rejected") >= 2 else 1.0


# --------------------------------------------------------------------------- black hole

def _two_means(rows, seed=0):
    vecs = [_style_tags(r["tags"]) for r in rows]
    n = len(rows)
    sim = [[model.jaccard(vecs[i], vecs[j]) for j in range(n)] for i in range(n)]
    pairs = sorted(((sim[i][j], i, j) for i in range(n) for j in range(i + 1, n)))
    s, a, b = pairs[min(seed, len(pairs) - 1)]
    meds = [a, b]
    for _ in range(12):
        groups = [[], []]
        for i in range(n):
            groups[0 if sim[i][meds[0]] >= sim[i][meds[1]] else 1].append(i)
        if not groups[0] or not groups[1]:
            return None
        new = [max(g, key=lambda i: sum(sim[i][j] for j in g)) for g in groups]
        if new == meds:
            break
        meds = new
    return groups, sim


def black_hole(profile, rows):
    sun = [r for r in rows if r["rating"] >= 0.7 and len(_style_tags(r["tags"])) >= 2]
    need = math.ceil(BLACK_HOLE_MIN * _trust(profile["id"], "black_hole"))
    if len(sun) < need or profile.get("binary"):
        return None
    res = _two_means(sun)
    if not res:
        return None
    groups, sim = res
    if min(len(g) for g in groups) < 4:
        return None
    intra = [sim[i][j] for g in groups for i in g for j in g if i < j]
    inter = [sim[i][j] for i in groups[0] for j in groups[1]]
    mi, mx = sum(intra) / len(intra), sum(inter) / len(inter)
    sil = []
    for gi, g in enumerate(groups):
        other = groups[1 - gi]
        for i in g:
            a = 1 - sum(sim[i][j] for j in g if j != i) / max(1, len(g) - 1)
            b = 1 - sum(sim[i][j] for j in other) / len(other)
            sil.append((b - a) / max(a, b, 1e-9))
    silhouette = sum(sil) / len(sil)
    if silhouette < 0.2 or mx > 0.6 * mi:
        return None
    # stable: other starting pairs reach (nearly) the same split
    base = {sun[i]["id"] for i in groups[0]}
    for seed in (1, 2):
        other = _two_means(sun, seed)
        if not other:
            return None
        got = {sun[i]["id"] for i in other[0][0]}
        agree = max(len(base & got) + len(({r["id"] for r in sun} - base) & ({r["id"] for r in sun} - got)),
                    len(base & ({r["id"] for r in sun} - got)) + len(({r["id"] for r in sun} - base) & got)) / len(sun)
        if agree < 0.9:
            return None
    def names(g):
        cnt = {}
        for i in g:
            for t in _style_tags(sun[i]["tags"]):
                cnt[t] = cnt.get(t, 0) + 1
        other = groups[1] if g is groups[0] else groups[0]
        oc = {}
        for i in other:
            for t in _style_tags(sun[i]["tags"]):
                oc[t] = oc.get(t, 0) + 1
        sc = sorted(cnt, key=lambda t: -(cnt[t] / len(g) - oc.get(t, 0) / len(other)))
        return [t.split(":", 1)[1] for t in sc[:2]]
    n0, n1 = names(groups[0]), names(groups[1])
    return {"sig": "black_hole", "n": len(sun), "silhouette": round(silhouette, 3), "intra": round(mi, 3), "inter": round(mx, 3),
            "groups": [{"name": " ".join(n0).title() or "Taste one", "ids": [sun[i]["id"] for i in groups[0]]},
                       {"name": " ".join(n1).title() or "Taste two", "ids": [sun[i]["id"] for i in groups[1]]}],
            "basis": f"{len(sun)} Sun and Inner listings, split quality {silhouette:.2f} (0.20 needed), same split from 3 starting points",
            "title": "Your sun holds two tastes",
            "body": f"{len(sun)} listings pulled into the {profile['name']} sun, and they split into two groups that rarely share a trait."}


# --------------------------------------------------------------------------- new star

def new_star(profile, rows, mdl):
    best = None
    by_tag = {}
    for r in rows:
        for t in _style_tags(r["tags"]):
            by_tag.setdefault(t, []).append(r)
    need = math.ceil(NEW_STAR_MIN * _trust(profile["id"], "new_star"))
    for t, rs in by_tag.items():
        liked = [r for r in rs if r["rating"] >= 0.6 and not r["planet_id"]]
        if len(liked) < need or len({r["batch_id"] for r in liked}) < 2:
            continue
        res = [r["rating"] - mdl.predict(r["tags"], drop=r) for r in liked]       # honest: the model as if it had never seen the row
        mean = sum(res) / len(res)
        if mean >= 0.12 and (not best or mean * len(liked) > best[0]):
            best = (mean * len(liked), t, liked, mean)
    if not best:
        return None
    _, t, liked, mean = best
    val = t.split(":", 1)[1]
    return {"sig": f"new_star:{t}", "tag": t, "n": len(liked), "batches": len({r["batch_id"] for r in liked}), "residual": round(mean, 3),
            "ids": [r["id"] for r in liked], "basis": f"{len(liked)} listings across {len({r['batch_id'] for r in liked})} batches, rated on average "
            f"{round(mean * 100)} points higher than the model predicted for each without seeing it", "title": f"A new star: {val}",
            "body": f"You keep rating {val} listings higher than anything else about them explains. That looks like its own taste."}


# --------------------------------------------------------------------------- dwarf planet

def dwarf_planet(profile, rows):
    out = None
    for pl in db.q("SELECT * FROM planets WHERE profile_id=?", (profile["id"],)):
        moons = [r for r in rows if r["planet_id"] == pl["id"] or db.q1("SELECT 1 FROM planet_members WHERE planet_id=? AND listing_id=?", (pl["id"], r["id"]))]
        if len(moons) < 2:
            continue
        last = max(r["created_at"] for r in moons)
        since = db.q1("SELECT COUNT(*) n FROM batches WHERE profile_id=? AND created_at>?", (profile["id"], last))["n"]
        if since < math.ceil(DWARF_BATCHES * _trust(profile["id"], "dwarf_planet")):
            continue
        cnt = {}
        for r in moons:
            for t in _style_tags(r["tags"]):
                cnt[t] = cnt.get(t, 0) + 1
        member_ids = {r["id"] for r in moons}
        for top in sorted((t for t in cnt if cnt[t] >= max(2, math.ceil(len(moons) * 0.6))), key=lambda t: (-cnt[t], t)):
            recent = sorted((r for r in rows if r["id"] not in member_ids and top in (r["tags"] or []) and r["created_at"] > last), key=lambda r: -r["created_at"])[:6]
            passed = [r for r in recent if r["r"] > m.FROST]
            if len(recent) >= 3 and len(passed) / len(recent) >= 0.8:
                val = top.split(":", 1)[1]
                out = {"sig": f"dwarf_planet:{pl['id']}", "planet_id": pl["id"], "planet": pl["name"], "moons": len(moons), "batches_since": since,
                       "matching": len(recent), "passed": len(passed), "trait": val,
                       "basis": f"{len(moons)} moons, no new one in {since} batches, and you passed on {len(passed)} of the last {len(recent)} {val} listings",
                       "title": f"{pl['name']} stopped growing",
                       "body": f"{len(moons)} moons, and nothing new in {since} batches. You also passed on {len(passed)} of the last {len(recent)} {val} listings."}
                break
        if out:
            break
    return out


# --------------------------------------------------------------------------- asteroid shower

def asteroid_shower(profile, rows, mdl):
    belt = [r for r in rows if m.zone(r["r"]) == "Belt"]
    if len(belt) < BELT_CAP:
        return None
    scored = sorted(((abs(mdl.residual(r)), r) for r in belt), key=lambda x: x[0])
    explained = [r for res, r in scored if res <= EXPLAIN_TOL]
    rest = [r for res, r in scored if res > EXPLAIN_TOL]
    if len(explained) < 3:
        return None
    cnt = {}
    for r in rest:
        for t in _style_tags(r["tags"]):
            if t.startswith(("shape:",)):
                cnt.setdefault(t, []).append(r["id"])
            else:
                cnt.setdefault(t, []).append(r["id"])
    grp = max(((t, ids) for t, ids in cnt.items() if len(ids) >= 4), key=lambda x: len(x[1]), default=None)
    why = mdl.top_tags(2, sign=-1)
    return {"sig": "asteroid_shower", "belt": len(belt), "cap": BELT_CAP, "explained": [r["id"] for r in explained], "unexplained": [r["id"] for r in rest],
            "why": [t.split(":", 1)[1] for t in why], "group": None if not grp else {"tag": grp[0], "ids": grp[1]},
            "basis": f"{len(belt)} in the belt (cap {BELT_CAP}); the model predicted {len(explained)} of them within {int(EXPLAIN_TOL * 100)} points without seeing them",
            "title": f"Your belt is full. {len(explained)} can burn up.",
            "body": "Claude already understands why you passed on these. What it learned stays after they're gone."}


# --------------------------------------------------------------------------- outlier

def outlier(profile, rows):
    first = [r for r in rows if r["origin"] == "placed" and r["kind"] in ("first", "move")]
    if len(rows) < OUTLIER_MIN_ROWS or not first:
        return None
    mdl = model.TraitModel(rows)
    if mdl.mae() > OUTLIER_MAX_MAE:
        return None
    newest = sorted(first, key=lambda r: -r["created_at"])[:8]
    cand = max(newest, key=lambda r: abs(mdl.residual(r)))
    res = mdl.residual(cand)
    if abs(res) < OUTLIER_RESIDUAL:
        return None
    pred = mdl.predict(cand["tags"], drop=cand)
    return {"sig": f"outlier:{cand['id']}", "id": cand["id"], "residual": round(res, 3), "predicted": round(pred, 3), "actual": round(cand["rating"], 3),
            "mae": round(mdl.mae(), 3), "basis": f"the model is usually within {round(mdl.mae() * 100)} points but missed this one by {round(abs(res) * 100)}",
            "title": f"{cand['title'][:48]} surprised me",
            "body": "You placed this far from where everything else about it points. Was it a real change of taste, curiosity, or a slip?"}


# --------------------------------------------------------------------------- queue

def detect(profile):
    rows = model.dataset(profile["id"])
    if len(rows) < 8:
        return []
    mdl = model.TraitModel(rows)
    found = []
    for kind, fn in (("black_hole", lambda: black_hole(profile, rows)), ("new_star", lambda: new_star(profile, rows, mdl)),
                     ("dwarf_planet", lambda: dwarf_planet(profile, rows)), ("asteroid_shower", lambda: asteroid_shower(profile, rows, mdl)),
                     ("outlier", lambda: outlier(profile, rows))):
        try:
            ev = fn()
        except Exception:
            log.exception("event detector %s failed", kind)
            continue
        if ev:
            found.append((kind, ev))
    return found


def _size(ev):
    return ev.get("n") or ev.get("belt") or ev.get("moons") or 1


def refresh(profile):
    """Detect and queue new events for one system. Returns the ids queued."""
    queued = []
    for kind, ev in detect(profile):
        prior = [e for e in db.q("SELECT * FROM events WHERE profile_id=? AND kind=?", (profile["id"], kind)) if (e["evidence"] or {}).get("sig") == ev["sig"]]
        if any(e["status"] in ("queued", "shown") for e in prior):
            continue
        if any(e["status"] == "confirmed" for e in prior) and kind in ("black_hole", "asteroid_shower", "new_star"):
            continue
        rej = [e for e in prior if e["status"] == "rejected"]
        if rej:
            last = max(rej, key=lambda e: e["id"])
            if (last["muted_until"] or 0) > time.time() or _size(ev) < 1.5 * _size(last["evidence"] or {}):
                continue
        queued.append(db.ex("INSERT INTO events (profile_id, kind, status, title, body, evidence, created_at) VALUES (?,?,?,?,?,?,?)",
                            (profile["id"], kind, "queued", ev["title"], ev["body"], db.dumps(ev), db.now())))
    return queued


_last = {}


def refresh_if_due(profile):
    """Cheap to call on every state poll: re-detects only when placements, planets or the sun count changed."""
    pid = profile["id"]
    fp = (db.q1("SELECT COALESCE(MAX(id),0) a, COUNT(*) n FROM placements WHERE profile_id=? AND undone=0", (pid,)),
          db.q1("SELECT COUNT(*) n FROM planets WHERE profile_id=?", (pid,))["n"], profile.get("binary"), db.q1("SELECT COUNT(*) n FROM events WHERE profile_id=?", (pid,))["n"])
    key = repr(fp)
    if _last.get(pid) == key:
        return []
    out = refresh(profile)
    _last[pid] = repr((fp[0], fp[1], fp[2], db.q1("SELECT COUNT(*) n FROM events WHERE profile_id=?", (pid,))["n"]))
    return out


def next_event(profile_id):
    return db.q1("SELECT * FROM events WHERE profile_id=? AND status IN ('queued','shown') ORDER BY (status='shown') DESC, id LIMIT 1", (profile_id,))


def reject(ev, why="rejected"):
    sz = _size(ev["evidence"] or {})
    db.ex("UPDATE events SET status='rejected', resolved_at=?, muted_until=? WHERE id=?", (db.now(), db.now() + MUTE_DAYS * 86400, ev["id"]))
    return {"ok": True, "status": "rejected", "muted_days": MUTE_DAYS, "size": sz}


# --------------------------------------------------------------------------- answering an event

def resolve(user, event_id, action, name=None, hunt=None):
    """Apply the person's answer. Returns what the client should do next. Nothing happens without this call."""
    from . import orbit
    ev = db.q1("SELECT e.* FROM events e JOIN profiles p ON p.id=e.profile_id WHERE e.id=? AND p.user_id=?", (event_id, user["id"]))
    if not ev or ev["status"] in ("confirmed", "rejected"):
        raise orbit.OrbitError("That event is already settled", 404)
    p = db.q1("SELECT * FROM profiles WHERE id=?", (ev["profile_id"],))
    e, kind = ev["evidence"] or {}, ev["kind"]
    out = {"ok": True}

    def confirm():
        db.ex("UPDATE events SET status='confirmed', resolved_at=?, resolution=? WHERE id=?", (db.now(), action, event_id))
        _note(user, p, ev["title"], action)

    def decline():
        db.ex("UPDATE events SET resolution=? WHERE id=?", (action, event_id))
        _note(user, p, ev["title"], action)
        return reject(ev)
    if kind == "black_hole":
        g = e["groups"]
        if action == "binary":
            orbit.make_binary(user, p["id"], [name or g[0]["name"], g[1]["name"]], [g[0]["ids"], g[1]["ids"]])
            confirm()
        elif action == "split":
            new = orbit.create_system(user, p["id"], name or g[1]["name"], hunt or f"{p['hunt']} ({g[1]['name']})", g[1]["ids"])
            out["system_id"] = new["id"]
            confirm()
        elif action == "keep":
            return decline()
        else:
            raise orbit.OrbitError("Unknown answer")
    elif kind == "new_star":
        val = e["tag"].split(":", 1)[1]
        if action == "system":
            new = orbit.create_system(user, p["id"], name or val.title(), hunt or f"{val} {p['hunt']}".strip(), e["ids"])
            out["system_id"] = new["id"]
            confirm()
        elif action == "planet":
            orbit.create_planet(user, p, name or val.title(), f"Listings with {val}", "Inner", "other", e["ids"])
            confirm()
        elif action == "dismiss":
            return decline()
        else:
            raise orbit.OrbitError("Unknown answer")
    elif kind == "dwarf_planet":
        pl = db.q1("SELECT * FROM planets WHERE id=?", (e["planet_id"],))
        if action in ("out", "in") and pl:
            lo, hi = orbit.ZONE_EDGES["Belt" if action == "out" else "Inner"]
            db.ex("UPDATE planets SET r=? WHERE id=?", ((lo + hi) / 2, pl["id"]))
            confirm()
        elif action == "leave":
            return decline()
        else:
            raise orbit.OrbitError("Unknown answer")
    elif kind == "asteroid_shower":
        if action in ("forget", "forget_and_planet"):
            if action == "forget_and_planet" and e.get("group"):
                orbit.create_planet(user, p, name or e["group"]["tag"].split(":", 1)[1].title(), "", "Outer", "other", e["group"]["ids"])
            out.update(lessons.forget(p["id"], e["explained"]))
            confirm()
        elif action == "not_yet":
            return decline()
        else:
            raise orbit.OrbitError("Unknown answer")
    elif kind == "outlier":
        if action == "real":
            confirm()
        elif action == "curious":   # counts for half as much, like a comet
            db.ex("UPDATE swipes SET weight=0.5 WHERE listing_id=?", (e["id"],))
            db.ex("UPDATE placements SET weight=0.5 WHERE listing_id=? AND undone=0", (e["id"],))
            confirm()
        elif action == "mistake":
            out["move"] = e["id"]
            confirm()
        else:
            raise orbit.OrbitError("Unknown answer")
    else:
        raise orbit.OrbitError("Unknown event")
    return out


def _note(user, profile, title, action):
    """The vault is the admin's; a dated line about every settled event goes there."""
    if user.get("role") != "admin":
        return
    try:
        from . import obsidian
        obsidian.log_event(profile, title, action)
    except Exception:
        log.exception("Obsidian event note failed")
