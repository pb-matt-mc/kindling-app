from app import dupes


def L(title, price, loc="Philly", ph=None):
    return {"title": title, "price": price, "location_text": loc, "phash": ph}


def test_same_photo_and_price_is_a_repost():
    kept, n = dupes.collapse([L("Green sofa", 200, ph="0" * 16), L("Sofa for sale", 205, ph="0" * 15 + "1")])
    assert n == 1 and len(kept) == 1


def test_cheaper_copy_wins():
    kept, _ = dupes.collapse([L("Big green velvet sofa", 300, ph="0" * 16), L("Big green velvet sofa", 280, ph="0" * 16)])
    assert len(kept) == 1 and kept[0]["price"] == 280


def test_without_a_photo_a_price_drop_is_not_a_repost():
    kept, n = dupes.collapse([L("Big green velvet sofa", 300), L("Big green velvet sofa", 250)])
    assert n == 0 and len(kept) == 2


def test_different_items_survive():
    kept, n = dupes.collapse([L("Green velvet sofa", 300, ph="0" * 16), L("Oak table", 300, ph="f" * 16)])
    assert n == 0 and len(kept) == 2


def test_repost_of_earlier_shown_is_dropped():
    earlier = [dupes.sig(L("Big green velvet sofa", 250))]
    kept, n = dupes.collapse([L("Big green velvet sofa", 250)], earlier)
    assert kept == [] and n == 1


def test_short_titles_need_more_than_a_title_match():
    kept, n = dupes.collapse([L("Sofa", 100), L("Sofa", 100)])
    assert n == 0  # title under 12 chars isn't enough alone
