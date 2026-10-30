"""Spending page: Claude dollars (priced per call in costs.py) and ScrapeCreators credits, per person."""
import datetime as dt
import time

import httpx

from . import config, costs, db
from .log import log

WEEKS = 8
_balance_cache = {"at": 0.0, "value": None}


def _my_profiles(user_id):
    return {r["id"]: r["name"] for r in db.q("SELECT id, name FROM profiles WHERE user_id=?", (user_id,))}


def _credits(pids, since=0.0):
    if not pids:
        return 0
    marks = ",".join("?" * len(pids))
    return db.q1(f"SELECT COALESCE(SUM(credits_used),0) c FROM batches WHERE profile_id IN ({marks}) AND created_at>=?",
                 (*pids, since))["c"]


def _claude(user_id, since=0.0):
    return db.q1("SELECT COALESCE(SUM(cost),0) c FROM usage WHERE user_id=? AND at>=?", (user_id, since))["c"]


def summary(user):
    uid = user["id"]
    profiles = _my_profiles(uid)
    pids = list(profiles)
    week = costs.week_start()
    month = (dt.datetime.now() - dt.timedelta(days=30)).timestamp()

    def window(since):
        return {"claude": round(_claude(uid, since), 4), "credits": _credits(pids, since)}

    # last few weeks, oldest first, Monday-to-Monday like the budget
    series = []
    for i in range(WEEKS - 1, -1, -1):
        start = week - dt.timedelta(days=7 * i)
        end = start + dt.timedelta(days=7)
        s, e = start.timestamp(), end.timestamp()
        cr = 0
        if pids:
            marks = ",".join("?" * len(pids))
            cr = db.q1(f"SELECT COALESCE(SUM(credits_used),0) c FROM batches WHERE profile_id IN ({marks}) "
                       f"AND created_at>=? AND created_at<?", (*pids, s, e))["c"]
        cl = db.q1("SELECT COALESCE(SUM(cost),0) c FROM usage WHERE user_id=? AND at>=? AND at<?", (uid, s, e))["c"]
        series.append({"label": start.strftime("%b %-d"), "claude": round(cl, 4), "credits": cr})

    by_hunt = []
    for pid, name in profiles.items():
        cl = db.q1("SELECT COALESCE(SUM(u.cost),0) c FROM usage u JOIN batches b ON b.id=u.batch_id "
                   "WHERE u.user_id=? AND b.profile_id=?", (uid, pid))["c"]
        cr = _credits([pid])
        n = db.q1("SELECT COUNT(*) n FROM batches WHERE profile_id=?", (pid,))["n"]
        if cl or cr or n:
            by_hunt.append({"name": name, "claude": round(cl, 4), "credits": cr, "batches": n})
    by_hunt.sort(key=lambda h: (-h["claude"], -h["credits"]))

    by_model = [{"model": r["model"], "cost": round(r["c"], 4), "calls": r["n"],
                 "input_tokens": r["i"], "output_tokens": r["o"]}
                for r in db.q("SELECT model, SUM(cost) c, COUNT(*) n, SUM(input_tokens) i, SUM(output_tokens) o "
                              "FROM usage WHERE user_id=? GROUP BY model ORDER BY c DESC", (uid,))]

    done = db.q1(f"SELECT COUNT(*) n FROM batches WHERE status='done' AND profile_id IN "
                 f"({','.join('?' * len(pids)) or 'NULL'})", tuple(pids))["n"] if pids else 0
    since = db.q1("SELECT MIN(at) t FROM usage WHERE user_id=?", (uid,))["t"]
    out = {
        "budget": costs.budget(user),
        "week": window(week.timestamp()),
        "month": window(month),
        "all": window(0.0),
        "series": series,
        "by_hunt": by_hunt,
        "by_model": by_model,
        "per_batch_claude": None,
        "tracking_since": since,
    }
    if done:
        tracked = db.q1(f"SELECT COUNT(DISTINCT u.batch_id) n, COALESCE(SUM(u.cost),0) c FROM usage u "
                        f"JOIN batches b ON b.id=u.batch_id WHERE u.user_id=? AND b.status='done'", (uid,))
        if tracked["n"]:
            out["per_batch_claude"] = round(tracked["c"] / tracked["n"], 4)
    if user["role"] == "admin":
        wk = week.timestamp()
        out["everyone"] = {
            "week_claude": round(db.q1("SELECT COALESCE(SUM(cost),0) c FROM usage WHERE at>=?", (wk,))["c"], 4),
            "all_claude": round(db.q1("SELECT COALESCE(SUM(cost),0) c FROM usage")["c"], 4),
            "week_credits": db.q1("SELECT COALESCE(SUM(credits_used),0) c FROM batches WHERE created_at>=?", (wk,))["c"],
            "all_credits": db.q1("SELECT COALESCE(SUM(credits_used),0) c FROM batches")["c"],
            "people": db.q1("SELECT COUNT(*) n FROM users WHERE disabled=0")["n"],
        }
        out["scrape_balance"] = scrape_balance()
    return out


def _find_number(obj, keys=("creditCount", "credit_count", "credits", "credit_balance", "creditBalance",
                             "balance", "remaining", "credits_remaining")):
    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return v
        for v in obj.values():
            n = _find_number(v, keys)
            if n is not None:
                return n
    return None


def scrape_balance():
    """Credits left on the ScrapeCreators key, checked at most every 10 minutes. None if unknown."""
    if config.source_mode() != "scrapecreators" or not config.SCRAPECREATORS_API_KEY:
        return None
    if time.time() - _balance_cache["at"] < 600:
        return _balance_cache["value"]
    value = None
    try:
        r = httpx.get("https://api.scrapecreators.com/v1/account/credit-balance",
                      headers={"x-api-key": config.SCRAPECREATORS_API_KEY}, timeout=10)
        if r.status_code == 200:
            body = r.json()
            value = _find_number(body)
            if value is None:
                log.info("ScrapeCreators balance: couldn't find the number in a reply with keys %s",
                         list(body)[:10] if isinstance(body, dict) else type(body).__name__)
        else:
            log.warning("ScrapeCreators balance check returned HTTP %s", r.status_code)
    except (httpx.HTTPError, ValueError) as e:
        log.warning("ScrapeCreators balance check failed: %s", e)
    _balance_cache.update(at=time.time(), value=value)
    return value
