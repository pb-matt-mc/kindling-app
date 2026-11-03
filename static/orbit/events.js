// Events: Claude proposes, you confirm. One at a time, only between batches, each with the numbers behind it.
import { $, $$, ICON, api, esc, h, toast } from "./util.js";

let open = false, dismissed = new Set();

const TAG = { black_hole: ["Black hole", "sun", "blackhole"], new_star: ["New star", "sun", "sun"], dwarf_planet: ["Dwarf planet", "wrong", "planet"],
              asteroid_shower: ["Asteroid shower", "comet", "belt"], outlier: ["Outlier", "guess", "guess"] };
const thumbs = (list) => `<div class="thumbs">${(list || []).map((t) => (t.photo ? `<img src="${esc(t.photo)}" alt="${esc(t.title || "")}">` : "")).join("")}</div>`;

export async function showNextEvent(ctx, { force } = {}) {
  if (open) return;
  let ev;
  try { ev = await api("/o/events/next"); } catch (_) { return; }
  if (!ev || (!force && dismissed.has(ev.id))) return;
  open = true;
  const [label, tagClass, icon] = TAG[ev.kind] || ["Event", "", "guess"];
  const root = h(`<section class="event${ev.kind === "black_hole" ? " deep" : ""}" role="dialog" aria-modal="true" aria-label="${esc(ev.title)}"><div class="inner">
    <div class="between"><span class="tag ${tagClass}">${ICON[icon] || ""}${esc(label)}</span><button class="btn ghost small" data-later aria-label="Not now">${ICON.close}</button></div>
    ${ev.kind === "black_hole" ? `<div class="bhwrap" aria-hidden="true"><svg viewBox="0 0 390 120" preserveAspectRatio="xMidYMid meet"><g class="spin"><ellipse cx="195" cy="60" rx="186" ry="40" fill="none" stroke="#FFC933" stroke-width="2" stroke-dasharray="40 10 6 22" transform="rotate(-8 195 60)"/><ellipse cx="195" cy="60" rx="140" ry="30" fill="none" stroke="#FF9A4D" stroke-width="3" stroke-dasharray="70 14 12 30" transform="rotate(-8 195 60)"/></g><g class="spin b"><ellipse cx="195" cy="60" rx="96" ry="22" fill="none" stroke="#FFF1B8" stroke-width="3" stroke-dasharray="90 24" transform="rotate(-8 195 60)"/></g></svg></div>` : ""}
    <h1 class="h1">${esc(ev.title)}</h1><p class="p">${esc(ev.body)}</p>
    <div id="evbody" class="stack" style="gap:12px"></div>
    <p class="sm" id="evbasis"></p><p class="sm" id="everr" style="color:var(--alert)" hidden></p>
    <div id="evacts" class="stack"></div></div></section>`);
  document.body.append(root);
  const body = $("#evbody", root), acts = $("#evacts", root);
  $("#evbasis", root).textContent = ev.basis ? `Measured: ${ev.basis}.` : "";
  const finish = (msg) => { root.remove(); open = false; if (msg) toast(msg); ctx.refresh().then(() => { if (!location.hash.startsWith("#move")) location.hash = location.hash || "#place"; }); };
  const answer = async (action, extra = {}, msg) => {
    try {
      const res = await api(`/o/events/${ev.id}/resolve`, { body: { action, ...extra } });
      root.remove(); open = false; if (msg) toast(msg);
      await ctx.refresh();
      if (res.move) location.hash = "#move/" + res.move; else if (res.system_id) location.hash = "#place";
      else window.dispatchEvent(new HashChangeEvent("hashchange"));
    } catch (e) { const er = $("#everr", root); er.textContent = e.message; er.hidden = false; }
  };
  const btn = (label, cls, fn) => { const b = h(`<button class="btn ${cls}">${label}</button>`); b.onclick = fn; acts.append(b); return b; };
  $("[data-later]", root).onclick = () => { dismissed.add(ev.id); root.remove(); open = false; };
  document.addEventListener("keydown", function esc_(e) { if (e.key === "Escape" && root.isConnected) { dismissed.add(ev.id); root.remove(); open = false; document.removeEventListener("keydown", esc_); } });

  if (ev.kind === "black_hole") {
    body.innerHTML = `<div class="tiles">${ev.groups.map((g, i) => `<div class="tile">${thumbs(g.thumbs)}<div class="field-in"><label class="sr" for="sn${i}">Name of sun ${i + 1}</label><input id="sn${i}" type="text" maxlength="40" value="${esc(g.name)}"></div><div class="data" style="color:var(--ink-muted)">${g.n} listings</div></div>`).join("")}</div>`;
    const names = () => [$("#sn0", root).value.trim(), $("#sn1", root).value.trim()];
    btn("Make a binary star", "primary", () => answer("binary", { name: names()[0] }, "Two suns, one hunt"));
    btn("Split into a second system", "", () => answer("split", { name: names()[1] }, "Second system created"));
    btn("Keep one sun", "ghost", () => answer("keep"));
    $("#sn0", root).addEventListener("change", () => {});
  } else if (ev.kind === "new_star") {
    body.innerHTML = `<div class="grp">${thumbs(ev.thumbs)}<div><div class="h3">${ev.n} listings</div><div class="sm">${esc(ev.tag.split(":")[1])}</div></div></div>`;
    btn("Make it a new system", "primary", () => answer("system", {}, "New system created"));
    btn("Make it a planet", "", () => answer("planet", {}, "Planet created"));
    btn("Not a star", "ghost", () => answer("dismiss"));
  } else if (ev.kind === "dwarf_planet") {
    body.innerHTML = `<div class="guessbox"><div class="hd"><span>Claude's guess</span></div><p>This was curiosity, not taste. Move it out toward the belt.</p></div><p class="sm">Your answer teaches Claude how much to trust this kind of guess.</p>`;
    btn("Move out", "guess", () => answer("out", {}, `${esc(ev.planet)} moved out`));
    btn("Move in", "", () => answer("in", {}, `${esc(ev.planet)} moved in`));
    btn("Leave it", "ghost", () => answer("leave"));
  } else if (ev.kind === "asteroid_shower") {
    body.innerHTML = `<div class="between"><span class="data" style="color:var(--ink-muted)">Belt ${ev.belt}/${ev.cap}</span></div>
      <div class="grp">${thumbs(ev.burn)}<div class="grow"><div class="h3">${ev.explained} burn up</div><div class="sm">Well explained${ev.why.length ? ": " + esc(ev.why.join(", ")) : ""}</div></div></div>
      <div class="grp">${thumbs(ev.stay)}<div class="grow"><div class="h3">${ev.unexplained} stay for now</div><div class="sm">Claude can't explain these yet</div></div></div>
      ${ev.group ? `<div class="guessbox"><div class="hd"><span>Claude's guess</span></div><div class="row">${thumbs(ev.group.thumbs)}<span class="sm">${ev.group.n} of these landed together. Make them a planet and say why?</span></div></div>` : ""}`;
    btn("Not yet", "", () => answer("not_yet"));
    btn(`Forget ${ev.explained}`, "danger", () => answer("forget", {}, `${ev.explained} forgotten. What they taught stays.`));
    if (ev.group) btn(`Forget ${ev.explained} and make a planet`, "primary", () => answer("forget_and_planet", {}, "Forgotten, and a planet made"));
  } else if (ev.kind === "outlier") {
    body.innerHTML = `<div class="grp">${thumbs([ev.listing])}<div class="grow"><div class="h3 ellip">${esc(ev.listing.title || "")}</div><div class="sm">Expected about ${Math.round(ev.predicted * 100)}. You said ${Math.round(ev.actual * 100)}.</div></div></div>`;
    btn("A real change of taste", "primary", () => answer("real", {}, "Noted"));
    btn("Just curious", "", () => answer("curious", {}, "It will count for half"));
    btn("That was a slip: move it", "ghost", () => answer("mistake"));
  }
  (acts.querySelector("button") || $("[data-later]", root)).focus({ preventScroll: true });
}
