"""Command line helpers for the server.

  python -m app.cli admin-code            sign one of the admin's devices in (first-time setup, or a lost phone)
  python -m app.cli invite [--cap 3]      invite a new person (standard account, weekly Claude cap in USD)
  python -m app.cli users                 who has an account, and this week's Claude spend
"""
import argparse

from . import auth, costs, db


def main():
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("admin-code", help="one-time code that signs a device into the admin account")
    inv = sub.add_parser("invite", help="one-time code for a new standard account")
    inv.add_argument("--cap", type=float, default=auth.DEFAULT_FRIEND_CAP, help="weekly Claude budget in USD")
    sub.add_parser("users", help="list accounts")
    args = ap.parse_args()
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
