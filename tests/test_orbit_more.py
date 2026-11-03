"""Binary stars, recap, export columns and Obsidian notes."""
import csv
import io
import math
from pathlib import Path

import pytest

from app import config, db, events, obsidian, orbit, orbit_math as m, scores
from tests.world import batch, listing, populate


def place(api, lid, r=0.3, theta=0.0, **kw):
    res = api.post("/api/o/place", json={"listing_id": lid, "r": r, "theta": theta, **kw})
    assert res.status_code == 200, res.text
    return res.json()


def ids(b):
    return [l["id"] for l in b["listings"]]


# ---- binary stars ----------------------------------------------------------------------------------

def sun_groups(api, ready_batch):
    a, b, c, d = ids(ready_batch)[:4]
    db.ex("UPDATE listings SET tags=? WHERE id IN (?,?)", ('["style:rolled","color:green"]', a, b))
    db.ex("UPDATE listings SET tags=? WHERE id IN (?,?)", ('["style:danish","color:tan"]', c, d))
    return [[a, b], [c, d]]


def test_a_binary_star_has_exactly_two_suns_and_never_a_third(api, ready_batch, admin):
    g = sun_groups(api, ready_batch)
    pid = db.active_profile(admin["id"])["id"]
    for grp in g:
        for lid in grp:
            place(api, lid)
    assert api.post(f"/api/o/systems/{pid}/binary", json={"names": ["Rolled", "Low Danish"], "groups": g}).status_code == 200
    assert api.post(f"/api/o/systems/{pid}/binary", json={"names": ["A", "B"], "groups": g}).status_code == 409
    st = api.get("/api/o/state").json()
    assert st["system"]["binary"]["names"] == ["Rolled", "Low Danish"]
    assert {p["id"]: p["sun"] for p in st["placed"]} == {g[0][0]: 0, g[0][1]: 0, g[1][0]: 1, g[1][1]: 1}


def test_binary_star_validation(api, ready_batch, admin):
    g = sun_groups(api, ready_batch)
    pid = db.active_profile(admin["id"])["id"]
    assert api.post(f"/api/o/systems/{pid}/binary", json={"names": ["Same", "same"], "groups": g}).status_code == 400
    assert api.post(f"/api/o/systems/{pid}/binary", json={"names": ["A"], "groups": g}).status_code == 400
    assert api.post(f"/api/o/systems/{pid}/binary", json={"names": ["A", "B"], "groups": [[1], [2], [3]]}).status_code == 400
    assert api.post(f"/api/o/systems/{pid}/binary", json={"names": ["A", "B"], "groups": [[999], [998]]}).status_code == 409
    assert api.get("/api/o/state").json()["system"]["binary"] is None


def test_claude_picks_the_starting_sun_and_locks_it_before_the_listing_is_seen(api, ready_batch, admin):
    g = sun_groups(api, ready_batch)
    pid = db.active_profile(admin["id"])["id"]
    orbit.make_binary(admin, pid, ["Rolled", "Danish"], g)
    # a fresh batch's listings: one that looks like each sun
    db.ex("UPDATE batches SET status='done'")
    b = db.ex("INSERT INTO batches (profile_id, number, status, size, created_at) VALUES (?,?,?,?,?)", (pid, 2, "ready", 2, db.now()))
    x = listing(pid, b, ["style:rolled", "color:green", "feature:z"])
    y = listing(pid, b, ["style:danish", "color:tan", "feature:q"])
    for lid in (x, y):
        db.ex("INSERT INTO predictions (listing_id, profile_id, batch_id, predicted, created_at) VALUES (?,?,?,?,?)", (lid, pid, b, .6, db.now()))
    q = {c["id"]: c for c in api.get("/api/o/state").json()["queue"]}
    assert q[x]["sun_guess"] == 0 and q[y]["sun_guess"] == 1
    db.ex("UPDATE listings SET tags='[\"style:danish\",\"color:tan\"]' WHERE id=?", (x,))     # later tag changes can't alter a locked guess
    assert {c["id"]: c["sun_guess"] for c in api.get("/api/o/state").json()["queue"]}[x] == 0


def test_the_sun_pick_is_scored_when_you_place_and_kept_apart_from_confidence(api, ready_batch, admin):
    g = sun_groups(api, ready_batch)
    pid = db.active_profile(admin["id"])["id"]
    orbit.make_binary(admin, pid, ["Rolled", "Danish"], g)
    db.ex("UPDATE batches SET status='done'")
    b = db.ex("INSERT INTO batches (profile_id, number, status, size, created_at) VALUES (?,?,?,?,?)", (pid, 2, "ready", 12, db.now()))
    lids = []
    for i in range(10):
        lid = listing(pid, b, ["style:rolled", "color:green"] if i % 2 == 0 else ["style:danish", "color:tan"])
        db.ex("INSERT INTO predictions (listing_id, profile_id, batch_id, predicted, created_at) VALUES (?,?,?,?,?)", (lid, pid, b, .6, db.now()))
        lids.append(lid)
    api.get("/api/o/state")                                      # locks the guesses
    for i, lid in enumerate(lids):
        sun = (i % 2) if i < 8 else 1 - (i % 2)                    # the person disagrees with Claude on the last two
        place(api, lid, r=m.r_from_rating(.6), sun=sun)
    p = db.q1("SELECT sun_guess, sun_actual FROM predictions WHERE listing_id=?", (lids[0],))
    assert (p["sun_guess"], p["sun_actual"]) == (0, 0)
    sp = api.get("/api/o/state").json()["scores"]
    assert sp["sun_pick"]["state"] == "ready" and sp["sun_pick"]["value"] == pytest.approx(0.8)
    assert sp["confidence"]["value"] == pytest.approx(1.0, abs=1e-6)       # rating confidence is untouched by the sun pick
    # undoing a placement un-scores its sun pick too
    last = api.get("/api/o/state").json()["last_placement"]["id"]
    api.post("/api/o/undo", json={"placement_id": last})
    assert db.q1("SELECT sun_actual FROM predictions WHERE listing_id=?", (lids[-1],))["sun_actual"] is None


def test_sun_is_ignored_outside_binary_systems(api, ready_batch):
    lid = ids(ready_batch)[0]
    place(api, lid, sun=1)
    assert orbit.current(lid)["sun"] == 0


def test_end_binary_returns_to_one_sun(api, ready_batch, admin):
    g = sun_groups(api, ready_batch)
    pid = db.active_profile(admin["id"])["id"]
    orbit.make_binary(admin, pid, ["A", "B"], g)
    assert api.delete(f"/api/o/systems/{pid}/binary").json() == {"ok": True}
    assert api.get("/api/o/state").json()["system"]["binary"] is None


# ---- recap ------------------------------------------------------------------------------------------

def test_recap_counts_verdicts_comets_and_rockets(api, ready_batch):
    pl = api.post("/api/o/planets", json={"name": "P", "orbit": "Outer"}).json()
    lids = ids(ready_batch)
    db.ex("UPDATE listings SET explore=1 WHERE id=?", (lids[0],))
    for i, lid in enumerate(lids[:4]):
        pred = db.q1("SELECT predicted FROM predictions WHERE listing_id=?", (lid,))["predicted"]
        off = (0.0, 0.1, 0.5, 0.0)[i]
        place(api, lid, r=m.r_from_rating(max(0, min(1, pred + off if pred + off <= 1 else pred - off))))
    api.post("/api/o/rocket", json={"listing_id": lids[4], "planet_id": pl["id"]})
    place(api, lids[5])
    r = api.get(f"/api/o/recap/{ready_batch['id']}").json()
    assert r["batch"]["id"] == ready_batch["id"] and len(r["items"]) == 6
    c = r["counts"]
    assert c["called"] >= 2 and c["close"] >= 1 and c["rocketed"] == 1 and c["called"] + c["close"] + c["missed"] + c["unscored"] == 6
    assert r["comets"]["n"] == 1
    assert api.get("/api/o/recap").status_code == 404                       # no finished batch yet: nothing to recap
    assert api.get("/api/o/recap/9999").status_code == 404


def test_recap_reports_the_confidence_change(api, admin):
    pid = db.active_profile(admin["id"])["id"]
    b1, b2 = batch(pid, 1, created=100), batch(pid, 2, created=200)
    for i in range(12):
        lid = listing(pid, b1, ["a:b"], rating=0.5)
        db.ex("INSERT INTO predictions (listing_id, profile_id, batch_id, predicted, created_at, checked_at, actual_rating, gap) VALUES (?,?,?,?,?,?,?,?)", (lid, pid, b1, .5, 1, 100 + i, .5, .20))
    for i in range(6):
        lid = listing(pid, b2, ["a:b"], rating=0.5)
        db.ex("INSERT INTO predictions (listing_id, profile_id, batch_id, predicted, created_at, checked_at, actual_rating, gap) VALUES (?,?,?,?,?,?,?,?)", (lid, pid, b2, .5, 1, 300 + i, .5, .02))
    r = api_recap(admin, b2)
    assert r["confidence_before"]["state"] == "ready" and r["confidence_before"]["value"] == pytest.approx(0.8, abs=0.01)
    assert r["confidence"]["value"] > r["confidence_before"]["value"]


def api_recap(user, bid):
    return orbit.recap(user, bid)


# ---- export -------------------------------------------------------------------------------------------

def test_export_keeps_the_old_columns_and_adds_orbits(api, ready_batch):
    lids = ids(ready_batch)
    pl = api.post("/api/o/planets", json={"name": "Rolled arms", "orbit": "Mid", "reason": "wrong"}).json()
    place(api, lids[0], r=0.4, theta=0.2)
    api.post("/api/o/rocket", json={"listing_id": lids[1], "planet_id": pl["id"]})
    db.ex("UPDATE listings SET avail='gone' WHERE id=?", (lids[1],))
    res = api.post("/api/export?fmt=csv", json={})
    assert res.status_code == 200
    rows = list(csv.reader(io.StringIO(res.text.lstrip("﻿"))))
    head = rows[0]
    assert head[:7] == ["Name", "Link", "Price", "Top 5 qualities", "Your ranking (0-100)", "Your call", "Claude's expected approval (%)"]
    assert head[7:] == ["Orbit", "Reasons", "Planet", "Claude's predicted rating (0-100)", "Gap (points)", "Status"]
    body = {r[0]: r for r in rows[1:]}
    first = [r for r in rows[1:] if r[7] == "Inner" or r[7] == "Mid"]
    assert any(r[9] == "Rolled arms" and r[12] == "Sold" for r in rows[1:])         # the rocketed, sold one
    assert any(r[7] in ("Inner", "Mid") and r[3] != "" and "%" in r[8] for r in rows[1:])
    assert all(len(r) == len(head) for r in rows[1:])
    assert 'filename="orbit-' in res.headers["content-disposition"]


# ---- obsidian -------------------------------------------------------------------------------------------

def test_obsidian_notes_keep_marketplace_links_and_record_the_gap(api, ready_batch, admin, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OBSIDIAN_DIR", str(tmp_path))
    lids = ids(ready_batch)
    for lid in lids:
        place(api, lid, r=0.35 if lid % 2 else 0.9)
    profile = db.active_profile(admin["id"])
    batch_row = db.q1("SELECT * FROM batches WHERE id=?", (ready_batch["id"],))
    from app import learn
    obsidian.export_batch(profile, batch_row, learn.swiped(profile["id"], ready_batch["id"]))
    note = next((tmp_path / "Batches").rglob("*.md")).read_text()
    assert "## Inside the frost line (liked)" in note and "## Outside the frost line (passed)" in note
    assert "called_it:" in note and "Confidence after this batch:" in note and "Claude guessed" in note
    assert "marketplace/item/" in note or "facebook.com" in note
    sysnote = (tmp_path / "Systems" / f"{profile['name']}.md").read_text()
    assert "Confidence:" in sysnote and "## Events" in sysnote


def test_event_lines_accumulate_in_the_system_note(admin, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OBSIDIAN_DIR", str(tmp_path))
    profile = db.active_profile(admin["id"])
    obsidian.log_event(profile, "Your sun holds two tastes", "binary")
    obsidian.log_event(profile, "Your belt is full", "forget")
    obsidian.export_system(profile)                                # a refresh must not erase the history
    txt = (tmp_path / "Systems" / f"{profile['name']}.md").read_text()
    assert "Your sun holds two tastes (binary)" in txt and "Your belt is full (forget)" in txt


def test_no_vault_configured_means_no_files(admin, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OBSIDIAN_DIR", "")
    obsidian.log_event(db.active_profile(admin["id"]), "x", "y")
    assert list(tmp_path.iterdir()) == []
