"""Claude API spend: priced from the token counts the API reports on every call, per person, per week.

Prices are USD per million tokens (Claude API pricing page, checked Oct 2026). Override with
KINDLING_PRICES, e.g. '{"claude-sonnet-5-5": [2, 10]}', if they change or you switch models.
"""
import contextvars
import datetime as dt
import json
import os

from . import db
from .log import log

PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
HAIKU_LONG = (0.50, 2.50)  # Haiku 5.5 prompts over 100k tokens
try:
    PRICES.update({k: tuple(v) for k, v in json.loads(os.getenv("KINDLING_PRICES", "{}")).items()})
except (ValueError, TypeError):
    log.warning("KINDLING_PRICES isn't valid JSON; using built-in prices")

# who the Claude calls in the current task are for: (user_id, batch_id)
billing = contextvars.ContextVar("billing", default=(None, None))


class OverBudget(Exception):
    pass


def price(model, input_tokens, output_tokens):
    rate = PRICES.get(model)
    if model == "claude-haiku-5-5" and input_tokens > 100_000:
        rate = HAIKU_LONG
    if not rate:
        log.warning("no price known for model %s; billing at Sonnet 5.5 rates", model)
        rate = PRICES["claude-sonnet-5-5"]
    return (input_tokens * rate[0] + output_tokens * rate[1]) / 1_000_000


def record(model, usage, label=""):
    user_id, batch_id = billing.get()
    if not user_id or not usage:
        return 0.0
    inp = int(usage.get("input_tokens") or 0) + int(usage.get("cache_creation_input_tokens") or 0) \
        + int(usage.get("cache_read_input_tokens") or 0)
    out = int(usage.get("output_tokens") or 0)
    cost = price(model, inp, out)
    db.ex("INSERT INTO usage (user_id, batch_id, label, model, input_tokens, output_tokens, cost, at) "
          "VALUES (?,?,?,?,?,?,?,?)", (user_id, batch_id, label[:80], model, inp, out, cost, db.now()))
    return cost


def week_start(now=None):
    """Weeks reset Monday 00:00, server local time."""
    now = now or dt.datetime.now()
    monday = (now - dt.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday


def spent(user_id, since=None):
    since = since or week_start()
    return db.q1("SELECT COALESCE(SUM(cost), 0) c FROM usage WHERE user_id=? AND at>=?",
                 (user_id, since.timestamp()))["c"]


def budget(user):
    cap = user.get("claude_cap")
    used = spent(user["id"])
    resets = week_start() + dt.timedelta(days=7)
    return {"cap": cap, "spent": round(used, 4), "left": None if cap is None else max(0.0, round(cap - used, 4)),
            "over": cap is not None and used >= cap, "resets_at": resets.timestamp(),
            "resets_label": resets.strftime("%a %b %-d")}


def check(user_id=None):
    """Raise OverBudget if the billed person has used up this week's Claude budget."""
    uid = user_id or billing.get()[0]
    if not uid:
        return
    u = db.q1("SELECT * FROM users WHERE id=?", (uid,))
    if u and u["claude_cap"] is not None and spent(uid) >= u["claude_cap"]:
        raise OverBudget(f"This week's ${u['claude_cap']:.2f} of Claude is used up")
