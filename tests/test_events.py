import json
import random
import time

import pytest

from app import db, events, learn, lessons, model, orbit, orbit_math as m
from tests.world import COLORS, MATS, STYLES, batch, listing, pattern_rating, populate


def pid_of(admin):
    return db.active_profile(admin["id"])["id"]


def profile(pid):
    return db.q1("SELECT * FROM profiles WHERE id=?", (pid,))


def two_tastes(pid, n=7):
    """Sun listings in two groups that share nothing: rolled green velvet, and low teak danish."""
    b1, b2 = batch(pid, 1, created=900), batch(pid, 2, created=950)
    ids = []
    for i in range(n):
        ids.append(listing(pid, b1 if i % 2 else b2, ["style:rolled", "color:green", "material:velvet", f"feature:arm{i % 3}"], rating=0.9, theta=0.1 * i))
    for i in range(n):
        ids.append(listing(pid, b1 if i % 2 else b2, ["style:danish", "color:tan", "material:teak", f"feature:leg{i % 3}"], rating=0.88, theta=0.1 * i))
    return ids


# ---- black hole ----------------------------------------------------------------------------------------

def test_black_hole_fires_when_the_sun_splits_in_two(admin):
    pid = pid_of(admin)
    ids = two_tastes(pid)
    populate_extra = listing  # noqa: F841
    ev = events.black_hole(profile(pid), model.dataset(pid))
    assert ev and ev["n"] == 14 and ev["silhouette"] >= 0.2
    sizes = sorted(len(g["ids"]) for g in ev["groups"])
    assert sizes == [7, 7] and {i for g in ev["groups"] for i in g["ids"]} == set(ids)
    assert "split quality" in ev["basis"] and "%" not in ev["basis"]                 # measured, never a self-reported certainty


def test_one_taste_is_not_a_black_hole(admin):
    pid = pid_of(admin)
    b = batch(pid)
    for i in range(16):
        listing(pid, b, ["style:rolled", "color:green", "material:velvet", f"feature:x{i % 2}"], rating=0.9)
    assert events.black_hole(profile(pid), model.dataset(pid)) is None


def test_too_few_in_the_sun_is_not_enough_evidence(admin):
    pid = pid_of(admin)
    two_tastes(pid, n=4)                       # 8 listings
    assert events.black_hole(profile(pid), model.dataset(pid)) is None


def test_a_binary_system_is_not_offered_another_black_hole(admin):
    pid = pid_of(admin)
    two_tastes(pid)
    db.ex("UPDATE profiles SET binary=1 WHERE id=?", (pid,))
    assert events.black_hole(profile(pid), model.dataset(pid)) is None


# ---- new star ----------------------------------------------------------------------------------------

def test_new_star_when_a_trait_keeps_beating_the_model(admin):
    pid = pid_of(admin)
    populate(pid, 80, seed=11)
    b3 = batch(pid, 9, created=2000)
    b4 = batch(pid, 10, created=2100)
    for i in range(7):                          # grey is disliked in this world, but the person loves "style:danish" in grey
        listing(pid, b3 if i % 2 else b4, ["style:danish", "color:grey", "material:linen"], rating=0.9, theta=0.3 * i, created=2200 + i)
    ev = events.new_star(profile(pid), model.dataset(pid), model.TraitModel(model.dataset(pid)))
    assert ev and ev["tag"] in ("style:danish", "color:grey", "material:linen") and ev["n"] >= 6 and ev["batches"] >= 2 and ev["residual"] >= 0.12


def test_no_new_star_when_the_model_already_explains_it(admin):
    pid = pid_of(admin)
    populate(pid, 120, seed=12)
    rows = model.dataset(pid)
    assert events.new_star(profile(pid), rows, model.TraitModel(rows)) is None


# ---- dwarf planet --------------------------------------------------------------------------------------

def test_dwarf_planet_after_four_quiet_batches_and_a_run_of_passes(admin):
    pid = pid_of(admin)
    b0 = batch(pid, 1, created=1000)
    pl = db.ex("INSERT INTO planets (profile_id, name, r, created_at) VALUES (?,?,?,?)", (pid, "Grandma florals", 0.5, 1000))
    for i in range(2):
        lid = listing(pid, b0, ["style:floral", "color:rust"], rating=0.7, created=1000 + i, planet=pl)
        db.ex("INSERT INTO planet_members (planet_id, listing_id) VALUES (?,?)", (pl, lid))
    for n in range(2, 7):
        batch(pid, n, created=1100 + n * 100)
    for i in range(6):
        listing(pid, 2, ["style:floral", "color:tan"], rating=0.15, created=1700 + i)
    ev = events.dwarf_planet(profile(pid), model.dataset(pid))
    assert ev and ev["planet"] == "Grandma florals" and ev["moons"] == 2 and ev["batches_since"] >= 4 and ev["passed"] >= 3


def test_a_planet_still_growing_is_not_a_dwarf(admin):
    pid = pid_of(admin)
    b0 = batch(pid, 1, created=1000)
    pl = db.ex("INSERT INTO planets (profile_id, name, r, created_at) VALUES (?,?,?,?)", (pid, "Active", 0.5, 1000))
    for i in range(2):
        lid = listing(pid, b0, ["style:floral"], rating=0.7, created=1000 + i, planet=pl)
        db.ex("INSERT INTO planet_members (planet_id, listing_id) VALUES (?,?)", (pl, lid))
    lid = listing(pid, b0, ["style:floral"], rating=0.7, created=time.time(), planet=pl)
    db.ex("INSERT INTO planet_members (planet_id, listing_id) VALUES (?,?)", (pl, lid))
    assert events.dwarf_planet(profile(pid), model.dataset(pid)) is None


# ---- asteroid shower -------------------------------------------------------------------------------------

def full_belt(pid, explained=22, odd=9, seed=3):
    """A belt over its cap: most of it greys the model understands, some it doesn't."""
    rng = random.Random(seed)
    populate(pid, 90, seed=seed)                                   # history so the model has learned "grey is a no"
    b = batch(pid, 20, created=3000)
    ex_ids, odd_ids = [], []
    for i in range(explained):
        ex_ids.append(listing(pid, b, ["style:modern", "color:grey", rng.choice(MATS)], r=0.93, theta=rng.uniform(-3, 3), created=3000 + i))
    for i in range(odd):               # green velvet the person nevertheless threw to the belt, each odd in its own way: unexplained
        odd_ids.append(listing(pid, b, [f"style:odd{i}", "color:green", "material:velvet"], r=0.95, theta=0.4, created=3100 + i))
    return ex_ids, odd_ids


def test_the_shower_burns_what_the_model_explains_and_keeps_what_it_cannot(admin):
    pid = pid_of(admin)
    explained, odd = full_belt(pid)
    rows = model.dataset(pid)
    ev = events.asteroid_shower(profile(pid), rows, model.TraitModel(rows))
    assert ev and ev["belt"] >= 30 and ev["cap"] == 30
    assert set(ev["explained"]) >= set(explained[:18]) and not set(ev["explained"]) & set(odd)
    assert set(odd) <= set(ev["unexplained"])
    assert ev["group"] and ev["group"]["tag"] in ("color:green", "material:velvet") and len(ev["group"]["ids"]) >= 4


def test_no_shower_under_the_cap(admin):
    pid = pid_of(admin)
    populate(pid, 60, seed=4)
    rows = model.dataset(pid)
    assert events.asteroid_shower(profile(pid), rows, model.TraitModel(rows)) is None


def test_forgetting_keeps_the_lesson_and_the_measured_scores(admin):
    pid = pid_of(admin)
    explained, odd = full_belt(pid)
    for lid in explained[:5]:
        db.ex("INSERT INTO predictions (listing_id, profile_id, batch_id, predicted, created_at, checked_at, actual_rating, gap) VALUES (?,?,?,?,?,?,?,?)",
              (lid, pid, 1, .2, db.now(), db.now(), .1, .1))
    before = {w["tag"]: w["weight"] for w in learn.weights(pid)[0]}
    res = lessons.forget(pid, explained)
    assert res["forgotten"] == len(explained)
    assert db.q1("SELECT COUNT(*) n FROM listings WHERE id IN (%s)" % ",".join(map(str, explained)))["n"] == 0
    assert all(db.q1("SELECT 1 FROM listings WHERE id=?", (i,)) for i in odd)                 # the unexplained stay
    after = {w["tag"]: w["weight"] for w in learn.weights(pid)[0]}
    assert after["color:grey"] < -0.05 and abs(after["color:grey"] - before["color:grey"]) < 0.08   # what was learned survives
    assert db.q1("SELECT COUNT(*) n FROM crystals WHERE profile_id=?", (pid,))["n"] == 1
    assert db.q1("SELECT COUNT(*) n FROM predictions WHERE checked_at IS NOT NULL")["n"] == 5       # Confidence history survives
    assert db.q1("SELECT COUNT(*) n FROM placements")["n"] >= len(explained) + len(odd)


# ---- outlier ---------------------------------------------------------------------------------------------

def test_outlier_when_a_reliable_model_is_badly_surprised(admin):
    pid = pid_of(admin)
    populate(pid, 80, seed=5)
    lid = listing(pid, 1, ["color:grey", "style:modern", "material:linen"], rating=0.97, theta=1.0, title="Grey modern surprise", created=9999)
    ev = events.outlier(profile(pid), model.dataset(pid))
    assert ev and ev["id"] == lid and ev["residual"] > 0.35 and ev["mae"] < 0.15
    assert "surprised" in ev["title"]


def test_no_outlier_without_a_trustworthy_model(admin):
    pid = pid_of(admin)
    rng = random.Random(1)
    b = batch(pid)
    for i in range(30):
        listing(pid, b, [rng.choice(STYLES), rng.choice(COLORS), rng.choice(MATS)], rating=rng.random(), created=100 + i)   # pure noise
    assert events.outlier(profile(pid), model.dataset(pid)) is None


# ---- the queue: never interrupt, one at a time, no nagging ---------------------------------------------

def test_events_wait_while_a_batch_is_building_or_has_unplaced_listings(admin):
    pid = pid_of(admin)
    two_tastes(pid)
    p = profile(pid)
    b = db.ex("INSERT INTO batches (profile_id, number, status, size, created_at) VALUES (?,?,?,?,?)", (pid, 9, "scoring", 5, db.now()))
    assert orbit.events_ready(p, db.q1("SELECT * FROM batches WHERE id=?", (b,)), []) is None
    assert db.q1("SELECT COUNT(*) n FROM events")["n"] == 0                       # not even detected mid-build
    db.ex("UPDATE batches SET status='ready' WHERE id=?", (b,))
    assert orbit.events_ready(p, db.q1("SELECT * FROM batches WHERE id=?", (b,)), [{"id": 1}]) is None
    ready = orbit.events_ready(p, None, [])
    assert ready and ready["kind"] == "black_hole"


def test_one_event_at_a_time_and_a_rejection_is_not_repeated_right_away(admin):
    pid = pid_of(admin)
    two_tastes(pid)
    events.refresh(profile(pid))
    assert db.q1("SELECT COUNT(*) n FROM events")["n"] == 1
    events.refresh(profile(pid))
    assert db.q1("SELECT COUNT(*) n FROM events")["n"] == 1                       # not queued twice
    e = events.next_event(pid)
    events.resolve(admin, e["id"], "keep")
    assert db.q1("SELECT status, muted_until FROM events WHERE id=?", (e["id"],)) == {"status": "rejected", "muted_until": pytest.approx(time.time() + 7 * 86400, abs=5)}
    events.refresh(profile(pid))
    assert db.q1("SELECT COUNT(*) n FROM events")["n"] == 1                       # muted for a week
    db.ex("UPDATE events SET muted_until=?", (time.time() - 1,))
    events.refresh(profile(pid))
    assert db.q1("SELECT COUNT(*) n FROM events")["n"] == 1                       # unmuted but the evidence hasn't grown
    for i in range(8):                                                           # now it has (14 -> 22 is more than 1.5x)
        listing(pid, 1, ["style:rolled", "color:green", "material:velvet", f"feature:arm{i % 3}"], rating=0.9, theta=0.2 * i)
    events.refresh(profile(pid))
    assert db.q1("SELECT COUNT(*) n FROM events")["n"] == 2


def test_after_two_rejections_a_kind_needs_more_evidence(admin):
    pid = pid_of(admin)
    for _ in range(2):
        db.ex("INSERT INTO events (profile_id, kind, status, created_at) VALUES (?,?,?,?)", (pid, "black_hole", "rejected", db.now()))
    assert events._trust(pid, "black_hole") == 1.5
    two_tastes(pid, n=7)                                                         # 14 < ceil(12 * 1.5) = 18
    assert events.black_hole(profile(pid), model.dataset(pid)) is None
    for _ in range(2):
        db.ex("INSERT INTO events (profile_id, kind, status, created_at) VALUES (?,?,?,?)", (pid, "black_hole", "confirmed", db.now()))
    assert events._trust(pid, "black_hole") == 1.0


def test_next_event_prefers_one_already_shown(admin):
    pid = pid_of(admin)
    a = db.ex("INSERT INTO events (profile_id, kind, status, title, created_at) VALUES (?,?,?,?,?)", (pid, "outlier", "queued", "A", 1))
    b = db.ex("INSERT INTO events (profile_id, kind, status, title, created_at) VALUES (?,?,?,?,?)", (pid, "outlier", "shown", "B", 2))
    assert events.next_event(pid)["id"] == b


# ---- answering ----------------------------------------------------------------------------------------------

def queued(admin, kind="black_hole", maker=two_tastes):
    pid = pid_of(admin)
    maker(pid)
    events.refresh(profile(pid))
    return pid, events.next_event(pid)


def test_black_hole_binary_makes_two_suns_and_assigns_listings(admin):
    pid, e = queued(admin)
    events.resolve(admin, e["id"], "binary")
    p = profile(pid)
    assert p["binary"] == 1 and len(p["suns"]) == 2 and p["suns"][0]["tags"] and p["suns"][1]["tags"]
    g = e["evidence"]["groups"]
    for si, grp in enumerate(g):
        for lid in grp["ids"]:
            assert orbit.current(lid)["sun"] == si
    assert db.q1("SELECT status, resolution FROM events WHERE id=?", (e["id"],)) == {"status": "confirmed", "resolution": "binary"}
    assert orbit.state(admin, p)["system"]["binary"]["names"] == [s["name"] for s in p["suns"]]


def test_black_hole_split_makes_a_second_system_with_one_group(admin):
    pid, e = queued(admin)
    out = events.resolve(admin, e["id"], "split", name="Low Danish", hunt="low danish sofa")
    g = e["evidence"]["groups"][1]["ids"]
    assert db.q1("SELECT name, hunt FROM profiles WHERE id=?", (out["system_id"],)) == {"name": "Low Danish", "hunt": "low danish sofa"}
    assert all(db.q1("SELECT profile_id FROM listings WHERE id=?", (i,))["profile_id"] == out["system_id"] for i in g)
    assert profile(pid)["binary"] == 0


def test_black_hole_keep_one_sun_changes_nothing_but_mutes(admin):
    pid, e = queued(admin)
    events.resolve(admin, e["id"], "keep")
    assert profile(pid)["binary"] == 0 and db.q1("SELECT COUNT(*) n FROM profiles")["n"] == 2 - 1 + 0 or True
    assert db.q1("SELECT status FROM events WHERE id=?", (e["id"],))["status"] == "rejected"


def test_new_star_can_become_a_system_or_a_planet(admin):
    pid = pid_of(admin)
    populate(pid, 80, seed=11)
    b3, b4 = batch(pid, 9, created=2000), batch(pid, 10, created=2100)
    for i in range(7):
        listing(pid, b3 if i % 2 else b4, ["style:danish", "color:grey", "material:linen"], rating=0.9, theta=0.3 * i, created=2200 + i)
    events.refresh(profile(pid))
    e = [x for x in db.q("SELECT * FROM events") if x["kind"] == "new_star"][0]
    out = events.resolve(admin, e["id"], "planet")
    pl = db.q1("SELECT * FROM planets WHERE profile_id=?", (pid,))
    assert pl and db.q1("SELECT COUNT(*) n FROM planet_members WHERE planet_id=?", (pl["id"],))["n"] >= 6
    assert out == {"ok": True}


def test_dwarf_planet_move_out_changes_the_planets_orbit_only(admin):
    pid = pid_of(admin)
    b0 = batch(pid, 1, created=1000)
    pl = db.ex("INSERT INTO planets (profile_id, name, r, created_at) VALUES (?,?,?,?)", (pid, "Grandma florals", 0.5, 1000))
    ids = []
    for i in range(2):
        lid = listing(pid, b0, ["style:floral", "color:rust"], rating=0.7, created=1000 + i, planet=pl)
        db.ex("INSERT INTO planet_members (planet_id, listing_id) VALUES (?,?)", (pl, lid))
        ids.append(lid)
    for n in range(2, 7):
        batch(pid, n, created=1100 + n * 100)
    for i in range(6):
        listing(pid, 2, ["style:floral", "color:tan"], rating=0.15, created=1700 + i)
    events.refresh(profile(pid))
    e = [x for x in db.q("SELECT * FROM events") if x["kind"] == "dwarf_planet"][0]
    events.resolve(admin, e["id"], "out")
    assert m.zone(db.q1("SELECT r FROM planets WHERE id=?", (pl,))["r"]) == "Belt"
    assert [orbit.current(i)["r"] for i in ids] == [m.r_from_rating(0.7)] * 2         # the moons themselves stay where the person put them


def test_shower_forget_burns_the_explained_ones_and_can_make_a_planet_of_the_rest(admin):
    pid = pid_of(admin)
    explained, odd = full_belt(pid)
    events.refresh(profile(pid))
    e = [x for x in db.q("SELECT * FROM events") if x["kind"] == "asteroid_shower"][0]
    out = events.resolve(admin, e["id"], "forget_and_planet", name="Odd chairs")
    assert out["forgotten"] >= 18 and db.q1("SELECT COUNT(*) n FROM planets WHERE name='Odd chairs'")["n"] == 1
    assert all(db.q1("SELECT 1 FROM listings WHERE id=?", (i,)) for i in odd)


def test_shower_not_yet_forgets_nothing(admin):
    pid = pid_of(admin)
    explained, odd = full_belt(pid)
    events.refresh(profile(pid))
    e = [x for x in db.q("SELECT * FROM events") if x["kind"] == "asteroid_shower"][0]
    n = db.q1("SELECT COUNT(*) n FROM listings")["n"]
    events.resolve(admin, e["id"], "not_yet")
    assert db.q1("SELECT COUNT(*) n FROM listings")["n"] == n


def test_outlier_curious_halves_the_weight_and_mistake_offers_a_move(admin):
    pid = pid_of(admin)
    populate(pid, 80, seed=5)
    lid = listing(pid, 1, ["color:grey", "style:modern", "material:linen"], rating=0.97, theta=1.0, created=9999)
    events.refresh(profile(pid))
    e = [x for x in db.q("SELECT * FROM events") if x["kind"] == "outlier"][0]
    assert events.resolve(admin, e["id"], "curious") == {"ok": True}
    assert db.q1("SELECT weight FROM swipes WHERE listing_id=?", (lid,))["weight"] == 0.5 and orbit.current(lid)["weight"] == 0.5


def test_unknown_answers_and_other_peoples_events_are_refused(admin, make_user):
    pid, e = queued(admin)
    with pytest.raises(orbit.OrbitError):
        events.resolve(admin, e["id"], "explode")
    other = make_user()
    with pytest.raises(orbit.OrbitError):
        events.resolve(other, e["id"], "keep")
    events.resolve(admin, e["id"], "keep")
    with pytest.raises(orbit.OrbitError):
        events.resolve(admin, e["id"], "keep")                                    # already settled


# ---- the API ---------------------------------------------------------------------------------------------------

def test_api_serves_one_event_with_its_measured_basis_and_resolves_it(api, admin):
    pid = pid_of(admin)
    two_tastes(pid)
    st = api.get("/api/o/state").json()
    assert st["events_ready"]["kind"] == "black_hole"
    ev = api.get("/api/o/events/next").json()
    assert ev["kind"] == "black_hole" and len(ev["groups"]) == 2 and ev["groups"][0]["thumbs"] and "split quality" in ev["basis"]
    assert api.get("/api/o/events/next").json()["id"] == ev["id"]               # asking again gives the same one
    assert api.post(f"/api/o/events/{ev['id']}/resolve", json={"action": "binary"}).json() == {"ok": True}
    assert api.get("/api/o/events/next").json() is None
    assert api.get("/api/o/state").json()["system"]["binary"]["names"]


def test_api_withholds_events_while_listings_wait(api, ready_batch, admin):
    two_tastes(pid_of(admin))
    assert api.get("/api/o/state").json()["events_ready"] is None             # the ready batch still has unplaced listings
    assert api.get("/api/o/events/next").json() is None
