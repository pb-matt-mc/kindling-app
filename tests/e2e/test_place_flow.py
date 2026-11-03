"""The Place screen end to end, with real mouse or real touch events on every device in the matrix:
drag, tentative drop, Back to listing, Place here, undo, rocket (both release styles), drawer, dismiss, New planet."""
import math

import pytest

THETA_RIGHT = 0.0


def inside_viewport(session, selectors):
    """Every named element, when visible, sits fully inside the visible viewport."""
    js = """(sels) => { const out = [], vw = innerWidth, vh = (visualViewport ? visualViewport.height : innerHeight);
      for (const s of sels) for (const e of document.querySelectorAll(s)) {
        const r = e.getBoundingClientRect(); if (!r.width || !r.height || e.hidden || getComputedStyle(e).visibility === 'hidden') continue;
        if (r.left < -1 || r.top < -1 || r.right > vw + 1 || r.bottom > vh + 1) out.push(s + ' ' + [r.left, r.top, r.right, r.bottom].map(Math.round)); }
      return out; }"""
    return session.page.evaluate(js, selectors)


@pytest.fixture
def batch(orbit):
    return orbit.start_batch(size=6)


def test_listing_floats_with_claudes_guess_always_visible(session, orbit, batch):
    p = session.page
    first = batch["queue"][0]
    assert p.locator("#card .tt").inner_text() == first["title"]
    assert p.locator("#gtxt").text_content() == first["guess"]            # the down label is Claude's guess
    assert p.locator("#conftxt").inner_text() == "Still learning"
    assert "float" in p.locator("#card").get_attribute("class")
    assert inside_viewport(session, ["#card", ".lab", "#rocket", ".top", ".panel"]) == []


def test_field_fits_without_clipping_at_this_size(session, orbit, batch):
    assert inside_viewport(session, ["#stage svg.bg", ".lab", "#rocket", "#card", ".panel", ".nav"]) == []
    assert session.layout_problems(kinds=("overflow",)) == []
    sr = session.page.evaluate("(() => { const r = document.querySelector('#stage svg.bg').getBoundingClientRect(); return [r.width, r.height]; })()")
    assert sr[0] > 150 and sr[1] > 150


def test_drag_rests_tentatively_and_commits_nothing(session, orbit, batch):
    p = session.page
    n0 = len(orbit.state()["placed"])
    target = orbit.field(0.5, THETA_RIGHT)
    orbit.drag(orbit.card_center(), target)
    assert orbit.phase() == "parked"
    assert p.locator("#placehere").is_visible() and p.locator("#back").is_visible()
    assert "Right vibe" in p.locator("#rd2").inner_text() or "Wrong vibe" in p.locator("#rd2").inner_text() or "%" in p.locator("#rd2").inner_text()
    assert "like" in p.locator("#rd1").inner_text()
    assert len(orbit.state()["placed"]) == n0                               # nothing counted yet
    assert "float" in (p.locator("#thumb").get_attribute("class") or "")    # a resting listing floats, so it reads as undecided


def test_readout_matches_the_math(session, orbit, batch):
    p = session.page
    orbit.drag(orbit.card_center(), orbit.field(0.8, -math.pi / 4))          # outer, between price and right vibe
    r1, r2 = p.locator("#rd1").inner_text(), p.locator("#rd2").inner_text()
    assert "Outer" in r1 and "pass" in r1
    assert "50% Price" in r2 and "50% Right vibe" in r2


def test_back_to_listing_returns_the_card(session, orbit, batch):
    p = session.page
    orbit.drag(orbit.card_center(), orbit.field(0.6, 1.0))
    orbit.tap("#back")
    assert orbit.phase() == "idle" and p.locator("#card").is_visible()
    assert len(orbit.state()["placed"]) == 0


def test_drag_again_while_resting_then_place_here_commits_the_final_spot(session, orbit, batch):
    p = session.page
    orbit.drag(orbit.card_center(), orbit.field(0.9, 2.0))
    orbit.drag(orbit.thumb_center(), orbit.field(0.2, 0.0))
    assert orbit.phase() == "parked" and len(orbit.state()["placed"]) == 0
    first_id = batch["queue"][0]["id"]
    orbit.tap("#placehere")
    p.wait_for_selector(".panel .guessbox")
    st = orbit.state()
    pl = [x for x in st["placed"] if x["id"] == first_id][0]
    assert pl["kind"] == "first" and pl["zone"] in ("Inner", "Sun") and pl["r"] < 0.45
    assert any(w in p.locator(".panel .guessbox").inner_text().lower() for w in ("called it", "close", "claude missed"))
    assert "Claude guessed" in p.locator(".panel .guessbox p").text_content()
    assert p.locator("#ghost").is_visible() or p.locator("#ghost").count() == 1


def test_tap_without_dragging_opens_the_listing_sheet_and_keeps_the_card(session, orbit, batch):
    p = session.page
    c = orbit.card_center()
    orbit.tap(c["x"], c["y"])
    p.wait_for_selector(".sheet")
    assert batch["queue"][0]["title"] in p.locator(".sheet").inner_text()
    assert inside_viewport(session, [".sheet"]) == []
    p.keyboard.press("Escape")
    assert orbit.phase() == "idle" and len(orbit.state()["placed"]) == 0


def test_undo_after_placing(session, orbit, batch):
    p = session.page
    orbit.drag(orbit.card_center(), orbit.field(0.5, 0.5))
    orbit.tap("#placehere")
    p.wait_for_selector(".panel .guessbox")
    orbit.tap("#undo2")
    p.wait_for_selector("#card:not([hidden])")
    st = orbit.state()
    assert st["placed"] == [] and len(st["queue"]) == 6 and orbit.phase() == "idle"


def test_next_listing_advances_and_the_header_can_still_undo(session, orbit, batch):
    p = session.page
    orbit.drag(orbit.card_center(), orbit.field(0.5, 0.5))
    orbit.tap("#placehere")
    p.wait_for_selector(".panel .guessbox")
    orbit.tap("#next")
    p.wait_for_selector("#card:not([hidden])")
    assert p.locator("#card .tt").inner_text() == batch["queue"][1]["title"]
    assert p.locator("#undo").is_visible()
    orbit.tap("#undo")
    p.wait_for_function("__orbit.state.queue.length === 6")
    assert p.locator("#card .tt").inner_text() == batch["queue"][0]["title"]


def test_same_spot_listings_stay_separately_visible(session, orbit, batch):
    p = session.page
    for _ in range(3):
        orbit.drag(orbit.card_center(), orbit.field(0.55, 0.9))
        orbit.tap("#placehere")
        p.wait_for_selector(".panel .guessbox")
        orbit.tap("#next")
        p.wait_for_selector("#card:not([hidden])")
    pos = p.evaluate("[...document.querySelectorAll('#dots .dot')].map(d => { const r = d.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top)]; })")
    assert len(pos) == 3 and len({tuple(x) for x in pos}) == 3                  # three dots, three different places on screen
    stored = [(x["r"], x["theta"]) for x in orbit.state()["placed"]]
    assert len(set(stored)) == 1 or max(abs(a[0] - stored[0][0]) for a in stored) < 0.02    # while the stored positions are (nearly) one spot


# ---- rocket -----------------------------------------------------------------------------------------

@pytest.fixture
def planets(orbit, batch):
    a = orbit.api("/o/planets", {"name": "Rolled arms", "orbit": "Mid", "reason": "wrong"})
    b = orbit.api("/o/planets", {"name": "Too formal", "orbit": "Outer", "reason": "price"})
    orbit.page.reload()
    orbit.page.wait_for_selector("#card:not([hidden])")
    return [a, b]


def drawer_item(session, name):
    return session.page.locator(f".drawer .item:has-text('{name}')").first


def center(loc):
    b = loc.bounding_box()
    return {"x": b["x"] + b["width"] / 2, "y": b["y"] + b["height"] / 2}


def test_dragging_onto_the_rocket_blasts_off_and_opens_the_drawer(session, orbit, planets):
    p = session.page
    orbit.drag(orbit.card_center(), orbit.rocket(), hold_at_end=True)
    assert "blast" in p.locator("#rocket").get_attribute("class")
    assert p.locator("#drawer").is_visible()
    items = p.locator(".drawer .item")
    assert items.count() == 3 and "New planet" in items.nth(2).inner_text()           # ends in New planet
    assert inside_viewport(session, ["#drawer", "#rocket"]) == []
    drawer_box = p.locator("#drawer").bounding_box()
    assert drawer_box["x"] + drawer_box["width"] <= p.locator("#rocket").bounding_box()["x"] + 1     # the drawer is to its left
    orbit.release(orbit.rocket())


def test_release_on_a_planet_sends_the_listing_there(session, orbit, planets):
    p = session.page
    orbit.drag(orbit.card_center(), orbit.rocket(), hold_at_end=True)
    orbit.move_to(center(drawer_item(session, "Too formal")))
    assert "over" in drawer_item(session, "Too formal").get_attribute("class")
    orbit.release(center(drawer_item(session, "Too formal")))
    p.wait_for_selector(".panel .guessbox")
    st = orbit.state()
    sent = [x for x in st["placed"] if x["kind"] == "rocket"]
    assert len(sent) == 1 and sent[0]["planet_id"] == planets[1]["id"]
    assert "sent to too formal" in p.locator(".panel .guessbox").inner_text().lower()
    assert st["scores"]["rocket"]["rocketed"] == 1
    assert st["scores"]["confidence"]["n"] == 0 if "n" in st["scores"]["confidence"] else True      # no score for a rocketed listing


def test_release_on_the_rocket_then_tap_a_planet(session, orbit, planets):
    p = session.page
    orbit.drag(orbit.card_center(), orbit.rocket())
    assert orbit.phase() == "rocket" and p.locator("#drawer").is_visible()
    assert len(orbit.state()["placed"]) == 0
    orbit.tap(center(drawer_item(session, "Rolled arms"))["x"], center(drawer_item(session, "Rolled arms"))["y"])
    p.wait_for_selector(".panel .guessbox")
    sent = [x for x in orbit.state()["placed"] if x["kind"] == "rocket"]
    assert len(sent) == 1 and sent[0]["planet_id"] == planets[0]["id"]


def test_dismissing_the_drawer_returns_the_listing_to_the_field(session, orbit, planets):
    p = session.page
    orbit.drag(orbit.card_center(), orbit.rocket())
    assert orbit.phase() == "rocket"
    p.keyboard.press("Escape")
    assert orbit.phase() == "idle" and p.locator("#card").is_visible() and not p.locator("#drawer").is_visible()
    assert len(orbit.state()["placed"]) == 0
    # and from a resting spot it returns to that spot
    orbit.drag(orbit.card_center(), orbit.field(0.6, 2.0))
    spot = orbit.thumb_center()
    orbit.drag(orbit.thumb_center(), orbit.rocket())
    orbit.tap("#cancelrocket")
    assert orbit.phase() == "parked"
    now = orbit.thumb_center()
    assert abs(now["x"] - spot["x"]) < 9 and abs(now["y"] - spot["y"]) < 9      # a resting listing floats a few pixels
    assert len(orbit.state()["placed"]) == 0


def test_leaving_the_rocket_while_dragging_closes_the_drawer_and_keeps_dragging(session, orbit, planets):
    p = session.page
    orbit.drag(orbit.card_center(), orbit.rocket(), hold_at_end=True)
    assert p.locator("#drawer").is_visible()
    away = orbit.field(0.6, -math.pi / 2)               # straight up toward Price: clear of the drawer, which hugs the bottom right
    orbit.move_to(away)
    assert not p.locator("#drawer").is_visible()
    orbit.release(away)
    assert orbit.phase() == "parked"


def test_new_planet_from_the_drawer_then_the_listing_goes_there(session, orbit, planets):
    p = session.page
    orbit.drag(orbit.card_center(), orbit.rocket())
    orbit.tap("[data-new]")
    p.wait_for_selector(".sheet #pn")
    assert inside_viewport(session, [".sheet"]) == []
    p.fill("#pn", "Low Danish")
    p.fill("#pd", "teak legs, low profile")
    p.locator("#po button:has-text('Inner')").click()
    p.locator("#pr button:has-text('Price')").click()
    assert inside_viewport(session, [".sheet", "#pmake"]) == []                  # reachable even with the keyboard up
    orbit.tap("#pmake")
    p.wait_for_selector(".panel .guessbox")
    mine = [x for x in orbit.state()["planets"] if x["name"] == "Low Danish"][0]
    assert mine["zone"] == "Inner" and orbit.state()["placed"][0]["planet_id"] == mine["id"]


def test_cancelling_new_planet_returns_the_listing(session, orbit, planets):
    p = session.page
    orbit.drag(orbit.card_center(), orbit.rocket())
    orbit.tap("[data-new]")
    p.wait_for_selector(".sheet #pn")
    p.keyboard.press("Escape")
    assert orbit.phase() == "idle" and p.locator("#card").is_visible()


# ---- platform ---------------------------------------------------------------------------------------

def test_no_outside_requests_and_a_strict_csp(session, orbit, batch):
    session.page.reload()
    session.page.wait_for_selector("#stage")
    session.page.wait_for_timeout(600)
    assert session.external_requests == []
    r = session.ctx.request.get(session.server["url"] + "/")
    assert "default-src 'self'" in r.headers.get("content-security-policy", "")


def test_fonts_come_from_the_app(session, orbit, batch):
    fonts = session.page.evaluate("document.fonts.ready.then(() => [...document.fonts].filter(f => f.status === 'loaded').map(f => f.family))")
    assert "League Spartan" in fonts or "Atkinson Hyperlegible" in fonts
    assert all(u.startswith(session.server["url"]) for u in session.requests if u.endswith(".woff2"))


def test_manifest_and_icons_say_orbit(session):
    m = session.ctx.request.get(session.server["url"] + "/manifest.webmanifest").json()
    assert m["name"] == "Orbit" and m["short_name"] == "Orbit" and m["id"] == "/" and m["orientation"] == "any"
    kinds = {(i["sizes"], i["purpose"]) for i in m["icons"]}
    assert ("192x192", "any") in kinds and ("512x512", "maskable") in kinds
    for i in m["icons"]:
        assert session.ctx.request.get(session.server["url"] + i["src"]).ok


def test_haptics_only_where_supported_and_always_with_a_visual_cue(session, orbit, batch):
    p = session.page
    p.evaluate("window.__v = []; if (!('vibrate' in navigator)) {} else navigator.vibrate = (x) => (__v.push(x), true)")
    orbit.drag(orbit.card_center(), orbit.field(0.5, 0.5))
    orbit.tap("#placehere")
    p.wait_for_selector(".panel .guessbox")
    assert p.locator("#thumb.pulse").count() == 1                              # visual cue, regardless of the device
    if p.evaluate("'vibrate' in navigator"):
        assert p.evaluate("__v.length") > 0
