import json
import math
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from app import orbit_math as m

ROOT = Path(__file__).resolve().parents[1]
RNG = random.Random(1)


# ---- zones and rating: the prototype's pixel numbers, scaled to field units ----------------------

@pytest.mark.parametrize("px,name", [(0, "Sun"), (34, "Sun"), (34.01, "Inner"), (80, "Inner"), (80.01, "Mid"),
                                      (116, "Mid"), (116.01, "Outer"), (160, "Outer"), (160.01, "Belt"), (186, "Belt")])
def test_zone_edges_match_the_prototype(px, name):
    assert m.zone(px / 186) == name


def test_frost_line_is_the_like_or_pass_boundary():
    assert m.is_like(m.FROST) and not m.is_like(m.FROST + 1e-9)
    assert m.rating(m.FROST) == pytest.approx(0.5)


def test_rating_endpoints():
    assert m.rating(0) == 1.0 and m.rating(1) == 0.0
    assert m.rating(5) == 0.0 and m.rating(-1) == 1.0       # clamped


def test_rating_is_strictly_decreasing_with_distance():
    rs = [i / 500 for i in range(501)]
    vals = [m.rating(r) for r in rs]
    assert all(a > b for a, b in zip(vals, vals[1:]))


def test_rating_and_its_inverse_round_trip():
    for _ in range(500):
        x = RNG.random()
        assert m.rating(m.r_from_rating(x)) == pytest.approx(x, abs=1e-12)
        r = RNG.random()
        assert m.r_from_rating(m.rating(r)) == pytest.approx(r, abs=1e-12)


def test_old_swipe_ranks_land_on_the_right_side_of_the_frost_line():
    assert m.is_like(m.r_from_rating(0.75)) and not m.is_like(m.r_from_rating(0.25))
    assert m.zone(m.r_from_rating(0.75)) in ("Inner", "Mid")
    assert m.zone(m.r_from_rating(0.25)) in ("Outer",)
    assert m.zone(m.r_from_rating(1.0)) == "Sun" and m.zone(m.r_from_rating(0.0)) == "Belt"


def test_keeper_display_position_is_inside_the_sun():
    assert m.zone(m.KEEPER_DISPLAY_R) == "Sun"


# ---- reasons ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("theta,axis", [(-math.pi / 2, "price"), (0, "right"), (math.pi / 2, "guess"),
                                         (math.pi, "wrong"), (-math.pi, "wrong")])
def test_on_an_axis_the_reason_is_pure(theta, axis):
    w = m.reason_weights(theta)
    assert w[axis] == pytest.approx(1.0)
    assert sum(w.values()) == pytest.approx(1.0)
    assert m.percents(w)[axis] == 100


def test_diagonal_splits_evenly():
    w = m.reason_weights(-math.pi / 4)            # up and to the right: price and right vibe
    assert w["price"] == pytest.approx(0.5) and w["right"] == pytest.approx(0.5)
    assert m.percents(w) == {"price": 50, "right": 50, "guess": 0, "wrong": 0}


def test_weights_always_sum_to_one_and_touch_at_most_two_axes():
    for _ in range(2000):
        w = m.reason_weights(RNG.uniform(-10, 10))
        assert sum(w.values()) == pytest.approx(1.0)
        assert sum(1 for v in w.values() if v > 1e-12) <= 2


def test_weights_are_continuous_in_angle():
    prev = m.reason_weights(-math.pi)
    t = -math.pi
    while t < math.pi:
        t += 0.001
        cur = m.reason_weights(t)
        assert max(abs(cur[k] - prev[k]) for k in cur) < 0.002
        prev = cur


def test_percentages_total_100_in_steps_of_5():
    for _ in range(3000):
        p = m.percents(m.reason_weights(RNG.uniform(-math.pi, math.pi)))
        assert sum(p.values()) == 100 and all(v % 5 == 0 for v in p.values())


def test_percentages_follow_the_dominant_axis():
    for _ in range(500):
        w = m.reason_weights(RNG.uniform(-math.pi, math.pi))
        p = m.percents(w)
        top = m.dominant_axis(w)
        assert p[top] == max(p.values())


def test_inside_the_sun_there_are_no_reasons():
    b = m.blend(0.1, 1.234)
    assert b["zone"] == "Sun" and b["reasons"] is None and b["percents"] is None and b["like"]


def test_polar_clamps_to_the_field_and_points_the_right_way():
    r, t = m.polar(3, 4)
    assert r == 1.0 and t == pytest.approx(math.atan2(4, 3))
    assert m.polar(0, -0.5) == (0.5, -math.pi / 2)             # up on screen is Price
    assert m.polar(0, 0)[0] == 0


def test_axes_sit_where_the_handoff_puts_them():
    ax = dict(m.AXES)
    assert ax["price"] == -math.pi / 2 and ax["guess"] == math.pi / 2 and ax["wrong"] == math.pi and ax["right"] == 0


# ---- same-spot listings stay separately visible ------------------------------------------------------

def pts(n, x=0.3, y=0.2, jitter=0.0):
    return [{"id": i, "x": x + RNG.uniform(-jitter, jitter), "y": y + RNG.uniform(-jitter, jitter)} for i in range(1, n + 1)]


def test_fan_out_never_changes_stored_positions():
    items = pts(8)
    before = json.dumps(items)
    out = m.fan_out(items, 0.12)
    assert json.dumps(items) == before
    assert {p["id"]: (p["true_x"], p["true_y"]) for p in out["placed"]} == {i["id"]: (i["x"], i["y"]) for i in items}


def test_fan_out_is_independent_of_input_order():
    items = pts(9, jitter=0.02)
    a = m.fan_out(items, 0.12)
    b = m.fan_out(list(reversed(items)), 0.12)
    assert a == b


def test_fan_out_separates_a_pile():
    out = m.fan_out(pts(10), 0.12, max_visible=12)["placed"]
    assert len(out) == 10
    d = min(math.hypot(a["x"] - b["x"], a["y"] - b["y"]) for i, a in enumerate(out) for b in out[i + 1:])
    assert d >= 0.12 * 0.9


def test_fan_out_leaves_lone_listings_alone():
    out = m.fan_out([{"id": 1, "x": 0, "y": 0}, {"id": 2, "x": 0.5, "y": 0.5}], 0.12)["placed"]
    assert all((p["x"], p["y"]) == (p["true_x"], p["true_y"]) and not p["leader"] for p in out)


def test_a_dense_sun_folds_the_overflow_into_one_badge():
    items = [{"id": i, "x": 0.05, "y": -0.04} for i in range(1, 55)]
    out = m.fan_out(items, 0.12, max_visible=12)
    assert len(out["placed"]) == 11 and len(out["collapsed"]) == 1
    assert sorted(p["id"] for p in out["placed"]) + out["collapsed"][0]["ids"] == list(range(1, 55))


# ---- the JavaScript mirror gives the same answers ------------------------------------------------------

def test_fixtures_still_match_the_python(tmp_path):
    fx = json.loads((ROOT / "tests/fixtures/orbit_math.json").read_text())
    for c in fx["blend"]:
        got = m.blend(c["r"], c["theta"])
        assert got["zone"] == c["out"]["zone"] and got["percents"] == c["out"]["percents"]
        assert got["rating"] == pytest.approx(c["out"]["rating"], abs=1e-12)
    for c in fx["fan_out"]:
        assert [p["id"] for p in m.fan_out(c["items"], c["marker"])["placed"]] == [p["id"] for p in c["out"]["placed"]]


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_javascript_matches_python_on_every_fixture():
    r = subprocess.run(["node", str(ROOT / "tests/js_math_check.js")], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["total"] == 0


def test_fixture_file_matches_what_the_generator_would_write(tmp_path):
    """Changing the math without regenerating the fixtures (and so re-checking the JS) fails here."""
    src = (ROOT / "scripts/make_math_fixtures.py").read_text().replace(
        'dest = ROOT / "tests/fixtures/orbit_math.json"', f'dest = Path(r"{tmp_path}/fx.json")')
    script = tmp_path / "gen.py"
    script.write_text(src.replace("ROOT = Path(__file__).resolve().parents[1]", f'ROOT = Path(r"{ROOT}")'))
    subprocess.run(["python3", str(script)], check=True, capture_output=True)
    assert json.loads((tmp_path / "fx.json").read_text()) == json.loads((ROOT / "tests/fixtures/orbit_math.json").read_text())
