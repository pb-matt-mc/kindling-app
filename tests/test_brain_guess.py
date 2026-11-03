"""Claude's guess of what the person will dislike: parsed, trimmed, and never allowed to break a batch."""
import asyncio

from app import brain, config


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def deep(monkeypatch, reply):
    monkeypatch.setattr(config, "brain_mode", lambda: "claude")

    async def fake_call(model, content, max_tokens=1500, label="claude"):
        return reply
    monkeypatch.setattr(brain, "_call", fake_call)
    return run(brain.deep_score({"name": "Couch", "hunt": "couch", "criteria": []}, {"weights": [], "mean": .5, "n_swipes": 0, "liked": [], "disliked": [],
                                                                                      "groups": [], "concepts": [], "query_stats": []},
                                {"title": "Green sofa", "price_text": "$100", "price": 100}, []))


def test_the_guess_is_returned_and_cleaned(monkeypatch):
    out = deep(monkeypatch, {"fit": 90, "score": 70, "guess": "  Legs   look wobbly \n", "checklist": [], "take": "x", "tags": ["color:green"], "features": {}})
    assert out["guess"] == "Legs look wobbly"


def test_a_missing_or_silly_guess_never_breaks_the_listing(monkeypatch):
    assert deep(monkeypatch, {"fit": 90, "score": 70, "checklist": [], "take": "x", "tags": [], "features": {}})["guess"] == ""
    assert deep(monkeypatch, {"fit": 90, "score": 70, "guess": None, "checklist": [], "take": "x", "tags": [], "features": {}})["guess"] == ""
    assert len(deep(monkeypatch, {"fit": 90, "score": 70, "guess": "word " * 100, "checklist": [], "take": "x", "tags": [], "features": {}})["guess"]) <= 60


def test_the_prompt_asks_for_the_guess(monkeypatch):
    seen = {}
    monkeypatch.setattr(config, "brain_mode", lambda: "claude")

    async def fake_call(model, content, max_tokens=1500, label="claude"):
        seen["prompt"] = content[0]["text"]
        return {"fit": 90, "score": 70, "checklist": [], "take": "", "tags": [], "features": {}}
    monkeypatch.setattr(brain, "_call", fake_call)
    run(brain.deep_score({"name": "C", "hunt": "c", "criteria": []}, {"weights": [], "mean": .5, "n_swipes": 0, "liked": [], "disliked": [], "groups": [], "concepts": [], "query_stats": []},
                         {"title": "t", "price_text": "$1", "price": 1}, []))
    assert '"guess"' in seen["prompt"] and "most likely to dislike" in seen["prompt"]
