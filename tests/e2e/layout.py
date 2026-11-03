"""Layout checks (clipping, overflow, unreachable, tap, icon) shared with scripts/ui-audit. Phase 3 extends them for the field."""
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
