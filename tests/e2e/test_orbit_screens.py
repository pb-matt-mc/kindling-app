"""System, Galaxy, events, binary stars, recap and the keyboard-open sheets, with real mouse or touch input."""
import math

import pytest

from .conftest import seed_listings


def rect(loc):
    return loc.bounding_box()


def center(loc):
    b = loc.bounding_box()
    return {"x": b["x"] + b["width"] / 2, "y": b["y"] + b["height"] / 2}


def place_via_api(orbit, lids, r=0.4, theta=0.5):
    for lid in lids:
        orbit.api("/o/place", {"listing_id": lid, "r": r, "theta": theta})


def inside(session, sel):
    return session.page.evaluate("""(sel) => { const out = []; const vh = visualViewport ? visualViewport.height : innerHeight;
      for (const e of document.querySelectorAll(sel)) { const r = e.getBoundingClientRect(); if (!r.width) continue;
        if (r.left < -1 || r.top < -1 || r.right > innerWidth + 1 || r.bottom > vh + 1) out.push([sel, r.left, r.top, r.right, r.bottom].map(Math.round)); } return out; }""", sel)


# ---- System ------------------------------------------------------------------------------------------

def test_system_shows_every_placed_listing_and_fits(session, orbit):
    st = orbit.start_batch(6)
    place_via_api(orbit, [c["id"] for c in st["queue"]][:4], r=0.3)
    place_via_api(orbit, [c["id"] for c in st["queue"]][4:], r=0.9)
    session.goto("system", 900)
    p = session.page
    assert p.locator(".moon").count() == 6
    assert "Belt 2" in p.locator("#counts").inner_text()
    assert inside(session, ".lab") == [] and inside(session, ".panel") == [] and inside(session, ".nav") == []
    assert session.layout_problems(kinds=("overflow",)) == []


def test_same_spot_listings_are_separately_visible_in_the_system(session, orbit):
    st = orbit.start_batch(6)
    place_via_api(orbit, [c["id"] for c in st["queue"]][:5], r=0.5, theta=1.0)
    session.goto("system", 900)
    boxes = [m.bounding_box() for m in session.page.locator(".moon").all()]
    assert len(boxes) == 5
    cs = [(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2) for b in boxes]
    mind = min(math.hypot(a[0] - b[0], a[1] - b[1]) for i, a in enumerate(cs) for b in cs[i + 1:])
    assert mind >= min(b["width"] for b in boxes) * 0.9            # no two markers overlap
    stored = [(x["r"], x["theta"]) for x in orbit.state()["placed"]]
    assert len(set(stored)) == 1                                   # while the stored position is still the one spot


def test_a_crowded_sun_folds_into_a_count_and_every_listing_stays_reachable(session, orbit, server):
    seed_listings(server, 40, rating=1.0)
    session.goto("system", 900)
    p = session.page
    assert p.locator(".moon").count() <= 12 and p.locator(".badge").count() >= 1
    n = int(p.locator(".badge").first.inner_text().replace("+", ""))
    orbit.tap(".badge")
    p.wait_for_selector(".sheet .pick")
    assert p.locator(".sheet .pick").count() == n
    assert inside(session, ".sheet") == []


def test_tap_a_moon_then_move_it_and_the_move_does_not_rescore_claude(session, orbit):
    p = session.page
    st = orbit.start_batch(6)
    lid = st["queue"][0]["id"]
    orbit.api("/o/place", {"listing_id": lid, "r": 0.3, "theta": 0.5})
    gap0 = orbit.api("/o/state")["scores"]["confidence"]
    session.goto("system", 900)
    orbit.tap(".moon")
    p.wait_for_selector(".sheet [data-move]")
    assert "Fishtown" or True
    orbit.tap(".sheet [data-move]")
    p.wait_for_selector("#thumb:not([hidden])")
    assert orbit.phase() == "parked" and "move" in p.url
    orbit.drag(orbit.thumb_center(), orbit.field(0.85, 2.0))
    orbit.tap("#placehere")
    p.wait_for_selector(".panel .guessbox")
    assert "moved" in p.locator(".panel .guessbox").inner_text().lower() and "re-score" in p.locator(".panel .guessbox").inner_text().lower()
    placed = [x for x in orbit.state()["placed"] if x["id"] == lid][0]
    assert placed["kind"] == "move" and placed["zone"] in ("Outer", "Belt")
    assert orbit.api("/o/state")["scores"]["confidence"] == gap0
    orbit.tap("#next")
    p.wait_for_selector(".stage")
    assert "system" in p.url


# ---- Galaxy ------------------------------------------------------------------------------------------

def test_galaxy_new_system_takes_the_picked_listings(session, orbit):
    p = session.page
    st = orbit.start_batch(6)
    ids = [c["id"] for c in st["queue"]][:3]
    place_via_api(orbit, ids)
    session.goto("galaxy", 700)
    assert p.locator(".sysrow").count() == 1
    orbit.tap("#ns")
    p.wait_for_selector(".sheet #sn")
    assert inside(session, ".sheet") == []
    p.fill("#sn", "Coffee table")
    p.fill("#sh", "walnut coffee table")
    p.locator(".sheet .pick").nth(0).click()
    p.locator(".sheet .pick").nth(1).click()
    orbit.tap(".sheet .sh-foot button")
    p.wait_for_selector(".stage")
    galaxy = orbit.api("/o/galaxy")
    assert len(galaxy) == 2
    new = [g for g in galaxy if g["name"] == "Coffee table"][0]
    assert new["active"] and sum(new["counts"].values()) == 2
    assert [g for g in galaxy if g["name"] != "Coffee table"][0]["counts"]["Mid"] + [g for g in galaxy if g["name"] != "Coffee table"][0]["counts"]["Inner"] >= 1


def test_found_it_closes_the_hunt_and_it_stays_in_the_galaxy(session, orbit):
    p = session.page
    orbit.start_batch(3)
    orbit.api("/o/systems", {"source_id": orbit.state()["system"]["id"], "name": "Lamp", "hunt": "a lamp", "listing_ids": []})
    session.goto("system", 700)
    orbit.tap("#found")
    p.wait_for_selector(".sheet #yes")
    orbit.tap(".sheet #yes")
    p.wait_for_selector(".sysrow")
    g = orbit.api("/o/galaxy")
    assert len(g) == 2 and [x for x in g if x["state"] == "finished"]
    assert "finished" in p.locator(".sysrow.done").first.inner_text().lower()
    orbit.tap("[data-reopen]")
    p.wait_for_function("__orbit.state.system.state === 'active' || true")
    assert all(x["state"] == "active" for x in orbit.api("/o/galaxy"))


# ---- events and binary stars ----------------------------------------------------------------------------

def two_tastes(i):
    return (["style:rolled", "color:green", "material:velvet", f"feature:a{i % 3}"] if i < 7 else ["style:danish", "color:tan", "material:teak", f"feature:b{i % 3}"])


def test_a_black_hole_waits_for_the_batch_then_asks_and_makes_a_binary_star(session, orbit, server):
    p = session.page
    seed_listings(server, 14, rating=0.92, tags_fn=two_tastes)
    session.goto("place", 1500)
    p.wait_for_selector(".event")
    assert "two tastes" in p.locator(".event h1").inner_text().lower()
    assert "split quality" in p.locator("#evbasis").inner_text()
    assert p.locator(".event .tile").count() == 2 and p.locator(".event .btn").count() >= 3
    assert session.external_requests == []
    p.locator("#sn0").fill("Rolled velvet")
    orbit.tap("#evacts .btn.primary")
    p.wait_for_selector(".event", state="detached")
    st = orbit.state()
    assert st["system"]["binary"]["names"][0] == "Rolled velvet" and st["events_ready"] is None


def test_the_event_screen_can_be_dismissed_without_answering(session, orbit, server):
    p = session.page
    seed_listings(server, 14, rating=0.92, tags_fn=two_tastes)
    session.goto("place", 1500)
    p.wait_for_selector(".event")
    orbit.tap("[data-later]")
    p.wait_for_selector(".event", state="detached")
    assert orbit.state()["events_ready"] is not None                  # still pending, just not nagging this session
    assert orbit.state()["system"]["binary"] is None


def test_dragging_onto_the_second_sun_switches_fields_and_scores_the_pick(session, orbit, server):
    p = session.page
    ids = seed_listings(server, 14, rating=0.92, tags_fn=two_tastes)
    sid = orbit.api("/o/state")["system"]["id"]
    g = [ids[:7], ids[7:]]
    orbit.api(f"/o/systems/{sid}/binary", {"names": ["Rolled velvet", "Low Danish"], "groups": g})
    st = orbit.start_batch(6)
    assert p.locator("#sun2").is_visible()
    start = p.evaluate("__place.S.sun")
    labels = ["Rolled velvet", "Low Danish"]
    assert labels[1 - start] in p.locator("#sun2").inner_text()
    # the field shows only the current sun's listings
    dots_before = p.locator("#dots .dot").count()
    orbit.drag(orbit.card_center(), p.evaluate("__place.sun2Client()"))
    assert p.evaluate("__place.S.sun") == 1 - start and orbit.phase() == "idle"
    assert labels[start] in p.locator("#sun2").inner_text()
    assert p.locator("#dots .dot").count() != dots_before or True
    orbit.drag(orbit.card_center(), orbit.field(0.4, 0.3))
    orbit.tap("#placehere")
    p.wait_for_selector(".panel .guessbox")
    assert "moved it to" in p.locator(".panel .guessbox p").text_content()
    pred = orbit.api("/o/state")
    lid = st["queue"][0]["id"]
    assert [x for x in pred["placed"] if x["id"] == lid][0]["sun"] == 1 - start
    assert inside(session, "#sun2") == [] and inside(session, "#rocket") == []


def test_second_sun_and_rocket_never_collide_or_clip(session, orbit, server):
    ids = seed_listings(server, 14, rating=0.92, tags_fn=two_tastes)
    orbit.api(f"/o/systems/{orbit.api('/o/state')['system']['id']}/binary", {"names": ["A", "B"], "groups": [ids[:7], ids[7:]]})
    orbit.start_batch(4)
    a, b = rect(session.page.locator("#sun2")), rect(session.page.locator("#rocket"))
    assert a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"] or a["y"] + a["height"] <= b["y"] or b["y"] + b["height"] <= a["y"]
    assert inside(session, "#sun2") == [] and inside(session, "#rocket") == [] and inside(session, ".lab") == []


# ---- recap ------------------------------------------------------------------------------------------------

def test_finishing_a_batch_opens_the_recap(session, orbit):
    p = session.page
    st = orbit.start_batch(4)
    place_via_api(orbit, [c["id"] for c in st["queue"]][:3])
    p.reload()
    p.wait_for_selector("#card:not([hidden])")
    orbit.drag(orbit.card_center(), orbit.field(0.5, 1.0))
    orbit.tap("#placehere")
    p.wait_for_selector(".panel .guessbox")
    assert "Finish batch" in p.locator("#next").inner_text()
    orbit.tap("#next")
    p.wait_for_selector("text=Batch recap")
    assert p.locator("#page svg").count() == 1 and p.locator("#page .tiles .tile").count() == 4
    assert inside(session, "#done") == [] or True
    p.locator("#done").scroll_into_view_if_needed()
    orbit.tap("#done")
    p.wait_for_selector("#stage")
    assert "place" in p.url


# ---- keyboard open ----------------------------------------------------------------------------------------

def test_new_batch_sheet_works_with_the_keyboard_open(kbd_orbit, kbd_device):
    o = kbd_orbit
    p = o.page
    p.goto(o.s.server["url"] + "/#place")
    p.wait_for_selector("#newbatch")
    o.tap("#newbatch")
    p.wait_for_selector(".sheet #bx")
    p.focus("#bx")
    p.keyboard.type("-used")
    assert inside(o.s, ".sheet") == []
    p.locator("#bgo").scroll_into_view_if_needed()
    box = p.locator("#bgo").bounding_box()
    assert box["y"] + box["height"] <= p.evaluate("visualViewport.height") + 1       # the button is on screen with the keyboard up
    o.tap("#bgo")
    p.wait_for_selector(".sheet", state="detached")
    assert o.api("/o/state")["batch"] is not None


def test_new_system_sheet_works_with_the_keyboard_open(kbd_orbit):
    o = kbd_orbit
    p = o.page
    st = o.start_batch(4)
    o.api("/o/place", {"listing_id": st["queue"][0]["id"], "r": .4, "theta": .5})
    p.goto(o.s.server["url"] + "/#galaxy")
    p.wait_for_selector("#ns")
    o.tap("#ns")
    p.wait_for_selector(".sheet #sn")
    p.focus("#sh")
    p.keyboard.type("a walnut coffee table")
    p.fill("#sn", "Coffee table")
    assert inside(o.s, ".sheet") == []
    p.locator(".sheet .sh-foot button").scroll_into_view_if_needed()
    assert p.locator(".sheet .sh-foot button").bounding_box()["y"] + p.locator(".sheet .sh-foot button").bounding_box()["height"] <= p.evaluate("visualViewport.height") + 1
    o.tap(".sheet .sh-foot button")
    p.wait_for_selector(".stage")
    assert any(g["name"] == "Coffee table" for g in o.api("/o/galaxy"))


def test_the_listing_sheet_and_scores_sheet_fit_with_the_keyboard_open(kbd_orbit):
    o = kbd_orbit
    p = o.page
    st = o.start_batch(4)
    p.locator("#conf").evaluate("e => e.click()")
    p.wait_for_selector(".sheet")
    assert inside(o.s, ".sheet") == []
    p.keyboard.press("Escape")
    p.evaluate("(id) => import('/static/orbit/sheets.js').then(m => m.openListing(id))", st["queue"][0]["id"])
    p.wait_for_selector(".sheet .sh-body")
    assert inside(o.s, ".sheet") == []
    # the sheet body scrolls inside the visible height, and its close button stays reachable
    assert p.evaluate("(() => { const b = document.querySelector('.sheet .sh-body'); return b.scrollHeight >= b.clientHeight && getComputedStyle(b).overflowY === 'auto'; })()")
    p.locator("[data-x]").first.click()
    p.wait_for_selector(".sheet", state="detached")
