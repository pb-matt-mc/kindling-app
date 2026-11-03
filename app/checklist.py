"""What a hunt's checklist answers do to a listing.

Each checklist item the person wrote can be flagged "must have". Claude answers every item for every
listing with yes, no or unsure.
  * a "no" on a must-have item removes the listing from the batch
  * a "no" on any other item only lowers its predicted rating (SOFT_NO_PENALTY each, at most MAX_PENALTY)
  * "unsure" never counts against a listing: Claude couldn't tell from the photos and text
"""
SOFT_NO_PENALTY = 0.06
MAX_PENALTY = 0.18


def _norm(s):
    return " ".join(str(s or "").lower().split())


def pair(criteria, checklist):
    """[(criterion text or the answer's own label, answer dict)]. Claude is asked for one answer per item in
    the same order, so equal lengths pair by position; otherwise pair by matching text."""
    crit = [c for c in criteria or []]
    if crit and len(crit) == len(checklist):
        return list(zip(crit, checklist))
    out = []
    for a in checklist:
        label = _norm(a.get("item"))
        match = next((c for c in crit if _norm(c) == label or (label and (_norm(c) in label or label in _norm(c)))), None)
        out.append((match if match is not None else a.get("item") or "", a))
    return out


def effect(criteria, must_have, checklist):
    """-> {"drop": [must-have items answered no], "nos": soft "no" count, "penalty": amount to subtract from predicted}"""
    must = {_norm(m) for m in must_have or []}
    drop, nos = [], 0
    for text, ans in pair(criteria, checklist or []):
        if ans.get("status") != "no":
            continue
        if _norm(text) in must:
            drop.append(text)
        else:
            nos += 1
    return {"drop": drop, "nos": nos, "penalty": min(MAX_PENALTY, SOFT_NO_PENALTY * nos)}
