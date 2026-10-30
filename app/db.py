"""SQLite storage. Every table is keyed by profile so profiles stay fully separate."""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager

from . import config

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  hunt TEXT NOT NULL DEFAULT '',
  criteria TEXT NOT NULL DEFAULT '[]',
  min_price REAL,
  max_price REAL,
  location_name TEXT NOT NULL DEFAULT 'Philadelphia, PA',
  location_slug TEXT NOT NULL DEFAULT 'philly',
  lat REAL NOT NULL DEFAULT 39.9526,
  lng REAL NOT NULL DEFAULT -75.1652,
  radius_km REAL NOT NULL DEFAULT 40,
  batch_size INTEGER NOT NULL DEFAULT 15,
  taste_summary TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  profile_id INTEGER NOT NULL,
  number INTEGER NOT NULL,
  status TEXT NOT NULL,
  size INTEGER NOT NULL,
  queries TEXT NOT NULL DEFAULT '[]',
  progress TEXT NOT NULL DEFAULT '',
  error TEXT,
  credits_used INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  ready_at REAL,
  finished_at REAL
);
CREATE TABLE IF NOT EXISTS listings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  profile_id INTEGER NOT NULL,
  batch_id INTEGER NOT NULL,
  fb_id TEXT NOT NULL,
  url TEXT,
  title TEXT,
  price REAL,
  price_text TEXT,
  location_text TEXT,
  description TEXT,
  condition TEXT,
  fb_attributes TEXT NOT NULL DEFAULT '[]',
  photos TEXT NOT NULL DEFAULT '[]',
  query TEXT,
  tags TEXT NOT NULL DEFAULT '[]',
  features TEXT NOT NULL DEFAULT '{}',
  checklist TEXT NOT NULL DEFAULT '[]',
  take TEXT,
  claude_score REAL,
  model_score REAL,
  predicted REAL,
  explore INTEGER NOT NULL DEFAULT 0,
  position INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS swipes (
  listing_id INTEGER PRIMARY KEY,
  verdict TEXT NOT NULL,
  rank REAL NOT NULL,
  manual INTEGER NOT NULL DEFAULT 0,
  swiped_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS groups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  profile_id INTEGER NOT NULL,
  label TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS group_members (
  group_id INTEGER NOT NULL,
  listing_id INTEGER NOT NULL,
  PRIMARY KEY (group_id, listing_id)
);
CREATE TABLE IF NOT EXISTS seen (
  profile_id INTEGER NOT NULL,
  fb_id TEXT NOT NULL,
  PRIMARY KEY (profile_id, fb_id)
);
CREATE TABLE IF NOT EXISTS crystals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  profile_id INTEGER NOT NULL,
  number INTEGER NOT NULL,
  n_listings INTEGER NOT NULL,
  mean REAL NOT NULL,
  weights TEXT NOT NULL DEFAULT '[]',
  concepts TEXT NOT NULL DEFAULT '[]',
  query_stats TEXT NOT NULL DEFAULT '[]',
  landmarks TEXT NOT NULL DEFAULT '[]',
  taste_summary TEXT NOT NULL DEFAULT '',
  kept INTEGER NOT NULL DEFAULT 0,
  kept_in_web INTEGER NOT NULL DEFAULT 0,
  forgotten INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'user',          -- 'admin' or 'user'
  claude_cap REAL,                             -- weekly Claude API budget in USD; NULL = no cap
  disabled INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  last_seen REAL
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  device TEXT,
  created_at REAL NOT NULL,
  last_seen REAL
);
CREATE TABLE IF NOT EXISTS invites (
  code_hash TEXT PRIMARY KEY,
  role TEXT NOT NULL DEFAULT 'user',
  claude_cap REAL,
  for_user_id INTEGER,                         -- set = signs a new device into an existing account
  created_by INTEGER,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  used_by INTEGER,
  used_at REAL
);
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  batch_id INTEGER,
  label TEXT,
  model TEXT NOT NULL,
  input_tokens INTEGER NOT NULL,
  output_tokens INTEGER NOT NULL,
  cost REAL NOT NULL,
  at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_user ON usage(user_id, at);
CREATE INDEX IF NOT EXISTS idx_listings_batch ON listings(batch_id);
CREATE INDEX IF NOT EXISTS idx_listings_profile ON listings(profile_id);
"""

JSON_COLS = {"criteria", "queries", "modifiers", "stats", "weights", "concepts", "query_stats", "landmarks", "fb_attributes", "photos", "tags", "features", "checklist"}


def _connect():
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_conn = _connect()


@contextmanager
def tx():
    with _lock:
        try:
            yield _conn
            _conn.commit()
        except Exception:
            _conn.rollback()
            raise


def row(r):
    if r is None:
        return None
    d = dict(r)
    for k in JSON_COLS & d.keys():
        try:
            d[k] = json.loads(d[k]) if d[k] else ({} if k in ("features",) else None if k == "stats" else [])
        except (TypeError, ValueError):
            pass
    return d


def q(sql, args=()):
    with _lock:
        return [row(r) for r in _conn.execute(sql, args).fetchall()]


def q1(sql, args=()):
    with _lock:
        return row(_conn.execute(sql, args).fetchone())


def ex(sql, args=()):
    with tx() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid


def dumps(v):
    return json.dumps(v, ensure_ascii=False)


def now():
    return time.time()


MIGRATIONS = [
    ("profiles", "weirdness", "INTEGER NOT NULL DEFAULT 25"),
    ("batches", "weirdness", "INTEGER"),
    ("batches", "modifiers", "TEXT NOT NULL DEFAULT '[]'"),
    ("batches", "stats", "TEXT"),                              # frozen recap numbers once listings are forgotten
    ("listings", "state", "TEXT NOT NULL DEFAULT 'web'"),      # 'web' = a node in the web, 'out' = keeper only
    ("listings", "keeper", "INTEGER NOT NULL DEFAULT 0"),
    ("listings", "absorbed", "INTEGER NOT NULL DEFAULT 0"),    # its taste already lives in a crystal
    ("profiles", "user_id", "INTEGER"),                        # whose hunt this is
    ("seen", "phash", "TEXT"),                                 # photo fingerprint, to spot reposts
    ("seen", "tkey", "TEXT"),
    ("seen", "price", "REAL"),
    ("seen", "loc", "TEXT"),
]


def init():
    with tx() as c:
        c.executescript(SCHEMA)
        for table, col, decl in MIGRATIONS:
            cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
            if col not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    # The first account is the admin, and owns everything made before accounts existed
    admin = q1("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")
    if not admin:
        aid = ex("INSERT INTO users (name, role, claude_cap, created_at) VALUES (?,?,?,?)", ("Admin", "admin", None, now()))
    else:
        aid = admin["id"]
    ex("UPDATE profiles SET user_id=? WHERE user_id IS NULL", (aid,))
    if not q1("SELECT id FROM profiles WHERE user_id=? LIMIT 1", (aid,)):
        new_profile(aid, "Couch", "A couch for my Philadelphia apartment.")


def recover_interrupted():
    """Mark batches left mid-build by a restart as failed so the UI can rebuild them.

    Only the serving process calls this (startup hook), never import time, so a
    script or test importing the app can't clobber a batch the live server is building.
    """
    ex(
        "UPDATE batches SET status='error', error='Interrupted by a server restart' "
        "WHERE status IN ('queued','searching','screening','scoring')"
    )


def new_profile(user_id, name, hunt=""):
    with tx() as c:
        c.execute("UPDATE profiles SET active=0 WHERE user_id=?", (user_id,))
        cur = c.execute("INSERT INTO profiles (name, hunt, criteria, active, user_id, created_at) VALUES (?,?,?,1,?,?)",
                        (name, hunt, dumps([]), user_id, now()))
        return cur.lastrowid


def active_profile(user_id):
    """Each person has their own active hunt."""
    p = q1("SELECT * FROM profiles WHERE user_id=? AND active=1 ORDER BY id LIMIT 1", (user_id,))
    if not p:
        p = q1("SELECT * FROM profiles WHERE user_id=? ORDER BY id LIMIT 1", (user_id,))
        if not p:
            new_profile(user_id, "My hunt")
            p = q1("SELECT * FROM profiles WHERE user_id=? ORDER BY id LIMIT 1", (user_id,))
        ex("UPDATE profiles SET active=1 WHERE id=?", (p["id"],))
        p["active"] = 1
    return p
