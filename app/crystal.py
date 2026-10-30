"""Crystallize: lock the web's taste into a crystal, keep the keepers, let the rest of the listings go."""
import math

from . import config, db, learn
from .log import log


class CrystalError(Exception):
    pass


def _blocking_batch(profile_id):
    b = db.q1("SELECT * FROM batches WHERE profile_id=? AND status!='done' ORDER BY id DESC LIMIT 1", (profile_id,))
    if b and b["status"] not in ("error",):
        return b
    return None


def _top(ev, sign, n=6):
    rows = [e for e in ev if e["n"] >= 2 and not e["tag"].startswith(("shape:", "condition:"))]
    rows = sorted(rows, key=lambda e: -sign * e["sum"] / (e["n"] + learn.SHRINK))
    return [e["tag"].split(":", 1)[1] for e in rows if sign * e["sum"] > 0][:n]


def _concepts(profile_id):
    out = []
    for g in learn.groups(profile_id):
        out.append({"label": g["label"], "traits": [t.split(":", 1)[1] for t in learn.concept_traits(g["member_tags"])],
                    "size": len(g["members"])})
    return out


def preview(profile):
    pid = profile["id"]
    web = learn.swiped(pid)
    ev_rows = [r for r in web if not r["absorbed"]]
    ev, _ = learn.evidence(ev_rows)
    blocking = _blocking_batch(pid)
    return {
        "web_count": len(web),
        "limit": learn.WEB_LIMIT,
        "new_evidence": len(ev_rows),
        "pulls": _top(ev, 1),
        "pushes": _top(ev, -1),
        "traits": len([e for e in ev if e["n"] >= 2]),
        "concepts": _concepts(pid),
        "searches": len(learn.live_query_stats(pid)),
        "taste_summary": profile["taste_summary"],
        "crystals": db.q1("SELECT COUNT(*) n FROM crystals WHERE profile_id=?", (pid,))["n"],
        "fade": learn.CRYSTAL_FADE,
        "blocking_batch": blocking["number"] if blocking else None,
        "listings": [{"id": r["id"], "title": r["title"], "price": r["price"], "price_text": r["price_text"],
                      "photos": r["photos"], "location_text": r["location_text"], "verdict": r["verdict"],
                      "rank": r["rank"], "keeper": bool(r["keeper"]), "carried": bool(r["absorbed"]),
                      "predicted": r["predicted"], "explore": r["explore"]}
                     for r in web],
    }


def _fallback_landmarks(profile_id):
    g = learn.graph(profile_id)
    ranks = {n["id"]: n["rank"] for n in g["nodes"]}
    out = []
    for i, c in enumerate(g["clusters"]):
        r = 1 - sum(ranks[m] for m in c["members"]) / len(c["members"])  # loved traits sit near the middle
        a = i * 2 * math.pi / max(1, len(g["clusters"]))
        out.append({"label": c["label"], "weight": c["weight"], "x": r * math.cos(a), "y": r * math.sin(a)})
    return out


def crystallize(profile, keepers, keep_in_web, landmarks=None):
    pid = profile["id"]
    blocking = _blocking_batch(pid)
    if blocking:
        raise CrystalError(f"Finish batch {blocking['number']} first, then crystallize.")
    web = learn.swiped(pid)
    if not web:
        raise CrystalError("The web is empty, so there's nothing to crystallize yet.")
    web_ids = {r["id"] for r in web}
    keepers = set(keepers or []) & web_ids
    keep_in_web = set(keep_in_web or []) & web_ids

    ev_rows = [r for r in web if not r["absorbed"]]
    ev, mean = learn.evidence(ev_rows)
    concepts = _concepts(pid)
    qstats = learn.live_query_stats(pid)
    lms = [l for l in (landmarks or []) if isinstance(l, dict) and l.get("label")][:8] or _fallback_landmarks(pid)
    number = (db.q1("SELECT MAX(number) n FROM crystals WHERE profile_id=?", (pid,))["n"] or 0) + 1

    forget = [r for r in web if r["id"] not in keep_in_web and r["id"] not in keepers]
    with db.tx() as c:
        # freeze recap numbers for every finished batch before its listings go
        for b in c.execute("SELECT id FROM batches WHERE profile_id=? AND status='done' AND stats IS NULL",
                           (pid,)).fetchall():
            st = learn.batch_stats(pid, b[0])
            if st:
                c.execute("UPDATE batches SET stats=? WHERE id=?", (db.dumps(st), b[0]))
        c.execute(
            "INSERT INTO crystals (profile_id, number, n_listings, mean, weights, concepts, query_stats, landmarks, "
            "taste_summary, kept, kept_in_web, forgotten, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, number, len(ev_rows), mean, db.dumps(ev), db.dumps(concepts), db.dumps(qstats), db.dumps(lms),
             profile["taste_summary"] or "", len(keepers), len(keep_in_web), len(forget), db.now()))
        for r in web:
            if r["id"] in keep_in_web:
                c.execute("UPDATE listings SET absorbed=1, keeper=? WHERE id=?", (int(r["id"] in keepers), r["id"]))
            elif r["id"] in keepers:
                c.execute("UPDATE listings SET state='out', keeper=1, absorbed=1 WHERE id=?", (r["id"],))
        gone = [r["id"] for r in forget]
        for i in range(0, len(gone), 500):
            chunk = gone[i:i + 500]
            marks = ",".join("?" * len(chunk))
            c.execute(f"DELETE FROM swipes WHERE listing_id IN ({marks})", chunk)
            c.execute(f"DELETE FROM listings WHERE id IN ({marks})", chunk)
        # categories only exist in the web; keep the ones that still have two listings there
        c.execute("DELETE FROM group_members WHERE listing_id NOT IN (SELECT id FROM listings WHERE state='web')")
        c.execute("DELETE FROM groups WHERE profile_id=? AND id NOT IN "
                  "(SELECT group_id FROM group_members GROUP BY group_id HAVING COUNT(*) >= 2)", (pid,))
        c.execute("DELETE FROM group_members WHERE group_id NOT IN (SELECT id FROM groups)")

    removed = _sweep_images()
    log.info("crystal %s formed for profile %s: %d listings of taste, %d keepers, %d kept in web, %d forgotten, "
             "%d image files cleared", number, pid, len(ev_rows), len(keepers), len(keep_in_web), len(forget), removed)
    return {"number": number, "absorbed": len(ev_rows), "kept": len(keepers), "kept_in_web": len(keep_in_web),
            "forgotten": len(forget)}


def _sweep_images():
    """Delete cached photos nothing points at anymore (forgotten listings, unpicked thumbnails)."""
    used = set()
    for r in db.q("SELECT photos FROM listings"):
        for p in r["photos"] or []:
            used.add(p.rsplit("/", 1)[-1])
    active = db.q1("SELECT COUNT(*) n FROM batches WHERE status IN ('queued','searching','screening','scoring')")["n"]
    if active:
        return 0  # a batch is mid-build and may be using fresh thumbnails
    removed = 0
    for f in config.IMG_DIR.iterdir():
        if f.is_file() and f.name not in used:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def keepers(profile_id):
    return db.q("SELECT l.*, s.verdict, s.rank FROM listings l LEFT JOIN swipes s ON s.listing_id=l.id "
                "WHERE l.profile_id=? AND l.keeper=1 ORDER BY l.created_at DESC", (profile_id,))
