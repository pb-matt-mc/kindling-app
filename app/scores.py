"""Measured scores per system. Nothing here is self-reported by a model.

Confidence: how close Claude's predicted rating was to the person's, over checked predictions only (the locked
prediction made before a listing was shown, compared with the first placement). Moves and rocketed listings never
create a check, so they cannot move it.

Wild card rate: how often the person places toward Claude's guess (the down axis). It reads placements only, and
Confidence reads predictions only, so neither can feed the other.

Confidence shows "learning" until it is statistically determinable: at least MIN_CHECKED checks and a 95% interval
narrower than plus or minus MAX_HALF_WIDTH. Wild card rate is a yes/no frequency, whose interval is naturally wide, so it
shows after WILD_MIN placements and always carries its interval instead.
"""
import math

from . import db
from .orbit_math import SUN_R

MIN_CHECKED = 5
WILD_MIN = 10
MAX_HALF_WIDTH = 0.15      # 15 points
WINDOW = 30                # most recent checks that count
RECENCY = 0.93             # each older check counts this much as the next newer one
Z = 2.0


def _weighted_mean_interval(values):
    """values newest first -> (mean, half_width of ~95% interval, effective n)."""
    w = [RECENCY ** i for i in range(len(values))]
    sw = sum(w)
    mean = sum(wi * v for wi, v in zip(w, values)) / sw
    var = sum(wi * (v - mean) ** 2 for wi, v in zip(w, values)) / sw
    n_eff = sw * sw / sum(wi * wi for wi in w)
    return mean, Z * math.sqrt(var / n_eff), n_eff


def _learning(n):
    return {"state": "learning", "n": n, "needed": MIN_CHECKED}


def confidence(profile_id):
    gaps = [r["gap"] for r in db.q(
        "SELECT gap FROM predictions WHERE profile_id=? AND checked_at IS NOT NULL AND gap IS NOT NULL "
        "ORDER BY checked_at DESC, listing_id DESC LIMIT ?", (profile_id, WINDOW))]
    if len(gaps) < MIN_CHECKED:
        return _learning(len(gaps))
    mean, half, n_eff = _weighted_mean_interval(gaps)
    if half > MAX_HALF_WIDTH:
        return {**_learning(len(gaps)), "half_width": round(half, 4)}
    return {"state": "ready", "value": round(1.0 - mean, 4), "half_width": round(half, 4), "n": len(gaps)}


def wild_card_rate(profile_id):
    rows = db.q("SELECT reasons FROM placements WHERE profile_id=? AND kind='first' AND origin='placed' "
                "AND reason_known=1 AND undone=0 AND r>? ORDER BY id DESC LIMIT ?", (profile_id, SUN_R, WINDOW))
    hits = [1.0 if (r["reasons"] or {}).get("guess", 0) >= 0.5 else 0.0 for r in rows if r["reasons"]]
    if len(hits) < WILD_MIN:
        return {"state": "learning", "n": len(hits), "needed": WILD_MIN}
    mean, half, _ = _weighted_mean_interval(hits)
    return {"state": "ready", "value": round(mean, 4), "half_width": round(half, 4), "n": len(hits)}


def sun_pick(profile_id):
    """Binary stars: how often Claude's starting sun was the one the person left the listing on. Kept apart from Confidence."""
    rows = db.q("SELECT sun_guess, sun_actual FROM predictions WHERE profile_id=? AND sun_guess IS NOT NULL AND sun_actual IS NOT NULL "
                "AND checked_at IS NOT NULL ORDER BY checked_at DESC LIMIT ?", (profile_id, WINDOW))
    if len(rows) < MIN_CHECKED:
        return {"state": "learning", "n": len(rows), "needed": MIN_CHECKED}
    return {"state": "ready", "value": round(sum(1 for r in rows if r["sun_guess"] == r["sun_actual"]) / len(rows), 4), "n": len(rows)}
