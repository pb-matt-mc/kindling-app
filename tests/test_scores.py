import json

import pytest

from app import db, scores


def pid(admin):
    return db.active_profile(admin["id"])["id"]


def check(p, n, gap, base=1000):
    for i in range(n):
        lid = db.ex("INSERT INTO listings (profile_id, batch_id, fb_id, created_at) VALUES (?,?,?,?)", (p, 1, f"c{base}{i}{gap}", db.now()))
        db.ex("INSERT INTO predictions (listing_id, profile_id, batch_id, predicted, created_at, checked_at, actual_rating, gap) "
              "VALUES (?,?,?,?,?,?,?,?)", (lid, p, 1, .5, db.now(), base + i, .5 + gap, gap))


def place(p, guess_share, n=1, kind="first", origin="placed", r=0.4, known=1):
    for _ in range(n):
        lid = db.ex("INSERT INTO listings (profile_id, batch_id, fb_id, created_at) VALUES (?,?,?,?)", (p, 1, f"p{db.now()}{_}{guess_share}", db.now()))
        reasons = {"price": 1 - guess_share, "right": 0, "guess": guess_share, "wrong": 0}
        db.ex("INSERT INTO placements (listing_id, profile_id, kind, origin, r, theta, rating, reasons, reason_known, created_at) "
              "VALUES (?,?,?,?,?,?,?,?,?,?)", (lid, p, kind, origin, r, 1.0, .6, db.dumps(reasons), known, db.now()))


def test_still_learning_until_enough_checks(admin):
    p = pid(admin)
    assert scores.confidence(p) == {"state": "learning", "n": 0, "needed": 5}
    check(p, 4, 0.1)
    assert scores.confidence(p)["state"] == "learning"


def test_confidence_is_one_minus_the_typical_gap(admin):
    p = pid(admin)
    check(p, 12, 0.10)
    c = scores.confidence(p)
    assert c["state"] == "ready" and c["value"] == pytest.approx(0.90, abs=1e-6) and c["n"] == 12


def test_a_noisy_early_score_is_not_shown_as_a_fact(admin):
    p = pid(admin)
    for i, g in enumerate([0.02, 0.5, 0.05, 0.6, 0.0, 0.45]):
        check(p, 1, g, base=2000 + i)
    c = scores.confidence(p)
    assert c["state"] == "learning" and c["half_width"] > scores.MAX_HALF_WIDTH


def test_recent_checks_count_more(admin):
    p = pid(admin)
    check(p, 15, 0.40, base=1)          # old and poor
    check(p, 15, 0.05, base=100)        # recent and good
    assert scores.confidence(p)["value"] > 0.80


def test_only_the_latest_window_counts(admin):
    p = pid(admin)
    check(p, 40, 0.9, base=1)
    check(p, 30, 0.1, base=1000)
    assert scores.confidence(p)["value"] == pytest.approx(0.9, abs=1e-6)


def test_checks_are_per_system(admin, make_user):
    other = db.q1("SELECT id FROM profiles WHERE user_id=?", (make_user()["id"],))["id"]
    check(pid(admin), 10, 0.1)
    assert scores.confidence(other)["state"] == "learning"


def test_unchecked_predictions_never_count(admin):
    p = pid(admin)
    for i in range(10):
        lid = db.ex("INSERT INTO listings (profile_id, batch_id, fb_id, created_at) VALUES (?,?,?,?)", (p, 1, f"u{i}", db.now()))
        db.ex("INSERT INTO predictions (listing_id, profile_id, batch_id, predicted, created_at) VALUES (?,?,?,?,?)", (lid, p, 1, .5, db.now()))
    assert scores.confidence(p)["n"] == 0


def test_wild_card_rate_counts_placements_toward_the_guess(admin):
    p = pid(admin)
    place(p, 0.9, n=6)
    place(p, 0.1, n=4)
    w = scores.wild_card_rate(p)
    assert w["state"] == "ready" and w["n"] == 10 and w["half_width"] > 0.15   # shown, with its wide interval
    place(p, 0.9, n=20)
    place(p, 0.1, n=10)
    w = scores.wild_card_rate(p)
    assert w["state"] == "ready" and 0.4 < w["value"] < 0.8 and w["half_width"] < 0.25


def test_wild_card_ignores_moves_rockets_migrated_unknown_and_the_sun(admin):
    p = pid(admin)
    place(p, 1.0, n=10, kind="move")
    place(p, 1.0, n=10, kind="rocket")
    place(p, 1.0, n=10, origin="migrated", known=0)
    place(p, 1.0, n=10, r=0.05)
    assert scores.wild_card_rate(p) == {"state": "learning", "n": 0, "needed": scores.WILD_MIN}


def test_the_two_scores_cannot_influence_each_other(admin):
    p = pid(admin)
    check(p, 12, 0.2)
    before = scores.confidence(p)
    place(p, 1.0, n=30)
    place(p, 0.0, n=30)
    assert scores.confidence(p) == before
    wc = scores.wild_card_rate(p)
    check(p, 20, 0.0, base=5000)
    assert scores.wild_card_rate(p) == wc
