"""Open every Kindling screen and dialog at phone/desktop sizes and flag layout defects.

    .venv-ui/bin/python scripts/ui-audit/audit.py --out specs/ui-responsive-overhaul/baseline
    ... --viewports s26-portrait,s26-portrait-chrome --only export --fail-on clipping,unreachable,icon

Needs the instance from `serve.sh start`. Defect kinds:
  clipping     the top overlay/screen box extends past the viewport edge
  unreachable  a control that can't be scrolled fully into view, or is covered by something else
  icon         an svg inside a control that is smaller than 12px or larger than 36px
  tap          a control smaller than 40px in either direction
  overflow     the page or overlay scrolls sideways
"""
import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

# CSS px. s26 sizes are an assumption (19.5:9, DPR 3); "chrome" = with the browser's address/nav bars showing.
VIEWPORTS = {
    "s26-portrait": (360, 780, 3, True),
    "s26-portrait-chrome": (360, 690, 3, True),
    "s26-landscape": (780, 360, 3, True),
    "s26-landscape-chrome": (780, 300, 3, True),
    "desktop-720": (1280, 720, 1, False),
    "desktop-1080": (1920, 1080, 1, False),
    "ultrawide": (2560, 1080, 1, False),
}
ALL_KINDS = ["clipping", "unreachable", "icon", "tap", "overflow"]

CHECK_JS = r"""
() => {
  const out = [];
  const vw = innerWidth, vh = innerHeight;
  const vis = (e) => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none" && !e.closest("[hidden]"); };
  const name = (e) => { const t = (e.id ? "#" + e.id : "") || (e.className && typeof e.className === "string" ? "." + e.className.trim().split(/\s+/).slice(0, 2).join(".") : "");
    return e.tagName.toLowerCase() + t + ((e.textContent || "").trim().slice(0, 24) ? ` "${(e.textContent || "").trim().replace(/\s+/g, " ").slice(0, 24)}"` : ""); };
  // the layer the user is looking at: topmost overlay, else the app screen
  const layers = [...document.querySelectorAll(".dialog, .sheet, .modal, .viewer")].filter(vis);
  const top = layers.sort((a, b) => (+getComputedStyle(a).zIndex || 0) - (+getComputedStyle(b).zIndex || 0)).pop()
    || document.querySelector("#app .screen") || document.querySelector("#app");
  const lr = top.getBoundingClientRect();
  if (lr.bottom > vh + 1 || lr.right > vw + 1 || lr.left < -1 || lr.top < -1)
    out.push(["clipping", `${name(top)} box is ${Math.round(lr.left)},${Math.round(lr.top)} to ${Math.round(lr.right)},${Math.round(lr.bottom)} in a ${vw}x${vh} viewport`]);
  if (document.documentElement.scrollWidth > vw + 1) out.push(["overflow", `page scrolls sideways (${document.documentElement.scrollWidth} > ${vw})`]);
  if (top.scrollWidth > top.clientWidth + 1 && getComputedStyle(top).overflowX === "visible") out.push(["overflow", `${name(top)} content wider than itself`]);

  const sel = "button, a[href], a.btn, input:not([type=hidden]), textarea, select, label.btn, [role=button]";
  for (const e of top.querySelectorAll(sel)) {
    if (!vis(e) || e.closest(".web svg, .tap-zone") || e.disabled) continue;
    if (e.tagName === "INPUT" && e.type === "file") continue;  // always hidden behind a label
    e.scrollIntoView({ block: "center", inline: "center" });
    const r = e.getBoundingClientRect();
    const inside = r.top >= -1 && r.left >= -1 && r.bottom <= vh + 1 && r.right <= vw + 1;
    const cx = Math.min(Math.max(r.left + r.width / 2, 0), vw - 1), cy = Math.min(Math.max(r.top + r.height / 2, 0), vh - 1);
    const hit = document.elementFromPoint(cx, cy);
    const reachable = inside && hit && (e.contains(hit) || hit.contains(e));
    if (!reachable) out.push(["unreachable", `${name(e)} ${inside ? "is covered by " + (hit ? name(hit) : "nothing") : "cannot be scrolled into view (at " + Math.round(r.left) + "," + Math.round(r.top) + " size " + Math.round(r.width) + "x" + Math.round(r.height) + ")"}`]);
    else if (r.width < 40 || r.height < 40) {
      if (!(e.tagName === "INPUT" || e.tagName === "TEXTAREA" || e.tagName === "SELECT" || e.closest(".tabs")) || r.height < 28)
        out.push(["tap", `${name(e)} is ${Math.round(r.width)}x${Math.round(r.height)}`]);
    }
  }
  for (const s of top.querySelectorAll("svg")) {
    if (!vis(s) || s.closest(".art, .flame, .gem, .hero-card, .web, defs") || s.classList.contains("gem")) continue;
    if (!s.closest("button, a, .btn, label, .pill, .chip, .icon-btn, .nav-card")) continue;
    const r = s.getBoundingClientRect();
    if (r.width < 12 || r.height < 12 || r.width > 36 || r.height > 36)
      out.push(["icon", `svg in ${name(s.closest("button, a, .btn, label, .pill, .chip, .icon-btn, .nav-card"))} is ${Math.round(r.width)}x${Math.round(r.height)}`]);
  }
  return out;
}
"""


def scenarios(user):
    """(name, setup(page)). Setup navigates and opens things; failures are reported, not fatal."""
    def hash_(h):
        def go(p):
            p.evaluate(f"location.hash = '{h}'")
            p.wait_for_timeout(600)
        return go

    def keepers_tab(p):
        hash_("likes")(p)
        p.click('.tabs button[data-t="keepers"]')
        p.wait_for_timeout(500)

    def export_dialog(tab=None):
        def go(p):
            keepers_tab(p)
            p.click("#kexport")
            p.wait_for_selector(".dialog")
            if tab:
                p.click(f'.dialog .tabs button[data-t="{tab}"]')
            p.wait_for_timeout(300)
        return go

    def crystallize(p):
        hash_("likes")(p)
        p.click("#crys-side")
        p.wait_for_selector(".modal", timeout=4000)
        p.wait_for_timeout(500)

    if user == "brew":
        return [("home-brewing", hash_("home")), ("swipe-brewing", hash_("swipe"))]
    return [
        ("home", hash_("home")),
        ("swipe", hash_("swipe")),
        ("likes-web", hash_("likes")),
        ("likes-keepers", keepers_tab),
        ("export-new", export_dialog()),
        ("export-update", export_dialog("upd")),
        ("export-availability", export_dialog("avail")),
        ("crystallize", crystallize),
        ("profile", hash_("profile")),
        ("vibe", hash_("vibe")),
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8099")
    ap.add_argument("--tokens", default="/tmp/kindling-ui/tokens.json")
    ap.add_argument("--out", default="specs/ui-responsive-overhaul/run")
    ap.add_argument("--viewports", default="s26-portrait,s26-portrait-chrome,s26-landscape,s26-landscape-chrome,desktop-720,desktop-1080,ultrawide")
    ap.add_argument("--only", default="", help="substring of scenario names to run")
    ap.add_argument("--fail-on", default="", help="comma list of kinds (or 'all') that make the exit code non-zero")
    ap.add_argument("--all", action="store_true", help="every viewport (the default)")
    args = ap.parse_args()

    tokens = json.loads(Path(args.tokens).read_text())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    fail_kinds = set(ALL_KINDS if args.fail_on == "all" else filter(None, args.fail_on.split(",")))
    lines, counts = [], {k: 0 for k in ALL_KINDS}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for vp in args.viewports.split(","):
            w, h, dpr, mobile = VIEWPORTS[vp]
            for user in ("main", "brew"):
                ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=dpr, is_mobile=mobile, has_touch=mobile)
                ctx.add_cookies([{"name": "orbit_session", "value": tokens[user]["token"], "url": args.url}])
                page = ctx.new_page()
                page.goto(args.url + "/#home")
                page.wait_for_timeout(800)
                for name, setup in scenarios(user):
                    if args.only and args.only not in name:
                        continue
                    tag = f"{vp} / {name}"
                    try:
                        page.evaluate("document.querySelectorAll('.dialog,.backdrop,.sheet,.modal,.viewer').forEach(e => e.remove())")
                        setup(page)
                        found = page.evaluate(CHECK_JS)
                        page.evaluate("document.querySelectorAll('*').forEach(e => e.scrollTop && (e.scrollTop = 0))")
                        page.wait_for_timeout(150)
                        page.screenshot(path=str(out / f"{vp}__{name}.png"))
                    except Exception as e:  # a scenario that can't be set up is a finding too
                        lines.append(f"{tag}: SCENARIO-ERROR {str(e).splitlines()[0][:140]}")
                        continue
                    seen = set()
                    for kind, msg in found:
                        if (kind, msg) in seen:
                            continue
                        seen.add((kind, msg))
                        counts[kind] += 1
                        lines.append(f"{tag}: {kind.upper()} {'unreachable' if kind == 'unreachable' else ''} {msg}".replace("  ", " "))
                ctx.close()
        browser.close()
    summary = "\n".join(f"{k}: {v}" for k, v in counts.items())
    (out / "report.txt").write_text("\n".join(lines) + "\n\n" + summary + "\n")
    print("\n".join(lines[:80]))
    if len(lines) > 80:
        print(f"... {len(lines) - 80} more in {out / 'report.txt'}")
    print("\n" + summary)
    bad = sum(counts[k] for k in fail_kinds)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
