"""One-off data repairs, always dry-run first and always behind a fresh verified backup."""
import re
from pathlib import Path

from . import backup, db

NOTE_ID = re.compile(r"marketplace/item/([A-Za-z0-9]+)")


class RepairError(Exception):
    pass


def shown_ids_from_vault(vault_dir):
    ids, files = set(), 0
    for f in Path(vault_dir).rglob("*.md"):
        files += 1
        ids.update(NOTE_ID.findall(f.read_text(errors="replace")))
    return ids, files


def release_unshown(vault_dir, apply=False, backup_dir=None):
    """Free the 'seen' rows for listings that were screened but never put in a batch.

    Before the Phase 1 fix, every screened candidate (up to 45 per batch) was remembered as seen, so about 60%
    of what a hunt remembers was never shown. Crystallize also deletes the rows of listings that WERE shown, so
    'no listing row' is not proof. The proof used here is the Obsidian batch notes, which list every listing the
    admin was shown. Only the admin's hunts are touched (nobody else has notes), and a row is released only when
    its id is in neither a note nor a live listing and it is newer than the oldest proven row (earlier batches have
    no notes). Refuses if the notes account for under 80% of what the database says was shown (wrong folder).
    """
    admin = db.q1("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")
    pids = [r["id"] for r in db.q("SELECT id FROM profiles WHERE user_id=?", (admin["id"],))]
    marks = ",".join("?" * len(pids))
    note_ids, n_files = shown_ids_from_vault(vault_dir)
    live = {r["fb_id"] for r in db.q(f"SELECT fb_id FROM listings WHERE profile_id IN ({marks})", pids)}
    proven = note_ids | live
    expected = len(live) + sum((b["stats"] or {}).get("shown", 0)
                               for b in db.q(f"SELECT stats FROM batches WHERE profile_id IN ({marks})", pids))
    rows = db.q(f"SELECT rowid rid, profile_id, fb_id FROM seen WHERE state='shown' AND profile_id IN ({marks}) ORDER BY rowid", pids)
    # Rows are written in the order batches ran. Batches from before the notes began (Oct 30 and earlier) have no
    # note to prove what they showed, so anything older than the oldest proven-shown row of its hunt is kept.
    oldest = {}
    for r in rows:
        if r["fb_id"] in proven:
            oldest.setdefault(r["profile_id"], r["rid"])
    keep_old = [r for r in rows if r["fb_id"] not in proven and r["rid"] < oldest.get(r["profile_id"], 0)]
    keep_old_ids = {(r["profile_id"], r["fb_id"]) for r in keep_old}
    kept = [r for r in rows if r["fb_id"] in proven]
    release = [r for r in rows if r["fb_id"] not in proven and (r["profile_id"], r["fb_id"]) not in keep_old_ids]
    report = {"notes": n_files, "note_ids": len(note_ids), "expected_shown": expected, "seen_rows": len(rows),
              "kept_proven_shown": len(kept), "kept_older_than_notes": len(keep_old), "released": len(release),
              "applied": False}
    if not n_files or len(kept) < 0.8 * expected:
        raise RepairError(f"The notes in {vault_dir} account for {len(kept)} of the {expected} listings the database says "
                          f"were shown. That's the wrong folder or incomplete notes, so nothing was changed. {report}")
    if apply and release:
        backup.require_fresh(dir_=backup_dir)
        with db.tx() as c:
            c.executemany(f"DELETE FROM seen WHERE state='shown' AND fb_id=? AND profile_id IN ({marks})",
                          [(r["fb_id"], *pids) for r in release])
        report["applied"] = True
    return report
