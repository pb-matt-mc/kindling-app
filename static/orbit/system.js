// The System view: every placed listing on the field, planets in their orbits. Tap a moon to read it or move it.
import { $, $$, AXIS_COLOR, ICON, M, api, confText, esc, h, sheet, toast } from "./util.js";
import { BG, C, VB } from "./place.js";
import { newPlanetSheet, openListing } from "./sheets.js";

const angleFor = (p, i) => (p.theta != null ? p.theta : (p.id * 2.399963) % (2 * Math.PI));

export function mountSystem(main, ctx) {
  const sys = () => ctx.state.system;
  main.innerHTML = `
    <header class="top">
      <img class="mark" src="/static/icons/orbit-mark.svg" alt="" width="32" height="32">
      <a class="chip grow" href="#galaxy" style="min-width:0;justify-content:flex-start"><i></i><span class="ellip" id="sname"></span></a>
      <span class="data" id="counts" style="color:var(--ink-muted)"></span>
    </header>
    <div class="place" style="grid-template-rows:minmax(0,1fr) auto">
      <div class="stage" id="stage" style="touch-action:pan-y">${BG.replace('<polygon id="poly"', '<polygon id="poly" hidden').replace(/<g id="ghost".*?<\/g>/s, "")}
        <div id="bodies"></div><div id="moons"></div>
        <div class="lab label" data-ax="price" style="color:var(--dir-price)">${ICON.price}Price</div>
        <div class="lab label v" data-ax="wrong" style="color:var(--dir-wrong)">${ICON.wrong}Wrong vibe</div>
        <div class="lab label v" data-ax="right" style="color:var(--dir-right)">${ICON.right}Right vibe</div>
        <div class="lab label" data-ax="guess" style="color:var(--dir-guess)">${ICON.guess}Claude's guess</div>
        <div class="lab label" id="frostlab" style="color:var(--frost)">Frost line</div>
      </div>
      <div class="panel" id="panel"></div>
    </div>`;
  const stage = $("#stage", main), panel = $("#panel", main);
  let alive = true, sunFilter = null, g;
  const geom = () => { const W = stage.clientWidth, H = stage.clientHeight, k = Math.min(W / VB.w, H / VB.h); g = { W, H, k, ox: (W - VB.w * k) / 2, oy: (H - VB.h * k) / 2 }; };
  const px = (vx, vy) => ({ x: g.ox + (vx - VB.x0) * g.k, y: g.oy + (vy - VB.y0) * g.k });
  const fp = (r, t) => px(C.x + C.R * r * Math.cos(t), C.y + C.R * r * Math.sin(t));

  function paint() {
    if (!alive) return;
    geom();
    $("#sname", main).textContent = sys().name;
    const placed = ctx.state.placed.filter((p) => sunFilter == null || p.sun === sunFilter);
    const counts = { Sun: 0, Belt: 0 };
    ctx.state.placed.forEach((p) => { if (p.zone in counts) counts[p.zone]++; });
    $("#counts", main).textContent = `Sun ${counts.Sun} · Belt ${counts.Belt}`;
    const lp = (sel, vx, vy, tr) => { const el = $(sel, main), p = px(vx, vy); el.style.left = p.x + "px"; el.style.top = p.y + "px"; el.style.transform = tr; };
    lp('[data-ax="price"]', 195, 176, "translate(-50%,-50%)"); lp('[data-ax="guess"]', 195, 576, "translate(-50%,-50%)");
    lp('[data-ax="wrong"]', 10, 384, "translate(-50%,-50%) rotate(180deg)"); lp('[data-ax="right"]', 380, 384, "translate(-50%,-50%)");
    lp("#frostlab", 195 + 116 * 0.7071 + 4, 384 - 116 * 0.7071 - 6, "translate(0,-50%)");
    // moons, fanned out so a pile stays readable. Stored positions are never touched.
    const d = Math.max(26, Math.min(36, 34 * g.k)), marker = d / (C.R * g.k);
    const items = placed.map((p) => { const a = angleFor(p); return { id: p.id, x: p.r * Math.cos(a), y: p.r * Math.sin(a), p }; });
    const out = M.fanOut(items, marker, 12);
    const byId = Object.fromEntries(items.map((i) => [i.id, i.p]));
    let html = "";
    for (const it of out.placed) {
      const p = byId[it.id], pos = px(C.x + C.R * it.x, C.y + C.R * it.y);
      html += `<button class="moon${p.gone ? " gone" : ""}" data-id="${p.id}" aria-label="${esc(p.title)}${p.gone ? ", sold" : ""}, ${p.zone}" style="left:${(pos.x - d / 2).toFixed(1)}px;top:${(pos.y - d / 2).toFixed(1)}px;width:${d}px;height:${d}px;${p.photo ? `background:url(${esc(p.photo)}) center/cover` : ""}"></button>`;
      if (it.leader) html += "";
    }
    for (const c of out.collapsed) {
      const pos = px(C.x + C.R * c.x, C.y + C.R * c.y);
      html += `<button class="badge" data-more="${c.ids.join(",")}" aria-label="${c.ids.length} more listings here" style="left:${(pos.x - 16).toFixed(1)}px;top:${(pos.y - 14).toFixed(1)}px">+${c.ids.length}</button>`;
    }
    $("#moons", main).innerHTML = html;
    $$(".moon", main).forEach((b) => (b.onclick = () => openListing(+b.dataset.id, { onMove: (id) => (location.hash = "#move/" + id) })));
    $$("[data-more]", main).forEach((b) => (b.onclick = () => morelist(b.dataset.more.split(",").map(Number))));
    // planets in their orbits
    const bodies = ctx.state.planets.map((pl, i) => {
      const a = pl.theta != null ? pl.theta : -Math.PI / 4 + i * 0.9, pos = fp(pl.r, a);
      return `<button class="body" data-planet="${pl.id}" aria-label="Planet ${esc(pl.name)}, ${pl.moons} moons" style="left:${pos.x - 20}px;top:${pos.y - 20}px;width:40px;height:40px;color:var(--ink)">
        <span style="top:92%">${esc(pl.name)}<small>${pl.moons} moon${pl.moons === 1 ? "" : "s"}</small></span><svg viewBox="0 0 24 24" width="30" height="30" fill="var(--space)" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="5.5"/><path d="M7.2 9.8C3.9 11.6 2 13.7 2.6 14.9c.8 1.5 5.5.5 10.500-2.100s8.500-5.900 7.700-7.400c-.5-1-2.700-.9-5.600.1"/></svg></button>`;
    }).join("");
    $("#bodies", main).innerHTML = bodies;
    $$(".body", main).forEach((b) => (b.onclick = () => planetSheet(+b.dataset.planet)));
    paintPanel();
  }

  function paintPanel() {
    const s = sys(), finished = s.state === "finished", ev = ctx.state.events_ready;
    const bin = s.binary;
    panel.innerHTML = `${ev ? `<div class="guessbox"><div class="hd"><span>Claude noticed something</span></div><p>${esc(ctx.state.events_ready.title || "Take a look")}</p><button class="btn guess" id="seeev">See what's happening</button></div>` : ""}
      ${bin ? `<div class="seg" role="group" aria-label="Which sun">${[null, 0, 1].map((v) => `<button data-sun="${v}" aria-pressed="${sunFilter === v}">${v == null ? "Both" : (bin.names[v] || "Sun " + (v + 1))}</button>`).join("")}</div>` : ""}
      <div class="acts"><button class="btn" id="np">${ICON.planet} New planet</button>
        ${finished ? '<button class="btn" id="reopen">Reopen hunt</button>' : '<button class="btn" id="found">Found it</button>'}</div>
      <p class="sm" style="text-align:center">Frost line: inside it is a like, outside it is a pass. Tap a listing to read it or move it.</p>
      <p class="sm" style="text-align:center">${esc(confText(ctx.state.scores.confidence))} · rocket use ${ctx.state.scores.rocket.share == null ? "—" : Math.round(ctx.state.scores.rocket.share * 100) + "%"}</p>`;
    $("#np", panel).onclick = () => newPlanetSheet(ctx, { onCreated: () => toast("Planet created") && paint() });
    const f = $("#found", panel); if (f) f.onclick = confirmFound;
    const r = $("#reopen", panel); if (r) r.onclick = async () => { await api(`/o/systems/${sys().id}/reopen`, { body: {} }); await ctx.refresh(); };
    const e = $("#seeev", panel); if (e) e.onclick = async () => (await import("./events.js")).showNextEvent(ctx, { force: true });
    $$("[data-sun]", panel).forEach((b) => (b.onclick = () => { const v = b.dataset.sun; sunFilter = v === "null" ? null : +v; paint(); }));
  }

  function morelist(ids) {
    const rows = ctx.state.placed.filter((p) => ids.includes(p.id));
    const s = sheet({ title: `${rows.length} more here`, body: `<div class="list">${rows.map((p) => `<button class="pick" data-id="${p.id}">${p.photo ? `<img src="${esc(p.photo)}" alt="">` : ""}<span class="grow ellip">${esc(p.title)}</span><span class="tag">${esc(p.zone)}</span></button>`).join("")}</div>` });
    $$(".pick", s.el).forEach((b) => (b.onclick = () => { s.close(); openListing(+b.dataset.id, { onMove: (id) => (location.hash = "#move/" + id) }); }));
  }

  function planetSheet(id) {
    const pl = ctx.state.planets.find((p) => p.id === id);
    if (!pl) return;
    const moons = ctx.state.placed.filter((p) => p.planet_id === id);
    const foot = h('<button class="btn danger" id="delp">Remove planet</button>');
    const s = sheet({ title: pl.name, body: `<p class="p">${esc(pl.description || "No description yet.")}</p><p class="sm">${pl.moons} moon${pl.moons === 1 ? "" : "s"} · ${esc(pl.zone)} orbit. Removing a planet keeps its listings where they are.</p>
      <div class="list">${moons.map((p) => `<button class="pick" data-id="${p.id}">${p.photo ? `<img src="${esc(p.photo)}" alt="">` : ""}<span class="grow ellip">${esc(p.title)}</span></button>`).join("")}</div>`, foot });
    $$(".pick", s.el).forEach((b) => (b.onclick = () => { s.close(); openListing(+b.dataset.id, { onMove: (i) => (location.hash = "#move/" + i) }); }));
    foot.onclick = async () => { await api("/o/planets/" + id, { method: "DELETE" }); s.close(); await ctx.refresh(); paint(); };
  }

  function confirmFound() {
    const foot = h('<div class="stack"><button class="btn primary" id="yes">Yes, I found it</button><button class="btn ghost" id="no">Not yet</button></div>');
    const s = sheet({ title: "Found it?", body: `<p class="p">${esc(sys().name)} will stay in the Galaxy as finished. Its listings and what Claude learned are kept, and you can reopen it any time.</p>`, foot });
    $("#no", foot).onclick = () => s.close();
    $("#yes", foot).onclick = async () => {
      try { await api(`/o/systems/${sys().id}/found`, { body: {} }); s.close(); toast("Hunt closed. Nice."); await ctx.refresh(); location.hash = "#galaxy"; }
      catch (e) { toast(e.message); }
    };
  }

  const ro = new ResizeObserver(paint); ro.observe(stage);
  ctx.onState = paint;
  paint();
  return { destroy() { alive = false; ro.disconnect(); ctx.onState = null; } };
}
