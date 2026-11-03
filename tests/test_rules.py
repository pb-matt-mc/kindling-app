import pytest
from app import rules


def test_parse_splits_rule_kinds():
    r = rules.parse(["-used", "!leather", "$750", "+$100", "velvet", "  ", "$1k"])
    assert r["exclude"] == ["used"] and r["nots"] == ["leather"] and r["soft"] == ["velvet"]
    assert r["under"] == 750 and r["over"] == 100  # "$1k" is looser than $750, tightest wins


def test_parse_money_forms():
    assert rules.parse(["$1,250"])["under"] == 1250
    assert rules.parse(["+$2k"])["over"] == 2000
    assert rules.parse(["$99.5"])["under"] == 99.5


@pytest.mark.parametrize("price,ok", [(749, True), (750, False), (100, False), (101, True), (None, False)])
def test_price_ok_bounds_are_strict(price, ok):
    assert rules.price_ok(price, rules.parse(["$750", "+$100"])) is ok


def test_price_ok_without_rules_allows_missing_price():
    assert rules.price_ok(None, rules.parse([])) is True


def test_mentions_whole_word_and_hyphen_variants():
    r = rules.parse(["-pet hair", "-used"])
    assert rules.mentions("Some pet-hair on it", r) == ["pet hair"]
    assert rules.mentions("unused cushions", r) == []  # not a whole word
    assert rules.mentions("Used once", r) == ["used"]


def test_search_prices_takes_tightest():
    lo, hi = rules.search_prices({"min_price": 50, "max_price": 900}, rules.parse(["$750", "+$100"]))
    assert (lo, hi) == (100, 750)


def test_describe_is_plain_english():
    d = rules.describe(rules.parse(["-used", "!leather", "$750"]))
    assert 'must not mention "used"' in d[0] and "must not be leather" in d[1] and "under $750" in d[2]
