"""Vibe hunts: start a hunt from a feeling instead of an item.

The person gives references (photos, a description, Facebook listing links, Pinterest pins and public
boards). Claude lists every way the vibe could be read and drafts a hunt. "Hone this hunt" then shows real
listings, one per reading, and the person reacts to them (like, love, hate, skip) and says why. Claude
sharpens the hunt from that. None of it touches the taste web unless the person asks for it at the end.
"""
import asyncio
import base64
import hashlib
import html
import io
import re
import uuid
from urllib.parse import urlparse

import httpx

from . import brain, config, costs, db, learn
from .log import log
from .pipeline import _save_image
from .sources import SourceError, get_source

MAX_IMAGES = 16          # photos Claude gets to see per vibe
MAX_UPLOAD = 8_000_000   # bytes
LOVES = 3                # hearts a person can hand out
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
REACTIONS = ("like", "love", "hate")
_running = {}


class VibeError(Exception):
    pass


# --------------------------------------------------------------------------- storage

def get(pid):
    return db.q1("SELECT * FROM vibes WHERE profile_id=?", (pid,))


def ensure(pid):
    if not get(pid):
        db.ex("INSERT INTO vibes (profile_id, created_at, updated_at) VALUES (?,?,?)", (pid, db.now(), db.now()))
    return get(pid)


def _set(pid, **kw):
    for k in ("sources", "draft", "readings", "items", "result", "rejected"):
        if k in kw:
            kw[k] = db.dumps(kw[k])
    kw["updated_at"] = db.now()
    db.ex(f"UPDATE vibes SET {', '.join(f'{k}=?' for k in kw)} WHERE profile_id=?", [*kw.values(), pid])


def view(v):
    """What the app gets: the stored row plus the size of the hone it would build."""
    v = dict(v)
    v["hone_size"] = brain.hone_size(len(v["readings"])) if v["readings"] else 0
    v["images_left"] = max(0, MAX_IMAGES - sum(len(s["images"]) for s in v["sources"]))
    v["loves_left"] = LOVES - sum(1 for i in v["items"] if i.get("reaction") == "love")
    return v


def _need(v, *states):
    if v["status"] not in states:
        raise VibeError(f"Can't do that right now (this vibe is at '{v['status']}').")


# --------------------------------------------------------------------------- images

def _store_jpeg(data):
    """Any image bytes -> a small JPEG under /img, or raise VibeError."""
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = im.convert("RGB")
            im.thumbnail((1024, 1024))
            out = io.BytesIO()
            im.save(out, "JPEG", quality=84)
    except Exception:
        raise VibeError("That file isn't an image Kindling can read.")
    jpg = out.getvalue()
    name = "v_" + hashlib.md5(jpg).hexdigest()[:14] + ".jpg"
    (config.IMG_DIR / name).write_bytes(jpg)
    return f"/img/{name}"


def _read_local(path):
    f = config.IMG_DIR / path.rsplit("/", 1)[-1]
    return (f.read_bytes(), "jpg") if f.is_file() else None


def add_image(pid, b64):
    v = ensure(pid)
    _need(v, "inputs", "drafted")
    if sum(len(s["images"]) for s in v["sources"]) >= MAX_IMAGES:
        raise VibeError(f"That's the most photos Claude can look at ({MAX_IMAGES}). Remove one first.")
    raw = b64.split(",", 1)[-1]
    try:
        data = base64.b64decode(raw, validate=False)
    except Exception:
        raise VibeError("Couldn't read that photo.")
    if len(data) > MAX_UPLOAD:
        raise VibeError("That photo is too big.")
    path = _store_jpeg(data)
    src = {"id": uuid.uuid4().hex[:8], "kind": "image", "label": "Your photo", "url": "", "text": "", "images": [path]}
    _set(pid, sources=v["sources"] + [src], error=None)
    return src


def remove_source(pid, sid):
    v = ensure(pid)
    _need(v, "inputs", "drafted")
    _set(pid, sources=[s for s in v["sources"] if s["id"] != sid])


# --------------------------------------------------------------------------- links

def _pinterest_host(host):
    return bool(re.search(r"(^|\.)pinterest\.[a-z.]{2,6}$", host or "")) or host == "pin.it"


async def _get(url, want="text"):
    """Fetch from Pinterest only, following redirects by hand so none can lead somewhere else."""
    async with httpx.AsyncClient(timeout=20, headers=UA, follow_redirects=False) as c:
        for _ in range(5):
            host = urlparse(url).hostname or ""
            if not (_pinterest_host(host) or host.endswith(".pinimg.com")):
                raise VibeError("That link goes somewhere Kindling won't open.")
            r = await c.get(url)
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                url = str(httpx.URL(url).join(r.headers["location"]))
                continue
            if r.status_code != 200:
                raise VibeError(f"Pinterest wouldn't show that (HTTP {r.status_code}). Is the board public?")
            if len(r.content) > MAX_UPLOAD:
                raise VibeError("That page is too big.")
            return r.content if want == "bytes" else r.text, url
    raise VibeError("Too many redirects.")


def _og(page, prop):
    m = re.search(r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]+content=["\']([^"\']*)["\']' % re.escape(prop), page, re.I) \
        or re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']%s["\']' % re.escape(prop), page, re.I)
    return html.unescape(m.group(1)).strip() if m else ""


async def _pin(url):
    page, final = await _get(url)
    img = _og(page, "og:image")
    if not img:
        raise VibeError("Couldn't find a picture on that pin. If the board is public, paste the board link instead.")
    title = _og(page, "og:title") or "Pinterest pin"
    return title, _og(page, "og:description"), [img]


async def _board(user, board):
    xml, _ = await _get(f"https://www.pinterest.com/{user}/{board}.rss")
    title = html.unescape((re.search(r"<title>(.*?)</title>", xml, re.S) or [0, "Pinterest board"])[1]).strip()
    imgs, notes = [], []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S)[:30]:
        body = html.unescape(item)
        m = re.search(r'src="(https://i\.pinimg\.com/[^"]+)"', body)
        if m:
            imgs.append(re.sub(r"/\d+x/", "/736x/", m.group(1)))
        t = re.search(r"<title>(.*?)</title>", item, re.S)
        if t and html.unescape(t.group(1)).strip():
            notes.append(html.unescape(t.group(1)).strip()[:80])
    if not imgs:
        raise VibeError("That board has no pins Kindling can see. It has to be public.")
    return title, "Pins: " + "; ".join(notes[:8]), imgs


async def add_link(pid, url):
    v = ensure(pid)
    _need(v, "inputs", "drafted")
    url = url.strip()
    if not re.match(r"https?://", url):
        url = "https://" + url
    u = urlparse(url)
    host = (u.hostname or "").lower()
    room = MAX_IMAGES - sum(len(s["images"]) for s in v["sources"])
    if room <= 0:
        raise VibeError(f"That's the most photos Claude can look at ({MAX_IMAGES}). Remove one first.")
    src = {"id": uuid.uuid4().hex[:8], "kind": "", "label": "", "url": url[:300], "text": "", "images": []}
    urls = []
    if host.endswith("facebook.com") or host.endswith("fb.com"):
        m = re.search(r"/marketplace/item/(\d+)", u.path)
        if not m:
            raise VibeError("Paste a Facebook Marketplace listing link (it has /marketplace/item/ in it).")
        source = get_source()
        try:
            got, credits = await source.items([m.group(1)])
        except SourceError as e:
            raise VibeError(str(e))
        d = got.get(m.group(1))
        if not d:
            raise VibeError("Couldn't open that listing. It may be sold or removed.")
        db.ex("UPDATE vibes SET credits_used=credits_used+? WHERE profile_id=?", (credits, pid))
        src.update(kind="listing", label=d.get("title") or "Marketplace listing",
                   text=f"{d.get('title') or ''} {d.get('price_text') or ''}. {(d.get('description') or '')[:400]}")
        for i, pu in enumerate((d.get("photo_urls") or [])[:min(3, room)]):
            _, img = await _save_image(source, pu, "v_" + hashlib.md5(f"{m.group(1)}|{i}".encode()).hexdigest()[:12])
            if img:
                urls.append(img[0])
    elif _pinterest_host(host):
        if host == "pin.it":
            _, url = await _get(url)
            u = urlparse(url)
        parts = [p for p in u.path.split("/") if p]
        if parts[:1] == ["pin"] and len(parts) >= 2:
            title, desc, imgs = await _pin(url)
            src.update(kind="pin", label=title, text=f"Pinterest pin: {title}. {desc}"[:400])
        elif len(parts) >= 2 and parts[0] not in ("pin", "ideas", "search", "today", "news_hub"):
            title, desc, imgs = await _board(parts[0], parts[1].removesuffix(".rss"))
            src.update(kind="board", label=title, text=f"Pinterest board \"{title}\". {desc}"[:600])
        else:
            raise VibeError("Paste a Pinterest pin link or a public board link (pinterest.com/name/board).")
        for iu in imgs[:min(10, room)]:
            try:
                data, _ = await _get(iu, "bytes")
                urls.append(data)
            except VibeError:
                continue
    else:
        raise VibeError("Kindling can read Facebook Marketplace listings and Pinterest pins or public boards. "
                        "For anything else, save a screenshot and add it as a photo.")
    paths = []
    for d in urls:
        try:
            paths.append(_store_jpeg(d))
        except VibeError:
            continue
    if not paths and src["kind"] != "listing":
        raise VibeError("Couldn't load any pictures from that link.")
    src["images"] = paths[:room]
    _set(pid, sources=v["sources"] + [src], error=None)
    return src


# --------------------------------------------------------------------------- the steps

def start(pid, fn):
    if pid in _running and not _running[pid].done():
        return
    _running[pid] = asyncio.create_task(fn(pid))


def _profile(pid):
    return db.q1("SELECT * FROM profiles WHERE id=?", (pid,))


async def analyze(pid):
    v, profile = get(pid), _profile(pid)
    costs.billing.set((profile["user_id"], None))
    try:
        images = [x for s in v["sources"] for p in s["images"] if (x := _read_local(p))]
        notes = [s["text"] for s in v["sources"] if s["text"]]
        _set(pid, progress=f"Looking at {len(images)} picture{'s' if len(images) != 1 else ''}")
        out = await brain.vibe_analyze(profile, v["text"], notes, images, [r["label"] for r in v["rejected"]])
        if not out["readings"]:
            raise VibeError("Claude couldn't come up with any readings. Add a little more to go on.")
        readings = [{"id": f"r{i + 1}", **r} for i, r in enumerate(out["readings"])]
        draft = {k: out[k] for k in ("summary", "hunt", "criteria", "min_price", "max_price")}
        _set(pid, status="drafted", progress="", error=None, draft=draft, readings=readings)
    except (brain.BrainError, VibeError) as e:
        log.warning("vibe %s: analysis failed: %s", pid, e)
        _set(pid, status="inputs", progress="", error=str(e))
    except Exception as e:
        log.exception("vibe %s: analysis crashed", pid)
        _set(pid, status="inputs", progress="", error=f"{type(e).__name__}: {e}")


def _pick(readings, cands, scored, n):
    """One listing per reading first (the fewest that test every reading), then the next best from each in turn."""
    by = {r["id"]: sorted([c for c in cands if c["reading_id"] == r["id"] and scored[c["key"]]["fit"] >= 35],
                          key=lambda c: -scored[c["key"]]["fit"]) for r in readings}
    chosen, skipped = [], [r["label"] for r in readings if not by[r["id"]]]
    depth = 0
    while len(chosen) < n and any(len(x) > depth for x in by.values()):
        for r in readings:
            if depth < len(by[r["id"]]) and len(chosen) < n:
                chosen.append(by[r["id"]][depth])
        depth += 1
    return chosen, skipped


async def build_hone(pid):
    v, profile = get(pid), _profile(pid)
    costs.billing.set((profile["user_id"], None))
    src = get_source()
    credits = 0
    try:
        draft, readings = v["draft"], v["readings"]
        n = brain.hone_size(len(readings))
        sprofile = {**profile, "min_price": draft.get("min_price"), "max_price": draft.get("max_price")}
        seen = {r["fb_id"] for r in db.q("SELECT fb_id FROM seen WHERE profile_id=?", (pid,))}
        _set(pid, progress=f"Searching Marketplace for {len(readings)} readings")
        sem = asyncio.Semaphore(4)
        pool, taken = {}, set()
        per = max(3, -(-n // len(readings)) + 1)  # candidates per reading, so a short list can still fill the grid

        async def look(r):
            nonlocal credits
            async with sem:
                try:
                    found, _cur, c = await src.search(sprofile, r["query"])
                except SourceError as e:
                    log.warning("vibe %s: search '%s' failed: %s", pid, r["query"], e)
                    return r["id"], []
                credits += c
                return r["id"], found

        for rid, found in await asyncio.gather(*(look(r) for r in readings)):
            mine = []
            for l in found:
                if l["fb_id"] in seen or l["fb_id"] in taken or not l.get("thumb_url"):
                    continue
                if draft.get("max_price") and l["price"] and l["price"] > draft["max_price"]:
                    continue
                taken.add(l["fb_id"])
                mine.append({**l, "reading_id": rid})
                if len(mine) == per:
                    break
            pool[rid] = mine
        cands = [c for r in readings for c in pool.get(r["id"], [])]
        if not cands:
            raise VibeError("No listings turned up nearby for any reading. Try a wider radius or a higher budget.")
        _set(pid, progress=f"Eyeballing {len(cands)} listings")
        lab = {r["id"]: r for r in readings}
        shots = {}

        async def thumb(c):
            async with sem:
                path, img = await _save_image(src, c["thumb_url"], "t_" + hashlib.md5(c["fb_id"].encode()).hexdigest()[:12])
                shots[c["fb_id"]] = (path, img)

        await asyncio.gather(*(thumb(c) for c in cands))
        cands = [c for c in cands if shots[c["fb_id"]][0]]
        asked = [{"key": c["fb_id"], "reading": lab[c["reading_id"]]["label"], "title": c["title"],
                  "price_text": c.get("price_text"), "image": shots[c["fb_id"]][1]} for c in cands]
        scored = await brain.vibe_pick(draft, readings, asked)
        for c in cands:
            c["key"] = c["fb_id"]
        chosen, skipped = _pick(readings, cands, scored, n)
        if not chosen:
            raise VibeError("Nothing found nearby was a good example of any reading.")
        items = [{
            "id": c["fb_id"], "reading_id": c["reading_id"], "reading": lab[c["reading_id"]]["label"],
            "query": lab[c["reading_id"]]["query"], "title": c["title"], "price": c.get("price"),
            "price_text": c.get("price_text") or "", "url": c.get("url") or "", "location_text": c.get("location_text") or "",
            "photo": shots[c["fb_id"]][0], "tags": scored[c["fb_id"]]["tags"], "facets": scored[c["fb_id"]]["facets"],
            "reaction": None, "why": [], "note": "",
        } for c in chosen]
        with db.tx() as cx:
            cx.executemany("INSERT OR IGNORE INTO seen (profile_id, fb_id) VALUES (?,?)", [(pid, i["id"]) for i in items])
        got = {i["reading_id"] for i in items}
        _set(pid, status="hone", progress="", error=None, items=items, honed=1,
             readings=[{**r, "found": r["id"] in got} for r in readings],
             credits_used=v["credits_used"] + credits)
        log.info("vibe %s: hone ready, %d listings for %d readings (skipped %s), %d credits", pid, len(items),
                 len(readings), skipped, credits)
    except (brain.BrainError, VibeError, SourceError) as e:
        log.warning("vibe %s: hone failed: %s", pid, e)
        _set(pid, status="drafted", progress="", error=str(e), credits_used=v["credits_used"] + credits)
    except Exception as e:
        log.exception("vibe %s: hone crashed", pid)
        _set(pid, status="drafted", progress="", error=f"{type(e).__name__}: {e}", credits_used=v["credits_used"] + credits)


def remove_reading(pid, rid):
    """The person says this reading of the vibe is wrong. It's dropped from the hone and remembered, so a
    redo and the final sharpening both steer away from it."""
    v = ensure(pid)
    _need(v, "drafted")
    r = next((x for x in v["readings"] if x["id"] == rid), None)
    if not r:
        raise VibeError("That reading is already gone.")
    if len(v["readings"]) <= 1:
        raise VibeError("Keep at least one reading, or change your references and redo the hunt.")
    _set(pid, readings=[x for x in v["readings"] if x["id"] != rid],
         rejected=v["rejected"] + [{"label": r["label"], "query": r["query"]}])


def react(pid, item_id, reaction, why, note):
    v = ensure(pid)
    _need(v, "hone")
    if reaction not in REACTIONS and reaction is not None:
        raise VibeError("Reaction must be like, love or hate.")
    items = v["items"]
    it = next((i for i in items if i["id"] == item_id), None)
    if not it:
        raise VibeError("That listing isn't in this hone.")
    if reaction == "love" and it.get("reaction") != "love" and \
            sum(1 for i in items if i.get("reaction") == "love") >= LOVES:
        raise VibeError(f"You can love up to {LOVES}. Take a heart off another one first.")
    it["reaction"] = reaction
    ok = {f["label"] for f in it["facets"]} | {"Not sure"}
    it["why"] = [w for w in (why or []) if w in ok][:6] if reaction else []
    it["note"] = (note or "").strip()[:200] if reaction else ""
    _set(pid, items=items)
    return it


async def refine(pid):
    v, profile = get(pid), _profile(pid)
    costs.billing.set((profile["user_id"], None))
    try:
        out = await brain.vibe_refine(profile, v["draft"], v["items"], [r["label"] for r in v["rejected"]])
        _set(pid, status="refined", progress="", error=None, result=out)
    except brain.BrainError as e:
        log.warning("vibe %s: refine failed: %s", pid, e)
        _set(pid, status="hone", progress="", error=str(e))
    except Exception as e:
        log.exception("vibe %s: refine crashed", pid)
        _set(pid, status="hone", progress="", error=f"{type(e).__name__}: {e}")


# --------------------------------------------------------------------------- finishing

def apply(pid, hunt, criteria, min_price, max_price):
    """Write the hunt (as edited) onto the profile. The hone ratings are not used anywhere else."""
    v = ensure(pid)
    _need(v, "drafted", "refined", "applied")
    db.ex("UPDATE profiles SET hunt=?, criteria=?, min_price=?, max_price=? WHERE id=?",
          (hunt.strip(), db.dumps([c.strip() for c in criteria if c.strip()]), min_price, max_price, pid))
    _set(pid, status="applied", error=None)


WEB_RANK = {"love": 0.95, "like": 0.75, "hate": 0.05}


def add_to_web(pid):
    """Optional: put the rated hone listings into the taste web as a finished batch of their own."""
    v = ensure(pid)
    if v["web_added"]:
        raise VibeError("Those are already in your web.")
    rated = [i for i in v["items"] if i.get("reaction")]
    if not rated:
        raise VibeError("Nothing was rated.")
    room = learn.WEB_LIMIT - learn.web_count(pid)
    if room <= 0:
        raise VibeError("Your web is full. Crystallize it first.")
    rated = rated[:room]
    number = (db.q1("SELECT MAX(number) n FROM batches WHERE profile_id=?", (pid,))["n"] or 0) + 1
    t = db.now()
    with db.tx() as c:
        bid = c.execute("INSERT INTO batches (profile_id, number, status, size, queries, progress, created_at, ready_at, "
                        "finished_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (pid, number, "done", len(rated), db.dumps(sorted({i["query"] for i in rated})),
                         "Vibe hone", t, t, t)).lastrowid
        for pos, i in enumerate(rated):
            why = "; ".join([w for w in i["why"] if w != "Not sure"] + ([i["note"]] if i["note"] else []))
            lid = c.execute(
                "INSERT INTO listings (profile_id, batch_id, fb_id, url, title, price, price_text, location_text, "
                "photos, query, tags, take, position, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, bid, i["id"], i["url"], i["title"], i["price"], i["price_text"], i["location_text"],
                 db.dumps([i["photo"]]), i["query"], db.dumps(i["tags"]),
                 f"From your vibe hone ({i['reading']})." + (f" You said: {why}." if why else ""), pos, t)).lastrowid
            c.execute("INSERT INTO swipes (listing_id, verdict, rank, manual, swiped_at) VALUES (?,?,?,?,?)",
                      (lid, "dislike" if i["reaction"] == "hate" else "like", WEB_RANK[i["reaction"]], 1, t))
    _set(pid, web_added=1)
    return len(rated)
