"""Seed the isolated UI-audit instance. `init` runs before the server (users/sessions), `populate` after (HTTP)."""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

DATA = Path(os.environ["KINDLING_DATA_DIR"])
assert str(DATA).startswith("/tmp/"), "seed only runs against a /tmp data dir"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def init():
    from app import auth, db
    db.init()
    tokens = {}
    for key, name in (("main", "Audit"), ("brew", "Brewer")):
        uid = db.ex("INSERT INTO users (name, role, claude_cap, created_at) VALUES (?,?,?,?)",
                    (name, "user", 3.0, db.now()))
        pid = db.new_profile(uid, "Couch hunt", "mid-century couch, good condition")
        tokens[key] = {"token": auth.new_session(uid, "ui-audit"), "uid": uid, "pid": pid}
    (DATA / "tokens.json").write_text(json.dumps(tokens))


def populate(base):
    import httpx
    tok = json.loads((DATA / "tokens.json").read_text())["main"]
    c = httpx.Client(base_url=base + "/api", cookies={"kindling_session": tok["token"]}, timeout=60)

    def batch():
        b = c.post("/batches", json={"size": 30}).json()
        for _ in range(120):
            b = c.get(f"/batches/{b['id']}").json()
            if b["status"] in ("ready", "error"):
                break
            time.sleep(0.5)
        assert b["status"] == "ready", b.get("error") or b["status"]
        return b

    liked = []
    for n, upto in enumerate((30, 22)):  # 52 swiped = web locked (50); the second batch keeps 8 unswiped for the swipe screen
        b = batch()
        for i, l in enumerate(b["listings"][:upto]):
            v = "like" if i % 3 else "dislike"
            c.post("/swipe", json={"listing_id": l["id"], "verdict": v})
            if v == "like":
                liked.append(l["id"])
        if n == 0:
            c.post(f"/batches/{b['id']}/finish")
    # some keepers with mixed availability
    db = sqlite3.connect(DATA / "kindling.db")
    # the second user has a batch stuck mid-brew (inserted after startup, which retires interrupted batches)
    bp = json.loads((DATA / "tokens.json").read_text())["brew"]["pid"]
    db.execute("INSERT INTO batches (profile_id, number, status, size, weirdness, modifiers, progress, created_at) "
               "VALUES (?,?,?,?,?,?,?,?)", (bp, 1, "scoring", 12, 20, '["velvet"]', "Looked at 4 of 12", time.time()))
    for i, lid in enumerate(liked[:8]):
        db.execute("UPDATE listings SET keeper=1, avail=?, avail_at=? WHERE id=?", (("live", "gone", None)[i % 3], time.time() - 3600 * (i + 1), lid))
    db.commit()
    print("seeded:", len(liked), "likes,", min(8, len(liked)), "keepers")


if __name__ == "__main__":
    init() if sys.argv[1] == "init" else populate(sys.argv[2])
