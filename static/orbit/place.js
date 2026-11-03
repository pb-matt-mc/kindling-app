// The Place screen: a listing floats at the sun; drag it onto the field, let go to rest it, tap Place here to commit.
// All geometry is the handoff prototype's 390x844 frame (sun at 195,384, field radius 186), scaled to the stage.
import { $, $$, AXIS_COLOR, AXIS_LABEL, ICON, M, api, confText, esc, h, haptic, money, splitText, toast, topReason } from "./util.js";
import { newBatchSheet, newPlanetSheet, openListing, scoresSheet } from "./sheets.js";

export const VB = { x0: 0, y0: 160, w: 390, h: 440 };
export const C = { x: 195, y: 384, R: 186 };
const MOVE_PX = 12;

export const BG = `<svg class="bg" viewBox="${VB.x0} ${VB.y0} ${VB.w} ${VB.h}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
  <path d="M195 354V208M195 414V560M165 384H19M225 384H371" stroke="#3A4CA0" fill="none"/>
  <circle cx="195" cy="384" r="62" fill="none" stroke="#F6DC8E" stroke-width="1.25"/>
  <circle cx="195" cy="384" r="98" fill="none" stroke="#E3DDB8" opacity=".75"/>
  <circle cx="195" cy="384" r="116" fill="none" stroke="#8FE3FF" stroke-width="1.5" stroke-dasharray="1 7" stroke-linecap="round"/>
  <circle cx="195" cy="384" r="146" fill="none" stroke="#8FA0DC"/>
  <circle cx="195" cy="384" r="176" fill="none" stroke="#7F89BA" stroke-width="3" stroke-dasharray="1 11" stroke-linecap="round"/>
  <circle cx="195" cy="384" r="170" fill="none" stroke="#7F89BA" stroke-width="2" stroke-dasharray="1 17" stroke-linecap="round" opacity=".7"/>
  <polygon id="poly" points="" fill-opacity=".28" stroke-width="1.5" stroke-linejoin="round"/>
  <g id="ghost" hidden><circle id="gring" class="ghostring" cx="195" cy="384" r="0"/><line id="gline" stroke="#D4F54A" stroke-width="1.5" stroke-dasharray="3 5"/></g>
  <circle cx="195" cy="384" r="30" fill="#FFC933"/><circle cx="195" cy="384" r="16" fill="#FFF1B8"/></svg>`;

export function mountPlace(main, ctx, { moveId } = {}) {
  main.innerHTML = `
    <header class="top">
      <img class="mark" src="/static/icons/orbit-mark.svg" alt="" width="32" height="32">
      <a class="chip grow" href="#galaxy" style="min-width:0;justify-content:flex-start" aria-label="Systems"><i></i><span class="ellip" id="sysname"></span></a>
      <button class="btn ghost small" id="undo" aria-label="Undo last placement" hidden>${ICON.undo}<span class="data">Undo</span></button>
      <button class="btn ghost small" id="conf" aria-label="How Claude is doing"><span class="data" id="conftxt"></span></button>
      <span class="data" id="count" style="color:var(--ink-muted)"></span>
    </header>
    <div class="place">
      <div class="stage" id="stage">
        ${BG}
        <div class="blend" id="blend"></div>
        <div class="lab label" data-ax="price" style="color:var(--dir-price)">${ICON.price}Price</div>
        <div class="lab label v" data-ax="wrong" style="color:var(--dir-wrong)">${ICON.wrong}Wrong vibe</div>
        <div class="lab label v" data-ax="right" style="color:var(--dir-right)">${ICON.right}Right vibe</div>
        <div class="lab label" data-ax="guess" style="color:var(--dir-guess)">${ICON.guess}<span class="gtxt" id="gtxt"></span></div>
        <div id="dots"></div>
        <div class="readout" id="readout" hidden><div><span id="rd1"></span><span id="rd2"></span></div></div>
        <div class="card float" id="card" hidden><img alt=""><div class="tx"><div class="tt"></div><div class="between"><span class="pr"></span><span class="lo"></span></div></div></div>
        <img class="thumb" id="thumb" alt="" hidden>
        <button class="rocket" id="rocket" aria-label="Rocket: send this listing to a planet" aria-haspopup="true">${ICON.rocket}<small>Rocket</small></button>
        <div class="drawer" id="drawer" role="menu" aria-label="Your planets" hidden></div>
        <button class="second-sun" id="sun2" aria-label="Switch to the other sun" hidden><span></span></button>
        <div id="center" style="position:absolute;inset:0;display:none;align-items:center;justify-content:center;text-align:center;padding:24px 56px;pointer-events:none"></div>
      </div>
      <div class="panel" id="panel"></div>
    </div>`;
  const stage = $("#stage", main), card = $("#card", main), thumb = $("#thumb", main), rocketEl = $("#rocket", main), drawer = $("#drawer", main),
    panel = $("#panel", main), sun2 = $("#sun2", main), readout = $("#readout", main), blendEl = $("#blend", main);
  const labs = Object.fromEntries($$(".lab", stage).map((l) => [l.dataset.ax, l]));

  // ---- state ----
  const S = { sun: 0, phase: "idle", listing: null, r: 0, theta: -Math.PI / 2, from: "idle", origin: null, start: null, moved: false,
              hot: false, pinned: false, over: null, result: null, busy: false, sun2hot: false, count: 0 };
  let g = null, alive = true, pollTimer = null;
  const isMove = !!moveId;

  const queue = () => ctx.state.queue;
  const hasListing = () => !!S.listing;

  async function pickListing() {
    if (isMove) {
      try { S.listing = await api("/o/listing/" + moveId); } catch (e) { toast(e.message); location.hash = "#system"; return; }
      const p = S.listing.placement;
      S.r = p ? p.r : 0.5; S.theta = p && p.theta != null ? p.theta : -Math.PI / 2;
      S.phase = "parked"; S.from = "parked"; S.origin = { r: S.r, theta: S.theta };
      S.sun = S.listing.placement && S.listing.placement.sun ? S.listing.placement.sun : 0;
    } else {
      S.listing = queue()[0] || null;
      S.sun = S.listing && S.listing.sun_guess ? S.listing.sun_guess : 0;
      S.phase = "idle"; S.r = 0; S.theta = -Math.PI / 2; S.result = null;
    }
    S.hot = false; S.pinned = false;
  }

  // ---- geometry ----
  function geom() {
    const W = stage.clientWidth, H = stage.clientHeight;
    const k = Math.min(W / VB.w, H / VB.h);
    const ox = (W - VB.w * k) / 2, oy = (H - VB.h * k) / 2;
    g = { W, H, k, ox, oy };
  }
  const px = (vx, vy) => ({ x: g.ox + (vx - VB.x0) * g.k, y: g.oy + (vy - VB.y0) * g.k });
  const vb = (x, y) => ({ x: (x - g.ox) / g.k + VB.x0, y: (y - g.oy) / g.k + VB.y0 });
  const fieldPx = (r, th) => px(C.x + C.R * r * Math.cos(th), C.y + C.R * r * Math.sin(th));
  const place_ = (el, cx, cy, w, hh = w) => { el.style.left = cx - w / 2 + "px"; el.style.top = cy - hh / 2 + "px"; el.style.width = w + "px"; if (hh !== undefined) el.style.height = hh + "px"; };
  const clampIn = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  // ---- painting ----
  function paintHeader() {
    const s = ctx.state;
    $("#sysname", main).textContent = s.system.binary ? `${s.system.name} · ${s.system.binary.names[S.sun] || ""}` : s.system.name;
    $("#conftxt", main).textContent = confText(s.scores.confidence);
    $("#conftxt", main).style.color = s.scores.confidence.state === "ready" ? "var(--dir-guess)" : "var(--ink-muted)";
    const total = s.batch_total, done = total ? total - queue().length : 0;
    $("#count", main).textContent = isMove ? "" : total && s.batch ? `${Math.min(done + (S.phase === "placed" ? 0 : 1), total)}/${total}` : "";
    $("#undo", main).hidden = !s.last_placement || isMove;
  }

  function guessText() { return S.listing ? S.listing.guess : "Claude's guess"; }

  function paint() {
    if (!alive) return;
    geom();
    paintHeader();
    const L = S.listing, live = S.phase === "held" || S.phase === "parked";
    // field blend ring and labels
    const bs = px(C.x, C.y), br = 176 * g.k;
    blendEl.style.cssText = `left:${bs.x - br}px;top:${bs.y - br}px;width:${2 * br}px;height:${2 * br}px`;
    const lp = (el, vx, vy) => { const p = px(vx, vy); el.style.left = p.x + "px"; el.style.top = p.y + "px"; };
    lp(labs.price, 195, 176); lp(labs.guess, 195, 576); lp(labs.wrong, 10, 384); lp(labs.right, 380, 384);
    labs.price.style.transform = "translate(-50%,-50%)"; labs.guess.style.transform = "translate(-50%,-50%)";
    labs.wrong.style.transform = "translate(-50%,-50%) rotate(180deg)"; labs.right.style.transform = "translate(-50%,-50%)";
    labs.guess.style.maxWidth = Math.max(80, g.W - 150) + "px";
    $("#gtxt", main).textContent = guessText();
    const b = M.blend(S.r, S.theta);
    for (const k of M.AXIS_NAMES) labs[k].style.opacity = live && b.zone !== "Sun" ? (0.5 + 0.5 * b.reasons[k]).toFixed(2) : 1;
    // blend polygon
    const poly = $("#poly", main);
    if (live && b.zone !== "Sun" && S.r > 0.02) {
      const mx = Math.max(...M.AXIS_NAMES.map((k) => b.reasons[k])) || 1;
      poly.setAttribute("points", M.AXES.map(([k, a]) => `${(C.x + Math.cos(a) * C.R * S.r * b.reasons[k] / mx).toFixed(1)},${(C.y + Math.sin(a) * C.R * S.r * b.reasons[k] / mx).toFixed(1)}`).join(" "));
      const col = AXIS_COLOR[M.dominantAxis(b.reasons)];
      poly.style.fill = col; poly.style.stroke = col;
    } else poly.setAttribute("points", "");
    // readout
    readout.hidden = !live || !L;
    if (live && L) {
      $("#rd1", main).textContent = b.zone === "Sun" ? "Sun" : `${b.zone} · ${b.like ? "like" : "pass"}`;
      $("#rd2", main).textContent = b.zone === "Sun" ? "No complaints" : splitText(b.percents).replace(/Claude's guess/g, L.guess);
    }
    // the listing: card while idle, a round thumbnail once picked up
    const cw = Math.min(240 * g.k, g.W - 24), ch = Math.min(336 * g.k, g.H - 24);
    card.hidden = !(L && S.phase === "idle");
    if (!card.hidden) {
      const c = px(C.x, C.y + 8);
      place_(card, c.x, c.y, cw, ch);
      $("img", card).src = (L.photos || [])[0] || ""; $("img", card).alt = L.title;
      $(".tt", card).textContent = L.title; $(".pr", card).textContent = money(L); $(".lo", card).textContent = L.location_text || "";
      let badge = $(".cometbadge", card);
      if (L.comet && !badge) card.append(h(`<span class="tag comet cometbadge">${ICON.comet} Comet</span>`));
      if (!L.comet && badge) badge.remove();
    }
    const showThumb = L && (S.phase === "held" || S.phase === "parked" || S.phase === "placed" || S.phase === "rocket");
    thumb.hidden = !showThumb;
    if (showThumb) {
      const ts = clampIn(56 * g.k, 40, 64);
      let pos = fieldPx(S.r, S.theta);
      if (S.phase === "rocket") pos = rocketCenter();
      place_(thumb, pos.x, pos.y, S.phase === "rocket" ? ts * 0.6 : ts);
      thumb.src = (L.photos || [])[0] || ""; thumb.alt = `${L.title}, ${S.phase === "placed" ? "placed" : "resting on the field"}`;
      thumb.classList.toggle("float", S.phase === "parked");
      thumb.style.transition = S.phase === "held" ? "none" : "left .2s var(--ease), top .2s var(--ease), width .2s var(--ease), height .2s var(--ease)";
    }
    // Claude's guess after placing: a dashed ring at the predicted rating and a line to where you put it
    const gh = $("#ghost", main), res = S.result;
    gh.hidden = !(S.phase === "placed" && res && res.compare);
    if (!gh.hidden) {
      const pr = res.compare.predicted_r;
      $("#gring", main).setAttribute("r", (C.R * pr).toFixed(1));
      const you = { x: C.x + C.R * S.r * Math.cos(S.theta), y: C.y + C.R * S.r * Math.sin(S.theta) };
      const ang = S.r > 0.02 ? S.theta : -Math.PI / 2;
      const gp = { x: C.x + C.R * pr * Math.cos(ang), y: C.y + C.R * pr * Math.sin(ang) };
      const ln = $("#gline", main);
      ln.setAttribute("x1", gp.x); ln.setAttribute("y1", gp.y); ln.setAttribute("x2", you.x); ln.setAttribute("y2", you.y);
    }
    paintDots();
    paintRocket();
    paintCenter();
    paintPanel();
  }

  function rocketCenter() {
    const c = px(345, 548), half = 32;
    return { x: clampIn(c.x, half + 4, g.W - half - 4), y: clampIn(c.y, half + 4, g.H - half - 20) };
  }

  function paintRocket() {
    const c = rocketCenter();
    place_(rocketEl, c.x, c.y, 64);
    rocketEl.classList.toggle("hot", S.hot || S.pinned);
    rocketEl.classList.toggle("blast", S.hot || S.pinned);
    rocketEl.hidden = isMove || !hasListing();
    const open = (S.hot || S.pinned) && !rocketEl.hidden;
    drawer.hidden = !open;
    if (open) {
      const planets = ctx.state.planets;
      const key = planets.map((p) => p.id + p.name + p.moons).join("|");
      if (drawer.dataset.key !== key) {
        drawer.dataset.key = key;
        drawer.innerHTML = `<button class="btn ghost small close" data-close aria-label="Close planets">${ICON.close}</button>` +
          planets.map((p) => `<button class="item" role="menuitem" data-planet="${p.id}">${ICON.planet}<span class="grow"><b>${esc(p.name)}</b><small>${p.moons} moon${p.moons === 1 ? "" : "s"} · ${esc(p.zone)}</small></span></button>`).join("") +
          `<button class="item new" role="menuitem" data-new>${ICON.plus}<span class="grow"><b>New planet</b></span></button>`;
        $$("[data-planet]", drawer).forEach((b) => (b.onclick = () => rocketTo(+b.dataset.planet)));
        $("[data-new]", drawer).onclick = () => startNewPlanet();
        $("[data-close]", drawer).onclick = dismissRocket;
      }
      const w = Math.min(230, c.x - 32 - 16), right = g.W - (c.x - 32 - 8);
      drawer.style.width = Math.max(150, w) + "px"; drawer.style.right = Math.max(4, right) + "px";
      drawer.style.bottom = Math.max(4, g.H - (c.y + 32)) + "px"; drawer.style.maxHeight = (g.H - 16) + "px";
      $$(".item", drawer).forEach((it) => it.classList.toggle("over", S.over === it.dataset.planet || (S.over === "new" && it.hasAttribute("data-new"))));
    }
    // second sun (binary stars)
    const bin = ctx.state.system.binary;
    sun2.hidden = !bin || isMove || !hasListing();
    if (!sun2.hidden) {
      const sc = px(48, 548), sz = clampIn(46 * g.k, 36, 52);
      place_(sun2, clampIn(sc.x, sz / 2 + 4, g.W), clampIn(sc.y, sz / 2 + 4, g.H - sz / 2 - 18), sz);
      $("span", sun2).textContent = bin.names[1 - S.sun] || "Other sun";
      sun2.classList.toggle("hot", S.sun2hot);
    }
  }

  function paintDots() {
    const el = $("#dots", main);
    const bin = ctx.state.system.binary;
    const placed = ctx.state.placed.filter((p) => p.id !== (S.listing && S.listing.id) && (!bin || (p.sun || 0) === S.sun));
    const d = clampIn(11 * g.k, 8, 14), marker = d / (C.R * g.k);
    const items = placed.map((p) => {
      const q = p.zone === "Sun" ? (p.theta != null ? p.theta : p.id * 2.399963) : (p.theta != null ? p.theta : p.id * 2.399963);
      return { id: p.id, x: p.r * Math.cos(q), y: p.r * Math.sin(q), p };
    });
    const out = M.fanOut(items, marker, 12);
    const byId = Object.fromEntries(items.map((i) => [i.id, i.p]));
    const html = [];
    for (const it of out.placed) {
      const p = byId[it.id], pos = px(C.x + C.R * it.x, C.y + C.R * it.y);
      const col = p.zone === "Sun" ? "var(--sun)" : p.reasons ? AXIS_COLOR[M.dominantAxis(p.reasons)] : "var(--ink-faint)";
      html.push(`<i class="dot" style="left:${(pos.x - d / 2).toFixed(1)}px;top:${(pos.y - d / 2).toFixed(1)}px;width:${d}px;height:${d}px;background:${col};opacity:${p.gone ? .35 : 1}"></i>`);
    }
    for (const c of out.collapsed) {
      const pos = px(C.x + C.R * c.x, C.y + C.R * c.y);
      html.push(`<i class="dot" style="left:${(pos.x - d).toFixed(1)}px;top:${(pos.y - d).toFixed(1)}px;width:${2 * d}px;height:${2 * d}px;background:var(--sun);display:grid;place-items:center;font:500 9px/1 var(--font-mono);color:var(--on-color)">+${c.ids.length}</i>`);
    }
    const sig = html.join("");
    if (el.dataset.sig !== sig) { el.dataset.sig = sig; el.innerHTML = sig; }
  }

  function paintCenter() {
    const el = $("#center", main), b = ctx.state.batch;
    let html = "";
    if (!hasListing() && !isMove) {
      if (b && ["queued", "searching", "screening", "scoring"].includes(b.status)) html = `<div class="stack" style="align-items:center"><div class="spinner" role="status" aria-label="Building a batch"></div><p class="p">${esc(b.progress || "Starting")}</p></div>`;
      else if (b && b.status === "error") html = `<div class="stack" style="align-items:center"><p class="h3">That batch didn't finish</p><p class="sm">${esc(b.error || "")}</p></div>`;
      else html = `<div class="stack" style="align-items:center"><p class="h3">Nothing floating right now</p><p class="sm">Start a batch and listings will drift in.</p></div>`;
    }
    el.style.display = html ? "flex" : "none";
    if (el.dataset.sig !== html) { el.dataset.sig = html; el.innerHTML = html; }
  }

  function paintPanel() {
    const L = S.listing, b = ctx.state.batch;
    let html = "", wire = () => {};
    if (!L && !isMove) {
      const busy = b && ["queued", "searching", "screening", "scoring"].includes(b.status);
      html = busy ? '<p class="sm" style="text-align:center">You can leave this screen. Your batch keeps building.</p>'
        : `<button class="btn primary" id="newbatch">${b && b.status === "error" ? "Try again" : "New batch"}</button>`;
      wire = () => { const nb = $("#newbatch", panel); if (nb) nb.onclick = () => newBatchSheet(ctx, { onStarted: () => poll() }); };
    } else if (S.phase === "idle") {
      html = '<p class="sm" style="text-align:center">Hold and drag. Let go to think it over. Nothing counts until you tap Place here.</p>';
    } else if (S.phase === "held") {
      html = `<div class="stack" style="text-align:center;gap:2px"><div class="h3 ellip">${esc(L.title)}</div><div class="data" style="color:var(--sun)">${esc(money(L))}</div></div>`;
    } else if (S.phase === "parked") {
      html = `<div class="between"><span class="h3 ellip grow">${esc(L.title)}</span><span class="data" style="color:var(--sun)">${esc(money(L))}</span></div>
        <div class="acts"><button class="btn" id="back">${isMove ? "Cancel" : "Back to listing"}</button><button class="btn primary" id="placehere"${S.busy ? " disabled" : ""}>Place here</button></div>`;
      wire = () => { $("#back", panel).onclick = backToListing; $("#placehere", panel).onclick = placeHere; };
    } else if (S.phase === "rocket") {
      html = `<p class="sm" style="text-align:center">Choose a planet for ${esc(L.title)}.</p><button class="btn" id="cancelrocket">Never mind</button>`;
      wire = () => { $("#cancelrocket", panel).onclick = dismissRocket; };
    } else if (S.phase === "placed") {
      const r = S.result, cmp = r.compare;
      const b0 = M.blend(S.r, S.theta);
      let head, sub;
      if (r.kind === "rocket") { head = `Sent to ${r.planet}`; sub = "Rocketed listings teach a little and never score Claude's guess."; }
      else if (cmp) {
        head = cmp.verdict;
        sub = `Claude guessed ${M.zone(cmp.predicted_r)}, mostly ${esc(cmp.guess || "a hunch")}. You said ${b0.zone === "Sun" ? "the Sun" : b0.zone + ", mostly " + esc(topReason(b0.percents, L.guess))}.`;
      } else { head = isMove ? "Moved" : "Placed"; sub = isMove || r.kind === "move" ? "Later moves update your taste but don't re-score Claude." : "No prediction was recorded for this one, so it doesn't count toward Confidence."; }
      const bin2 = ctx.state.system.binary;
      if (bin2 && L.sun_guess != null && !isMove) sub += ` Claude started this on ${esc(bin2.names[L.sun_guess])}${(S.sun || 0) === L.sun_guess ? ", and you kept it there" : ", and you moved it to " + esc(bin2.names[S.sun])}.`;
      const conf = r.scores && r.scores.confidence;
      html = `<div class="guessbox"><div class="hd"><span>${esc(head)}</span><span>${esc(conf ? confText(conf) : "")}</span></div><p>${sub}</p>
        <div class="acts" style="grid-template-columns:1fr 2fr"><button class="btn" id="undo2">${ICON.undo} Undo</button><button class="btn guess" id="next">${nextLabel()}</button></div></div>`;
      wire = () => { $("#undo2", panel).onclick = undoLast; $("#next", panel).onclick = next; };
    }
    if (panel.dataset.sig !== html + S.busy) { panel.dataset.sig = html + S.busy; panel.innerHTML = html; wire(); }
  }
  const nextLabel = () => (isMove ? "Done" : queue().length ? "Next listing" : "Finish batch");

  // ---- pointer handling ----
  const rect = (el) => el.getBoundingClientRect();
  const inRect = (r, x, y, pad = 0) => x >= r.left - pad && x <= r.right + pad && y >= r.top - pad && y <= r.bottom + pad;

  function onDown(e) {
    if (e.button > 0 || S.busy) return;
    const L = S.listing;
    if (!L) return;
    const sr = rect(stage), x = e.clientX, y = e.clientY;
    if (S.phase === "idle" && !card.hidden && inRect(rect(card), x, y)) {
      S.from = "idle"; S.origin = { r: 0, theta: -Math.PI / 2 };
    } else if (S.phase === "parked" && !thumb.hidden && inRect(rect(thumb), x, y, 14)) {
      S.from = "parked"; S.origin = { r: S.r, theta: S.theta };
    } else if (S.phase === "rocket" && !thumb.hidden && inRect(rect(thumb), x, y, 10)) {
      return;
    } else return;
    S.start = { x, y, ox: fieldPx(S.origin.r, S.origin.theta), rr: sr };
    S.moved = false;
    try { stage.setPointerCapture(e.pointerId); } catch (_) { /* some touch browsers refuse; the move events still arrive */ }
    S.phase = "held"; S.r = S.origin.r; S.theta = S.origin.theta; S.pinned = false;
    haptic(8);
    paint();
    e.preventDefault();
  }

  function overWhat(x, y) {
    const els = document.elementsFromPoint(x, y);
    const it = els.find((n) => n.closest && n.closest(".drawer .item"));
    if (it) { const i = it.closest(".item"); return i.hasAttribute("data-new") ? "new" : i.dataset.planet; }
    if (inRect(rect(rocketEl), x, y, 10)) return "rocket";
    if (!sun2.hidden && inRect(rect(sun2), x, y, 10)) return "sun2";
    if (!drawer.hidden && inRect(rect(drawer), x, y)) return "drawer";
    return null;
  }

  function onMove(e) {
    if (S.phase !== "held" || !S.start) return;
    const mx = e.clientX - S.start.x, my = e.clientY - S.start.y;
    if (Math.hypot(mx, my) > MOVE_PX) S.moved = true;
    // new thumb centre in stage pixels, then to field units about the sun (clamped to the field edge)
    const c0 = px(C.x, C.y), cx = S.start.ox.x + mx, cy = S.start.ox.y + my;
    const [r, th] = M.polar((cx - c0.x) / (C.R * g.k), (cy - c0.y) / (C.R * g.k));
    S.r = r; S.theta = th;
    const o = overWhat(e.clientX, e.clientY);
    const wasHot = S.hot;
    S.hot = !!o && o !== "sun2";                                  // over the rocket, its drawer, or a planet in it
    S.over = o && !["rocket", "drawer", "sun2"].includes(o) ? o : null;
    S.sun2hot = o === "sun2";
    if (S.hot && !wasHot) haptic(12, rocketEl);
    paint();
    e.preventDefault();
  }

  function onUp(e) {
    if (S.phase !== "held") return;
    try { stage.releasePointerCapture(e.pointerId); } catch (_) { /* already released */ }
    const o = overWhat(e.clientX, e.clientY);
    const target = S.over;
    S.start = null; S.sun2hot = false; S.droppedAt = performance.now();   // the click that follows a drag must not count as a tap
    if (e.type === "pointercancel") return restoreOrigin();
    if (target === "new") { S.phase = "rocket"; S.pinned = true; S.over = null; startNewPlanet(); return paint(); }
    if (target) { S.over = null; return rocketTo(+target); }
    if (o === "rocket" || o === "drawer") { S.phase = "rocket"; S.pinned = true; S.hot = false; S.over = null; haptic(10); return paint(); }
    if (o === "sun2") { S.hot = false; return switchSun(); }
    S.hot = false; S.over = null;
    if (!S.moved) {
      restoreOrigin();
      if (S.listing) openListing(S.listing.id);
      return;
    }
    S.phase = "parked";
    haptic(6);
    paint();
  }

  function restoreOrigin() {
    S.phase = S.from; S.r = S.origin.r; S.theta = S.origin.theta; S.hot = false; S.pinned = false; S.over = null;
    paint();
  }
  function backToListing() { S.phase = "idle"; S.r = 0; S.theta = -Math.PI / 2; S.hot = false; paint(); }
  function dismissRocket() {
    S.pinned = false; S.hot = false; S.over = null;
    S.phase = S.from === "parked" ? "parked" : "idle";
    S.r = S.origin ? S.origin.r : 0; S.theta = S.origin ? S.origin.theta : -Math.PI / 2;
    paint();
  }

  // ---- actions ----
  async function placeHere() {
    if (S.busy || !S.listing) return;
    S.busy = true; paintPanel();
    try {
      const res = await api("/o/place", { body: { listing_id: S.listing.id, r: S.r, theta: S.theta, sun: S.sun || 0 } });
      S.result = { kind: res.placement.kind, compare: res.compare, scores: res.scores, batch_done: res.batch_done };
      S.phase = "placed";
      haptic([14, 40, 14], thumb);
      await ctx.refresh({ keepQueue: true });
      if (isMove) toast("Moved");
    } catch (e) { toast(e.message); }
    S.busy = false; paint();
  }

  async function rocketTo(planetId) {
    if (S.busy || !S.listing) return;
    S.busy = true;
    try {
      const res = await api("/o/rocket", { body: { listing_id: S.listing.id, planet_id: planetId } });
      S.result = { kind: "rocket", planet: res.planet, scores: res.scores, batch_done: res.batch_done };
      S.phase = "placed"; S.hot = false; S.pinned = false; S.over = null;
      const pl = ctx.state.planets.find((p) => p.id === planetId);
      if (pl) { S.r = pl.r; S.theta = pl.theta != null ? pl.theta : -Math.PI / 2; }
      haptic([10, 30, 10, 30, 10], rocketEl);
      await ctx.refresh({ keepQueue: true });
    } catch (e) { toast(e.message); S.hot = false; S.pinned = false; restoreOrigin(); }
    S.busy = false; paint();
  }

  function startNewPlanet() {
    newPlanetSheet(ctx, { onCreated: (p) => rocketTo(p.id), onCancel: dismissRocket });
  }

  async function switchSun() { // binary stars: dragging onto the other sun switches fields (see binary.js)
    const mod = await import("./binary.js");
    S.sun2hot = false;
    await mod.switchSun(ctx, S, { paint, restoreOrigin });
  }

  async function next() {
    if (isMove) { location.hash = "#system"; return; }
    const done = S.result && S.result.batch_done;
    await ctx.refresh();
    if (done && !queue().length) { ctx.afterBatch && ctx.afterBatch(); return; }
    await pickListing();
    paint();
  }

  async function undoLast() {
    const lp = ctx.state.last_placement;
    if (!lp) return;
    try {
      await api("/o/undo", { body: { placement_id: lp.id } });
      haptic(12);
      toast("Undone");
      await ctx.refresh();
      await pickListing();
      if (isMove) { location.hash = "#system"; return; }
    } catch (e) { toast(e.message); }
    paint();
  }

  // ---- wiring ----
  stage.addEventListener("pointerdown", onDown);
  stage.addEventListener("pointermove", onMove);
  stage.addEventListener("pointerup", onUp);
  stage.addEventListener("pointercancel", onUp);
  stage.addEventListener("contextmenu", (e) => e.preventDefault());
  const justDropped = () => S.droppedAt && performance.now() - S.droppedAt < 350;
  stage.addEventListener("click", (e) => {   // tapping the empty field while the drawer is pinned dismisses it
    if (justDropped()) return;
    if (S.phase === "rocket" && !e.target.closest(".drawer") && !e.target.closest(".rocket") && !e.target.closest(".thumb")) dismissRocket();
  });
  rocketEl.addEventListener("click", () => {  // keyboard and tap: the rocket itself opens the drawer when a listing is waiting
    if (!hasListing() || S.phase === "held" || justDropped()) return;
    if (S.phase === "rocket") return dismissRocket();
    S.from = S.phase === "parked" ? "parked" : "idle";
    S.origin = { r: S.phase === "parked" ? S.r : 0, theta: S.phase === "parked" ? S.theta : -Math.PI / 2 };
    S.phase = "rocket"; S.pinned = true; haptic(10, rocketEl); paint();
  });
  const onKey = (e) => { if (e.key === "Escape" && (S.phase === "rocket")) dismissRocket(); };
  document.addEventListener("keydown", onKey);
  $("#conf", main).onclick = () => scoresSheet(ctx);
  $("#undo", main).onclick = undoLast;
  const ro = new ResizeObserver(() => paint());
  ro.observe(stage);

  function poll() {
    clearTimeout(pollTimer);
    const b = ctx.state.batch;
    if (!alive || !b || !["queued", "searching", "screening", "scoring"].includes(b.status)) return;
    pollTimer = setTimeout(async () => {
      await ctx.refresh();
      if (!S.listing && queue().length) await pickListing();
      paint(); poll();
    }, 1800);
  }

  (async () => {
    await pickListing();
    paint();
    poll();
  })();

  ctx.onState = () => { if (!alive) return; if (S.phase === "idle" && !isMove) { const q = queue()[0] || null; if ((q && q.id) !== (S.listing && S.listing.id)) S.listing = q; } paint(); poll(); };
  // Read by the browser tests: where a field position is on screen, and the live state machine.
  window.__place = { S, geom: () => { geom(); return g; },
    fieldClient(r, th) { geom(); const p = fieldPx(r, th), sr = stage.getBoundingClientRect(); return { x: sr.left + p.x, y: sr.top + p.y }; },
    rocketClient() { const r = rocketEl.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; },
    sun2Client() { const r = sun2.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; } };
  return { destroy() { alive = false; clearTimeout(pollTimer); ro.disconnect(); document.removeEventListener("keydown", onKey); ctx.onState = null; }, _S: S };
}
