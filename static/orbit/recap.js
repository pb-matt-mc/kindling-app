// Batch recap: where everything landed, how close Claude got, and what the batch did to Confidence.
import { $, $$, AXIS_COLOR, ICON, M, api, confText, esc, h, money, toast } from "./util.js";

export function mountRecap(main, ctx, arg) {
  main.innerHTML = `<header class="top"><img class="mark" src="/static/icons/orbit-mark.svg" alt="" width="32" height="32"><h1 class="h2 grow">Batch recap</h1></header><div class="page" id="page"><div class="spinner" role="status" aria-label="Loading"></div></div>`;
  let alive = true;
  (async () => {
    let r;
    try { r = await api("/o/recap" + (arg ? "/" + arg : "")); } catch (e) { toast(e.message); location.hash = "#place"; return; }
    if (!alive) return;
    const c = r.counts;
    const before = r.confidence_before, now = r.confidence;
    const delta = before.state === "ready" && now.state === "ready" ? Math.round((now.value - before.value) * 100) : null;
    const dots = r.items.map((i) => {
      const th = i.theta != null ? i.theta : (i.id * 2.399963) % (2 * Math.PI);
      const x = 100 + 92 * i.r * Math.cos(th), y = 100 + 92 * i.r * Math.sin(th);
      const col = i.reasons ? AXIS_COLOR[M.dominantAxis(i.reasons)] : "var(--sun)";
      const ghost = i.predicted_r != null ? `<line x1="${x.toFixed(1)}" y1="${y.toFixed(1)}" x2="${(100 + 92 * i.predicted_r * Math.cos(th)).toFixed(1)}" y2="${(100 + 92 * i.predicted_r * Math.sin(th)).toFixed(1)}" stroke="#D4F54A" stroke-width="1" stroke-dasharray="2 3" opacity=".7"/><circle cx="${(100 + 92 * i.predicted_r * Math.cos(th)).toFixed(1)}" cy="${(100 + 92 * i.predicted_r * Math.sin(th)).toFixed(1)}" r="2.5" fill="none" stroke="#D4F54A"/>` : "";
      return `${ghost}<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${i.comet ? 5 : 4}" fill="${col}" stroke="${i.comet ? "#8FE3FF" : "#0B1440"}" stroke-width="${i.comet ? 1.5 : 1}"/>`;
    }).join("");
    $("#page", main).innerHTML = `
      <div class="between"><span class="tag">${esc(r.system)} · batch ${r.batch.number}</span><span class="data" style="color:var(--dir-guess)">${esc(confText(now))}${delta != null ? ` (${delta >= 0 ? "+" : ""}${delta})` : ""}</span></div>
      <svg viewBox="0 0 200 200" role="img" aria-label="Where this batch landed" style="width:100%;max-width:340px;margin:0 auto">
        <circle cx="100" cy="100" r="92" fill="none" stroke="#7F89BA" stroke-dasharray="1 5"/><circle cx="100" cy="100" r="${(M.FROST * 92).toFixed(1)}" fill="none" stroke="#8FE3FF" stroke-dasharray="1 5"/>
        <circle cx="100" cy="100" r="${(M.INNER_R * 92).toFixed(1)}" fill="none" stroke="#F6DC8E" opacity=".5"/><circle cx="100" cy="100" r="${(M.SUN_R * 92).toFixed(1)}" fill="#FFC933"/>${dots}</svg>
      <p class="sm" style="text-align:center">Filled dot: where you put it. Lime ring: where Claude guessed. Blue outline: a comet.</p>
      <div class="tiles"><div class="tile"><b class="h2">${c.called}</b><span class="sm">Called it</span></div><div class="tile"><b class="h2">${c.close}</b><span class="sm">Close</span></div>
        <div class="tile"><b class="h2">${c.missed}</b><span class="sm">Claude missed</span></div><div class="tile"><b class="h2">${c.rocketed}</b><span class="sm">Rocketed (not scored)</span></div></div>
      ${r.comets.n ? `<div class="panelbox"><b>Comets</b><p class="sm">${r.comets.n} exploration pick${r.comets.n === 1 ? "" : "s"}; you placed ${r.comets.liked} inside the frost line.</p></div>` : ""}
      <div class="list">${r.items.map((i) => `<div class="grp"><img src="${esc(i.photo || "")}" alt="" width="44" height="44" style="border-radius:50%;object-fit:cover"><div class="grow" style="min-width:0"><div class="h3 ellip">${esc(i.title)}</div><div class="sm">${esc(i.zone)} · ${i.like ? "like" : "pass"}${i.comet ? " · comet" : ""}</div></div>${i.verdict ? `<span class="tag guess">${esc(i.verdict)}</span>` : i.kind === "rocket" ? '<span class="tag">Rocket</span>' : ""}</div>`).join("")}</div>
      <button class="btn primary" id="done">Done</button>`;
    $("#done", main).onclick = async () => { await ctx.refresh(); location.hash = "#place"; };
  })();
  return { destroy() { alive = false; } };
}
