import random
import time

import pytest

from app import model
from tests.world import COLORS, MATS, STYLES, pattern_rating


def rows(n, seed=1, noise=True):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        tags = [rng.choice(STYLES), rng.choice(COLORS), rng.choice(MATS)]
        out.append({"id": i, "tags": tags, "rating": pattern_rating(tags, rng if noise else None), "reasons": None, "weight": 1.0})
    return out


def test_it_learns_the_pattern_better_than_guessing_the_average():
    train, test = rows(150, 1), rows(80, 2)
    mdl = model.TraitModel(train)
    base = sum(abs(r["rating"] - mdl.mean) for r in test) / len(test)
    err = sum(abs(r["rating"] - mdl.predict(r["tags"])) for r in test) / len(test)
    assert err < 0.55 * base, (err, base)
    assert mdl.predict(["color:green", "material:velvet", "style:rolled"]) > mdl.predict(["color:grey", "material:linen", "style:modern"]) + 0.3


def test_more_evidence_means_a_better_model():
    test = rows(80, 9)
    errs = []
    for n in (10, 40, 160):
        mdl = model.TraitModel(rows(n, 3))
        errs.append(sum(abs(r["rating"] - mdl.predict(r["tags"])) for r in test) / len(test))
    assert errs[0] > errs[1] > errs[2] * 0.95 and errs[2] < errs[0]


def test_rare_traits_are_shrunk_toward_neutral():
    data = rows(60, 4) + [{"id": 999, "tags": ["style:oneoff"], "rating": 0.99, "reasons": None, "weight": 1.0}]
    mdl = model.TraitModel(data)
    assert abs(mdl.weight("style:oneoff")) < abs(mdl.weight("color:green"))


def test_leave_one_out_residual_is_honest():
    data = rows(120, 5)
    mdl = model.TraitModel(data)
    target = {"id": 5000, "tags": ["color:green", "material:velvet", "style:modern"], "rating": 0.05, "reasons": None, "weight": 1.0}
    mdl2 = model.TraitModel(data + [target])
    assert abs(mdl2.residual(target)) > 0.3                       # a contrarian is not explained, even though it was in training
    typical = data[0]
    assert abs(mdl.residual(typical)) < 0.12                       # a typical one is
    assert sum(mdl.explained(r) for r in data) / len(data) > 0.85


def test_loo_matches_a_real_refit_without_the_row():
    data = rows(60, 6)
    i = 7
    full = model.TraitModel(data)
    without = model.TraitModel(data[:i] + data[i + 1:])
    assert full.predict(data[i]["tags"], drop=data[i]) == pytest.approx(without.predict(data[i]["tags"]), abs=1e-9)


def test_rocketed_listings_count_for_less():
    a = [{"id": i, "tags": ["x:a"], "rating": 0.9, "reasons": None, "weight": 1.0} for i in range(4)]
    b = [{"id": 10 + i, "tags": ["x:b"], "rating": 0.9, "reasons": None, "weight": 0.25} for i in range(4)]
    c = [{"id": 20 + i, "tags": ["x:c"], "rating": 0.1, "reasons": None, "weight": 1.0} for i in range(8)]
    mdl = model.TraitModel(a + b + c)
    assert mdl.weight("x:a") > mdl.weight("x:b") > 0


def test_reasons_are_learned_per_trait():
    data = []
    for i in range(30):
        data.append({"id": i, "tags": ["style:modern"], "rating": 0.3, "reasons": {"price": 0.1, "right": 0.0, "guess": 0.0, "wrong": 0.9}, "weight": 1.0})
        data.append({"id": 100 + i, "tags": ["color:green"], "rating": 0.7, "reasons": {"price": 0.9, "right": 0.1, "guess": 0.0, "wrong": 0.0}, "weight": 1.0})
    mdl = model.TraitModel(data)
    assert mdl.predict_reasons(["style:modern"])["wrong"] > 0.5
    assert mdl.predict_reasons(["color:green"])["price"] > 0.5
    assert sum(mdl.predict_reasons(["style:modern"]).values()) == pytest.approx(1.0)


def test_empty_and_tiny_datasets_do_not_crash():
    assert model.TraitModel([]).predict(["a:b"]) == 0.5
    one = model.TraitModel([{"id": 1, "tags": ["a:b"], "rating": 0.8, "reasons": None, "weight": 1.0}])
    assert 0 <= one.predict(["a:b"]) <= 1 and one.mae() >= 0


def test_training_is_cheap_enough_to_share_a_small_machine():
    big = rows(5000, 7)                 # ~10x anything the app will hold
    t = time.process_time()
    mdl = model.TraitModel(big)
    explained = sum(mdl.explained(r) for r in big)
    cpu = time.process_time() - t
    assert cpu < 1.5 and explained > 0, cpu
