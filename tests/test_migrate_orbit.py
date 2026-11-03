import pytest

from app import backup, db, migrate_orbit as mo, orbit_math as m


@pytest.fixture
def world(admin, tmp_path):
    """A small Kindling database: 2 hunts, swipes (one manual re-rank), 2 keepers, a group, a crystal."""
    p1 = db.active_profile(admin["id"])["id"]
    p2 = db.new_profile(admin["id"], "Lamp", "a lamp")
    b1 = db.ex("INSERT INTO batches (profile_id, number, status, size, created_at) VALUES (?,?,?,?,?)", (p1, 1, "done", 6, db.now()))
    b2 = db.ex("INSERT INTO batches (profile_id, number, status, size, created_at) VALUES (?,?,?,?,?)", (p2, 1, "done", 2, db.now()))
    ids = []
    for i, (bid, pid, rank, manual, keeper) in enumerate([(b1, p1, .75, 0, 1), (b1, p1, .25, 0, 0), (b1, p1, .9, 1, 1), (b1, p1, .1, 1, 0),
                                                           (b1, p1, .75, 0, 0), (b2, p2, .75, 0, 0)]):
        lid = db.ex("INSERT INTO listings (profile_id, batch_id, fb_id, title, keeper, state, created_at) VALUES (?,?,?,?,?,?,?)",
                    (pid, bid, f"f{i}", f"t{i}", keeper, "out" if keeper else "web", db.now()))
        db.ex("INSERT INTO swipes (listing_id, verdict, rank, manual, swiped_at) VALUES (?,?,?,?,?)",
              (lid, "like" if rank >= .5 else "dislike", rank, manual, db.now()))
        ids.append(lid)
    db.ex("INSERT INTO listings (profile_id, batch_id, fb_id, created_at) VALUES (?,?,?,?)", (p1, b1, "unswiped", db.now()))
    gid = db.ex("INSERT INTO groups (profile_id, label, created_at) VALUES (?,?,?)", (p1, "Rolled arms", db.now()))
    db.ex("INSERT INTO group_members (group_id, listing_id) VALUES (?,?)", (gid, ids[0]))
    db.ex("INSERT INTO group_members (group_id, listing_id) VALUES (?,?)", (gid, ids[4]))
    db.ex("INSERT INTO crystals (profile_id, number, n_listings, mean, created_at) VALUES (?,?,?,?,?)", (p1, 1, 40, .5, db.now()))
    return {"ids": ids, "tmp": tmp_path, "p1": p1, "p2": p2}


def run(world, apply=True):
    if apply:
        backup.create("pre", dest_dir=world["tmp"] / "bk")
    return mo.apply(dry_run=not apply, backup_dir=world["tmp"] / "bk")


def test_dry_run_reports_and_changes_nothing(world):
    r = run(world, apply=False)
    assert r["placements_added"] == 6 and r["planets_added"] == 1 and r["applied"] is False
    assert db.q1("SELECT COUNT(*) n FROM placements")["n"] == 0 and not mo.is_migrated()


def test_a_real_run_needs_a_fresh_verified_backup(world):
    with pytest.raises(backup.BackupError):
        mo.apply(dry_run=False, backup_dir=world["tmp"] / "none")
    assert db.q1("SELECT COUNT(*) n FROM placements")["n"] == 0


def test_old_swipes_keep_their_rating_and_have_no_known_reason(world):
    run(world)
    rows = {p["listing_id"]: p for p in db.q("SELECT * FROM placements")}
    assert len(rows) == 6                                   # the unswiped listing gets none
    for lid, rank in zip(world["ids"], [.75, .25, .9, .1, .75, .75]):
        p = rows[lid]
        assert p["rating"] == pytest.approx(rank) and p["kind"] == "first"
        assert p["reason_known"] == 0 and p["reasons"] in (None, {}, []) and p["theta"] is None and p["weight"] == 1.0


def test_distance_follows_rating_for_ordinary_listings(world):
    run(world)
    rows = {p["listing_id"]: p for p in db.q("SELECT * FROM placements")}
    for lid in (world["ids"][1], world["ids"][3], world["ids"][4]):
        assert m.rating(rows[lid]["r"]) == pytest.approx(rows[lid]["rating"])
        assert m.is_like(rows[lid]["r"]) == (rows[lid]["rating"] >= .5)


def test_keepers_become_sun_listings_but_keep_their_old_rank(world):
    run(world)
    rows = {p["listing_id"]: p for p in db.q("SELECT * FROM placements")}
    for lid, rank in ((world["ids"][0], .75), (world["ids"][2], .9)):
        p = rows[lid]
        assert p["origin"] == "migrated_keeper" and m.zone(p["r"]) == "Sun" and p["rating"] == pytest.approx(rank)


def test_groups_become_planets_with_moons(world):
    run(world)
    pl = db.q("SELECT * FROM planets")
    assert len(pl) == 1 and pl[0]["name"] == "Rolled arms" and pl[0]["profile_id"] == world["p1"]
    assert m.zone(pl[0]["r"]) in ("Inner", "Mid")
    assert {r["listing_id"] for r in db.q("SELECT * FROM planet_members")} == {world["ids"][0], world["ids"][4]}


def test_old_tables_are_byte_for_byte_untouched(world):
    before = mo.fingerprint()
    r = run(world)
    assert r["old_tables_untouched"] and mo.fingerprint() == before
    assert before["swipes"][0] == 6 and before["users"][0] == 1


def test_running_twice_changes_nothing_more(world):
    run(world)
    snap = [dict(p) for p in db.q("SELECT * FROM placements ORDER BY id")]
    r = run(world)
    assert (r["placements_added"], r["placements_updated"], r["placements_removed"], r["planets_added"]) == (0, 0, 0, 0)
    assert [dict(p) for p in db.q("SELECT * FROM placements ORDER BY id")] == snap


def test_a_later_sync_follows_swipes_made_after_the_first_run(world):
    run(world)
    lid = world["ids"][1]
    db.ex("UPDATE swipes SET rank=0.8, verdict='like', manual=1 WHERE listing_id=?", (lid,))   # re-ranked in the old UI
    db.ex("DELETE FROM swipes WHERE listing_id=?", (world["ids"][3],))                          # undone
    new = db.ex("INSERT INTO listings (profile_id, batch_id, fb_id, created_at) VALUES (?,?,?,?)", (world["p1"], 1, "later", db.now()))
    db.ex("INSERT INTO swipes (listing_id, verdict, rank, swiped_at) VALUES (?,?,?,?)", (new, "like", .75, db.now()))
    r = run(world)
    assert (r["placements_added"], r["placements_updated"], r["placements_removed"]) == (1, 1, 1)
    rows = {p["listing_id"]: p for p in db.q("SELECT * FROM placements")}
    assert rows[lid]["rating"] == pytest.approx(0.8) and world["ids"][3] not in rows and new in rows


def test_real_orbit_placements_are_never_touched_by_sync_or_unmigrate(world):
    run(world)
    lid = world["ids"][5]
    db.ex("INSERT INTO placements (listing_id, profile_id, kind, origin, r, theta, rating, reasons, created_at) "
          "VALUES (?,?,?,?,?,?,?,?,?)", (lid, world["p2"], "move", "placed", .3, 1.0, .7, db.dumps({"price": 1}), db.now()))
    db.ex("DELETE FROM swipes WHERE listing_id=?", (lid,))
    run(world)
    mo.unmigrate()
    left = db.q("SELECT * FROM placements")
    assert len(left) == 1 and left[0]["origin"] == "placed"


def test_unmigrate_removes_exactly_what_migrate_added(world):
    before = mo.fingerprint()
    run(world)
    mo.unmigrate()
    assert mo.fingerprint() == before
    for t in ("placements", "planets", "planet_members", "schema_version"):
        assert db.q1(f"SELECT COUNT(*) n FROM {t}")["n"] == 0


def test_an_interrupted_migration_leaves_nothing_behind(world, monkeypatch):
    real = db.now
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        if calls["n"] > 0:
            raise RuntimeError("power cut")
        return real()
    backup.create("pre", dest_dir=world["tmp"] / "bk")
    monkeypatch.setattr(mo.db, "now", boom)
    with pytest.raises(RuntimeError):
        mo.sync()
    monkeypatch.undo()
    assert db.q1("SELECT COUNT(*) n FROM placements")["n"] == 0 and db.q1("SELECT COUNT(*) n FROM planets")["n"] == 0 and not mo.is_migrated()


def test_restoring_the_backup_returns_the_exact_original(world):
    snap = backup.table_checksums(db.config.DB_PATH)
    b = backup.create("pre", dest_dir=world["tmp"] / "bk")
    run(world)
    assert backup.table_checksums(db.config.DB_PATH) != snap
    copy = world["tmp"] / "restored.db"
    backup.restore(b, dest=copy)
    assert backup.table_checksums(copy) == snap
