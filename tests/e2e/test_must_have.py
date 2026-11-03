"""The checklist must-have toggle on the profile page, through a real browser with mouse and touch."""


def reset_checklist(s):
    s.goto("home", wait=300)
    s.page.evaluate("""async () => { const st = await (await fetch('/api/state')).json();
        await fetch('/api/profiles/' + st.profile.id, { method: 'PUT', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ criteria: [], must_have: [] }) }); }""")


def open_hunt_card(s):
    reset_checklist(s)
    s.page.goto(s.server["url"] + "/legacy#profile")       # the classic profile page; Orbit links to it as "Profile"
    s.page.wait_for_timeout(900)
    s.page.wait_for_selector("#f-crit", state="attached")
    if not s.page.locator("#f-crit").is_visible():  # cards fold; open the one holding the hunt
        s.page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
        s.page.locator("#f-crit").evaluate("e => e.closest('.card, section, details')?.classList.remove('folded')")


def press(s, selector):
    loc = s.page.locator(selector).first
    loc.scroll_into_view_if_needed()
    box = loc.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    if s.device.touch:
        s.page.touchscreen.tap(x, y)
    else:
        s.page.mouse.click(x, y)


def test_toggle_marks_a_checklist_item_as_must_have_and_it_saves(session):
    open_hunt_card(session)
    p = session.page
    p.fill("#f-crit", "Rolled arms")
    p.press("#f-crit", "Enter")
    p.fill("#f-crit", "Under 84 in")
    p.press("#f-crit", "Enter")
    chips = p.locator("#crit .chip")
    assert chips.count() == 2
    assert p.locator("#crit .must-btn").first.get_attribute("aria-pressed") == "false"
    assert "Nice to have" in p.locator("#crit .must-btn").first.inner_text()
    press(session, "#crit .chip:nth-child(1) .must-btn")
    assert p.locator("#crit .must-btn").first.get_attribute("aria-pressed") == "true"
    assert "Must have" in p.locator("#crit .must-btn").first.inner_text()      # state shown in words, not only color
    press(session, "#save")
    p.wait_for_timeout(600)
    saved = p.evaluate("fetch('/api/state').then(r => r.json()).then(s => s.profile)")
    assert saved["criteria"] == ["Rolled arms", "Under 84 in"] and saved["must_have"] == ["Rolled arms"]
    p.goto(session.server["url"] + "/legacy#profile")
    p.wait_for_timeout(900)
    assert p.locator("#crit .must-btn").first.get_attribute("aria-pressed") == "true"
    assert p.locator("#crit .must-btn").nth(1).get_attribute("aria-pressed") == "false"
    # removing the item takes its must-have flag with it
    p.locator("#crit button[data-i]").first.click()
    assert p.locator("#crit .chip").count() == 1 and p.locator("#crit .must-btn").first.get_attribute("aria-pressed") == "false"
