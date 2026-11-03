"""Kindling -> Orbit data migration. Additive only: it writes the new tables and never changes an old row.

  swipes   -> a `first` placement with the swipe's rank as rating, reasons unknown (reason_known = 0)
  keepers  -> Sun listings: displayed inside the Sun, but they keep their old rank as the rating taste learns from
  groups   -> planets (members become moons)
  hunts    -> systems (the profiles table is the systems table; `state` and `found_at` were added to it)

Safe to run again: it only adds what is missing and updates migrated rows whose swipe changed, so it can also be
re-run right before a later phase takes over from the swipe screen. `unmigrate` removes exactly the migrated rows.
Real placements (origin 'placed') are never touched by either.
"""
from . import backup, db
from .orbit_math import FROST, INNER_R, KEEPER_DISPLAY_R, r_from_rating

KEY = "orbit_placements"
VERSION = 1
OLD_TABLES = {  # the columns that existed before Orbit; the migration must leave these byte-for-byte alone
    "users": "id, name, role, claude_cap, disabled, created_at, last_seen",
    "sessions": "token_hash, user_id, device, created_at, last_seen",
    "invites": "code_hash, role, claude_cap, for_user_id, created_by, created_at, expires_at, used_by, used_at",
    "usage": "id, user_id, batch_id, label, model, input_tokens, output_tokens, cost, at",
    "profiles": "id, name, hunt, criteria, min_price, max_price, location_name, location_slug, lat, lng, radius_km, "
                "batch_size, taste_summary, active, created_at, user_id",
    "batches": "id, profile_id, number, status, size, queries, progress, error, credits_used, created_at, ready_at, finished_at",
    "listings": "id, profile_id, batch_id, fb_id, url, title, price, price_text, location_text, description, condition, "
                "fb_attributes, photos, query, tags, features, checklist, take, claude_score, model_score, predicted, "
                "explore, position, created_at",
    "swipes": "listing_id, verdict, rank, manual, swiped_at",
    "groups": "id, profile_id, label, created_at",
    "group_members": "group_id, listing_id",
    "crystals": "id, profile_id, number, n_listings, mean, weights, concepts, query_stats, landmarks, taste_summary, "
                "kept, kept_in_web, forgotten, created_at",
}
PLANET_R = (INNER_R + FROST) / 2


def fingerprint(conn=None):
    """{table: (rows, sha256)} over the pre-Orbit columns of every old table."""
    import hashlib
    out = {}
    c = conn or db._conn
    for t, cols in OLD_TABLES.items():
        h, n = hashlib.sha256(), 0
        for row in c.execute(f"SELECT {cols} FROM {t} ORDER BY 1, 2"):
            h.update(repr(tuple(row)).encode())
            n += 1
        out[t] = (n, h.hexdigest())
    return out


def is_migrated():
    return db.q1("SELECT version FROM schema_version WHERE key=?", (KEY,)) is not None


def _plan():
    swipes = db.q("SELECT s.listing_id, s.rank, s.swiped_at, l.profile_id, l.keeper FROM swipes s "
                  "JOIN listings l ON l.id=s.listing_id")
    return swipes, db.q("SELECT * FROM groups"), db.q("SELECT * FROM group_members")


def sync(apply=True):
    """Bring the migrated rows up to date with the old tables. Returns what changed (and writes it if apply)."""
    swipes, groups, members = _plan()
    have = {p["listing_id"]: p for p in db.q(
        "SELECT * FROM placements WHERE origin IN ('migrated','migrated_keeper') AND undone=0")}
    live = {s["listing_id"] for s in swipes}
    add, update = [], []
    for s in swipes:
        keeper = bool(s["keeper"])
        r = KEEPER_DISPLAY_R if keeper else r_from_rating(s["rank"])
        origin = "migrated_keeper" if keeper else "migrated"
        cur = have.get(s["listing_id"])
        row = (s["listing_id"], s["profile_id"], "first", origin, r, s["rank"], s["swiped_at"])
        if not cur:
            add.append(row)
        elif abs(cur["rating"] - s["rank"]) > 1e-12 or cur["origin"] != origin:
            update.append((origin, r, s["rank"], cur["id"]))
    remove = [p["id"] for lid, p in have.items() if lid not in live]
    known_planets = {p["legacy_group_id"]: p["id"] for p in db.q("SELECT id, legacy_group_id FROM planets WHERE legacy_group_id IS NOT NULL")}
    new_groups = [g for g in groups if g["id"] not in known_planets]
    report = {"placements_added": len(add), "placements_updated": len(update), "placements_removed": len(remove),
              "planets_added": len(new_groups), "applied": apply}
    if not apply:
        return report
    with db.tx() as c:
        c.executemany("INSERT INTO placements (listing_id, profile_id, kind, origin, r, theta, rating, reasons, reason_known, "
                      "weight, created_at) VALUES (?,?,?,?,?,NULL,?,NULL,0,1.0,?)", [(a, b, k, o, r, rt, ts) for a, b, k, o, r, rt, ts in add])
        c.executemany("UPDATE placements SET origin=?, r=?, rating=? WHERE id=?", update)
        c.executemany("DELETE FROM placements WHERE id=?", [(i,) for i in remove])
        for g in new_groups:
            cur = c.execute("INSERT INTO planets (profile_id, name, description, r, theta, reasons, legacy_group_id, created_at) "
                            "VALUES (?,?,?,?,NULL,NULL,?,?)", (g["profile_id"], g["label"], "", PLANET_R, g["id"], g["created_at"]))
            known_planets[g["id"]] = cur.lastrowid
        c.executemany("INSERT OR IGNORE INTO planet_members (planet_id, listing_id) VALUES (?,?)",
                      [(known_planets[m["group_id"]], m["listing_id"]) for m in members if m["group_id"] in known_planets])
        c.execute("INSERT OR REPLACE INTO schema_version (key, version, applied_at) VALUES (?,?,?)", (KEY, VERSION, db.now()))
    return report


def apply(dry_run=True, backup_dir=None):
    """The command-line entry. A real run needs a verified backup from the last hour."""
    if not dry_run:
        backup.require_fresh(dir_=backup_dir)
    before = fingerprint()
    report = sync(apply=not dry_run)
    report["old_tables_untouched"] = fingerprint() == before
    if not report["old_tables_untouched"]:
        raise RuntimeError("An old table changed during the migration. This is a bug; restore the backup.")
    return report


def unmigrate():
    """Remove exactly what migrate added. Placements made in Orbit are kept."""
    with db.tx() as c:
        c.execute("DELETE FROM placements WHERE origin IN ('migrated','migrated_keeper')")
        ids = [r[0] for r in c.execute("SELECT id FROM planets WHERE legacy_group_id IS NOT NULL")]
        c.executemany("DELETE FROM planet_members WHERE planet_id=?", [(i,) for i in ids])
        c.execute("DELETE FROM planets WHERE legacy_group_id IS NOT NULL")
        c.execute("DELETE FROM schema_version WHERE key=?", (KEY,))
    return {"unmigrated": True}
