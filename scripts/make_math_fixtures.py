#!/usr/bin/env python3
"""Regenerate tests/fixtures/orbit_math.json from app/orbit_math.py. Run only when the math is changed ON PURPOSE;
tests fail on any difference, in Python and in JavaScript."""
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import orbit_math as m  # noqa: E402

rng = random.Random(20261103)
radii = [0, 0.05, m.SUN_R, m.SUN_R + 1e-6, m.INNER_R, 0.5, m.FROST, m.FROST + 1e-6, m.OUTER_R, 0.95, 1.0]
radii += [rng.random() for _ in range(40)]
angles = [-math.pi, -3 * math.pi / 4, -math.pi / 2, -math.pi / 4, 0, math.pi / 4, math.pi / 2, 3 * math.pi / 4, math.pi]
angles += [rng.uniform(-math.pi, math.pi) for _ in range(60)]
blend = [{"r": r, "theta": a, "out": m.blend(r, a)} for r in radii for a in angles[:12]]
blend += [{"r": rng.random(), "theta": rng.uniform(-math.pi, math.pi)} for _ in range(150)]
for b in blend:
    b["out"] = m.blend(b["r"], b["theta"])
ratings = [{"x": x / 40, "r": m.r_from_rating(x / 40), "back": m.rating(m.r_from_rating(x / 40))} for x in range(41)]
polar = [{"dx": dx, "dy": dy, "out": list(m.polar(dx, dy))} for dx, dy in
         [(0, 0), (1, 0), (0, -1), (-0.3, 0.4), (2, 2), (-0.01, -0.5)] + [(rng.uniform(-1.2, 1.2), rng.uniform(-1.2, 1.2)) for _ in range(30)]]
fans = []
for scenario, pts in {
    "same_spot": [(i, 0.3, 0.2) for i in range(1, 6)],
    "near": [(1, 0.1, 0.1), (2, 0.11, 0.1), (3, 0.9, 0.9)],
    "dense_sun": [(i, 0.05 + 0.001 * (i % 5), -0.04) for i in range(1, 55)],
    "apart": [(1, 0, 0), (2, 0.5, 0.5)],
    "ids_out_of_order": [(9, 0.3, 0.3), (2, 0.3, 0.3), (5, 0.3, 0.3)],
}.items():
    items = [{"id": i, "x": x, "y": y} for i, x, y in pts]
    fans.append({"name": scenario, "items": items, "marker": 0.12, "out": m.fan_out(items, 0.12)})
out = {"constants": {"SUN_R": m.SUN_R, "INNER_R": m.INNER_R, "FROST": m.FROST, "OUTER_R": m.OUTER_R},
       "blend": blend, "ratings": ratings, "polar": polar, "fan_out": fans}
dest = ROOT / "tests/fixtures/orbit_math.json"
dest.write_text(json.dumps(out, indent=0))
print(f"wrote {dest} ({len(blend)} blend, {len(fans)} fan-out cases)")
