"""Browser harness. Starts a private mock-data instance on loopback port 8011 (never the live :8010, never
the real data dir), signs a test user in, and hands out Playwright pages for any device in devices.py.

Run:  .venv/bin/python -m pytest -m e2e tests/e2e           (quick matrix)
      ORBIT_FULL_MATRIX=1 .venv/bin/python -m pytest -m e2e (every device and variant)
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from .devices import FULL, KEYBOARD, QUICK

ROOT = Path(__file__).resolve().parents[2]
PORT = int(os.getenv("ORBIT_E2E_PORT", "8031"))
assert PORT not in (8000, 8010, 8011, 8012, 8020, 25565), "e2e must not use a live port"
MATRIX = FULL if os.getenv("ORBIT_FULL_MATRIX") else QUICK


def pytest_collection_modifyitems(items):
    for it in items:
        if "tests/e2e" in str(it.fspath).replace("\\", "/"):
            it.add_marker(pytest.mark.e2e)


def pytest_generate_tests(metafunc):
    if "device" in metafunc.fixturenames:
        metafunc.parametrize("device", MATRIX, ids=[d.id for d in MATRIX])
    if "kbd_device" in metafunc.fixturenames:   # phones with the on-screen keyboard open, in a browser tab and installed
        metafunc.parametrize("kbd_device", KEYBOARD, ids=[d.id for d in KEYBOARD])


@pytest.fixture(scope="session")
def server():
    data = Path(tempfile.mkdtemp(prefix="orbit-e2e-"))
    env = {**os.environ, "KINDLING_DATA_DIR": str(data), "KINDLING_SOURCE": "mock", "ANTHROPIC_API_KEY": "",
           "SCRAPECREATORS_API_KEY": "", "APIFY_TOKEN": "", "KINDLING_OBSIDIAN_DIR": ""}
    seed = (
        "import json; from app import auth, db; db.init();"
        "uid=db.ex(\"INSERT INTO users (name, role, claude_cap, created_at) VALUES ('Tester','user',3.0,?)\",(db.now(),));"
        "pid=db.new_profile(uid,'Couch','mid-century couch');"
        f"open('{data}/token.json','w').write(json.dumps({{'token':auth.new_session(uid,'e2e'),'pid':pid}}))"
    )
    subprocess.run([sys.executable, "-c", seed], cwd=ROOT, env=env, check=True)
    token = json.loads((data / "token.json").read_text())["token"]
    try:   # never attach to a server that is already there (a leftover from an interrupted run would answer with stale data)
        socket.create_connection(("127.0.0.1", PORT), timeout=0.3).close()
        raise RuntimeError(f"port {PORT} is already in use; stop the leftover test server first")
    except OSError:
        pass
    proc = subprocess.Popen(["nice", "-n", "10", sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                             "--port", str(PORT), "--log-level", "warning"], cwd=ROOT, env=env,
                            stdout=open(data / "uvicorn.out", "w"), stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{PORT}"
    for _ in range(80):
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=0.3).close()
            break
        except OSError:
            time.sleep(0.25)
    else:
        proc.kill()
        raise RuntimeError("e2e server did not start: " + (data / "uvicorn.out").read_text())
    yield {"url": url, "token": token, "data": data}
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


STANDALONE_JS = """
(() => {
  const real = window.matchMedia.bind(window);
  window.matchMedia = (q) => {
    const m = /display-mode:\\s*(\\w[\\w-]*)/.exec(q);
    if (!m) return real(q);
    const hit = m[1] === 'standalone';
    return { matches: hit, media: q, onchange: null, addListener() {}, removeListener() {},
             addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; } };
  };
  Object.defineProperty(navigator, 'standalone', { value: true, configurable: true });
})();
"""


class Session:
    """A page plus everything it asked the network for."""

    def __init__(self, page, ctx, device, server):
        self.page, self.ctx, self.device, self.server = page, ctx, device, server
        self.requests, self.errors = [], []
        page.on("request", lambda r: self.requests.append(r.url))
        page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: m.type == "error" and self.errors.append(f"console: {m.text}"))

    @property
    def external_requests(self):
        origin = self.server["url"]
        return sorted({u for u in self.requests if not u.startswith((origin, "data:", "blob:", "about:"))})

    def goto(self, hash_="home", wait=700):
        self.page.goto(self.server["url"] + "/#" + hash_)
        self.page.wait_for_timeout(wait)

    def layout_problems(self, kinds=("clipping", "overflow", "unreachable")):
        from .layout import CHECK_JS
        return [f"{k}: {m}" for k, m in self.page.evaluate(CHECK_JS) if k in kinds]


@pytest.fixture
def make_session(browser, server):
    made = []

    def make(device):
        # `screen` is the physical screen, which the on-screen keyboard and the browser bars never change
        opts = dict(viewport={"width": device.w, "height": device.height}, screen={"width": device.w, "height": device.h},
                    device_scale_factor=device.dpr, is_mobile=device.touch, has_touch=device.touch)
        if device.ua:
            opts["user_agent"] = device.ua
        ctx = browser.new_context(**opts)
        ctx.add_cookies([{"name": "orbit_session", "value": server["token"], "url": server["url"]}])
        page = ctx.new_page()
        if device.installed:
            # Chromium cannot emulate the display-mode media feature (checked: CDP and headless both ignore it), so
            # installed mode is faked for JS only. Orbit CSS must therefore key off html[data-display] (set by script from
            # matchMedia / navigator.standalone), never off @media (display-mode). Real installs are covered by the
            # real-phone checklist.
            page.add_init_script(STANDALONE_JS)
        s = Session(page, ctx, device, server)
        made.append(ctx)
        return s
    yield make
    for c in made:
        c.close()


@pytest.fixture
def session(device, make_session):
    return make_session(device)


# ---------------------------------------------------------------------------------------------------------
# Orbit helpers

import sqlite3  # noqa: E402

def db_file(data):
    return next((data / n for n in ("orbit.db", "kindling.db") if (data / n).exists()), data / "orbit.db")


TABLES_TO_CLEAR = ("placements", "predictions", "swipes", "planet_members", "planets", "events", "seen", "listings", "batches")


def reset_tester(server):
    """Wipe the tester's hunt data between tests (the server keeps running; SQLite WAL lets us write alongside it)."""
    c = sqlite3.connect(db_file(server["data"]), timeout=30)
    for t in TABLES_TO_CLEAR:
        c.execute(f"DELETE FROM {t}")
    c.execute("DELETE FROM crystals")
    uid = c.execute("SELECT id FROM users WHERE name='Tester'").fetchone()[0]
    c.execute("UPDATE profiles SET state='active', found_at=NULL, active=0 WHERE user_id=?", (uid,))
    c.execute("DELETE FROM profiles WHERE user_id=? AND id NOT IN (SELECT MIN(id) FROM profiles WHERE user_id=?)", (uid, uid))
    c.execute("UPDATE profiles SET active=1, hunt='mid-century couch', criteria='[]', must_have='[]', binary=0, suns='[]' WHERE user_id=?", (uid,))
    c.commit()
    c.close()


class Orbit:
    """Drives the Orbit UI with a real mouse or real touch events, depending on the device."""

    def __init__(self, s):
        self.s, self.page, self.d = s, s.page, s.device
        self.cdp = s.ctx.new_cdp_session(s.page) if s.device.touch else None

    # data
    def api(self, path, body=None, method=None):
        if self.page.url.startswith("about:"):          # fetch needs a real origin
            self.page.goto(self.s.server["url"] + "/#place")
            self.page.wait_for_selector("#stage, .page")
        js = "async ([p, b, m]) => { const r = await fetch('/api' + p, { method: m || (b ? 'POST' : 'GET'), headers: {'content-type':'application/json'}, body: b ? JSON.stringify(b) : undefined }); return r.json(); }"
        return self.page.evaluate(js, [path, body, method])

    def start_batch(self, size=6):
        self.page.goto(self.s.server["url"] + "/#place")
        self.page.wait_for_selector("#stage")
        self.api("/batches", {"size": size, "weirdness": 20, "modifiers": []})
        for _ in range(120):
            st = self.api("/o/state")
            if st["batch"] and st["batch"]["status"] == "ready":
                break
            self.page.wait_for_timeout(250)
        self.page.reload()
        try:
            self.page.wait_for_selector("#card:not([hidden])", timeout=15000)
        except Exception:
            raise AssertionError(f"no card; errors={self.s.errors}; state={self.api('/o/state')['batch']}; url={self.page.url}; "
                                 f"html={self.page.inner_html('#app')[:300]}")
        return self.api("/o/state")

    def state(self):
        return self.api("/o/state")

    # input
    def _touch(self, kind, x, y):
        pts = [] if kind == "touchEnd" else [{"x": x, "y": y, "id": 1}]
        self.cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": pts})

    def drag(self, a, b, hold_at_end=False, steps=14):
        """Press at a, move to b in steps, release (unless hold_at_end)."""
        if self.d.touch:
            self._touch("touchStart", a["x"], a["y"])
            for i in range(1, steps + 1):
                self._touch("touchMove", a["x"] + (b["x"] - a["x"]) * i / steps, a["y"] + (b["y"] - a["y"]) * i / steps)
                self.page.wait_for_timeout(8)
            if not hold_at_end:
                self._touch("touchEnd", b["x"], b["y"])
        else:
            self.page.mouse.move(a["x"], a["y"])
            self.page.mouse.down()
            self.page.mouse.move(b["x"], b["y"], steps=steps)
            if not hold_at_end:
                self.page.mouse.up()
        self.page.wait_for_timeout(120)

    def move_to(self, b, steps=6):
        if self.d.touch:
            self._touch("touchMove", b["x"], b["y"])
        else:
            self.page.mouse.move(b["x"], b["y"], steps=steps)
        self.page.wait_for_timeout(100)

    def release(self, at):
        if self.d.touch:
            self._touch("touchEnd", at["x"], at["y"])
        else:
            self.page.mouse.up()
        self.page.wait_for_timeout(150)

    def tap(self, x, y=None):
        if y is None:
            self.page.locator(x).first.scroll_into_view_if_needed()      # a person scrolls to a button before pressing it
            box = self.page.locator(x).first.bounding_box()
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        if self.d.touch:
            self.page.touchscreen.tap(x, y)
        else:
            self.page.mouse.click(x, y)
        self.page.wait_for_timeout(150)

    # geometry
    def card_center(self):
        b = self.page.locator("#card").bounding_box()
        return {"x": b["x"] + b["width"] / 2, "y": b["y"] + b["height"] / 2}

    def thumb_center(self):
        b = self.page.locator("#thumb").bounding_box()
        return {"x": b["x"] + b["width"] / 2, "y": b["y"] + b["height"] / 2}

    def field(self, r, theta):
        return self.page.evaluate("([r, t]) => __place.fieldClient(r, t)", [r, theta])

    def rocket(self):
        return self.page.evaluate("__place.rocketClient()")

    def phase(self):
        return self.page.evaluate("__place.S.phase")


@pytest.fixture
def orbit(session, server):
    reset_tester(server)
    o = Orbit(session)
    yield o
    assert session.errors == [], session.errors


@pytest.fixture
def kbd_orbit(kbd_device, make_session, server):
    reset_tester(server)
    s = make_session(kbd_device)
    o = Orbit(s)
    yield o
    assert s.errors == [], s.errors


def seed_listings(server, n, rating=0.9, tags_fn=None, prefix="seed", batch_number=77):
    """Insert n placed listings straight into the tester's active system. Returns their ids."""
    import json, time
    c = sqlite3.connect(db_file(server["data"]), timeout=30)
    uid = c.execute("SELECT id FROM users WHERE name='Tester'").fetchone()[0]
    pid = c.execute("SELECT id FROM profiles WHERE user_id=? AND active=1", (uid,)).fetchone()[0]
    b = c.execute("INSERT INTO batches (profile_id, number, status, size, created_at) VALUES (?,?,?,?,?)", (pid, batch_number, "done", n, time.time())).lastrowid
    ids = []
    import math
    for i in range(n):
        tags = tags_fn(i) if tags_fn else ["style:x"]
        lid = c.execute("INSERT INTO listings (profile_id, batch_id, fb_id, title, photos, tags, created_at) VALUES (?,?,?,?,?,?,?)",
                        (pid, b, f"{prefix}{time.time()}{i}", f"Seeded {i}", json.dumps(["/static/icon-192.png"]), json.dumps(tags), time.time() + i)).lastrowid
        r = 0.05 if rating >= 0.95 else (1 - rating) * 1.2
        c.execute("INSERT INTO placements (listing_id, profile_id, kind, origin, r, theta, rating, reasons, reason_known, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (lid, pid, "first", "placed", r, 0.0, rating, json.dumps({"price": 0, "right": 1, "guess": 0, "wrong": 0}), 1, time.time() + i))
        c.execute("INSERT INTO swipes (listing_id, verdict, rank, swiped_at) VALUES (?,?,?,?)", (lid, "like", rating, time.time()))
        ids.append(lid)
    c.commit()
    c.close()
    return ids
