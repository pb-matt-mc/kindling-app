"""Optional: notes in the Obsidian vault. One note per finished batch (with where each listing landed and how close
Claude got), one standing note per system (current scores, planets, events), and a dated line when an event is settled.
Listing links keep the Marketplace URL format: the release-unshown repair uses those links as proof of what was shown."""
import time
from pathlib import Path

from . import config, db, orbit_math as m, scores


def _root():
    if not config.OBSIDIAN_DIR:
        return None
    root = Path(config.OBSIDIAN_DIR).expanduser()
    return root if root.is_dir() else None


def _where(r):
    z = m.zone(r)
    return z


def _split(reasons):
    if not reasons:
        return ""
    return ", ".join(f"{round(v * 100)}% {m.AXIS_NAMES_PRETTY[k]}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]) if v >= 0.05)


def export_batch(profile, batch, rows):
    root = _root()
    if not root:
        return
    folder = root / "Batches" / _safe(profile["name"])
    folder.mkdir(parents=True, exist_ok=True)
    date = time.strftime("%Y-%m-%d", time.localtime(batch["finished_at"] or time.time()))
    pl = {p["listing_id"]: p for p in db.q(
        "SELECT p.* FROM placements p JOIN listings l ON l.id=p.listing_id WHERE l.batch_id=? AND p.undone=0 AND p.id="
        "(SELECT MAX(id) FROM placements q WHERE q.listing_id=p.listing_id AND q.undone=0)", (batch["id"],))}
    pr = {p["listing_id"]: p for p in db.q("SELECT * FROM predictions WHERE batch_id=?", (batch["id"],))}
    likes = [r for r in rows if r["verdict"] == "like"]
    passes = [r for r in rows if r["verdict"] != "like"]
    checked = [p for p in pr.values() if p["gap"] is not None]
    called = sum(1 for p in checked if p["gap"] < 0.06)
    close = sum(1 for p in checked if 0.06 <= p["gap"] < 0.16)
    lines = ["---", f"profile: {profile['name']}", f"batch: {batch['number']}", f"date: {date}", f"liked: {len(likes)}", f"passed: {len(passes)}",
             f"called_it: {called}", f"close: {close}", f"claude_missed: {len(checked) - called - close}",
             f"queries: [{', '.join(batch['queries'] or [])}]", "---", f"# {profile['name']} batch {batch['number']}", ""]
    conf = scores.confidence(profile["id"])
    lines += [f"Confidence after this batch: {'Still learning' if conf['state'] != 'ready' else str(round(conf['value'] * 100)) + '%'}", ""]
    if profile.get("taste_summary"):
        lines += ["## Taste so far", profile["taste_summary"], ""]

    def line(r):
        p, q = pl.get(r["id"]), pr.get(r["id"])
        where = f" · {_where(p['r'])}" if p else ""
        split = f" · {_split(p['reasons'])}" if p and p["reasons"] else ""
        how = ""
        if p and p["kind"] == "rocket":
            how = " · rocketed"
        elif q and q["gap"] is not None:
            how = f" · Claude guessed {round(q['predicted'] * 100)}, you said {round(q['actual_rating'] * 100)}"
        comet = " · comet" if r.get("explore") else ""
        return f"- [{r['title']}]({r['url']}) {r['price_text'] or ''} · {r['location_text'] or ''}{where}{split}{comet}{how}"
    lines.append("## Inside the frost line (liked)")
    for r in likes:
        lines.append(line(r))
        if r.get("take"):
            lines.append(f"    - {r['take']}")
    lines += ["", "## Outside the frost line (passed)"]
    for r in passes:
        lines.append(line(r))
    (folder / f"{date} batch {batch['number']}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    export_system(profile)


def export_system(profile):
    """The standing note for a system: scores, planets and a running list of events."""
    root = _root()
    if not root:
        return
    folder = root / "Systems"
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"{_safe(profile['name'])}.md"
    old_events = ""
    if f.exists():
        txt = f.read_text(encoding="utf-8")
        if "## Events" in txt:
            old_events = txt.split("## Events", 1)[1].strip("\n")
    conf, wild = scores.confidence(profile["id"]), scores.wild_card_rate(profile["id"])
    counts = {z: 0 for z, _ in m.ZONES}
    for p in db.q("SELECT r FROM placements p WHERE p.profile_id=? AND p.undone=0 AND p.id=(SELECT MAX(id) FROM placements q WHERE q.listing_id=p.listing_id AND q.undone=0)", (profile["id"],)):
        counts[m.zone(p["r"])] += 1
    planets = db.q("SELECT name, r FROM planets WHERE profile_id=? ORDER BY id", (profile["id"],))
    lines = ["---", f"system: {profile['name']}", f"state: {profile.get('state') or 'active'}", f"updated: {time.strftime('%Y-%m-%d')}", "---", f"# {profile['name']}", "",
             f"Hunting: {profile['hunt']}", "",
             f"- Confidence: {'Still learning' if conf['state'] != 'ready' else str(round(conf['value'] * 100)) + '%'}",
             f"- Wild card rate: {'Still learning' if wild['state'] != 'ready' else str(round(wild['value'] * 100)) + '%'}",
             "- " + " · ".join(f"{z} {n}" for z, n in counts.items()), ""]
    if planets:
        lines += ["## Planets"] + [f"- {p['name']} ({m.zone(p['r'])})" for p in planets] + [""]
    lines += ["## Events", old_events]
    f.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def log_event(profile, title, action):
    root = _root()
    if not root:
        return
    export_system(profile)
    f = root / "Systems" / f"{_safe(profile['name'])}.md"
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(f"\n- {time.strftime('%Y-%m-%d')}: {title} ({action})")


def _safe(s):
    return "".join(ch for ch in s if ch.isalnum() or ch in " -_").strip() or "Profile"
