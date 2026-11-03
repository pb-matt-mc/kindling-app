"""Forgetting: the asteroid shower's other half. What the forgotten listings taught is frozen into a lesson (the same
crystal store learn.py already reads, so older lessons fade as newer ones form), then the listings go. Placements and
checked predictions are kept so the measured scores survive too."""
from . import config, crystal, db, learn
from .log import log


def forget(profile_id, listing_ids):
    ids = set(listing_ids)
    rows = [r for r in learn.swiped(profile_id) if r["id"] in ids]
    if not rows:
        return {"forgotten": 0}
    # What these listings taught is measured against the taste as it stood BEFORE they go, not against their own average
    # (which, for a belt of passes, would cancel the lesson out). Their true average is kept for the running mean.
    ref_mean = learn.weights(profile_id)[1]
    fresh = [r for r in rows if not r["absorbed"]]
    ev, _ = learn.evidence(fresh)
    acc = {}
    for r in fresh:
        w = r.get("weight", 1.0)
        for t in set(r["tags"] or []):
            a = acc.setdefault(t, {"tag": t, "sum": 0.0, "n": 0.0, "likes": 0.0})
            a["sum"] += (r["rank"] - ref_mean) * w
            a["n"] += w
            a["likes"] += w * (r["verdict"] == "like")
    ev = list(acc.values())
    mean = sum(r["rank"] * r.get("weight", 1.0) for r in fresh) / (sum(r.get("weight", 1.0) for r in fresh) or 1.0) if fresh else ref_mean
    qstats = [{"query": q, "shown": len(v), "likes": sum(1 for r in v if r["verdict"] == "like"), "first_used": min(r["created_at"] for r in v)}
              for q, v in _by_query(rows).items()]
    number = (db.q1("SELECT MAX(number) n FROM crystals WHERE profile_id=?", (profile_id,))["n"] or 0) + 1
    taste = db.q1("SELECT taste_summary FROM profiles WHERE id=?", (profile_id,))["taste_summary"] or ""
    with db.tx() as c:
        for b in c.execute("SELECT id FROM batches WHERE profile_id=? AND status='done' AND stats IS NULL", (profile_id,)).fetchall():
            st = learn.batch_stats(profile_id, b[0])
            if st:
                c.execute("UPDATE batches SET stats=? WHERE id=?", (db.dumps(st), b[0]))
        c.execute("INSERT INTO crystals (profile_id, number, n_listings, mean, weights, concepts, query_stats, landmarks, taste_summary, "
                  "kept, kept_in_web, forgotten, created_at) VALUES (?,?,?,?,?,?,?,?,?,0,0,?,?)",
                  (profile_id, number, len([r for r in rows if not r["absorbed"]]), mean, db.dumps(ev), "[]", db.dumps(qstats), "[]", taste,
                   len(rows), db.now()))
        gone = [r["id"] for r in rows]
        for i in range(0, len(gone), 500):
            chunk = gone[i:i + 500]
            marks = ",".join("?" * len(chunk))
            c.execute(f"DELETE FROM swipes WHERE listing_id IN ({marks})", chunk)
            c.execute(f"DELETE FROM planet_members WHERE listing_id IN ({marks})", chunk)
            c.execute(f"DELETE FROM listings WHERE id IN ({marks})", chunk)
    removed = crystal._sweep_images()
    log.info("lesson %s for system %s: %d listings forgotten, %d image files cleared", number, profile_id, len(rows), removed)
    return {"forgotten": len(rows), "lesson": number}


def _by_query(rows):
    out = {}
    for r in rows:
        if r.get("query"):
            out.setdefault(r["query"], []).append(r)
    return out
