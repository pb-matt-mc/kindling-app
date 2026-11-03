"""Test fixtures. The app reads its data dir at import, so point it at a temp dir before anything imports it.
Nothing here can reach the live data folder, the network, or a paid API."""
import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="orbit-test-")
os.environ["KINDLING_DATA_DIR"] = _TMP
os.environ["KINDLING_SOURCE"] = "mock"
for k in ("ANTHROPIC_API_KEY", "SCRAPECREATORS_API_KEY", "APIFY_TOKEN", "KINDLING_OBSIDIAN_DIR"):
    os.environ[k] = ""  # an empty variable beats .env

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth, config, db  # noqa: E402

assert str(config.DATA_DIR).startswith(tempfile.gettempdir()), "tests must never use the real data dir"


def wipe():
    db.init()
    with db.tx() as c:
        for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
            c.execute(f'DELETE FROM "{t}"')
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
            c.execute("DELETE FROM sqlite_sequence")
    for f in Path(config.IMG_DIR).glob("*"):
        f.unlink()
    db.init()


@pytest.fixture(autouse=True)
def clean_db():
    wipe()
    yield


@pytest.fixture
def admin():
    return db.q1("SELECT * FROM users WHERE role='admin'")


def _client(user):
    from app.main import app
    c = TestClient(app, base_url="http://testserver")
    c.cookies.set(auth.COOKIE, auth.new_session(user["id"], "pytest"))
    return c


@pytest.fixture
def api(admin):
    from app.main import app
    with TestClient(app) as c:  # runs startup hooks
        c.cookies.set(auth.COOKIE, auth.new_session(admin["id"], "pytest"))
        yield c


@pytest.fixture
def make_user():
    def make(name="Friend", cap=3.0):
        uid = db.ex("INSERT INTO users (name, role, claude_cap, created_at) VALUES (?,?,?,?)", (name, "user", cap, db.now()))
        db.new_profile(uid, "Hunt", "mid-century couch")
        return db.q1("SELECT * FROM users WHERE id=?", (uid,))
    return make


@pytest.fixture
def friend_api(make_user):
    from app.main import app
    u = make_user()
    with TestClient(app) as c:
        c.cookies.set(auth.COOKIE, auth.new_session(u["id"], "pytest"))
        c.user = u
        yield c


@pytest.fixture
def ready_batch(api):
    """A finished mock batch of 12 listings, built through the real pipeline."""
    import time
    b = api.post("/api/batches", json={"size": 12}).json()
    for _ in range(200):
        b = api.get(f"/api/batches/{b['id']}").json()
        if b["status"] in ("ready", "error"):
            break
        time.sleep(0.1)
    assert b["status"] == "ready", b.get("error")
    return b
