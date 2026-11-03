// The Galaxy: every hunt as a solar system. Switch, start a new one with chosen listings, or close one as found.
import { $, $$, ICON, api, confText, esc, h, sheet, toast } from "./util.js";
import { newPlanetSheet } from "./sheets.js";

export function mountGalaxy(main, ctx) {
  main.innerHTML = `<header class="top"><img class="mark" src="/static/icons/orbit-mark.svg" alt="" width="32" height="32"><h1 class="h2 grow">Galaxy</h1><span class="data" id="n" style="color:var(--ink-muted)"></span></header>
    <div class="page" id="page"></div>`;
  let alive = true;
  async function paint() {
    let list;
    try { list = await api("/o/galaxy"); } catch (e) { return toast(e.message); }
    if (!alive) return;
    $("#n", main).textContent = `${list.length} system${list.length === 1 ? "" : "s"}`;
    $("#page", main).innerHTML = `<div class="list">${list.map((s) => {
      const c = s.counts, tags = [s.binary ? "Binary star" : "", s.state === "finished" ? "Finished" : "", s.batch ? `Batch ${s.batch.number}` : ""].filter(Boolean);
      return `<div class="stack"><button class="sysrow${s.active ? " on" : ""}${s.state === "finished" ? " done" : ""}" data-id="${s.id}" aria-label="${esc(s.name)}${s.active ? ", current" : ""}">
        <span class="orb" aria-hidden="true"></span><span class="grow" style="min-width:0"><b class="h3 ellip" style="display:block">${esc(s.name)}</b>
        <span class="data" style="color:var(--ink-muted)">${c.Sun} in the Sun · ${c.Belt} in the belt</span>
        <span class="row" style="flex-wrap:wrap;margin-top:4px">${tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}<span class="tag guess">${esc(confText(s.confidence))}</span></span></span></button>
        ${s.state === "finished" ? `<button class="btn small ghost" data-reopen="${s.id}">Reopen</button>` : ""}</div>`;
    }).join("")}</div>
      <div class="acts" style="display:grid;grid-template-columns:1fr 1fr;gap:8px"><button class="btn" id="np">${ICON.planet} New planet</button><button class="btn primary" id="ns">${ICON.plus} New system</button></div>`;
    $$(".sysrow", main).forEach((b) => (b.onclick = async () => { await api(`/o/systems/${b.dataset.id}/activate`, { body: {} }); await ctx.refresh(); location.hash = "#place"; }));
    $$("[data-reopen]", main).forEach((b) => (b.onclick = async () => { await api(`/o/systems/${b.dataset.reopen}/reopen`, { body: {} }); await ctx.refresh(); paint(); }));
    $("#np", main).onclick = () => newPlanetSheet(ctx, { onCreated: () => toast("Planet created") });
    $("#ns", main).onclick = () => newSystem(list);
  }

  function newSystem() {
    const cur = ctx.state.system, placed = ctx.state.placed;
    const picked = new Set();
    const body = h(`<div class="stack" style="gap:16px">
      <div class="field-in"><label for="sn">Name</label><input id="sn" type="text" maxlength="40" autocomplete="off" placeholder="Coffee table"></div>
      <div class="field-in"><label for="sh">What are you hunting?</label><textarea id="sh" rows="2" maxlength="300" placeholder="A walnut coffee table, under 48 inches"></textarea><p class="sm">Claude searches with this. It is a new hunt with its own search terms.</p></div>
      <div class="field-in"><span class="label">Which listings follow the new sun?</span><p class="sm">Pick from ${esc(cur.name)}. They move over with their placements.</p>
        <div class="list" id="pk">${placed.length ? placed.slice(0, 80).map((p) => `<button type="button" class="pick" data-id="${p.id}" aria-pressed="false">${p.photo ? `<img src="${esc(p.photo)}" alt="">` : ""}<span class="grow ellip">${esc(p.title)}</span><span class="tag">${esc(p.zone)}</span></button>`).join("") : '<p class="empty">Nothing placed yet.</p>'}</div></div>
      <p class="sm" id="serr" style="color:var(--alert)" hidden></p></div>`);
    const foot = h('<button class="btn primary" id="mk" type="button">Create system</button>');
    const s = sheet({ title: "New system", body, foot });
    $$(".pick", body).forEach((b) => (b.onclick = () => { const id = +b.dataset.id; picked.has(id) ? picked.delete(id) : picked.add(id); b.setAttribute("aria-pressed", picked.has(id)); }));
    foot.onclick = async () => {
      try {
        await api("/o/systems", { body: { source_id: cur.id, name: $("#sn", body).value, hunt: $("#sh", body).value, listing_ids: [...picked] } });
        s.close(); await ctx.refresh(); toast("New system created"); location.hash = "#place";
      } catch (e) { const er = $("#serr", body); er.textContent = e.message; er.hidden = false; }
    };
  }

  paint();
  ctx.onState = null;
  return { destroy() { alive = false; } };
}
