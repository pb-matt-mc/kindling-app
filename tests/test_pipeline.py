"""Characterization of the batch pipeline through the mock source, including the four defects
confirmed during review. The defect tests are strict xfails: Phase 1 fixes them and must
delete the marker, so the suite cannot silently stay green with the bug still there."""
import asyncio
import json

import pytest

from app import brain, config, db, pipeline
from app.sources import Mock, SourceError


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def build(profile, size=8, weirdness=0, modifiers=None):
    bid = db.ex("INSERT INTO batches (profile_id, number, status, size, weirdness, modifiers, created_at) "
                "VALUES (?,?,?,?,?,?,?)", (profile["id"], 1, "queued", size, weirdness, db.dumps(modifiers or []), db.now()))
    run(pipeline.build(bid))
    return db.q1("SELECT * FROM batches WHERE id=?", (bid,))


@pytest.fixture
def profile(admin):
    p = db.active_profile(admin["id"])
    db.ex("UPDATE profiles SET hunt=?, max_price=NULL, min_price=NULL WHERE id=?", ("mid-century couch", p["id"]))
    return db.q1("SELECT * FROM profiles WHERE id=?", (p["id"],))


def test_batch_reaches_ready_with_requested_size_and_photos(profile):
    b = build(profile, size=8)
    assert b["status"] == "ready", b["error"]
    ls = db.q("SELECT * FROM listings WHERE batch_id=?", (b["id"],))
    assert len(ls) == 8 and all(l["photos"] for l in ls)
    assert all(l["predicted"] is not None and l["take"] for l in ls)


def test_listings_are_unique_and_never_repeat_across_batches(profile):
    b1 = build(profile, size=8)
    b2 = build(profile, size=8)
    ids1 = {l["fb_id"] for l in db.q("SELECT fb_id FROM listings WHERE batch_id=?", (b1["id"],))}
    ids2 = {l["fb_id"] for l in db.q("SELECT fb_id FROM listings WHERE batch_id=?", (b2["id"],))}
    assert not ids1 & ids2


def test_exclude_rule_keeps_the_word_out(profile):
    b = build(profile, size=8, modifiers=["-velvet"])
    assert b["status"] == "ready"
    for l in db.q("SELECT title, description FROM listings WHERE batch_id=?", (b["id"],)):
        assert "velvet" not in (l["title"] + l["description"]).lower()


def test_price_rule_is_hard(profile):
    b = build(profile, size=6, modifiers=["$300"])
    assert b["status"] == "ready"
    assert all(l["price"] < 300 for l in db.q("SELECT price FROM listings WHERE batch_id=?", (b["id"],)))


def test_failed_batch_does_not_burn_seen(profile, monkeypatch):
    async def boom(*a, **k):
        raise brain.BrainError("down")
    monkeypatch.setattr(brain, "screen", boom)
    b = build(profile)
    assert b["status"] == "error"
    assert db.q1("SELECT COUNT(*) n FROM seen WHERE profile_id=?", (profile["id"],))["n"] == 0


def test_explore_share_follows_weirdness(profile):
    b = build(profile, size=10, weirdness=100)
    n = db.q1("SELECT COUNT(*) n FROM listings WHERE batch_id=? AND explore=1", (b["id"],))["n"]
    assert n >= 4  # 5% + 45% of 10, rounded


# ---- the four defects confirmed during review, fixed in Phase 1 ----------------------

def shown_ids(batch):
    return {l["fb_id"] for l in db.q("SELECT fb_id FROM listings WHERE batch_id=?", (batch["id"],))}


def test_unpicked_good_listings_are_not_marked_seen(profile):
    """Defect 4: only listings put in a batch are remembered, so the rest stay eligible."""
    b = build(profile, size=6)
    seen = {r["fb_id"] for r in db.q("SELECT fb_id FROM seen WHERE profile_id=? AND state='shown'", (profile["id"],))}
    assert seen == shown_ids(b)


def test_unpicked_listings_can_appear_in_a_later_batch(profile):
    b1 = build(profile, size=4)
    b2 = build(profile, size=4)
    again = shown_ids(b2) - shown_ids(b1)
    assert again and not shown_ids(b1) & shown_ids(b2)
    unmarked = {r["fb_id"] for r in db.q("SELECT fb_id FROM seen WHERE state='shown'")}
    assert unmarked == shown_ids(b1) | shown_ids(b2)


def _fixed_terms_and_spy(monkeypatch):
    async def plan(*a, **k):
        return ["couch"]
    monkeypatch.setattr(brain, "plan_queries", plan)
    sent = []
    real = brain.screen

    async def spy(p, ctx, cands):
        sent.append({c["key"] for c in cands})
        return await real(p, ctx, cands)
    monkeypatch.setattr(brain, "screen", spy)
    return sent


def test_misfits_are_remembered_for_a_while_then_retried(profile, monkeypatch):
    sent = _fixed_terms_and_spy(monkeypatch)
    b1 = build(profile, size=4)
    assert db.q("SELECT 1 FROM seen WHERE state='rejected'")  # the mock mixes in unrelated junk the fit gate rejects
    skipped = sent[0] - shown_ids(b1)
    now = db.now()
    for fb in skipped:  # treat every screened-but-not-shown listing as recently judged a misfit
        db.ex("INSERT OR REPLACE INTO seen (profile_id, fb_id, state, at) VALUES (?,?,'rejected',?)", (profile["id"], fb, now))
    build(profile, size=4)
    assert not sent[1] & skipped                       # recently rejected: not screened again
    db.ex("UPDATE seen SET at=? WHERE state='rejected'", (now - (pipeline.REJECT_DAYS + 1) * 86400,))
    build(profile, size=4)
    assert sent[2] & skipped                           # expired: eligible again


def test_failed_batch_remembers_nothing(profile, monkeypatch):
    async def boom(*a, **k):
        raise brain.BrainError("down")
    monkeypatch.setattr(brain, "deep_score", boom)
    async def lethal(*a, **k):
        raise SourceError("closed")
    monkeypatch.setattr(Mock, "items", lethal)
    b = build(profile)
    assert b["status"] == "error"
    assert db.q1("SELECT COUNT(*) n FROM seen")["n"] == 0 and db.q1("SELECT COUNT(*) n FROM predictions")["n"] == 0


def test_every_search_term_gets_screening_slots(profile, monkeypatch):
    """Defect 3: terms take turns, so the last term is never starved by the 45-candidate cap."""
    queries = ["couch one", "couch two", "couch three"]

    async def plan(*a, **k):
        return queries
    monkeypatch.setattr(brain, "plan_queries", plan)
    sent = []
    real = brain.screen

    async def spy(p, ctx, cands):
        sent.extend(c["key"] for c in cands)
        return await real(p, ctx, cands)
    monkeypatch.setattr(brain, "screen", spy)
    build(profile, size=6)
    terms = {}
    for q in queries:
        found, _, _ = run(Mock().search(profile, q, None))
        terms.update({l["fb_id"]: q for l in found})
    per_term = {q: sum(1 for k in sent if terms.get(k) == q) for q in queries}
    assert all(n >= 10 for n in per_term.values()), per_term
    assert max(per_term.values()) - min(per_term.values()) <= 2, per_term


def _score_by_id(listing):
    import hashlib
    return int(hashlib.md5(listing["fb_id"].encode()).hexdigest()[:4], 16) / 65535 * 100


def test_closer_look_decides_who_is_shown(profile, monkeypatch):
    """Defect 1: more listings get the closer look than the batch holds, and the best by that look are shown."""
    real = brain.deep_score
    looked = {}

    async def scored(p, ctx, listing, imgs):
        out = await real(p, ctx, listing, imgs)
        out["score"] = _score_by_id(listing)
        looked[listing["fb_id"]] = out["score"]
        return out
    monkeypatch.setattr(brain, "deep_score", scored)
    b = build(profile, size=6)
    assert b["status"] == "ready"
    assert len(looked) >= 9                       # 1.5x the batch
    regular = db.q("SELECT fb_id, claude_score FROM listings WHERE batch_id=? AND explore=0", (b["id"],))
    cutoff = min(r["claude_score"] for r in regular)
    comets = {r["fb_id"] for r in db.q("SELECT fb_id FROM listings WHERE batch_id=? AND explore=1", (b["id"],))}
    better_left_out = [i for i, s in looked.items() if s > cutoff and i not in shown_ids(b) and i not in comets]
    assert better_left_out == []


def test_comets_keep_their_slots_whatever_they_score(profile, monkeypatch):
    real = brain.deep_score

    async def scored(p, ctx, listing, imgs):
        out = await real(p, ctx, listing, imgs)
        out["score"] = 1.0
        return out
    monkeypatch.setattr(brain, "deep_score", scored)
    b = build(profile, size=8, weirdness=100)
    n = db.q1("SELECT COUNT(*) n FROM listings WHERE batch_id=? AND explore=1", (b["id"],))["n"]
    assert n >= 4


def test_every_shown_listing_has_a_locked_prediction(profile):
    b = build(profile, size=6)
    ls = db.q("SELECT l.id, l.predicted FROM listings l WHERE l.batch_id=?", (b["id"],))
    preds = {p["listing_id"]: p for p in db.q("SELECT * FROM predictions WHERE batch_id=?", (b["id"],))}
    assert set(preds) == {l["id"] for l in ls}
    assert all(abs(preds[l["id"]]["predicted"] - l["predicted"]) < 1e-9 for l in ls)


def _checklist_brain(monkeypatch, answers):
    real = brain.deep_score

    async def deep(p, ctx, listing, imgs):
        out = await real(p, ctx, listing, imgs)
        out["checklist"] = answers(listing)
        out["score"] = 80
        return out
    monkeypatch.setattr(brain, "deep_score", deep)


def _flag(listing):
    return int(__import__("hashlib").md5(listing["fb_id"].encode()).hexdigest()[-1], 16) % 2


def test_must_have_no_removes_the_listing(profile, monkeypatch):
    _checklist_brain(monkeypatch, lambda l: [{"item": "Rolled arms", "status": "no" if _flag(l) else "yes", "note": ""},
                                             {"item": "Under 84 in", "status": "yes", "note": ""}])
    db.ex("UPDATE profiles SET criteria=?, must_have=? WHERE id=?",
          (db.dumps(["Rolled arms", "Under 84 in"]), db.dumps(["Rolled arms"]), profile["id"]))
    profile = db.q1("SELECT * FROM profiles WHERE id=?", (profile["id"],))
    b = build(profile, size=6)
    assert b["status"] == "ready"
    for l in db.q("SELECT fb_id, checklist FROM listings WHERE batch_id=?", (b["id"],)):
        assert l["checklist"][0]["status"] == "yes"


def test_soft_no_lowers_prediction_but_keeps_the_listing(profile, monkeypatch):
    _checklist_brain(monkeypatch, lambda l: [{"item": "Rolled arms", "status": "no", "note": ""},
                                             {"item": "Under 84 in", "status": "yes", "note": ""}])
    db.ex("UPDATE profiles SET criteria=?, must_have=? WHERE id=?",
          (db.dumps(["Rolled arms", "Under 84 in"]), db.dumps([]), profile["id"]))
    profile = db.q1("SELECT * FROM profiles WHERE id=?", (profile["id"],))
    b = build(profile, size=6)
    ls = db.q("SELECT predicted FROM listings WHERE batch_id=?", (b["id"],))
    assert len(ls) == 6
    assert all(abs(l["predicted"] - (0.8 - 0.06)) < 1e-9 for l in ls)       # no history yet: Claude's 80, minus one soft no
    assert {p["checklist_nos"] for p in db.q("SELECT checklist_nos FROM predictions")} == {1}


def test_all_must_haves_failing_explains_why(profile, monkeypatch):
    _checklist_brain(monkeypatch, lambda l: [{"item": "Rolled arms", "status": "no", "note": ""}])
    db.ex("UPDATE profiles SET criteria=?, must_have=? WHERE id=?", (db.dumps(["Rolled arms"]), db.dumps(["Rolled arms"]), profile["id"]))
    profile = db.q1("SELECT * FROM profiles WHERE id=?", (profile["id"],))
    b = build(profile, size=6)
    assert b["status"] == "error" and "must-have" in b["error"]


def test_default_hunt_is_unaffected_by_the_checklist(profile, monkeypatch):
    """No criteria and no must-haves: an item answered no changes nothing, as before."""
    _checklist_brain(monkeypatch, lambda l: [{"item": "Color", "status": "no", "note": ""}])
    b = build(profile, size=6)
    assert len(shown_ids(b)) == 6
