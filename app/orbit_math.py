"""Orbit's placing math. Pure functions, no database, mirrored one-for-one in static/orbit-math.js.

Geometry comes from the handoff prototype (screens/Main.dc.html): a 390x844 frame, the sun at (195, 384), a field
of radius 186 px. Everything here is in normalized field units (field radius = 1) so the field can scale to any
screen. Screen coordinates: x to the right, y DOWN, angle 0 = right, -pi/2 = up (Price), pi/2 = down (Claude's guess).

  distance from the sun is the rating, with the frost line at rating 0.5 (inside = like, outside = pass)
  direction is the reason: a continuous blend of the two nearest of the four axes
"""
import math

PROTOTYPE_FIELD_PX = 186.0
SUN_R = 34 / PROTOTYPE_FIELD_PX
INNER_R = 80 / PROTOTYPE_FIELD_PX
FROST = 116 / PROTOTYPE_FIELD_PX          # outer edge of Mid: the like or pass boundary
OUTER_R = 160 / PROTOTYPE_FIELD_PX
ZONES = (("Sun", SUN_R), ("Inner", INNER_R), ("Mid", FROST), ("Outer", OUTER_R), ("Belt", 1.0))

# axis -> angle. Price up, Claude's guess down, Wrong vibe left, Right vibe right.
AXES = (("price", -math.pi / 2), ("right", 0.0), ("guess", math.pi / 2), ("wrong", math.pi))
AXIS_NAMES = tuple(a for a, _ in AXES)
AXIS_NAMES_PRETTY = {"price": "Price", "right": "Right vibe", "guess": "Claude's guess", "wrong": "Wrong vibe"}
HALF_PI = math.pi / 2
KEEPER_DISPLAY_R = SUN_R * 0.55            # where migrated Sun listings sit (inside the Sun, direction unknown)


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def zone(r):
    for name, edge in ZONES:
        if r <= edge:
            return name
    return "Belt"


def is_like(r):
    return r <= FROST


def rating(r):
    """1.0 at the sun, 0.5 on the frost line, 0.0 at the edge of the field. Piecewise linear."""
    r = clamp(r, 0.0, 1.0)
    if r <= FROST:
        return 1.0 - 0.5 * r / FROST
    return 0.5 - 0.5 * (r - FROST) / (1.0 - FROST)


def r_from_rating(x):
    """Inverse of rating(). Old likes (0.75) and dislikes (0.25) land mid-way inside and outside the frost line."""
    x = clamp(x, 0.0, 1.0)
    if x >= 0.5:
        return 2.0 * FROST * (1.0 - x)
    return FROST + (1.0 - FROST) * 2.0 * (0.5 - x)


def polar(dx, dy):
    """(r, theta) from a screen offset in field units. r is clamped to the field edge."""
    r = math.hypot(dx, dy)
    theta = math.atan2(dy, dx)
    return min(r, 1.0), theta


def angular_distance(a, b):
    d = abs(a - b) % (2 * math.pi)
    return min(d, 2 * math.pi - d)


def reason_weights(theta):
    """{price, right, guess, wrong} summing to 1. Between two axes the weight splits linearly."""
    raw = {name: max(0.0, 1.0 - angular_distance(theta, ang) / HALF_PI) for name, ang in AXES}
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()}


def percents(weights, step=5):
    """Whole-number percentages in multiples of `step` that always total 100 (largest remainder, fixed tie order)."""
    units = 100 // step
    scaled = [(name, weights[name] * units) for name in AXIS_NAMES]
    base = {name: int(math.floor(v + 1e-9)) for name, v in scaled}
    left = units - sum(base.values())
    order = sorted(scaled, key=lambda nv: (-(nv[1] - math.floor(nv[1] + 1e-9)), AXIS_NAMES.index(nv[0])))
    for name, _ in order[:left]:
        base[name] += 1
    return {name: base[name] * step for name in AXIS_NAMES}


def blend(r, theta):
    """Everything the readout needs for one position. Inside the Sun there is no direction, so no reasons."""
    z = zone(r)
    out = {"r": r, "zone": z, "rating": rating(r), "like": is_like(r), "reasons": None, "percents": None}
    if z != "Sun":
        w = reason_weights(theta)
        out["reasons"], out["percents"] = w, percents(w)
    return out


def dominant_axis(weights):
    return max(AXIS_NAMES, key=lambda k: (weights[k], -AXIS_NAMES.index(k)))


GOLDEN_ANGLE = 2.399963229728653


def fan_out(items, marker, max_visible=12, spread=1.0):
    """Make listings at (nearly) the same spot separately visible without touching their stored position.

    items: [{"id", "x", "y"}] true positions in field units; marker: marker diameter in the same units.
    Items closer than one marker belong to a cluster. A cluster's members are laid on a golden-angle spiral around
    the cluster's centre, in id order, so the result depends only on the data and never on insertion order.
    Returns {"placed": [{"id", "x", "y", "true_x", "true_y", "leader"}], "collapsed": [{"ids", "x", "y"}]}:
    members past max_visible are folded into one count badge that opens a list (a dense Sun cannot hold 50 markers).
    """
    items = sorted(items, key=lambda i: i["id"])
    parent = list(range(len(items)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if math.hypot(items[i]["x"] - items[j]["x"], items[i]["y"] - items[j]["y"]) < marker:
                parent[find(j)] = find(i)
    groups = {}
    for i, it in enumerate(items):
        groups.setdefault(find(i), []).append(it)
    placed, collapsed = [], []
    for members in groups.values():
        cx = sum(m["x"] for m in members) / len(members)
        cy = sum(m["y"] for m in members) / len(members)
        for k, m in enumerate(members):
            if len(members) > max_visible and k >= max_visible - 1:
                break
            off = marker * spread * math.sqrt(k)
            x, y = (cx + off * math.cos(k * GOLDEN_ANGLE), cy + off * math.sin(k * GOLDEN_ANGLE)) if len(members) > 1 else (m["x"], m["y"])
            placed.append({"id": m["id"], "x": x, "y": y, "true_x": m["x"], "true_y": m["y"],
                           "leader": math.hypot(x - m["x"], y - m["y"]) > marker * 0.2})
        if len(members) > max_visible:
            rest = members[max_visible - 1:]
            collapsed.append({"ids": [m["id"] for m in rest], "x": cx, "y": cy})
    placed.sort(key=lambda p: p["id"])
    return {"placed": placed, "collapsed": collapsed}
