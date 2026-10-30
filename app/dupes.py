"""Spot the same item posted more than once under different listing IDs.

Marketplace sellers often repost (sometimes at a new price) or list the same thing several times.
Search gives no seller info, so a repost is recognized by what it looks like:
  - the main photo is near-identical AND (the price matches or the title mostly matches), or
  - the title, price and location are all exactly the same (for listings without a usable photo).
"""
import io
import re

PHOTO_BITS = 6     # max differing bits (of 64) for two photos to count as the same picture
TITLE_SIM = 0.5    # word overlap that counts as "mostly the same title"


def phash(data):
    """64-bit difference hash of an image, as 16 hex chars. None if it can't be read."""
    if not data:
        return None
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            g = im.convert("L").resize((9, 8), Image.LANCZOS)
            px = list(g.getdata())
    except Exception:
        return None
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return f"{bits:016x}"


def _bits_apart(a, b):
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def title_key(title):
    return " ".join(re.findall(r"[a-z0-9]+", (title or "").lower()))


def _title_sim(a, b):
    wa, wb = set(a.split()), set(b.split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _price_close(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= max(5.0, 0.05 * max(a, b))


def sig(l):
    """What a listing is compared on: {phash, tkey, price, loc}."""
    return {"phash": l.get("phash"), "tkey": title_key(l.get("title")), "price": l.get("price"),
            "loc": (l.get("location_text") or "").strip().lower()}


def same_item(a, b):
    if a["phash"] and b["phash"] and _bits_apart(a["phash"], b["phash"]) <= PHOTO_BITS:
        if _price_close(a["price"], b["price"]) or _title_sim(a["tkey"], b["tkey"]) >= TITLE_SIM:
            return True
    return (len(a["tkey"]) >= 12 and a["tkey"] == b["tkey"] and a["price"] == b["price"]
            and a["loc"] == b["loc"])


def collapse(listings, earlier=()):
    """Keep one of each item, in order. A repost of something in `earlier` (sigs of what this hunt has
    already been shown) is dropped. Within the list, the cheaper copy wins.
    Returns (kept, number_dropped)."""
    earlier = list(earlier)
    kept, ksigs, dropped = [], [], 0
    for l in listings:
        s = sig(l)
        if any(same_item(s, e) for e in earlier):
            dropped += 1
            continue
        hit = next((i for i, k in enumerate(ksigs) if same_item(s, k)), None)
        if hit is None:
            kept.append(l)
            ksigs.append(s)
            continue
        dropped += 1
        old = kept[hit]
        if l.get("price") is not None and (old.get("price") is None or l["price"] < old["price"]):
            kept[hit], ksigs[hit] = l, s
    return kept, dropped
