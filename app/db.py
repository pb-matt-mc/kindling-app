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
CREATE TABLE IF NOT EXISTS vibes (
  profile_id INTEGER PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'inputs',   -- inputs, analyzing, drafted, fetching, hone, refining, refined, applied
  progress TEXT NOT NULL DEFAULT '',
  error TEXT,
  text TEXT NOT NULL DEFAULT '',
  sources TEXT NOT NULL DEFAULT '[]',      -- photos, listing links, pins and boards the person gave
  draft TEXT NOT NULL DEFAULT '{}',        -- the hunt Claude wrote: hunt, criteria, min_price, max_price, summary
  readings TEXT NOT NULL DEFAULT '[]',     -- every way the vibe could be read, each with a search query
  items TEXT NOT NULL DEFAULT '[]',        -- the hone grid, with the person's reactions and reasons
  result TEXT NOT NULL DEFAULT '{}',       -- the hunt after honing, plus what was learned
  honed INTEGER NOT NULL DEFAULT 0,        -- one hone per hunt
  web_added INTEGER NOT NULL DEFAULT 0,
  credits_used INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS places (
  name TEXT PRIMARY KEY,
  lat REAL NOT NULL,
  lng REAL NOT NULL
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
CREATE TABLE IF NOT EXISTS predictions (
  listing_id INTEGER PRIMARY KEY,
  profile_id INTEGER NOT NULL,
  batch_id INTEGER NOT NULL,
  claude_score REAL,                -- Claude's closer-look score, 0-100
  model_score REAL,                 -- the local trait model, 0-1
  predicted REAL,                   -- the blended prediction the person was shown, 0-1
  checklist_nos INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL          -- written once, when the batch is built, before the person sees the listing
);
CREATE TABLE IF NOT EXISTS schema_version (
  key TEXT PRIMARY KEY,
  version INTEGER NOT NULL,
  applied_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS planets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  profile_id INTEGER NOT NULL,              -- the system it orbits in
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',     -- what belongs here
  r REAL NOT NULL,                          -- orbit, in field units (0 = sun, 1 = edge); a moon placed here inherits it
  theta REAL,                               -- direction; NULL = no particular reason
  reasons TEXT,                             -- {price,right,guess,wrong} the planet stands for, or NULL
  legacy_group_id INTEGER UNIQUE,           -- set when this planet was migrated from a Kindling group
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS planet_members (
  planet_id INTEGER NOT NULL,
  listing_id INTEGER NOT NULL,
  PRIMARY KEY (planet_id, listing_id)
);
CREATE TABLE IF NOT EXISTS placements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id INTEGER NOT NULL,
  profile_id INTEGER NOT NULL,
  kind TEXT NOT NULL,                       -- first (the scored placement) | move | rocket | sun_switch
  origin TEXT NOT NULL DEFAULT 'placed',    -- placed | migrated | migrated_keeper
  r REAL NOT NULL,                          -- stored position in field units, exactly where it was released
  theta REAL,                               -- NULL inside the Sun and for migrated swipes (no known reason)
  rating REAL NOT NULL,                     -- what taste learns from; equals rating(r) except for migrated Sun listings
  reasons TEXT,                             -- {price,right,guess,wrong}; NULL when unknown
  reason_known INTEGER NOT NULL DEFAULT 1,
  weight REAL NOT NULL DEFAULT 1.0,         -- learning weight (rocketed listings count less)
  planet_id INTEGER,
  sun INTEGER NOT NULL DEFAULT 0,           -- which sun, for a binary star
  undone INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_placements_listing ON placements(listing_id, id);
CREATE INDEX IF NOT EXISTS idx_placements_profile ON placements(profile_id, kind);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  profile_id INTEGER NOT NULL,
  kind TEXT NOT NULL,                       -- black_hole | new_star | dwarf_planet | asteroid_shower | outlier
  status TEXT NOT NULL DEFAULT 'queued',    -- queued | shown | confirmed | rejected
  title TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL DEFAULT '',
  evidence TEXT NOT NULL DEFAULT '{}',      -- the measured numbers that triggered it
  created_at REAL NOT NULL,
  shown_at REAL,
  resolved_at REAL,
  muted_until REAL                          -- a rejected event is not repeated before this
);
CREATE INDEX IF NOT EXISTS idx_usage_user ON usage(user_id, at);
CREATE INDEX IF NOT EXISTS idx_listings_batch ON listings(batch_id);
CREATE INDEX IF NOT EXISTS idx_listings_profile ON listings(profile_id);
"""

JSON_COLS = {"criteria", "queries", "modifiers", "stats", "weights", "concepts", "query_stats", "landmarks", "fb_attributes", "photos", "tags", "features", "checklist", "sources", "draft", "readings", "items", "result", "rejected", "must_have", "reasons", "evidence", "suns"}


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
    ("listings", "avail", "TEXT"),                             # keeper check: 'live' | 'gone' | NULL (never checked / couldn't tell)
    ("listings", "avail_at", "REAL"),                          # when the keeper was last checked
    ("listings", "price_prev", "REAL"),                        # price before the last check changed it
    ("listings", "absorbed", "INTEGER NOT NULL DEFAULT 0"),    # its taste already lives in a crystal
    ("profiles", "user_id", "INTEGER"),                        # whose hunt this is
    ("seen", "phash", "TEXT"),                                 # photo fingerprint, to spot reposts
    ("seen", "tkey", "TEXT"),
    ("seen", "price", "REAL"),
    ("seen", "loc", "TEXT"),
    ("profiles", "must_have", "TEXT NOT NULL DEFAULT '[]'"),  # checklist items that remove a listing when the answer is no
    ("seen", "state", "TEXT NOT NULL DEFAULT 'shown'"),        # 'shown' = put in a batch; 'rejected' = judged not a fit, skipped for a while
    ("seen", "at", "REAL"),
    ("profiles", "state", "TEXT NOT NULL DEFAULT 'active'"),   # active | finished ("found it")
    ("profiles", "found_at", "REAL"),
    ("events", "resolution", "TEXT"),                          # what the person chose, e.g. "binary" or "forget"
    ("profiles", "binary", "INTEGER NOT NULL DEFAULT 0"),      # a second sun inside this system
    ("profiles", "suns", "TEXT NOT NULL DEFAULT '[]'"),         # [{name, tags}] one entry per sun when binary
    ("predictions", "sun_guess", "INTEGER"),                   # which sun Claude started this listing on (binary stars)
    ("predictions", "sun_actual", "INTEGER"),
    ("swipes", "weight", "REAL NOT NULL DEFAULT 1.0"),       # learning weight; rocketed listings count less
    ("predictions", "guess_text", "TEXT"),                     # Claude's guess of what the person will dislike (the down label)
    ("predictions", "checked_at", "REAL"),                     # set once, when the first placement is made
    ("predictions", "actual_rating", "REAL"),
    ("predictions", "gap", "REAL"),                            # |predicted - actual|, the raw material for Confidence
    ("vibes", "rejected", "TEXT NOT NULL DEFAULT '[]'"),      # readings of a vibe the person said were wrong
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
        aid = ex("INSERT INTO users (name, role, claude_cap, created_at) VALUES (?,?,?,?)", ("Matt", "admin", None, now()))
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
    # vibe setup steps that were running go back to the step before them
    ex("UPDATE vibes SET status='inputs', progress='', error='Interrupted by a server restart. Try again.' WHERE status='analyzing'")
    ex("UPDATE vibes SET status='drafted', progress='', error='Interrupted by a server restart. Try again.' WHERE status='fetching'")
    ex("UPDATE vibes SET status='hone', progress='', error='Interrupted by a server restart. Try again.' WHERE status='refining'")


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
