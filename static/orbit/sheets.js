// Sheets: listing info, new planet, new batch, scores.
import { $, $$, AXIS_COLOR, AXIS_LABEL, ICON, M, api, confText, esc, h, money, sheet, toast } from "./util.js";

const CHECK = { yes: "✓", no: "✕", unsure: "?" };
const CHECK_WORD = { yes: "Yes", no: "No", unsure: "Not sure" };

export function checklistHtml(items) {
  if (!items?.length) return '<p class="empty">No checklist yet. Add one on your profile.</p>';
  return items.map((c) => `<div class="check"><div class="ic ${esc(c.status)}" aria-hidden="true">${CHECK[c.status] || "?"}</div>
    <div><b>${esc(c.item)}</b> <span class="sr">${CHECK_WORD[c.status] || ""}</span><span>${esc(c.note || "")}</span></div></div>`).join("");
}

export async function openListing(id, { onMove } = {}) {
  let l;
  try { l = await api("/o/listing/" + id); } catch (e) { return toast(e.message); }
  const pr = l.predicted != null ? Math.round(l.predicted * 100) : null;
  const place = l.placement && l.placement.r != null
    ? `<p class="sm">Placed in ${esc(M.zone(l.placement.r))}${l.planets?.length ? ", on " + esc(l.planets.map((p) => p.name).join(", ")) : ""}.</p>` : "";
  const body = `
    ${(l.photos || []).length ? `<div class="gallery">${l.photos.map((p, i) => `<img src="${esc(p)}" alt="Photo ${i + 1} of ${esc(l.title)}" loading="lazy">`).join("")}</div>` : ""}
    <div class="row" style="flex-wrap:wrap"><span class="price">${esc(money(l))}</span>${l.location_text ? `<span class="tag">${esc(l.location_text)}</span>` : ""}
      ${l.comet ? `<span class="tag comet">${ICON.comet} Comet</span>` : ""}${l.avail === "gone" ? '<span class="tag">Sold</span>' : ""}</div>
    ${place}
    <div class="stack"><span class="label" style="color:var(--dir-guess)">Claude's guess</span><p class="p" style="color:var(--ink)">${esc(l.guess)}${pr != null ? ` · predicted ${pr}%` : ""}</p>
      ${l.take ? `<p class="p">${esc(l.take)}</p>` : ""}</div>
    <div class="stack"><span class="label">Checklist</span>${checklistHtml(l.checklist)}</div>
    ${l.description ? `<div class="stack"><span class="label">Seller's words</span><p class="sm">${esc(l.description)}</p></div>` : ""}`;
  const foot = h('<div class="stack"></div>');
  if (l.url) foot.append(h(`<a class="btn" href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">Open on Marketplace</a>`));
  if (onMove && l.placement) foot.append(h('<button class="btn primary" data-move>Move here</button>'));
  const s = sheet({ title: l.title, body, foot });
  const mv = $("[data-move]", s.el);
  if (mv) mv.onclick = () => { s.close(); onMove(l.id); };
}

const ORBITS = ["Inner", "Mid", "Outer", "Belt"];
const REASONS = [["price", "Price"], ["right", "Right vibe"], ["wrong", "Wrong vibe"], ["other", "Something else"]];

export function newPlanetSheet(ctx, { onCreated, onCancel, seedName = "" } = {}) {
  let orbit = "Mid", reason = "other", picked = new Set(), timer;
  const body = h(`<div class="stack" style="gap:16px">
    <div class="field-in"><label for="pn">Name</label><input id="pn" type="text" maxlength="40" autocomplete="off" value="${esc(seedName)}"></div>
    <div class="field-in"><label for="pd">What belongs here</label><textarea id="pd" rows="2" maxlength="200" placeholder="Round, rolled arms. Fabric or leather is fine."></textarea></div>
    <div class="field-in"><span class="label">Orbit</span><div class="seg" id="po" role="group" aria-label="Orbit">${ORBITS.map((o) => `<button type="button" data-o="${o}" aria-pressed="${o === orbit}">${o}</button>`).join("")}</div></div>
    <div class="field-in"><span class="label">What's holding these back</span><div class="seg" id="pr" role="group" aria-label="Reason" style="grid-auto-flow:row;grid-template-columns:repeat(2,1fr)">${REASONS.map(([k, n]) => `<button type="button" data-r="${k}" aria-pressed="${k === reason}">${n}</button>`).join("")}</div></div>
    <div class="guessbox" id="sug" hidden><div class="hd"><span>Claude's guess</span></div><p class="sm" id="sugt"></p><div class="stack" id="sugl"></div></div>
    <p class="sm" id="perr" style="color:var(--alert)" hidden></p></div>`);
  const foot = h('<button class="btn primary" id="pmake" type="button">Create planet</button>');
  const s = sheet({ title: "New planet", body, foot, onClose: (why) => why !== "created" && onCancel && onCancel() });
  const seg = (sel, attr, set) => $$(`${sel} button`, body).forEach((b) => (b.onclick = () => { set(b.dataset[attr]); $$(`${sel} button`, body).forEach((x) => x.setAttribute("aria-pressed", x === b)); }));
  seg("#po", "o", (v) => (orbit = v));
  seg("#pr", "r", (v) => (reason = v));
  const suggest = async () => {
    const name = $("#pn", body).value, desc = $("#pd", body).value;
    if (!(name + desc).trim()) return ($("#sug", body).hidden = true);
    let list = [];
    try { list = await api(`/o/planets/suggest?name=${encodeURIComponent(name)}&description=${encodeURIComponent(desc)}`); } catch (_) { return; }
    $("#sug", body).hidden = !list.length;
    if (!list.length) return;
    picked = new Set([...picked].filter((id) => list.some((x) => x.id === id)));
    $("#sugt", body).textContent = `${list.length} listing${list.length > 1 ? "s" : ""} already look like this. Pull them in?`;
    $("#sugl", body).innerHTML = list.map((x) => `<button type="button" class="pick" data-id="${x.id}" aria-pressed="${picked.has(x.id)}">${x.photo ? `<img src="${esc(x.photo)}" alt="">` : ""}<span class="grow ellip">${esc(x.title)}</span><span class="tag">${picked.has(x.id) ? "In" : "Add"}</span></button>`).join("");
    $$(".pick", body).forEach((b) => (b.onclick = () => { const id = +b.dataset.id; picked.has(id) ? picked.delete(id) : picked.add(id); suggest(); }));
  };
  const later = () => { clearTimeout(timer); timer = setTimeout(suggest, 300); };
  $("#pn", body).oninput = later; $("#pd", body).oninput = later;
  if (seedName) suggest();
  foot.onclick = async () => {
    const err = $("#perr", body); err.hidden = true;
    try {
      const p = await api("/o/planets", { body: { name: $("#pn", body).value, description: $("#pd", body).value, orbit, reason, listing_ids: [...picked] } });
      s.close("created");
      await ctx.refresh();
      onCreated && onCreated(p);
    } catch (e) { err.textContent = e.message; err.hidden = false; }
  };
}

export function newBatchSheet(ctx, { onStarted } = {}) {
  const sys = ctx.state.system;
  let size = sys.batch_size || 15, rate = sys.comet_rate ?? 25;
  const mods = [...(ctx.state.last_modifiers || [])];
  const body = h(`<div class="stack" style="gap:16px">
    <div class="field-in"><span class="label">Listings in this batch</span><div class="row"><button class="btn" id="bm" aria-label="Fewer">−</button><b class="grow data" id="bn" style="text-align:center;font-size:20px"></b><button class="btn" id="bp" aria-label="More">+</button></div></div>
    <div class="field-in"><label for="cr">Comet rate <span class="data" id="crv"></span></label><input id="cr" type="range" min="0" max="100" step="5" value="${rate}" style="width:100%;accent-color:var(--sun)">
      <p class="sm">Comets are exploration picks, chosen to test a guess rather than to match it.</p></div>
    <div class="field-in"><label for="bx">Extras for this batch only</label><input id="bx" type="text" maxlength="60" placeholder="-used  !leather  $750  +$100  velvet" autocomplete="off">
      <div class="row" id="bxl" style="flex-wrap:wrap"></div><p class="sm">Start with - to forbid a word, ! to forbid an item, $ for a price ceiling, +$ for a floor.</p></div>
    <p class="sm" id="berr" style="color:var(--alert)" hidden></p></div>`);
  const foot = h('<button class="btn primary" id="bgo" type="button">Start batch</button>');
  const s = sheet({ title: "New batch", body, foot });
  const paint = () => {
    $("#bn", body).textContent = size; $("#crv", body).textContent = rate + "%";
    $("#bxl", body).innerHTML = mods.map((m, i) => `<button class="chip" data-i="${i}" aria-label="Remove ${esc(m)}">${esc(m)} ${ICON.close}</button>`).join("");
    $$("#bxl .chip", body).forEach((b) => (b.onclick = () => { mods.splice(+b.dataset.i, 1); paint(); }));
  };
  $("#bm", body).onclick = () => { size = Math.max(3, size - 1); paint(); };
  $("#bp", body).onclick = () => { size = Math.min(40, size + 1); paint(); };
  $("#cr", body).oninput = (e) => { rate = +e.target.value; paint(); };
  $("#bx", body).onkeydown = (e) => { if (e.key === "Enter" && e.target.value.trim()) { mods.push(e.target.value.trim()); e.target.value = ""; paint(); } };
  paint();
  foot.onclick = async () => {
    const v = $("#bx", body).value.trim(); if (v) mods.push(v);
    try {
      await api("/batches", { body: { size, weirdness: rate, modifiers: mods } });
      s.close("started");
      await ctx.refresh();
      onStarted && onStarted();
    } catch (e) { const er = $("#berr", body); er.textContent = e.message; er.hidden = false; }
  };
}

const pctText = (v) => (v == null ? "—" : Math.round(v * 100) + "%");
export function scoresSheet(ctx) {
  const sc = ctx.state.scores, c = sc.confidence, w = sc.wild_card, r = sc.rocket;
  const body = `<div class="stack" style="gap:16px">
    <div class="panelbox"><div class="between"><b>Confidence</b><span class="data" style="color:var(--dir-guess)">${esc(confText(c))}</span></div>
      <p class="sm">${c.state === "ready" ? `How close Claude's predicted rating was to yours, measured over your last ${c.n} placements (give or take ${Math.round(c.half_width * 100)} points).` :
        `Claude needs at least ${c.needed} placed predictions, and a steady enough record, before this number means anything. ${c.n} so far.`}</p></div>
    <div class="panelbox"><div class="between"><b>Wild card rate</b><span class="data">${w.state === "ready" ? pctText(w.value) : "Still learning"}</span></div>
      <p class="sm">How often you place toward Claude's guess instead of away from it. This never changes Confidence.</p></div>
    <div class="panelbox"><div class="between"><b>Rocket use</b><span class="data">${r.share == null ? "—" : pctText(r.share)}</span></div>
      <p class="sm">${r.rocketed} of ${r.placements} placements went by rocket. Rocketed listings teach Claude a quarter as much and never score a guess.</p></div></div>`;
  sheet({ title: "How Claude is doing", body });
}
