"""Orbit's local model, trained only on the person's placements. No LLM ranks listings or decides when an event fires.

An additive trait model, small enough to refit in milliseconds: a listing's rating is the average rating plus the
shrunken pull of each of its tags, and its reasons are the average reason split plus the same kind of pull. It also
answers "could the model have explained this listing without seeing it?" with an exact leave-one-out prediction,
which is what decides what an asteroid shower may forget (explained listings go first, surprising ones stay).

Pure Python on purpose: the app shares a small machine with other services, so there is nothing here that needs more than a
few thousand multiplications.
"""
from collections import defaultdict

SHRINK = 2.0          # pseudo-count pulling rare traits toward neutral (same idea as learn.py)
AXES = ("price", "right", "guess", "wrong")


class TraitModel:
    def __init__(self, rows):
        """rows: [{id, tags, rating, reasons (dict or None), weight}]"""
        self.rows = rows
        w = [r.get("weight", 1.0) for r in rows]
        self.wsum = sum(w) or 1.0
        self.mean = sum(r["rating"] * wi for r, wi in zip(rows, w)) / self.wsum if rows else 0.5
        known = [(r, wi) for r, wi in zip(rows, w) if r.get("reasons")]
        self.rsum = sum(wi for _, wi in known)
        self.rmean = {a: (sum(r["reasons"].get(a, 0.0) * wi for r, wi in known) / self.rsum if self.rsum else 0.25) for a in AXES}
        self.s = defaultdict(float)                    # per tag: weighted sum of (rating - mean)
        self.n = defaultdict(float)                    # per tag: total weight
        self.rs = defaultdict(lambda: defaultdict(float))
        self.rn = defaultdict(float)
        for r, wi in zip(rows, w):
            for t in set(r.get("tags") or []):
                self.s[t] += (r["rating"] - self.mean) * wi
                self.n[t] += wi
                if r.get("reasons"):
                    self.rn[t] += wi
                    for a in AXES:
                        self.rs[t][a] += (r["reasons"].get(a, 0.0) - self.rmean[a]) * wi

    # -- ratings
    def _mean_without(self, drop):
        wi = drop.get("weight", 1.0)
        rest = self.wsum - wi
        return (self.wsum * self.mean - wi * drop["rating"]) / rest if rest > 1e-9 else 0.5

    def weight(self, tag, drop=None, mean2=None):
        """A trait's pull. With drop=<a training row>, exactly what a refit without that row would give."""
        s, n = self.s.get(tag, 0.0), self.n.get(tag, 0.0)
        if drop is not None:
            wi = drop.get("weight", 1.0)
            mean2 = self._mean_without(drop) if mean2 is None else mean2
            inside = tag in set(drop.get("tags") or [])
            if inside:
                s -= wi * (drop["rating"] - self.mean)
                n -= wi
            s += n * (self.mean - mean2)
        return s / (n + SHRINK) if n > -1e-9 else 0.0

    def predict(self, tags, drop=None):
        """Predicted rating. With drop=<a training row>, the model as it would be had it never seen that row."""
        base, mean2 = self.mean, None
        if drop is not None:
            mean2 = base = self._mean_without(drop)
        return max(0.0, min(1.0, base + sum(self.weight(t, drop, mean2) for t in set(tags or []))))

    def residual(self, row):
        return row["rating"] - self.predict(row.get("tags"), drop=row)

    def explained(self, row, tol=0.12):
        return abs(self.residual(row)) <= tol

    # -- reasons
    def predict_reasons(self, tags, drop=None):
        """Predicted {price,right,guess,wrong} split; with drop=<a training row>, as if the model had never seen it."""
        dr = drop["reasons"] if drop is not None and drop.get("reasons") else None
        dw = drop.get("weight", 1.0) if dr else 0.0
        rm = dict(self.rmean)
        if dr:
            rest = self.rsum - dw
            rm = {a: ((self.rsum * self.rmean[a] - dw * dr.get(a, 0.0)) / rest if rest > 1e-9 else 0.25) for a in AXES}
        out = dict(rm)
        in_tags = set(drop.get("tags") or []) if dr else set()
        for t in set(tags or []):
            s = self.rs.get(t)
            if not s:
                continue
            n = self.rn.get(t, 0.0)
            for a in AXES:
                v = s[a]
                if dr:
                    if t in in_tags:
                        v -= dw * (dr.get(a, 0.0) - self.rmean[a])
                    v += (n - (dw if t in in_tags else 0.0)) * (self.rmean[a] - rm[a])
                out[a] += v / (max(n - (dw if dr and t in in_tags else 0.0), 0.0) + SHRINK)
        tot = sum(max(0.0, v) for v in out.values()) or 1.0
        return {a: max(0.0, v) / tot for a, v in out.items()}

    def mae(self, rows=None):
        rows = rows if rows is not None else self.rows
        return sum(abs(self.residual(r)) for r in rows) / len(rows) if rows else 0.0

    def top_tags(self, n=5, sign=-1, min_n=2):
        items = [(t, self.weight(t)) for t in self.s if self.n[t] >= min_n and not t.startswith(("shape:", "condition:", "price:", "size:"))]
        items = sorted(items, key=lambda x: x[1] * sign, reverse=True)
        return [t for t, w in items if w * sign > 0][:n]


def dataset(profile_id):
    """Training rows from the active placements of one system (migrated swipes included, with unknown reasons)."""
    from . import db
    rows = db.q(
        "SELECT p.listing_id id, p.rating, p.reasons, p.weight, p.r, p.created_at, p.kind, p.origin, p.planet_id, l.tags, l.title, l.batch_id, "
        "l.keeper, l.photos FROM placements p JOIN listings l ON l.id=p.listing_id WHERE p.profile_id=? AND p.undone=0 AND p.id="
        "(SELECT MAX(id) FROM placements q WHERE q.listing_id=p.listing_id AND q.undone=0)", (profile_id,))
    for r in rows:
        r["reasons"] = r["reasons"] or None
    return rows


def jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 0.0
