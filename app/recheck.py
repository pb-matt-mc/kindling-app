"""Before each batch, re-check the listings in the Sun and Inner orbit with the source.

A sold listing fades on the field but is never deleted, so what it taught the model is kept. A listing the source
can't answer for stays unmarked rather than being called sold. Each listing is re-checked at most once a day and
at most MAX_PER_BATCH are checked per batch (each costs about one source credit), oldest check first.
"""
from . import db
from .log import log
from .orbit_math import INNER_R

MAX_PER_BATCH = 25
MIN_AGE = 24 * 3600


async def run(profile_id, src, max_n=MAX_PER_BATCH, min_age=MIN_AGE):
    """-> {"checked", "live", "gone", "unknown", "changed", "credits"}"""
    now = db.now()
    rows = db.q(
        "SELECT l.id, l.fb_id, l.price, l.avail, l.avail_at FROM placements p JOIN listings l ON l.id=p.listing_id "
        "WHERE p.profile_id=? AND p.undone=0 AND p.r<=? AND p.id=(SELECT MAX(id) FROM placements q WHERE q.listing_id=p.listing_id "
        "AND q.undone=0) AND COALESCE(l.avail,'')!='gone' AND (l.avail_at IS NULL OR l.avail_at<?) "
        "ORDER BY COALESCE(l.avail_at, 0) ASC, l.id ASC LIMIT ?", (profile_id, INNER_R, now - min_age, max_n))
    out = {"checked": len(rows), "live": 0, "gone": 0, "unknown": 0, "changed": 0, "credits": 0}
    if not rows:
        return out
    by_fb = {r["fb_id"]: r for r in rows}
    details, credits = await src.items(list(by_fb))
    out["credits"] = credits
    for fb_id, r in by_fb.items():
        d = details.get(fb_id)
        if not d:
            out["unknown"] += 1
            continue
        state = "live" if d.get("is_live", True) else "gone"
        out[state] += 1
        new = d.get("price")
        if state == "live" and new is not None and r["price"] is not None and float(new) != float(r["price"]):
            out["changed"] += 1
            db.ex("UPDATE listings SET avail=?, avail_at=?, price_prev=?, price=?, price_text=? WHERE id=?",
                  (state, now, r["price"], new, d.get("price_text") or f"${new:g}", r["id"]))
        else:
            db.ex("UPDATE listings SET avail=?, avail_at=? WHERE id=?", (state, now, r["id"]))
    log.info("re-check for system %s: %s", profile_id, out)
    return out
