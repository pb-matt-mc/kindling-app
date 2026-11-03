from app import checklist as ck

CRIT = ["Rolled arms", "Under 84 in", "No pet hair"]


def ans(*statuses):
    return [{"item": c, "status": s, "note": ""} for c, s in zip(CRIT, statuses)]


def test_must_have_no_drops():
    e = ck.effect(CRIT, ["Rolled arms"], ans("no", "yes", "yes"))
    assert e["drop"] == ["Rolled arms"] and e["nos"] == 0


def test_soft_no_penalizes_each_up_to_the_cap():
    assert ck.effect(CRIT, [], ans("no", "yes", "yes"))["penalty"] == ck.SOFT_NO_PENALTY
    assert ck.effect(CRIT, [], ans("no", "no", "no"))["penalty"] == ck.MAX_PENALTY
    many = [{"item": f"x{i}", "status": "no"} for i in range(10)]
    assert ck.effect([], [], many)["penalty"] == ck.MAX_PENALTY


def test_unsure_and_yes_never_count_against():
    e = ck.effect(CRIT, ["Rolled arms", "Under 84 in"], ans("unsure", "yes", "yes"))
    assert e == {"drop": [], "nos": 0, "penalty": 0}


def test_matching_ignores_case_and_spacing():
    e = ck.effect(["Rolled  Arms"], ["rolled arms"], [{"item": "rolled arms", "status": "no"}])
    assert e["drop"]


def test_answers_in_a_different_count_match_by_text():
    answers = [{"item": "under 84 in", "status": "no"}, {"item": "Color", "status": "no"}]
    e = ck.effect(CRIT, ["Under 84 in"], answers)
    assert e["drop"] == ["Under 84 in"] and e["nos"] == 1


def test_no_checklist_set_means_no_effect():
    assert ck.effect([], [], [{"item": "Color", "status": "no"}])["drop"] == []


def test_missing_checklist_is_fine():
    assert ck.effect(CRIT, ["Rolled arms"], None) == {"drop": [], "nos": 0, "penalty": 0}
