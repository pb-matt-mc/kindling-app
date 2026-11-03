import math

import pytest

from app import db, learn, orbit, orbit_math as m, scores


def place(api, lid, r=0.3, theta=-math.pi / 2, **kw):
    res = api.post("/api/o/place", json={"listing_id": lid, "r": r, "theta": theta, **kw})
    assert res.status_code == 200, res.text
    return res.json()


def ids(batch):
    return [l["id"] for l in batch["listings"]]


def test_state_lists_the_queue_with_claudes_locked_guess(api, ready_batch):
    s = api.get("/api/o/state").json()
    assert [c["id"] for c in s["queue"]] == ids(ready_batch)
    assert all(c["guess"] and c["predicted"] is not None for c in s["queue"])
    assert s["scores"]["confidence"]["state"] == "learning" and s["batch"]["status"] == "ready"


def test_first_placement_is_scored_against_the_locked_prediction(api, ready_batch):
    lid = ids(ready_batch)[0]
    pred = db.q1("SELECT predicted FROM predictions WHERE listing_id=?", (lid,))["predicted"]
    r = place(api, lid, r=m.r_from_rating(pred))        # place exactly where Claude predicted
    assert r["placement"]["kind"] == "first" and r["compare"]["verdict"] == "Called it"
    assert r["compare"]["gap"] == pytest.approx(0, abs=1e-9) and r["compare"]["guess"]
    row = db.q1("SELECT * FROM predictions WHERE listing_id=?", (lid,))
    assert row["checked_at"] and row["gap"] == pytest.approx(0, abs=1e-9)


def test_verdict_thresholds(api, ready_batch):
    a, b, c = ids(ready_batch)[:3]
    for lid, off in ((a, 0.03), (b, 0.10), (c, 0.40)):
        pred = db.q1("SELECT predicted FROM predictions WHERE listing_id=?", (lid,))["predicted"]
        target = min(1.0, max(0.0, pred + off if pred + off <= 1 else pred - off))
        res = place(api, lid, r=m.r_from_rating(target))["compare"]
        assert res["verdict"] == orbit.verdict(res["gap"])
    assert [orbit.verdict(g) for g in (0.0, 0.059, 0.06, 0.159, 0.16, 0.9)] == ["Called it", "Called it", "Close", "Close", "Claude missed", "Claude missed"]


def test_placement_stores_the_exact_position_and_syncs_taste(api, ready_batch):
    lid = ids(ready_batch)[0]
    place(api, lid, r=0.7777, theta=2.5)
    p = db.q1("SELECT * FROM placements WHERE listing_id=?", (lid,))
    assert (p["r"], p["theta"]) == (0.7777, 2.5) and p["rating"] == pytest.approx(m.rating(0.7777)) and p["origin"] == "placed"
    s = db.q1("SELECT * FROM swipes WHERE listing_id=?", (lid,))
    assert s["verdict"] == "dislike" and s["rank"] == pytest.approx(m.rating(0.7777)) and s["weight"] == 1.0
    assert sum(p["reasons"].values()) == pytest.approx(1.0)


def test_inside_the_sun_there_is_no_direction_or_reasons(api, ready_batch):
    lid = ids(ready_batch)[0]
    r = place(api, lid, r=0.05, theta=1.0)
    p = db.q1("SELECT * FROM placements WHERE listing_id=?", (lid,))
    assert r["placement"]["zone"] == "Sun" and p["theta"] is None and not p["reasons"] and m.rating(0.05) > 0.9


def test_a_later_move_updates_taste_but_never_rescores_claude(api, ready_batch):
    lid = ids(ready_batch)[0]
    first = place(api, lid, r=0.3)
    gap = db.q1("SELECT gap, checked_at FROM predictions WHERE listing_id=?", (lid,))
    mv = place(api, lid, r=0.9)
    assert mv["placement"]["kind"] == "move" and mv["compare"] is None
    assert dict(db.q1("SELECT gap, checked_at FROM predictions WHERE listing_id=?", (lid,))) == dict(gap)
    s = db.q1("SELECT * FROM swipes WHERE listing_id=?", (lid,))
    assert s["rank"] == pytest.approx(m.rating(0.9)) and s["manual"] == 1       # taste follows the move
    assert db.q1("SELECT COUNT(*) n FROM placements WHERE listing_id=?", (lid,))["n"] == 2


def test_listings_at_the_same_spot_keep_their_own_stored_positions(api, ready_batch):
    a, b, c = ids(ready_batch)[:3]
    for lid in (a, b, c):
        place(api, lid, r=0.4, theta=0.5)
    rows = db.q("SELECT r, theta FROM placements ORDER BY id")
    assert len(rows) == 3 and all((x["r"], x["theta"]) == (0.4, 0.5) for x in rows)
    s = api.get("/api/o/state").json()
    assert len(s["placed"]) == 3 and {p["id"] for p in s["placed"]} == {a, b, c}


def test_placing_every_listing_finishes_the_batch(api, ready_batch):
    for lid in ids(ready_batch)[:-1]:
        assert place(api, lid)["batch_done"] is False
    assert place(api, ids(ready_batch)[-1])["batch_done"] is True
    assert db.q1("SELECT status FROM batches WHERE id=?", (ready_batch["id"],))["status"] == "done"
    s = api.get("/api/o/state").json()
    assert s["queue"] == [] and s["batch"] is None


def test_undo_first_returns_the_listing_and_unscores_it(api, ready_batch):
    lid = ids(ready_batch)[0]
    r = place(api, lid)
    assert api.get("/api/o/state").json()["last_placement"]["id"] == r["placement"]["id"]
    assert api.post("/api/o/undo", json={"placement_id": r["placement"]["id"]}).json()["restored"] is False
    row = db.q1("SELECT * FROM predictions WHERE listing_id=?", (lid,))
    assert row["checked_at"] is None and row["gap"] is None
    assert db.q1("SELECT 1 FROM swipes WHERE listing_id=?", (lid,)) is None
    assert lid in [c["id"] for c in api.get("/api/o/state").json()["queue"]]
    again = place(api, lid, r=0.5)                       # and it can be placed (and scored) again
    assert again["placement"]["kind"] == "first" and again["compare"]


def test_undo_a_move_restores_the_previous_position(api, ready_batch):
    lid = ids(ready_batch)[0]
    place(api, lid, r=0.3)
    mv = place(api, lid, r=0.9)
    assert api.post("/api/o/undo", json={"placement_id": mv["placement"]["id"]}).json()["restored"] is True
    assert db.q1("SELECT rank FROM swipes WHERE listing_id=?", (lid,))["rank"] == pytest.approx(m.rating(0.3))
    assert orbit.current(lid)["r"] == 0.3


def test_only_the_latest_placement_can_be_undone(api, ready_batch):
    lid = ids(ready_batch)[0]
    first = place(api, lid, r=0.3)
    place(api, lid, r=0.5)
    assert api.post("/api/o/undo", json={"placement_id": first["placement"]["id"]}).status_code == 409


def test_undoing_the_last_listing_reopens_a_finished_batch(api, ready_batch):
    last = None
    for lid in ids(ready_batch):
        last = place(api, lid)
    assert last["batch_done"]
    api.post("/api/o/undo", json={"placement_id": last["placement"]["id"]})
    assert db.q1("SELECT status FROM batches WHERE id=?", (ready_batch["id"],))["status"] == "ready"


def test_bad_positions_are_rejected(api, ready_batch):
    lid = ids(ready_batch)[0]
    assert api.post("/api/o/place", json={"listing_id": lid, "r": "far", "theta": 0}).status_code == 422
    assert api.post("/api/o/place", json={"listing_id": lid, "r": 0.5}).status_code == 422
    assert place(api, lid, r=5.0)["placement"]["r"] == 1.0                 # clamped to the field edge
    assert api.post("/api/o/place", json={"listing_id": 99999, "r": .5, "theta": 0}).status_code == 404


def test_other_people_cannot_place_or_undo_my_listings(api, friend_api, ready_batch):
    lid = ids(ready_batch)[0]
    assert friend_api.post("/api/o/place", json={"listing_id": lid, "r": .5, "theta": 0}).status_code == 404
    pid = place(api, lid)["placement"]["id"]
    assert friend_api.post("/api/o/undo", json={"placement_id": pid}).status_code == 404
    assert friend_api.get(f"/api/o/listing/{lid}").status_code == 404
    assert friend_api.get("/api/o/state").json()["placed"] == []


def test_confidence_comes_from_checked_predictions_only(api, ready_batch):
    for lid in ids(ready_batch):
        pred = db.q1("SELECT predicted FROM predictions WHERE listing_id=?", (lid,))["predicted"]
        place(api, lid, r=m.r_from_rating(pred))        # always agree with Claude
    c = api.get("/api/o/state").json()["scores"]["confidence"]
    assert c["state"] == "ready" and c["value"] == pytest.approx(1.0, abs=1e-6)


# ---- planets and the rocket ----------------------------------------------------------------------------

def planet(api, name="Rolled arms", orbit_="Mid", reason="wrong", **kw):
    r = api.post("/api/o/planets", json={"name": name, "orbit": orbit_, "reason": reason, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_planet_sits_in_its_orbit_and_stands_for_its_reason(api):
    p = planet(api, orbit_="Outer", reason="price")
    assert m.zone(p["r"]) == "Outer" and p["theta"] == pytest.approx(-math.pi / 2) and p["reasons"]["price"] == 1.0
    q = planet(api, "Other", "Belt", "other")
    assert m.zone(q["r"]) == "Belt" and q["theta"] is None and not q["reasons"]


def test_planet_validation(api):
    planet(api, "Dup")
    assert api.post("/api/o/planets", json={"name": "dup"}).status_code == 409
    assert api.post("/api/o/planets", json={"name": "  "}).status_code == 400
    assert api.post("/api/o/planets", json={"name": "X", "orbit": "Warp"}).status_code == 400
    assert api.post("/api/o/planets", json={"name": "X", "reason": "mood"}).status_code == 400


def test_rocket_inherits_the_planet_at_low_weight_and_does_not_score_claude(api, ready_batch):
    pl = planet(api, orbit_="Outer", reason="wrong")
    lid = ids(ready_batch)[0]
    r = api.post("/api/o/rocket", json={"listing_id": lid, "planet_id": pl["id"]}).json()
    p = orbit.current(lid)
    assert p["kind"] == "rocket" and (p["r"], p["theta"]) == (pl["r"], pl["theta"]) and p["weight"] == 0.25 and p["planet_id"] == pl["id"]
    s = db.q1("SELECT * FROM swipes WHERE listing_id=?", (lid,))
    assert s["weight"] == 0.25 and s["rank"] == pytest.approx(m.rating(pl["r"]))
    assert db.q1("SELECT checked_at FROM predictions WHERE listing_id=?", (lid,))["checked_at"] is None
    assert r["scores"]["rocket"]["rocketed"] == 1
    assert db.q1("SELECT 1 FROM planet_members WHERE planet_id=? AND listing_id=?", (pl["id"], lid))
    assert lid not in [c["id"] for c in api.get("/api/o/state").json()["queue"]]


def test_rocket_use_is_reported(api, ready_batch):
    pl = planet(api)
    a, b, c, d = ids(ready_batch)[:4]
    api.post("/api/o/rocket", json={"listing_id": a, "planet_id": pl["id"]})
    for lid in (b, c, d):
        place(api, lid)
    u = api.get("/api/o/state").json()["scores"]["rocket"]
    assert (u["rocketed"], u["placements"]) == (1, 4) and u["share"] == 0.25


def test_undo_a_rocket_returns_the_listing_and_drops_the_moon(api, ready_batch):
    pl = planet(api)
    lid = ids(ready_batch)[0]
    pid = api.post("/api/o/rocket", json={"listing_id": lid, "planet_id": pl["id"]}).json()["placement"]["id"]
    api.post("/api/o/undo", json={"placement_id": pid})
    assert db.q1("SELECT 1 FROM planet_members WHERE listing_id=?", (lid,)) is None and db.q1("SELECT 1 FROM swipes WHERE listing_id=?", (lid,)) is None


def test_a_rocketed_listing_teaches_taste_a_quarter_as_much(admin):
    pid = db.active_profile(admin["id"])["id"]
    bid = db.ex("INSERT INTO batches (profile_id, number, status, size, created_at) VALUES (?,?,?,?,?)", (pid, 1, "done", 9, db.now()))

    def add(tag, rank, w, i):
        lid = db.ex("INSERT INTO listings (profile_id, batch_id, fb_id, tags, created_at) VALUES (?,?,?,?,?)", (pid, bid, f"w{i}{tag}{w}", db.dumps([tag]), db.now()))
        db.ex("INSERT INTO swipes (listing_id, verdict, rank, swiped_at, weight) VALUES (?,?,?,?,?)", (lid, "like", rank, db.now(), w))
    for i in range(4):
        add("a:full", .9, 1.0, i)
        add("b:rocket", .9, 0.25, i)
        add("c:base", .1, 1.0, i)
    w = {x["tag"]: x["n"] for x in learn.weights(pid)[0]}
    assert w["a:full"] == 4 and w["b:rocket"] == pytest.approx(1.0)


def test_rocket_cannot_cross_systems_or_people(api, friend_api, ready_batch, admin):
    other = db.new_profile(admin["id"], "Lamp", "lamp")
    pl = db.ex("INSERT INTO planets (profile_id, name, r, created_at) VALUES (?,?,?,?)", (other, "Elsewhere", .5, db.now()))
    lid = ids(ready_batch)[0]
    assert api.post("/api/o/rocket", json={"listing_id": lid, "planet_id": pl}).status_code == 409
    mine = planet(api, "Mine")
    assert friend_api.post("/api/o/rocket", json={"listing_id": lid, "planet_id": mine["id"]}).status_code == 404


def test_suggested_moons_match_words_in_the_listing(api, ready_batch):
    lid = ids(ready_batch)[0]
    place(api, lid)
    title = db.q1("SELECT title FROM listings WHERE id=?", (lid,))["title"]
    word = max(title.split(), key=len)
    got = api.get("/api/o/planets/suggest", params={"name": word}).json()
    assert lid in [g["id"] for g in got]
    assert api.get("/api/o/planets/suggest", params={"name": "zzzzqq"}).json() == []


def test_delete_planet_keeps_listings_where_they_are(api, ready_batch):
    pl = planet(api)
    lid = ids(ready_batch)[0]
    api.post("/api/o/rocket", json={"listing_id": lid, "planet_id": pl["id"]})
    assert api.delete(f"/api/o/planets/{pl['id']}").json() == {"ok": True}
    assert orbit.current(lid) is not None and db.q1("SELECT COUNT(*) n FROM planet_members")["n"] == 0
