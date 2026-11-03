"""Command line helpers for the server.

  python -m app.cli admin-code            sign one of the admin's devices in (first-time setup, or a lost phone)
  python -m app.cli invite [--cap 3]      invite a new person (standard account, weekly Claude cap in USD)
  python -m app.cli users                 who has an account, and this week's Claude spend
  python -m app.cli backup [--label x]    verified snapshot of the database (safe while the server runs)
  python -m app.cli verify <file>         re-check a backup
  python -m app.cli restore <file>        put a backup back (STOP THE SERVER FIRST)
  python -m app.cli migrate-orbit [--apply]  copy swipes, keepers and groups into placements and planets (dry run unless --apply)
  python -m app.cli unmigrate-orbit       remove exactly what migrate-orbit added
  python -m app.cli release-unshown --vault <Batches folder> [--apply]
                                          free 'seen' rows for listings that were never shown (dry run unless --apply)
"""
import argparse

from . import auth, backup, costs, db


def main():
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("admin-code", help="one-time code that signs a device into the admin account")
    inv = sub.add_parser("invite", help="one-time code for a new standard account")
    inv.add_argument("--cap", type=float, default=auth.DEFAULT_FRIEND_CAP, help="weekly Claude budget in USD")
    sub.add_parser("users", help="list accounts")
    b = sub.add_parser("backup", help="verified snapshot of the database")
    b.add_argument("--label", default="manual")
    v = sub.add_parser("verify", help="re-check a backup file")
    v.add_argument("file")
    r = sub.add_parser("restore", help="restore a backup (stop the server first)")
    r.add_argument("file")
    r.add_argument("--yes", action="store_true", help="confirm the server is stopped")
    ru = sub.add_parser("release-unshown", help="free seen rows for listings that were screened but never shown")
    ru.add_argument("--vault", required=True, help="the Obsidian Batches folder (its notes list every shown listing)")
    ru.add_argument("--apply", action="store_true", help="actually delete; needs a fresh backup")
    mo = sub.add_parser("migrate-orbit", help="Kindling data -> Orbit placements and planets")
    mo.add_argument("--apply", action="store_true", help="actually write; needs a fresh verified backup")
    sub.add_parser("unmigrate-orbit", help="remove the migrated rows")
    args = ap.parse_args()
    if args.cmd in ("migrate-orbit", "unmigrate-orbit"):
        from . import migrate_orbit
        db.init()
        print(migrate_orbit.apply(dry_run=not args.apply) if args.cmd == "migrate-orbit" else migrate_orbit.unmigrate())
        return
    if args.cmd == "release-unshown":
        from . import maintenance
        db.init()
        print(maintenance.release_unshown(args.vault, apply=args.apply))
        return
    if args.cmd in ("backup", "verify", "restore"):  # these must not open or migrate the live database
        if args.cmd == "backup":
            print(backup.create(args.label))
        elif args.cmd == "verify":
            probs = backup.verify(args.file)
            print("ok" if not probs else "\n".join(probs))
            raise SystemExit(1 if probs else 0)
        else:
            if not args.yes:
                raise SystemExit("Stop the server first, then re-run with --yes.")
            kept = backup.restore(args.file)
            print(f"restored; previous database kept at {kept}")
        return
    db.init()

    if args.cmd == "admin-code":
        admin = db.q1("SELECT * FROM users WHERE role='admin' ORDER BY id LIMIT 1")
        code = auth.create_invite(role="admin", claude_cap=None, for_user_id=admin["id"], created_by=admin["id"])
        print(f"Admin sign-in code for {admin['name']}: {code}")
        print(f"Open Kindling, enter the code. Or go to <your Kindling URL>/#join/{code}  (expires in {auth.INVITE_DAYS} days)")
    elif args.cmd == "invite":
        admin = db.q1("SELECT * FROM users WHERE role='admin' ORDER BY id LIMIT 1")
        code = auth.create_invite(role="user", claude_cap=args.cap, created_by=admin["id"])
        print(f"Invite code: {code}  (standard account, ${args.cap:.2f}/week of Claude, expires in {auth.INVITE_DAYS} days)")
        print(f"Link: <your Kindling URL>/#join/{code}")
    elif args.cmd == "users":
        for u in db.q("SELECT * FROM users ORDER BY id"):
            b = costs.budget(u)
            cap = "no cap" if b["cap"] is None else f"${b['cap']:.2f}/week"
            print(f"{u['id']:>3}  {u['name']:<20} {u['role']:<6} {cap:<12} spent this week ${b['spent']:.2f}"
                  f"{'  (disabled)' if u['disabled'] else ''}")


if __name__ == "__main__":
    main()
