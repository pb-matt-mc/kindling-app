import pytest
from app import backup, db, maintenance


@pytest.fixture
def world(admin, tmp_path):
    p = db.active_profile(admin["id"])
    bid = db.ex("INSERT INTO batches (profile_id, number, status, size, stats, created_at) VALUES (?,?,?,?,?,?)",
                (p["id"], 1, "done", 5, db.dumps({"shown": 2, "likes": 1, "per_query": []}), db.now()))
    db.ex("INSERT INTO listings (profile_id, batch_id, fb_id, created_at) VALUES (?,?,?,?)", (p["id"], bid, "LIVE1", db.now()))
    for fb in ("LIVE1", "NOTE1", "NOTE2", "GHOST1", "GHOST2", "GHOST3"):
        db.ex("INSERT INTO seen (profile_id, fb_id) VALUES (?,?)", (p["id"], fb))   # legacy rows default to state 'shown'
    db.ex("INSERT INTO seen (profile_id, fb_id, state, at) VALUES (?,?,?,?)", (p["id"], "REJ1", "rejected", db.now()))
    vault = tmp_path / "Batches" / "Couch"
    vault.mkdir(parents=True)
    (vault / "b1.md").write_text("- [x](https://www.facebook.com/marketplace/item/NOTE1/) $5\n- [y](https://www.facebook.com/marketplace/item/NOTE2/)")
    return tmp_path


def test_dry_run_reports_without_changing(world):
    r = maintenance.release_unshown(world / "Batches")
    assert r["released"] == 3 and r["kept_proven_shown"] == 3 and r["kept_older_than_notes"] == 0 and r["applied"] is False
    assert db.q1("SELECT COUNT(*) n FROM seen")["n"] == 7


def test_apply_needs_a_fresh_backup(world):
    with pytest.raises(backup.BackupError):
        maintenance.release_unshown(world / "Batches", apply=True, backup_dir=world / "none")


def test_apply_releases_only_unproven_rows_and_keeps_rejections(world):
    b = backup.create("pre", dest_dir=world / "bk")
    r = maintenance.release_unshown(world / "Batches", apply=True, backup_dir=world / "bk")
    assert r["applied"] and r["released"] == 3
    left = {x["fb_id"] for x in db.q("SELECT fb_id FROM seen")}
    assert left == {"LIVE1", "NOTE1", "NOTE2", "REJ1"}
    assert maintenance.release_unshown(world / "Batches", apply=True, backup_dir=world / "bk")["released"] == 0  # idempotent
    assert backup.verify(b) == []


def test_wrong_folder_changes_nothing(world, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    backup.create("pre", dest_dir=world / "bk")
    with pytest.raises(maintenance.RepairError):
        maintenance.release_unshown(empty, apply=True, backup_dir=world / "bk")
    assert db.q1("SELECT COUNT(*) n FROM seen")["n"] == 7


def test_other_peoples_hunts_are_never_touched(world, make_user):
    u = make_user()
    pid = db.q1("SELECT id FROM profiles WHERE user_id=?", (u["id"],))["id"]
    db.ex("INSERT INTO seen (profile_id, fb_id) VALUES (?,?)", (pid, "FRIEND1"))
    backup.create("pre", dest_dir=world / "bk")
    maintenance.release_unshown(world / "Batches", apply=True, backup_dir=world / "bk")
    assert db.q1("SELECT 1 FROM seen WHERE fb_id='FRIEND1'")


def test_rows_older_than_the_notes_are_kept(world):
    p = db.active_profile(1)["id"]
    # make the oldest seen row (inserted first, before any proven row) an unprovable early-batch listing
    db.ex("INSERT INTO seen (profile_id, fb_id) VALUES (?,?)", (p, "EARLY1"))
    db.ex("UPDATE seen SET rowid = 0 WHERE fb_id='EARLY1'")
    backup.create("pre", dest_dir=world / "bk")
    r = maintenance.release_unshown(world / "Batches", apply=True, backup_dir=world / "bk")
    assert r["kept_older_than_notes"] == 1 and r["released"] == 3
    assert db.q1("SELECT 1 FROM seen WHERE fb_id='EARLY1'")
