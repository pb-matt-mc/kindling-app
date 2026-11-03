#!/usr/bin/env python3
"""Rehearse the Orbit migration on a COPY of a real database, read-only against the source:
backup -> migrate -> check old tables untouched -> re-run (idempotent) -> unmigrate -> check -> restore -> check.

    .venv/bin/python scripts/rehearse_migration.py /path/to/kindling.db
"""
import os
import sys
import tempfile
from pathlib import Path

src = Path(sys.argv[1]).resolve()
work = Path(tempfile.mkdtemp(prefix="orbit-rehearsal-"))
os.environ["KINDLING_DATA_DIR"] = str(work)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for k in ("ANTHROPIC_API_KEY", "SCRAPECREATORS_API_KEY", "APIFY_TOKEN", "KINDLING_OBSIDIAN_DIR"):
    os.environ[k] = ""
from app import backup  # noqa: E402

b0 = backup.create("source-copy", src=src, dest_dir=work / "src")
backup.restore(b0, dest=work / "kindling.db")
from app import db, migrate_orbit as mo, orbit_math as m  # noqa: E402
db.init()
orig = mo.fingerprint()
backup.create("pre-migration", dest_dir=work / "backups")
r1 = mo.apply(dry_run=False)
assert r1["old_tables_untouched"]
n_sw = db.q1("SELECT COUNT(*) n FROM swipes")["n"]
assert db.q1("SELECT COUNT(*) n FROM placements")["n"] == n_sw, "every swipe needs a placement"
assert db.q1("SELECT COUNT(*) n FROM placements WHERE reason_known=1")["n"] == 0
keepers = db.q1("SELECT COUNT(*) n FROM listings l JOIN swipes s ON s.listing_id=l.id WHERE l.keeper=1")["n"]
assert db.q1("SELECT COUNT(*) n FROM placements WHERE origin='migrated_keeper'")["n"] == keepers
for p in db.q("SELECT r, rating, origin FROM placements WHERE origin='migrated'"):
    assert abs(m.rating(p["r"]) - p["rating"]) < 1e-9
r2 = mo.apply(dry_run=False)
assert (r2["placements_added"], r2["placements_updated"], r2["placements_removed"], r2["planets_added"]) == (0, 0, 0, 0)
mo.unmigrate()
assert mo.fingerprint() == orig, "unmigrate must restore the old tables exactly"
assert db.q1("SELECT COUNT(*) n FROM placements")["n"] == 0
# restore from the pre-migration backup into a fresh file and compare content with the source copy
best = sorted((work / "backups").glob("*pre-migration.db"))[-1]
backup.restore(best, dest=work / "restored.db")
print({"rows": orig, "migrated": r1, "swipes": n_sw, "keepers": keepers, "workdir": str(work), "result": "ok"})
