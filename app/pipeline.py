"""Builds a batch: plan queries -> search -> screen thumbnails -> pick -> fetch details -> deep score."""
import asyncio
import itertools
import hashlib
import json
import random

from .log import log

from . import brain, checklist, config, costs, db, dupes, learn, obsidian, recheck, rules
from .sources import SourceError, get_source

_running = {}

LOOK_FACTOR = 1.5      # the closer look covers this many times the batch size, so it can choose who is shown
REJECT_DAYS = 30       # a listing judged "not a fit" is skipped this long; one merely not picked is never skipped
MAX_SCREEN = 45        # thumbnails screened per batch


def price_tag(price):
    if price is None:
        return None
    if price < 100:
        return "price:under $100"
    if price < 250:
        return "price:$100-250"
    if price < 500:
        return "price:$250-500"
    return "price:$500+"


def size_tag(width):
    try:
        w = float(width)
    except (TypeError, ValueError):
        return None
    return "size:" + ("under 72in" if w < 72 else "72-84in" if w <= 84 else "over 84in")


def _set(batch_id, **kw):
    cols = ", ".join(f"{k}=?" for k in kw)
    db.ex(f"UPDATE batches SET {cols} WHERE id=?", [*(db.dumps(v) if isinstance(v, (list, dict)) else v
                                                      for v in kw.values()), batch_id])


def _backfill_sigs(profile_id):
    """Listings saved before repost detection existed get a fingerprint from the photo already on disk."""
    rows = db.q("SELECT l.fb_id, l.title, l.price, l.location_text, l.photos FROM listings l "
                "JOIN seen s ON s.profile_id=l.profile_id AND s.fb_id=l.fb_id "
                "WHERE l.profile_id=? AND s.tkey IS NULL", (profile_id,))
    for r in rows:
        data = None
        first = (r["photos"] or [None])[0]
        if first and first.startswith("/img/"):
            f = config.IMG_DIR / first.rsplit("/", 1)[-1]
            data = f.read_bytes() if f.is_file() else None
        sg = dupes.sig({**r, "phash": dupes.phash(data)})
        db.ex("UPDATE seen SET phash=?, tkey=?, price=?, loc=? WHERE profile_id=? AND fb_id=?",
              (sg["phash"], sg["tkey"], sg["price"], sg["loc"], profile_id, r["fb_id"]))


async def _save_image(src, url, stem):
    if not url:
        return None, None
    try:
        data, ext = await src.image_bytes(url)
    except Exception:
        return None, None
    name = f"{stem}.{ext}"
    (config.IMG_DIR / name).write_bytes(data)
    return f"/img/{name}", (data, ext)


def start(batch_id):
    if batch_id in _running and not _running[batch_id].done():
        return
    _running[batch_id] = asyncio.create_task(build(batch_id))


async def build(batch_id):
    batch = db.q1("SELECT * FROM batches WHERE id=?", (batch_id,))
    profile = db.q1("SELECT * FROM profiles WHERE id=?", (batch["profile_id"],))
    src = get_source()
    credits = 0
    step = "starting"
    costs.billing.set((profile["user_id"], batch_id))
    log.info("batch %s (#%s, profile %s): building %s listings, weirdness %s, extras %s, source %s", batch_id,
             batch["number"], profile["id"], batch["size"], batch.get("weirdness"), batch.get("modifiers"), src.name)
    try:
        ctx = learn.context(profile)
        vb = db.q1("SELECT * FROM vibes WHERE profile_id=? AND status='applied'", (profile["id"],))
        if vb and vb["readings"]:  # a vibe hunt: many item types can serve it, so search and judge that way
            recent = [q for r in db.q("SELECT queries FROM batches WHERE profile_id=? AND id!=? AND progress!='Vibe hone' "
                                      "ORDER BY id DESC LIMIT 3", (profile["id"], batch_id)) for q in r["queries"]]
            ctx["vibe"] = {"readings": [r["label"] for r in vb["readings"]],
                           "loved": list(dict.fromkeys(i["reading"] for i in vb["items"]
                                                       if i.get("reaction") in ("love", "like"))),
                           "recent_queries": list(dict.fromkeys(recent))[:9]}
        vibe_hunt = "vibe" in ctx
        rl = rules.parse(batch.get("modifiers") or [])
        ctx["batch_modifiers"] = rl["soft"]
        ctx["batch_rules"] = rules.describe(rl)
        ctx["batch_nots"] = rl["nots"]
        lo, hi = rules.search_prices(profile, rl)
        if lo is not None and hi is not None and lo >= hi:
            raise SourceError(f"The price rules can't both be true (over ${lo:,.0f} and under ${hi:,.0f}).")
        search_profile = {**profile, "min_price": lo, "max_price": hi}
        dropped = {"price": 0, "mentions": 0, "is": 0, "must": 0}
        size = batch["size"]
        weird = (batch["weirdness"] if batch.get("weirdness") is not None else 25) / 100
        rng = random.Random(batch_id)

        # 0. the Sun and Inner orbit: sold listings fade (they are kept, with what they taught)
        step = "re-checking your Sun"
        try:
            _set(batch_id, status="searching", progress="Re-checking your Sun and Inner listings")
            credits += (await recheck.run(profile["id"], src))["credits"]
        except SourceError as e:
            log.warning("batch %s: re-check skipped (%s)", batch_id, e)

        # 1. queries
        step = "picking search terms"
        _set(batch_id, status="searching", progress="Picking search terms")
        n_q = (3 if vibe_hunt else 2) if src.name == "apify" else (5 if vibe_hunt else 3)
        queries = await brain.plan_queries(profile, ctx, n_q, weird)
        _set(batch_id, queries=queries, progress=f"Searching: {', '.join(queries)}")

        # 2. search
        step = "searching Marketplace"
        # skip what the person was shown, and what was recently judged not a fit. Listings that merely weren't
        # picked are never held back: they were never seen, so they stay eligible.
        seen = {r["fb_id"] for r in db.q("SELECT fb_id FROM seen WHERE profile_id=? AND (state='shown' OR at>?)",
                                         (profile["id"], db.now() - REJECT_DAYS * 86400))}
        pool, order = {}, []
        for q in queries:
            cursor = None
            for _page in range(2):
                found, cursor, c = await src.search(search_profile, q, cursor)
                credits += c
                for l in found:
                    if l["fb_id"] in seen or l["fb_id"] in pool:
                        continue
                    if profile.get("max_price") and l["price"] and l["price"] > profile["max_price"]:
                        continue
                    if profile.get("min_price") and l["price"] is not None and l["price"] < profile["min_price"]:
                        continue
                    if not rules.price_ok(l["price"], rl):
                        dropped["price"] += 1
                        continue
                    if rules.mentions(l["title"] or "", rl):  # cheap first pass on the title alone
                        dropped["mentions"] += 1
                        continue
                    l["query"] = q
                    pool[l["fb_id"]] = l
                    order.append(l["fb_id"])
                if not cursor or len(pool) >= size * 3:
                    break
            _set(batch_id, credits_used=credits, progress=f"Found {len(pool)} new listings")
        if not pool:
            raise SourceError("No new listings matched. Try widening the price range, radius, or hunt description.")
        # take turns between search terms so the first one can't fill every screening slot
        by_q = {}
        for i in order:
            by_q.setdefault(pool[i]["query"], []).append(i)
        order = [i for grp in itertools.zip_longest(*by_q.values()) for i in grp if i]

        # 3. screen thumbnails
        step = "screening thumbnails"
        cands = [pool[i] for i in order][:MAX_SCREEN]
        _set(batch_id, status="screening", progress=f"Eyeballing {len(cands)} thumbnails")

        async def thumb(l):
            stem = "t_" + hashlib.md5(l["fb_id"].encode()).hexdigest()[:12]
            path, img = await _save_image(src, l.get("thumb_url"), stem)
            l["thumb_path"] = path
            l["phash"] = dupes.phash(img[0]) if img else None
            return {"key": l["fb_id"], "title": l["title"], "price_text": l.get("price_text"), "image": img}
        shots = dict(zip([l["fb_id"] for l in cands], await asyncio.gather(*(thumb(l) for l in cands))))

        # the same item posted more than once: keep one, and skip reposts of anything this hunt already saw
        _backfill_sigs(profile["id"])
        earlier = [{"phash": r["phash"], "tkey": r["tkey"] or "", "price": r["price"], "loc": r["loc"] or ""}
                   for r in db.q("SELECT phash, tkey, price, loc FROM seen WHERE profile_id=? "
                                 "AND (phash IS NOT NULL OR tkey IS NOT NULL)", (profile["id"],))]
        cands, n_dupes = dupes.collapse(cands, earlier)
        if n_dupes:
            log.info("batch %s: dropped %d reposts of the same item", batch_id, n_dupes)
        rejected = {}  # fb_id -> listing, judged not a fit; remembered for REJECT_DAYS
        if not cands:
            raise SourceError("Everything found was a repost of something you've already seen. "
                              "Try a new angle in your hunt or the batch extras.")
        _set(batch_id, progress=f"Eyeballing {len(cands)} thumbnails")
        screened = [shots[l["fb_id"]] for l in cands]
        judged_thumbs = await brain.screen(profile, ctx, list(screened))
        fit = {k: v["fit"] for k, v in judged_thumbs.items()}
        appeal = {k: v["appeal"] for k, v in judged_thumbs.items()}

        # 4. choose who gets the closer look. "Fit" (is it even the kind of thing you're hunting?) is a hard gate
        # for every slot, comets included. Weirdness only bends taste: it loosens the appeal ranking, widens the
        # comet share, and relaxes how literally "the right kind of thing" is read.
        fit_min = (40 if vibe_hunt else 55) - 20 * weird
        relevant = [l for l in cands if fit.get(l["fb_id"], 0) >= fit_min]
        for l in cands:
            if l not in relevant:
                rejected[l["fb_id"]] = l
        if not relevant:
            raise SourceError(f"None of the {len(cands)} listings found were actually a fit for "
                              f"\"{profile['name']}\". Try different wording in your hunt description.")
        jitter = 0.7 * weird
        keyed = {l["fb_id"]: appeal.get(l["fb_id"], 0) * (1 - jitter) + rng.random() * 100 * jitter
                 for l in relevant}
        ranked = sorted(relevant, key=lambda l: -keyed[l["fb_id"]])
        if vibe_hunt:  # no one item type may take most of the batch, however well it scores
            cap, used, head, tail = -(-size // max(1, len(queries))) + 1, {}, [], []
            for l in ranked:
                if used.get(l["query"], 0) < cap:
                    used[l["query"]] = used.get(l["query"], 0) + 1
                    head.append(l)
                else:
                    tail.append(l)
            ranked = head + tail
        share = config.EXPLORE_SHARE if batch.get("weirdness") is None else 0.05 + 0.45 * weird
        n_comets = max(1, round(size * share)) if len(ranked) > size else 0
        # The closer look covers more listings than the batch holds, then the blended prediction (Claude's closer
        # look + the model of your placements) decides who is shown. Thumbnails only decide who gets looked at.
        n_look = min(len(ranked), max(size, -(-int(size * LOOK_FACTOR * 10) // 10)))
        regular_look = max(0, n_look - n_comets)
        picks = ranked[:regular_look]
        rest = ranked[regular_look:]
        comets = rng.sample(rest, min(n_comets, len(rest)))
        for l in comets:
            l["explore"] = 1
        picks += comets
        backups = [l for l in ranked if l not in picks]

        step = "taking a closer look"
        # 5. details + deep look; anything the closer look says isn't the right kind of thing is dropped
        _set(batch_id, status="scoring", progress=f"Taking a closer look at {len(picks)} listings")
        wmap = {w["tag"]: w["weight"] for w in ctx["weights"]}
        sem = asyncio.Semaphore(4)
        details = {}
        done = 0
        total = len(picks)
        criteria = profile.get("criteria") or []
        must_have = profile.get("must_have") or []

        async def deep(l):
            nonlocal done
            async with sem:
                d = details.get(l["fb_id"]) or {}
                if d and d.get("is_live") is False:
                    rejected[l["fb_id"]] = l
                    return None
                listing = {**l, **{k: v for k, v in d.items() if v not in (None, "", [])}}
                hit = rules.mentions(rules.listing_text(listing), rl)
                if hit or not rules.price_ok(listing.get("price"), rl):
                    dropped["mentions" if hit else "price"] += 1
                    done += 1
                    _set(batch_id, progress=f"Looked at {done} of {total}")
                    rejected[l["fb_id"]] = l
                    return None
                photos, imgs = [], []
                urls = (d.get("photo_urls") or [])[:config.PHOTOS_PER_LISTING] or [l.get("thumb_url")]
                for k, u in enumerate(urls):
                    stem = "p_" + hashlib.md5(f"{l['fb_id']}|{k}".encode()).hexdigest()[:12]
                    p, img = await _save_image(src, u, stem)
                    if p:
                        photos.append(p)
                        imgs.append(img)
                if not photos and l.get("thumb_path"):
                    photos = [l["thumb_path"]]
                try:
                    judged = await brain.deep_score(profile, ctx, listing, imgs)
                except brain.BrainError as e:
                    judged = {"score": appeal.get(l["fb_id"], 50), "fit": fit.get(l["fb_id"], 100),
                              "checklist": [], "take": f"Couldn't get a closer look ({e}).", "tags": [], "guess": "",
                              "features": {}}
                done += 1
                _set(batch_id, progress=f"Looked at {done} of {total}")
                if judged.get("fit", 100) < fit_min - 10:
                    rejected[l["fb_id"]] = l
                    return None
                if judged.get("breaks"):  # Claude says it is something you ruled out with !
                    dropped["is"] += 1
                    rejected[l["fb_id"]] = l
                    return None
                eff = checklist.effect(criteria, must_have, judged["checklist"])
                if eff["drop"]:  # a must-have answered no
                    dropped["must"] += 1
                    rejected[l["fb_id"]] = l
                    return None
                tags = set(judged["tags"])
                for t in (price_tag(listing.get("price")), size_tag(judged["features"].get("width_in")),
                          ("condition:" + listing["condition"].lower()) if listing.get("condition") else None):
                    if t:
                        tags.add(t)
                tags = sorted(tags)
                m = learn.model_score(tags, wmap, ctx["mean"])
                return {
                    "listing": listing, "photos": photos, "tags": tags, "features": judged["features"],
                    "checklist": judged["checklist"], "take": judged["take"],
                    "claude_score": judged["score"], "model_score": m, "nos": eff["nos"], "guess": judged.get("guess") or "",
                    "predicted": max(0.0, learn.blend(judged["score"], m, ctx["n_swipes"]) - eff["penalty"]),
                }

        async def look(group):
            nonlocal credits
            got, c = await src.items([l["fb_id"] for l in group])
            credits += c
            details.update(got)
            _set(batch_id, credits_used=credits)
            return [r for r in await asyncio.gather(*(deep(l) for l in group)) if r]

        def choose(found):
            """Comets keep their place; the rest are ranked by the prediction made after the closer look."""
            cm = [r for r in found if r["listing"].get("explore")]
            reg = sorted((r for r in found if not r["listing"].get("explore")), key=lambda r: -r["predicted"])
            return cm[:n_comets], reg

        looked = await look(picks)
        for _round in range(3):  # top up from the next best real matches when misfits or rules drop some
            comet_got, reg_got = choose(looked)
            missing = size - len(comet_got) - len(reg_got)
            if missing <= 0 or not backups:
                break
            extra, backups = backups[:missing], backups[missing:]
            total += len(extra)
            looked += await look(extra)
        comet_got, reg_got = choose(looked)
        results = reg_got[:max(0, size - len(comet_got))] + comet_got
        if not results:
            why = ""
            if any(dropped.values()):
                why = (f" Your batch rules ruled out {dropped['price']} on price, {dropped['mentions']} for "
                       f"mentioning an excluded word, {dropped['is']} for being something you said no to, and "
                       f"{dropped['must']} for failing a must-have.")
            raise SourceError("Nothing survived the closer look." + why + " Try loosening the rules or the hunt.")
        rng.shuffle(results)
        with db.tx() as cx:
            for pos, r in enumerate(results):
                l = r["listing"]
                cur = cx.execute(
                    "INSERT INTO listings (profile_id, batch_id, fb_id, url, title, price, price_text, location_text, "
                    "description, condition, fb_attributes, photos, query, tags, features, checklist, take, "
                    "claude_score, model_score, predicted, explore, position, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (profile["id"], batch_id, l["fb_id"], l.get("url"), l.get("title"), l.get("price"),
                     l.get("price_text"), l.get("location_text"), l.get("description"), l.get("condition"),
                     db.dumps(l.get("fb_attributes") or []), db.dumps(r["photos"]), l.get("query"),
                     db.dumps(r["tags"]), db.dumps(r["features"]), db.dumps(r["checklist"]), r["take"],
                     r["claude_score"], r["model_score"], r["predicted"], l.get("explore", 0), pos, db.now()))
                cx.execute("INSERT OR REPLACE INTO predictions (listing_id, profile_id, batch_id, claude_score, model_score, "
                           "predicted, checklist_nos, guess_text, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                           (cur.lastrowid, profile["id"], batch_id, r["claude_score"], r["model_score"], r["predicted"], r["nos"],
                            r["guess"], db.now()))
            # only what was shown (or judged not a fit) is remembered, in the same transaction as the batch itself
            cx.executemany("INSERT OR REPLACE INTO seen (profile_id, fb_id, phash, tkey, price, loc, state, at) "
                           "VALUES (?,?,?,?,?,?,?,?)",
                           [(profile["id"], r["listing"]["fb_id"], *dupes.sig(r["listing"]).values(), "shown", db.now())
                            for r in results] +
                           [(profile["id"], i, *dupes.sig(l).values(), "rejected", db.now())
                            for i, l in rejected.items() if i not in {r["listing"]["fb_id"] for r in results}])
        _set(batch_id, status="ready", size=len(results), progress="Ready", ready_at=db.now(),
             credits_used=credits)
        log.info("batch %s ready: %d listings, %d credits, queries %s, rules dropped %s", batch_id, len(results),
                 credits, queries, dropped)
    except Exception as e:  # surface every failure in the UI and the log
        known = isinstance(e, (SourceError, brain.BrainError))
        if known:
            log.error("batch %s failed while %s: %s", batch_id, step, e)
        else:
            log.exception("batch %s crashed while %s", batch_id, step)
        msg = str(e) if known else f"{type(e).__name__}: {e}"
        _set(batch_id, status="error", error=f"Failed while {step}: {msg}", credits_used=credits)


async def finish(batch_id):
    """Batch fully swiped and ranked: refresh the taste summary and export notes."""
    batch = db.q1("SELECT * FROM batches WHERE id=?", (batch_id,))
    if batch["status"] != "done":
        _set(batch_id, status="done", finished_at=db.now())
    profile = db.q1("SELECT * FROM profiles WHERE id=?", (batch["profile_id"],))
    costs.billing.set((profile["user_id"], batch_id))
    ctx = learn.context(profile)
    try:
        summary = await brain.summarize_taste(profile, ctx)
        if summary:
            db.ex("UPDATE profiles SET taste_summary=? WHERE id=?", (summary, profile["id"]))
            profile["taste_summary"] = summary
    except brain.BrainError as e:
        log.warning("batch %s: taste summary not updated (%s)", batch_id, e)
    owner = db.q1("SELECT role FROM users WHERE id=?", (profile["user_id"],))
    if not owner or owner["role"] != "admin":
        return  # the vault is the admin's; nobody else's batches get written into it
    try:
        obsidian.export_batch(profile, db.q1("SELECT * FROM batches WHERE id=?", (batch_id,)),
                              learn.swiped(profile["id"], batch_id))
    except Exception:
        log.exception("batch %s: Obsidian note export failed", batch_id)
