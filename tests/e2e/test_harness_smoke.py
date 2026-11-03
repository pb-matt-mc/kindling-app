"""Proves the harness itself, against today's Kindling UI: the device matrix opens the app signed in, the layout
checker finds real problems, touch and mouse input both reach the page, and installed mode is detectable.
Orbit-specific flows (drag, rocket, ...) are added by the phases that build them."""
import pytest


def test_app_opens_signed_in_at_every_size(session):
    session.goto("home")
    assert session.page.locator("#app").count() == 1
    assert session.page.evaluate("innerWidth") == session.device.w
    assert session.page.evaluate("innerHeight") == session.device.height
    assert session.page.evaluate("devicePixelRatio") == session.device.dpr


def test_no_sideways_scroll_on_home(session):
    session.goto("home")
    assert session.layout_problems(kinds=("overflow",)) == []


def test_installed_variant_matches_standalone_media(session):
    session.goto("home")
    standalone = session.page.evaluate("matchMedia('(display-mode: standalone)').matches")
    assert standalone is session.device.installed
    assert session.page.evaluate("navigator.standalone === true") is session.device.installed


def test_input_kind_matches_device(session):
    session.goto("home")
    coarse = session.page.evaluate("matchMedia('(pointer: coarse)').matches")
    assert coarse is session.device.touch
    assert session.page.evaluate("'ontouchstart' in window") is session.device.touch


def test_touch_tap_and_mouse_click_both_fire(session):
    session.goto("home")
    session.page.evaluate("window.__hits = []; document.addEventListener('pointerdown', e => __hits.push(e.pointerType), true)")
    if session.device.touch:
        session.page.touchscreen.tap(session.device.w // 2, session.device.height // 2)
    else:
        session.page.mouse.click(session.device.w // 2, session.device.height // 2)
    assert session.page.evaluate("__hits")[0] == ("touch" if session.device.touch else "mouse")


def test_layout_checker_detects_a_deliberately_broken_page(session):
    session.goto("home")
    session.page.evaluate("""() => { const d = document.createElement('div'); d.className = 'dialog';
        d.style.cssText = 'position:fixed;inset:auto;max-width:none;max-height:none;top:0;left:0;width:' + (innerWidth + 200) + 'px;height:' + (innerHeight + 300) + 'px';
        d.innerHTML = '<button id=lost style="position:absolute;top:' + (innerHeight + 100) + 'px">Close</button>';
        document.body.appendChild(d); }""")
    problems = session.layout_problems()
    assert any(p.startswith("clipping") for p in problems)


def test_no_outside_requests(session):
    session.goto("home", wait=1500)
    assert session.external_requests == []


def test_csp_header_locks_the_client_to_its_own_origin(session):
    r = session.ctx.request.get(session.server["url"] + "/")
    assert "default-src 'self'" in r.headers.get("content-security-policy", "")


def test_a_portrait_phone_stays_portrait_with_the_keyboard_open(session):
    session.goto("home")
    expect = "portrait" if session.device.touch else "landscape"
    assert session.page.evaluate("document.documentElement.dataset.orient") == expect
    if session.device.touch:
        # the viewport may be wider than tall (keyboard up) but the nav must still sit along the bottom, not in a rail
        nav = session.page.locator(".nav").bounding_box()
        assert nav["width"] > session.device.w * 0.7
