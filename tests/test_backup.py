import json
import sqlite3
import threading
import time

import pytest

from app import backup, db


@pytest.fixture
def seeded(admin, tmp_path):
    p = db.active_profile(admin["id"])
    bid = db.ex("INSERT INTO batches (profile_id, number, status, size, created_at) VALUES (?,?,?,?,?)", (p["id"], 1, "done", 3, db.now()))
    for i in range(5):
        db.ex("INSERT INTO listings (profile_id, batch_id, fb_id, title, created_at) VALUES (?,?,?,?,?)", (p["id"], bid, f"f{i}", f"t{i}", db.now()))
    return tmp_path


def test_backup_verifies_and_records_counts(seeded):
    b = backup.create("unit", dest_dir=seeded)
    assert backup.verify(b) == []
    meta = json.loads(b.with_suffix(".json").read_text())
    assert meta["tables"]["listings"][0] == 5 and meta["tables"]["users"][0] == 1
    assert oct(b.stat().st_mode)[-3:] == "600"


def test_backup_is_consistent_while_writers_are_active(seeded):
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            db.ex("INSERT INTO usage (user_id, model, input_tokens, output_tokens, cost, at) VALUES (1,'m',1,1,0,?)", (db.now(),))
            i += 1
    t = threading.Thread(target=writer)
    t.start()
    try:
        time.sleep(0.05)
        b = backup.create("busy", dest_dir=seeded)
    finally:
        stop.set()
        t.join()
    assert backup.verify(b) == []


def test_tampering_is_detected(seeded):
    b = backup.create("t", dest_dir=seeded)
    with open(b, "r+b") as f:
        f.seek(5000)
        f.write(b"\x00\x01\x02")
    assert backup.verify(b)


def test_missing_sidecar_fails_verification(seeded):
    b = backup.create("t", dest_dir=seeded)
    b.with_suffix(".json").unlink()
    assert backup.verify(b)


def test_require_fresh_demands_a_recent_verified_backup(seeded):
    with pytest.raises(backup.BackupError):
        backup.require_fresh(dir_=seeded)
    b = backup.create("t", dest_dir=seeded)
    assert backup.require_fresh(dir_=seeded) == b
    meta = json.loads(b.with_suffix(".json").read_text())
    meta["created"] -= 7200
    b.with_suffix(".json").write_text(json.dumps(meta))
    with pytest.raises(backup.BackupError):
        backup.require_fresh(dir_=seeded)


def test_restore_round_trip_returns_exact_contents(seeded):
    before = backup.table_checksums(db.config.DB_PATH)
    b = backup.create("rt", dest_dir=seeded)
    target = seeded / "restored.db"
    db_copy = sqlite3.connect(target)
    db_copy.execute("CREATE TABLE junk (x)")
    db_copy.commit()
    db_copy.close()
    kept = backup.restore(b, dest=target)
    assert kept and kept.exists()                       # the replaced file is kept
    assert backup.table_checksums(target) == before


def test_restore_refuses_a_bad_backup(seeded):
    b = backup.create("bad", dest_dir=seeded)
    b.with_suffix(".json").unlink()
    with pytest.raises(backup.BackupError):
        backup.restore(b, dest=seeded / "x.db")
    assert not (seeded / "x.db").exists()


def test_cli_restore_needs_explicit_yes(seeded, monkeypatch):
    from app import cli
    b = backup.create("cli", dest_dir=seeded)
    monkeypatch.setattr("sys.argv", ["cli", "restore", str(b)])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert "Stop the server" in str(e.value)
