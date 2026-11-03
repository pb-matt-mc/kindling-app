"""Build small synthetic worlds straight in the database: listings with tags, placed at chosen ratings."""
import json
import random

from app import db, orbit_math as m


def batch(pid, number=1, status="done", created=None):
    return db.ex("INSERT INTO batches (profile_id, number, status, size, created_at) VALUES (?,?,?,?,?)", (pid, number, status, 10, created or db.now()))


def listing(pid, bid, tags, rating=None, r=None, theta=0.0, kind="first", origin="placed", title=None, created=None, planet=None, reasons=None, weight=1.0):
    n = db.q1("SELECT COUNT(*) n FROM listings")["n"]
    lid = db.ex("INSERT INTO listings (profile_id, batch_id, fb_id, title, tags, photos, created_at, query) VALUES (?,?,?,?,?,?,?,?)",
                (pid, bid, f"w{n}-{random.random()}", title or f"Listing {n}", json.dumps(tags), json.dumps([f"/img/x{n}.jpg"]), created or db.now(), "q"))
    if rating is None and r is None:
        return lid
    if r is None:
        r = m.r_from_rating(rating)
    rating = m.rating(r) if rating is None else rating
    if reasons is None and r > m.SUN_R:
        reasons = m.reason_weights(theta)
    db.ex("INSERT INTO placements (listing_id, profile_id, kind, origin, r, theta, rating, reasons, reason_known, weight, planet_id, created_at) "
          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (lid, pid, kind, origin, r, theta if reasons else None, rating, json.dumps(reasons) if reasons else None,
                                                 1 if origin == "placed" else 0, weight, planet, created or db.now()))
    db.ex("INSERT OR REPLACE INTO swipes (listing_id, verdict, rank, manual, swiped_at, weight) VALUES (?,?,?,0,?,?)",
          (lid, "like" if m.is_like(r) else "dislike", rating, db.now(), weight))
    return lid


STYLES = ["style:rolled", "style:danish", "style:modern", "style:boho", "style:classic"]
COLORS = ["color:green", "color:grey", "color:tan", "color:rust", "color:navy"]
MATS = ["material:velvet", "material:teak", "material:leather", "material:linen", "material:wool"]


def pattern_rating(tags, rng=None):
    """The 'true' taste used by the synthetic people: loves green and velvet, dislikes grey and modern."""
    x = 0.55 + (0.25 if "color:green" in tags else 0) + (0.15 if "material:velvet" in tags else 0) \
        - (0.30 if "color:grey" in tags else 0) - (0.2 if "style:modern" in tags else 0)
    if rng:
        x += rng.uniform(-0.03, 0.03)
    return max(0.02, min(0.98, x))


def populate(pid, n, seed=1, batches=3, rating=pattern_rating):
    rng = random.Random(seed)
    bids = [batch(pid, i + 1, created=1000 + i * 100) for i in range(batches)]
    out = []
    for i in range(n):
        tags = [rng.choice(STYLES), rng.choice(COLORS), rng.choice(MATS)]
        out.append(listing(pid, bids[i % batches], tags, rating=rating(tags, rng), theta=rng.uniform(-3.1, 3.1), created=1000 + i))
    return out, bids
