"""Per-batch rules typed into the "This batch only" field.

  -word    the word or phrase must not appear anywhere in the listing's text
  !word    the item must not BE that (Claude judges it, so "faux leather" counts as leather)
  $750     price under $750
  +$100    price over $100
  anything else is a soft preference that steers search terms and appeal
"""
import re

_MONEY = r"\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(k)?\s*"


def _amount(num, k):
    v = float(num.replace(",", ""))
    return v * 1000 if k else v


def parse(mods):
    out = {"soft": [], "exclude": [], "nots": [], "under": None, "over": None}
    for raw in mods or []:
        m = " ".join(str(raw).split())
        if not m:
            continue
        over = re.fullmatch(r"\+\$" + _MONEY, m, re.I)
        under = re.fullmatch(r"\$" + _MONEY, m, re.I)
        if over:
            v = _amount(*over.groups())
            out["over"] = v if out["over"] is None else max(out["over"], v)
        elif under:
            v = _amount(*under.groups())
            out["under"] = v if out["under"] is None else min(out["under"], v)
        elif m.startswith("-") and len(m) > 1:
            out["exclude"].append(m[1:].strip())
        elif m.startswith("!") and len(m) > 1:
            out["nots"].append(m[1:].strip())
        else:
            out["soft"].append(m)
    return out


def describe(r):
    """Plain-English hard rules, for prompts and logs."""
    parts = [f'the listing must not mention "{w}"' for w in r["exclude"]]
    parts += [f"the item must not be {w}" for w in r["nots"]]
    if r["under"] is not None:
        parts.append(f"price under ${r['under']:,.0f}")
    if r["over"] is not None:
        parts.append(f"price over ${r['over']:,.0f}")
    return parts


def search_prices(profile, r):
    """Tightest min/max to hand the listing source, so fewer out-of-range listings cost credits."""
    lo, hi = profile.get("min_price"), profile.get("max_price")
    if r["over"] is not None:
        lo = max(lo or 0, r["over"])
    if r["under"] is not None:
        hi = r["under"] if hi is None else min(hi, r["under"])
    return lo, hi


def price_ok(price, r):
    if r["under"] is None and r["over"] is None:
        return True
    if price is None:
        return False  # can't confirm it meets a price rule
    if r["under"] is not None and not price < r["under"]:
        return False
    if r["over"] is not None and not price > r["over"]:
        return False
    return True


def listing_text(l):
    bits = [l.get("title") or "", l.get("description") or "", l.get("condition") or ""]
    for a in l.get("fb_attributes") or []:
        bits.append(f"{a.get('name') or ''} {a.get('value') or ''}")
    return " ".join(bits)


def mentions(text, r):
    """Which excluded words/phrases appear in the text (whole words, any case)."""
    hits = []
    for w in r["exclude"]:
        pat = r"[\s\-_]+".join(re.escape(part) for part in w.lower().split())  # "pet hair" also catches "pet-hair"
        if re.search(r"(?<![a-z0-9])" + pat + r"(?![a-z0-9])", text.lower()):
            hits.append(w)
    return hits
