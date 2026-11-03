"""Verified backups and restores of the SQLite database.

Uses SQLite's online backup API, so it is safe while the server is running (WAL mode). Every backup
gets a sidecar `.json` with a SHA-256, per-table row counts and per-table content checksums, and
`verify` re-checks all of it. Migrations must refuse to run without a fresh verified backup.
"""
import hashlib
import json
import shutil
import sqlite3
import time
from pathlib import Path

from . import config

BACKUP_DIR = config.DATA_DIR / "backups"
MAX_AGE_DEFAULT = 3600  # a backup older than this doesn't count as "fresh"


class BackupError(Exception):
    pass


def _connect(path, readonly=True):
    uri = f"file:{path}?mode={'ro' if readonly else 'rw'}"
    return sqlite3.connect(uri, uri=True, timeout=30)


def _tables(conn):
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def table_checksums(path):
    """{table: (row_count, sha256 of every row in primary-key/rowid order)}. Order-independent of insert history."""
    out = {}
    conn = _connect(path)
    try:
        for t in _tables(conn):
            h = hashlib.sha256()
            n = 0
            for row in conn.execute(f'SELECT * FROM "{t}" ORDER BY 1, 2'):
                h.update(repr(row).encode())
                n += 1
            out[t] = [n, h.hexdigest()]
    finally:
        conn.close()
    return out


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def create(label="manual", src=None, dest_dir=None):
    """Snapshot the live database. Returns the backup path. Raises BackupError if it doesn't verify."""
    src = Path(src or config.DB_PATH)
    if not src.is_file():
        raise BackupError(f"No database at {src}")
    dest_dir = Path(dest_dir or BACKUP_DIR)
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)
    dest = dest_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{safe}.db"
    n = 1
    while dest.exists():
        dest = dest_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{safe}-{n}.db"
        n += 1
    s = _connect(src)
    d = sqlite3.connect(dest)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()
    meta = {"created": time.time(), "source": str(src), "label": label, "sha256": _sha256_file(dest),
            "tables": table_checksums(dest)}
    dest.with_suffix(".json").write_text(json.dumps(meta, indent=1))
    dest.chmod(0o600)
    problems = verify(dest)
    if problems:
        raise BackupError("Backup did not verify: " + "; ".join(problems))
    return dest


def verify(path):
    """List of problems; empty means the backup is good."""
    path = Path(path)
    probs = []
    meta_path = path.with_suffix(".json")
    if not path.is_file():
        return [f"{path} is missing"]
    if not meta_path.is_file():
        return [f"{meta_path.name} is missing"]
    meta = json.loads(meta_path.read_text())
    if _sha256_file(path) != meta["sha256"]:
        probs.append("file checksum changed")
    try:
        conn = _connect(path)
        try:
            res = conn.execute("PRAGMA integrity_check").fetchall()
        finally:
            conn.close()
        if res != [("ok",)]:
            probs.append(f"integrity_check: {res[:3]}")
    except sqlite3.Error as e:
        probs.append(f"cannot open: {e}")
        return probs
    if table_checksums(path) != {k: list(v) for k, v in meta["tables"].items()}:
        probs.append("table contents differ from the recorded checksums")
    return probs


def latest(max_age=MAX_AGE_DEFAULT, dir_=None):
    """Newest backup that verifies and is younger than max_age seconds, else None."""
    d = Path(dir_ or BACKUP_DIR)
    for p in sorted(d.glob("*.db"), reverse=True):
        meta = p.with_suffix(".json")
        if meta.is_file() and time.time() - json.loads(meta.read_text())["created"] <= max_age and not verify(p):
            return p
    return None


def require_fresh(max_age=MAX_AGE_DEFAULT, dir_=None):
    p = latest(max_age, dir_)
    if not p:
        raise BackupError("No verified backup from the last %d minutes. Run: python -m app.cli backup" % (max_age // 60))
    return p


def restore(backup, dest=None):
    """Replace the database file with a verified backup. STOP THE SERVER FIRST.

    The file being replaced is kept next to it as `<name>.before-restore-<ts>`.
    """
    backup = Path(backup)
    probs = verify(backup)
    if probs:
        raise BackupError("Refusing to restore, backup does not verify: " + "; ".join(probs))
    dest = Path(dest or config.DB_PATH)
    kept = None
    if dest.exists():
        kept = dest.with_name(f"{dest.name}.before-restore-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(dest, kept)
    for suffix in ("-wal", "-shm"):
        side = Path(str(dest) + suffix)
        if side.exists():
            side.unlink()
    tmp = dest.with_name(dest.name + ".restoring")
    shutil.copy2(backup, tmp)
    tmp.replace(dest)
    return kept
