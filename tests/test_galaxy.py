import asyncio
import math

import pytest

from app import db, orbit, orbit_math as m, pipeline, recheck


def place(api, lid, r=0.3, theta=0.0):
    res = api.post("/api/o/place", json={"listing_id": lid, "r": r, "theta": theta})
    assert res.status_code == 200, res.text
    return res.json()


def ids(b):
    return [l["id"] for l in b["listings"]]


def test_galaxy_lists_every_system_with_counts(api, ready_batch):
    a, b, c = ids(ready_batch)[:3]
    place(api, a, r=0.05)
    place(api, b, r=0.95)
    g = api.get("/api/o/galaxy").json()
    assert len(g) == 1 and g[0]["active"] and g[0]["state"] == "active"
    assert g[0]["counts"]["Sun"] == 1 and g[0]["counts"]["Belt"] == 1 and g[0]["batch"]["status"] == "ready"


def test_a_new_system_takes_the_chosen_listings_with_it(api, ready_batch, admin):
    a, b, c = ids(ready_batch)[:3]
    for lid in (a, b, c):
        place(api, lid, r=0.4)
    old = db.active_profile(admin["id"])["id"]
    pl = api.post("/api/o/planets", json={"name": "P", "orbit": "Mid"}).json()
    api.post("/api/o/rocket", json={"listing_id": ids(ready_batch)[3], "planet_id": pl["id"]})
    r = api.post("/api/o/systems", json={"source_id": old, "name": "Coffee table", "hunt": "a walnut coffee table", "listing_ids": [a, b]})
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["name"] == "Coffee table" and new["hunt"] == "a walnut coffee table" and new["active"] == 1
    for lid in (a, b):
        assert db.q1("SELECT profile_id FROM listings WHERE id=?", (lid,))["profile_id"] == new["id"]
        assert orbit.current(lid)["profile_id"] == new["id"]
        assert db.q1("SELECT profile_id FROM predictions WHERE listing_id=?", (lid,))["profile_id"] == new["id"]
    assert db.q1("SELECT profile_id FROM listings WHERE id=?", (c,))["profile_id"] == old
    fb = db.q1("SELECT fb_id FROM listings WHERE id=?", (a,))["fb_id"]
    assert db.q1("SELECT 1 FROM seen WHERE profile_id=? AND fb_id=?", (new["id"], fb))
    st = api.get("/api/o/state").json()
    assert st["system"]["id"] == new["id"] and len(st["placed"]) == 2 and st["queue"] == []     # the new system is its own world
    assert api.get("/api/o/galaxy").json()[0]["active"] is False or len(api.get("/api/o/galaxy").json()) == 2


def test_a_moved_listing_leaves_its_planet_behind(api, ready_batch, admin):
    pl = api.post("/api/o/planets", json={"name": "P", "orbit": "Mid"}).json()
    lid = ids(ready_batch)[0]
    api.post("/api/o/rocket", json={"listing_id": lid, "planet_id": pl["id"]})
    api.post("/api/o/systems", json={"source_id": db.q1("SELECT profile_id p FROM listings WHERE id=?", (lid,))["p"], "name": "N", "hunt": "h", "listing_ids": [lid]})
    assert db.q1("SELECT 1 FROM planet_members WHERE listing_id=?", (lid,)) is None
    assert orbit.current(lid)["planet_id"] is None


def test_new_system_needs_a_name_and_a_hunt_and_only_my_listings(api, friend_api, ready_batch, admin):
    src = db.active_profile(admin["id"])["id"]
    lid = ids(ready_batch)[0]
    assert api.post("/api/o/systems", json={"source_id": src, "name": "", "hunt": "x"}).status_code == 400
    assert api.post("/api/o/systems", json={"source_id": src, "name": "N", "hunt": " "}).status_code == 400
    assert friend_api.post("/api/o/systems", json={"source_id": src, "name": "N", "hunt": "x"}).status_code == 404
    assert friend_api.post("/api/o/systems", json={"source_id": friend_api.get("/api/o/state").json()["system"]["id"], "name": "N", "hunt": "x", "listing_ids": [lid]}).status_code == 404
    other = db.new_profile(admin["id"], "Elsewhere", "e")
    assert api.post("/api/o/systems", json={"source_id": other, "name": "N", "hunt": "x", "listing_ids": [lid]}).status_code == 409


def test_found_it_closes_the_hunt_but_keeps_it(api, ready_batch, admin):
    for lid in ids(ready_batch):
        place(api, lid)
    src = db.active_profile(admin["id"])["id"]
    other = api.post("/api/o/systems", json={"source_id": src, "name": "Lamp", "hunt": "a lamp"}).json()["id"]
    assert api.post(f"/api/o/systems/{src}/found").json() == {"ok": True}
    g = {s["id"]: s for s in api.get("/api/o/galaxy").json()}
    assert g[src]["state"] == "finished" and g[src]["found_at"] and g[other]["active"]
    assert api.post("/api/o/systems/%d/activate" % src).status_code == 200      # you can still look at it
    assert api.post("/api/batches", json={"size": 5}).status_code == 409        # but it takes no new batches
    assert len(api.get("/api/o/state").json()["placed"]) == len(ids(ready_batch))   # and nothing it learned is lost
    assert api.post(f"/api/o/systems/{src}/reopen").json() == {"ok": True}
    assert api.get("/api/o/galaxy").json()[0]["state"] == "active"


def test_a_finished_system_takes_no_placements(api, ready_batch, admin):
    src = db.active_profile(admin["id"])["id"]
    lid = ids(ready_batch)[0]
    db.ex("UPDATE batches SET status='done' WHERE profile_id=?", (src,))
    db.ex("UPDATE profiles SET state='finished' WHERE id=?", (src,))
    assert api.post("/api/o/place", json={"listing_id": lid, "r": .5, "theta": 0}).status_code == 409


def test_cannot_close_a_hunt_while_a_batch_is_building(api, admin):
    src = db.active_profile(admin["id"])["id"]
    db.ex("INSERT INTO batches (profile_id, number, status, size, created_at) VALUES (?,?,?,?,?)", (src, 1, "scoring", 5, db.now()))
    assert api.post(f"/api/o/systems/{src}/found").status_code == 409


def test_other_people_cannot_touch_my_systems(api, friend_api, admin):
    src = db.active_profile(admin["id"])["id"]
    for path in ("activate", "found", "reopen"):
        assert friend_api.post(f"/api/o/systems/{src}/{path}").status_code == 404


# ---- re-check of Sun and Inner listings before each batch --------------------------------------------

class FakeSource:
    name = "fake"

    def __init__(self, gone=(), unknown=(), price=None):
        self.asked, self.gone, self.unknown, self.price = [], set(gone), set(unknown), price or {}

    async def items(self, fb_ids):
        self.asked += list(fb_ids)
        out = {}
        for i in fb_ids:
            if i in self.unknown:
                continue
            out[i] = {"is_live": i not in self.gone, **({"price": self.price[i], "price_text": f"${self.price[i]}"} if i in self.price else {})}
        return out, len(fb_ids)


def seed_ring(api, batch, rs):
    for lid, r in zip(ids(batch), rs):
        place(api, lid, r=r)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def fb(lid):
    return db.q1("SELECT fb_id FROM listings WHERE id=?", (lid,))["fb_id"]


def test_only_sun_and_inner_are_rechecked(api, ready_batch, admin):
    seed_ring(api, ready_batch, [0.05, 0.3, 0.5, 0.7, 0.95])      # Sun, Inner, Mid, Outer, Belt
    src = FakeSource()
    r = run(recheck.run(db.active_profile(admin["id"])["id"], src))
    assert sorted(src.asked) == sorted(fb(l) for l in ids(ready_batch)[:2]) and r["checked"] == 2 and r["live"] == 2 and r["credits"] == 2


def test_sold_listings_fade_but_are_kept_and_still_teach(api, ready_batch, admin):
    seed_ring(api, ready_batch, [0.05, 0.3])
    gone = ids(ready_batch)[0]
    pid = db.active_profile(admin["id"])["id"]
    before = [dict(x) for x in db.q("SELECT * FROM swipes ORDER BY listing_id")]
    r = run(recheck.run(pid, FakeSource(gone={fb(gone)})))
    assert r["gone"] == 1 and db.q1("SELECT avail FROM listings WHERE id=?", (gone,))["avail"] == "gone"
    assert orbit.current(gone) is not None                                  # still on the field
    assert [dict(x) for x in db.q("SELECT * FROM swipes ORDER BY listing_id")] == before     # and still teaching taste
    placed = {p["id"]: p for p in orbit.placed_view(pid)}
    assert placed[gone]["gone"] is True


def test_sold_stays_sold_and_checks_are_once_a_day(api, ready_batch, admin):
    seed_ring(api, ready_batch, [0.05, 0.3])
    pid = db.active_profile(admin["id"])["id"]
    gone = ids(ready_batch)[0]
    run(recheck.run(pid, FakeSource(gone={fb(gone)})))
    again = FakeSource()
    run(recheck.run(pid, again))
    assert again.asked == []                                                 # both were checked within a day; the sold one never again
    db.ex("UPDATE listings SET avail_at=avail_at-100000")
    later = FakeSource()
    run(recheck.run(pid, later))
    assert later.asked == [fb(ids(ready_batch)[1])]


def test_unknown_stays_unmarked_and_a_price_change_is_recorded(api, ready_batch, admin):
    seed_ring(api, ready_batch, [0.05, 0.3])
    a, b = ids(ready_batch)[:2]
    pid = db.active_profile(admin["id"])["id"]
    old = db.q1("SELECT price FROM listings WHERE id=?", (b,))["price"]
    r = run(recheck.run(pid, FakeSource(unknown={fb(a)}, price={fb(b): (old or 100) + 25})))
    assert r["unknown"] == 1 and r["changed"] == 1
    assert db.q1("SELECT avail, avail_at FROM listings WHERE id=?", (a,)) == {"avail": None, "avail_at": None}
    row = db.q1("SELECT price, price_prev FROM listings WHERE id=?", (b,))
    assert row["price_prev"] == old and row["price"] == (old or 100) + 25


def test_the_check_is_capped_per_batch(api, ready_batch, admin, monkeypatch):
    seed_ring(api, ready_batch, [0.05] * 5)
    src = FakeSource()
    r = run(recheck.run(db.active_profile(admin["id"])["id"], src, max_n=3))
    assert r["checked"] == 3 and len(src.asked) == 3


def test_a_source_failure_in_the_recheck_never_fails_the_batch(api, ready_batch, admin, monkeypatch):
    seed_ring(api, ready_batch, [0.05])
    from app.sources import Mock, SourceError
    real, calls = Mock.items, {"n": 0}

    async def flaky(self, fb_ids):
        calls["n"] += 1
        if calls["n"] == 1:           # the first source call is the re-check
            raise SourceError("source down")
        return await real(self, fb_ids)
    monkeypatch.setattr(Mock, "items", flaky)
    db.ex("UPDATE batches SET status='done'")
    bid = db.ex("INSERT INTO batches (profile_id, number, status, size, weirdness, modifiers, created_at) VALUES (?,?,?,?,?,?,?)",
                (db.active_profile(admin["id"])["id"], 2, "queued", 4, 0, "[]", db.now()))
    run(pipeline.build(bid))
    row = db.q1("SELECT status, error FROM batches WHERE id=?", (bid,))
    assert row["status"] == "ready", row["error"]
