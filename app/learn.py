"""The "algorithm": trait weights learned from swipes and web rankings, blended with Claude's read.

Every swiped listing has a rank in [0, 1] (1 = dead center of the web, loved; 0 = outer edge,
hated). A swipe sets a default rank (like 0.75, dislike 0.25); dragging it on the web refines it.
Each trait tag's weight is how far its listings' ranks sit from your average, shrunk toward 0
when it has only been seen a few times. A new listing's model score is your average plus the
weights of its tags. Early on Claude's judgement carries the prediction; as swipes pile up the
learned weights take a bigger share.

Crystals: when the web is crystallized, the raw evidence behind every trait (summed rank offsets,
counts, likes) is frozen into a crystal and the listings are let go. Weights are then computed from
the live web plus every crystal, with each older crystal counting half as much as the one after it,
so taste can drift without the past vanishing.
"""
import math
from collections import defaultdict
from itertools import combinations

from . import db

SHRINK = 2.0           # pseudo-count pulling rare traits toward neutral
MAX_MODEL_SHARE = 0.6  # learned model never fully drowns out Claude
FULL_TRUST_SWIPES = 60
WEB_LIMIT = 50         # New Batch locks once the web holds this many swiped listings
CRYSTAL_FADE = 0.5     # each older crystal counts this much as the next newer one


def swiped(profile_id, batch_id=None, evidence_only=False):
    """Swiped listings currently in the web. evidence_only skips ones whose taste is already crystallized."""
    sql = ("SELECT l.*, s.verdict, s.rank, s.manual, s.swiped_at FROM listings l "
           "JOIN swipes s ON s.listing_id = l.id WHERE l.profile_id=? AND l.state='web'")
    args = [profile_id]
    if evidence_only:
        sql += " AND l.absorbed=0"
    if batch_id:
        sql += " AND l.batch_id=?"
        args.append(batch_id)
    return db.q(sql + " ORDER BY s.rank DESC", args)


def web_count(profile_id):
    return db.q1("SELECT COUNT(*) n FROM listings l JOIN swipes s ON s.listing_id=l.id "
                 "WHERE l.profile_id=? AND l.state='web'", (profile_id,))["n"]


def crystals(profile_id):
    """Newest first, each with the fade factor it currently carries."""
    cs = db.q("SELECT * FROM crystals WHERE profile_id=? ORDER BY number DESC", (profile_id,))
    for i, c in enumerate(cs):
        c["factor"] = CRYSTAL_FADE ** i
    return cs


def evidence(rows):
    """Raw per-trait evidence from listing rows, relative to their own mean. What a crystal stores."""
    if not rows:
        return [], 0.5
    mean = sum(r["rank"] for r in rows) / len(rows)
    acc = defaultdict(lambda: {"sum": 0.0, "n": 0, "likes": 0})
    for r in rows:
        for t in r["tags"] or []:
            a = acc[t]
            a["sum"] += r["rank"] - mean
            a["n"] += 1
            a["likes"] += r["verdict"] == "like"
    return [{"tag": t, **a} for t, a in acc.items()], mean


def weights(profile_id):
    rows = swiped(profile_id, evidence_only=True)
    cs = crystals(profile_id)
    total = sum(r["rank"] for r in rows)
    count = float(len(rows))
    for c in cs:
        total += c["mean"] * c["n_listings"] * c["factor"]
        count += c["n_listings"] * c["factor"]
    if count == 0:
        return [], 0.5
    mean = total / count
    acc = defaultdict(lambda: {"sum": 0.0, "n": 0.0, "likes": 0.0})
    for r in rows:
        for t in r["tags"] or []:
            a = acc[t]
            a["sum"] += r["rank"] - mean
            a["n"] += 1
            a["likes"] += r["verdict"] == "like"
    for c in cs:
        f = c["factor"]
        for e in c["weights"] or []:
            a = acc[e["tag"]]
            a["sum"] += e["sum"] * f
            a["n"] += e["n"] * f
            a["likes"] += e["likes"] * f
    out = [{"tag": t, "weight": a["sum"] / (a["n"] + SHRINK), "n": round(a["n"], 1),
            "likes": round(a["likes"], 1), "dislikes": round(a["n"] - a["likes"], 1)} for t, a in acc.items()]
    out.sort(key=lambda w: w["weight"], reverse=True)
    return out, mean


def effective_swipes(profile_id):
    return len(swiped(profile_id, evidence_only=True)) + sum(c["n_listings"] * c["factor"] for c in crystals(profile_id))


def model_score(tags, wmap, mean):
    return max(0.0, min(1.0, mean + sum(wmap.get(t, 0.0) for t in tags or [])))


def blend(claude_score, m_score, n_swipes):
    share = MAX_MODEL_SHARE * min(1.0, n_swipes / FULL_TRUST_SWIPES)
    c = (claude_score if claude_score is not None else 50) / 100
    return (1 - share) * c + share * m_score


def live_query_stats(profile_id):
    """Search-term outcomes from listings not yet crystallized."""
    rows = db.q(
        "SELECT l.query, COUNT(s.listing_id) shown, SUM(CASE WHEN s.verdict='like' THEN 1 ELSE 0 END) likes, "
        "MIN(l.created_at) first_used FROM listings l LEFT JOIN swipes s ON s.listing_id=l.id "
        "WHERE l.profile_id=? AND l.query IS NOT NULL AND l.state='web' AND l.absorbed=0 "
        "GROUP BY l.query", (profile_id,))
    for r in rows:
        r["likes"] = r["likes"] or 0
    return rows


def query_stats(profile_id):
    merged = {}
    for r in live_query_stats(profile_id):
        merged[r["query"]] = dict(r)
    for c in crystals(profile_id):
        for r in c["query_stats"] or []:
            m = merged.setdefault(r["query"], {"query": r["query"], "shown": 0, "likes": 0,
                                               "first_used": r.get("first_used")})
            m["shown"] += r["shown"]
            m["likes"] += r["likes"]
            if r.get("first_used") and (m.get("first_used") is None or r["first_used"] < m["first_used"]):
                m["first_used"] = r["first_used"]
    out = sorted(merged.values(), key=lambda r: -(r.get("first_used") or 0))
    for r in out:
        r["hit_rate"] = (r["likes"] / r["shown"]) if r["shown"] else None
    return out


def groups(profile_id):
    gs = db.q("SELECT * FROM groups WHERE profile_id=? ORDER BY id", (profile_id,))
    for g in gs:
        mem = db.q("SELECT l.id, l.title, l.tags FROM group_members gm JOIN listings l ON l.id=gm.listing_id "
                   "WHERE gm.group_id=? AND l.state='web'", (g["id"],))
        g["members"] = [m["id"] for m in mem]
        g["titles"] = [m["title"] for m in mem]
        g["member_tags"] = [m["tags"] for m in mem]
    return [g for g in gs if len(g["members"]) >= 2]


def concept_traits(member_tags):
    """Traits most of a category's listings share: what the category means once its listings are gone."""
    counts = defaultdict(int)
    for tags in member_tags:
        for t in set(tags or []):
            if not t.startswith(("shape:", "condition:")):
                counts[t] += 1
    need = max(2, math.ceil(len(member_tags) / 2))
    return [t for t, n in sorted(counts.items(), key=lambda x: -x[1]) if n >= need][:5]


def concepts(profile_id):
    """Categories carried in crystals, newest first, one per label."""
    out, seen = [], set()
    for c in crystals(profile_id):
        for k in c["concepts"] or []:
            if k["label"].lower() not in seen:
                seen.add(k["label"].lower())
                out.append(k)
    return out


def context(profile):
    pid = profile["id"]
    w, mean = weights(pid)
    rows = swiped(pid)
    return {
        "weights": w,
        "mean": mean,
        "n_swipes": effective_swipes(pid),
        "liked": [r for r in rows if r["verdict"] == "like"][:6],
        "disliked": [r for r in reversed(rows) if r["verdict"] == "dislike"][:6],
        "groups": groups(pid),
        "concepts": concepts(pid)[:6],
        "query_stats": query_stats(pid),
    }


def batch_stats(profile_id, batch_id):
    rows = swiped(profile_id, batch_id)
    if not rows:
        return None
    hits = sum(((r["predicted"] or 0.5) >= 0.5) == (r["verdict"] == "like") for r in rows)
    likes = sum(r["verdict"] == "like" for r in rows)
    per_query = defaultdict(lambda: {"n": 0, "likes": 0})
    for r in rows:
        q = per_query[r["query"]]
        q["n"] += 1
        q["likes"] += r["verdict"] == "like"
    return {"shown": len(rows), "likes": likes, "accuracy": hits / len(rows), "like_rate": likes / len(rows),
            "error": sum(abs((r["predicted"] or 0.5) - r["rank"]) for r in rows) / len(rows),
            "per_query": [{"query": k, **v} for k, v in per_query.items()]}


def batch_accuracy(profile_id):
    """Per finished batch: how often the pre-swipe prediction matched your swipe."""
    out = []
    for b in db.q("SELECT id, number, stats FROM batches WHERE profile_id=? AND status='done' ORDER BY number",
                  (profile_id,)):
        st = b["stats"] or batch_stats(profile_id, b["id"])
        if not st:
            continue
        out.append({"batch": b["number"], "accuracy": st["accuracy"], "like_rate": st["like_rate"],
                    "error": st["error"], "n": st["shown"]})
    return out


def _jaccard(a, b):
    a, b = set(a or []), set(b or [])
    return len(a & b) / len(a | b) if a and b else 0.0


def graph(profile_id, batch_id=None):
    rows = swiped(profile_id, batch_id)
    w, _ = weights(profile_id)
    wmap = {x["tag"]: x for x in w}
    ids = {r["id"] for r in rows}
    # only categories with at least two listings in this view get drawn; members outside it are dropped
    gs = []
    for g in groups(profile_id):
        present = [m for m in g["members"] if m in ids]
        if len(present) >= 2:
            gs.append({**g, "members": present})
    member_of = defaultdict(list)
    for g in gs:
        for m in g["members"]:
            member_of[m].append(g["id"])

    nodes = [{
        "id": r["id"], "title": r["title"], "price": r["price"], "price_text": r["price_text"],
        "rank": r["rank"], "verdict": r["verdict"], "thumb": (r["photos"] or [None])[0],
        "tags": r["tags"], "groups": member_of.get(r["id"], []), "batch_id": r["batch_id"],
        "keeper": bool(r["keeper"]), "carried": bool(r["absorbed"]),
    } for r in rows]

    links, seen = [], set()
    # shared-trait links: each node keeps its few strongest neighbours
    for n in nodes:
        sims = sorted(((_jaccard(n["tags"], o["tags"]), o) for o in nodes if o["id"] != n["id"]),
                      key=lambda x: -x[0])[:3]
        for s, o in sims:
            key = tuple(sorted((n["id"], o["id"])))
            if s >= 0.25 and key not in seen:
                seen.add(key)
                shared = sorted(set(n["tags"]) & set(o["tags"]),
                                key=lambda t: -abs(wmap.get(t, {}).get("weight", 0)))
                links.append({"source": key[0], "target": key[1], "kind": "trait", "strength": s,
                              "value": (n["rank"] + o["rank"]) / 2, "shared": shared[:3]})
    # your own categories bind tighter
    for g in gs:
        mem = [m for m in g["members"] if m in ids]
        for a, b in combinations(mem, 2):
            key = tuple(sorted((a, b)))
            links.append({"source": key[0], "target": key[1], "kind": "group", "strength": 1.0,
                          "group": g["id"],
                          "value": sum(n["rank"] for n in nodes if n["id"] in key) / 2})

    # auto clusters for the zoomed-out view: traits that clearly sway you
    clusters = []
    for t in w:
        if t["tag"].split(":")[0] in ("shape", "condition"):
            continue
        members = [n["id"] for n in nodes if t["tag"] in (n["tags"] or [])]
        if len(members) >= 2 and abs(t["weight"]) >= 0.04:
            clusters.append({"label": t["tag"].split(":", 1)[1], "tag": t["tag"], "weight": t["weight"],
                             "members": members})
    clusters.sort(key=lambda c: -abs(c["weight"]))
    latest = db.q1("SELECT number, landmarks FROM crystals WHERE profile_id=? ORDER BY number DESC LIMIT 1",
                   (profile_id,))
    return {"nodes": nodes, "links": links, "clusters": clusters[:8],
            "groups": [{"id": g["id"], "label": g["label"], "members": g["members"]} for g in gs],
            "landmarks": (latest or {}).get("landmarks") or [] if not batch_id else []}
