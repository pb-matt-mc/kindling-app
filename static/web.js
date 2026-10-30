// The taste web: center = loved, edge = hated. Drag to re-rank, drop onto another node to group.
// Semantic zoom: far shows trait clusters, middle shows photos + your categories, close shows names and prices.

const NODE = 17;
const GROUP_COLORS = ["#ffd27a", "#8ec5ff", "#d9a3ff", "#7fe0c4", "#ff9fb2", "#c5e07f", "#ffb36b"];
const scoreColor = d3.interpolateRgbBasis(["#ff5a5f", "#f1b24a", "#4cc38a"]);

// Why two listings are tied together, in plain words
const short = (t) => ((t || "").length > 22 ? t.slice(0, 21) + "…" : t || "");

function linkWhy(l, groups) {
  if (l.kind === "group") {
    const g = groups.find((x) => x.id === l.group);
    return g ? `your "${g.label}" pile` : "same category";
  }
  const shared = (l.shared || []).filter((t) => !/^(shape|condition):/.test(t)).map((t) => t.split(":").slice(1).join(":"));
  return shared.length ? shared.slice(0, 2).join(" · ") : "similar overall";
}

export function createWeb(container, opts) {
  const { load, onSelect, onRank, onGroup, onLinkTap, onExport, emptyText } = opts;
  container.classList.add("web");
  container.innerHTML = "";
  const W = () => container.clientWidth || 360;
  const H = () => container.clientHeight || 480;
  const baseR = () => Math.min(W(), H()) / 2 - 22;
  let R = baseR();
  const fitK = () => Math.min(1, baseR() / R);
  const rankToR = (r) => 8 + (1 - r) * (R - 8);
  const rToRank = (d) => Math.max(0, Math.min(1, 1 - (d - 8) / (R - 8)));

  const svg = d3.select(container).append("svg");
  const defs = svg.append("defs");
  const glow = defs.append("radialGradient").attr("id", "glow");
  glow.append("stop").attr("offset", "0%").attr("stop-color", "#ff7a3d").attr("stop-opacity", 0.35);
  glow.append("stop").attr("offset", "100%").attr("stop-color", "#ff7a3d").attr("stop-opacity", 0);
  defs.append("clipPath").attr("id", "nodeclip").append("circle").attr("r", NODE);

  const root = svg.append("g");
  const ringsG = root.append("g");
  const landmarkG = root.append("g");
  const hullG = root.append("g");
  const linkG = root.append("g");
  const hitG = root.append("g");
  const nodeG = root.append("g");
  const labelG = root.append("g");

  const zoomUI = d3.select(container).append("div").attr("class", "web-zoom");
  const legend = d3.select(container).append("div").attr("class", "web-legend");
  legend.append("div").attr("class", "hint")
    .html("Drag toward the middle to love it more, out to like it less.<br>Drop one onto another (gold ring) to group them.");
  legend.append("div").attr("class", "scale-bar");
  const emptyEl = d3.select(container).append("div").attr("class", "web-empty").style("display", "none")
    .text(emptyText || "Swipe a batch and your web shows up here.");

  let nodes = [], links = [], clusters = [], allClusters = [], groups = [], landmarks = [];
  let landmarkSel;
  let nodeSel, linkSel, hitSel, linkLabelSel, clusterSel, hullSel, groupLabelSel;
  const byId = new Map();
  let k = 1;
  const zoom = d3.zoom().scaleExtent([0.6, 7]).on("zoom", (ev) => {
    root.attr("transform", ev.transform);
    k = ev.transform.k;
    applyZoomLevel();
  });
  svg.call(zoom).on("dblclick.zoom", null);
  const home = () => d3.zoomIdentity.translate(W() / 2, H() / 2).scale(fitK());
  svg.call(zoom.transform, home());
  zoomUI.append("button").text("+").on("click", () => svg.transition().duration(250).call(zoom.scaleBy, 1.6));
  zoomUI.append("button").text("−").on("click", () => svg.transition().duration(250).call(zoom.scaleBy, 0.62));
  zoomUI.append("button").html("&#8962;").attr("title", "Reset").on("click", () =>
    svg.transition().duration(300).call(zoom.transform, home()));
  if (onExport) {
    zoomUI.append("button").attr("title", "Export").attr("aria-label", "Export")
      .html('<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>')
      .on("click", () => onExport());
  }
  const fullBtn = zoomUI.append("button").attr("title", "Full screen").attr("aria-label", "Full screen");
  const FULL_IN = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>';
  const FULL_OUT = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/></svg>';
  const setFull = (on) => {
    container.classList.toggle("web-full", on);
    fullBtn.html(on ? FULL_OUT : FULL_IN);
  };
  setFull(false);
  fullBtn.on("click", () => setFull(!container.classList.contains("web-full")));

  function drawRings() {
    ringsG.selectAll("*").remove();
    ringsG.append("circle").attr("class", "center-glow").attr("r", R * 0.45);
    const rings = [[1, "love"], [0.75, "like"], [0.5, "meh"], [0.25, "nah"], [0, "nope"]];
    for (const [rank, label] of rings) {
      const r = rankToR(rank);
      if (r > 10) ringsG.append("circle").attr("class", "ring" + (rank === 0.5 ? " meh" : "")).attr("r", r);
      ringsG.append("text").attr("class", "ring-label").attr("x", 0).attr("y", -r - 4)
        .attr("text-anchor", "middle").text(label);
    }
  }

  const sim = d3.forceSimulation()
    .force("radial", d3.forceRadial((d) => rankToR(d.rank)).strength(0.9))
    .force("link", d3.forceLink().id((d) => d.id)
      .distance((l) => (l.kind === "group" ? 36 : 64))
      .strength((l) => (l.kind === "group" ? 0.5 : 0.06 * l.strength)))
    .force("collide", d3.forceCollide(NODE + 3))
    .force("charge", d3.forceManyBody().strength(-18))
    .on("tick", tick);


  function render(data) {
    // give big webs room to breathe, then start zoomed out to fit (cluster names first, like a map)
    const wantR = Math.max(baseR(), 34 * Math.sqrt(data.nodes.length || 1));
    if (Math.abs(wantR - R) > 8) {
      R = wantR;
      drawRings();
      placeLandmarks();
      sim.force("radial").radius((d) => rankToR(d.rank));
      svg.call(zoom.transform, home());
    }
    const prev = new Map(nodes.map((n) => [n.id, n]));
    nodes = data.nodes.map((n) => {
      const p = prev.get(n.id);
      const a = Math.random() * Math.PI * 2;
      return Object.assign(n, p ? { x: p.x, y: p.y } : { x: Math.cos(a) * rankToR(n.rank), y: Math.sin(a) * rankToR(n.rank) });
    });
    byId.clear();
    nodes.forEach((n) => byId.set(n.id, n));
    links = data.links.map((l) => ({ ...l }));
    allClusters = data.clusters || [];
    container.classList.toggle("has-cta", !!container.querySelector(".crys-cta"));
    clusters = allClusters.slice(0, 5);
    // faint names left behind by the last crystal: the old map under the new one
    landmarks = data.landmarks || [];
    landmarkSel = landmarkG.selectAll("text").data(landmarks).join("text").attr("class", "landmark")
      .text((l) => "◆ " + l.label)
      .style("fill", (l) => (l.weight >= 0 ? "#9fe4c1" : "#ffb3b5"));
    placeLandmarks();
    groups = (data.groups || [])
      .map((g, i) => ({ ...g, members: g.members.filter((id) => byId.has(id)), color: GROUP_COLORS[i % GROUP_COLORS.length] }))
      .filter((g) => g.members.length >= 2);
    emptyEl.style("display", nodes.length ? "none" : "grid");

    linkSel = linkG.selectAll("line").data(links).join("line").attr("class", "link")
      .attr("stroke", (l) => (l.kind === "group" ? groups.find((g) => g.id === l.group)?.color || "#ffd27a" : scoreColor(l.value)))
      .attr("stroke-opacity", (l) => (l.kind === "group" ? 0.75 : 0.22 + 0.4 * l.strength))
      .attr("stroke-width", (l) => (l.kind === "group" ? 2.2 : 1.2))
      .attr("stroke-dasharray", (l) => (l.kind === "group" ? "4 3" : null));
    // fat invisible copies so links are easy to tap
    hitSel = hitG.selectAll("line").data(links).join("line").attr("class", "link-hit")
      .on("click", (ev, l) => {
        ev.stopPropagation();
        const a = typeof l.source === "object" ? l.source : byId.get(l.source);
        const b = typeof l.target === "object" ? l.target : byId.get(l.target);
        onLinkTap?.(`${short(a?.title)} + ${short(b?.title)}: ${linkWhy(l, groups)}`);
      });
    linkLabelSel = labelG.selectAll("text.link-label").data(links).join("text").attr("class", "link-label")
      .text((l) => linkWhy(l, groups));

    hullSel = hullG.selectAll("path").data(groups, (g) => g.id).join("path").attr("class", "group-hull")
      .attr("fill", (g) => g.color).attr("fill-opacity", 0.07).attr("stroke", (g) => g.color);
    groupLabelSel = labelG.selectAll("text.group-label").data(groups, (g) => g.id).join("text")
      .attr("class", "group-label").attr("fill", (g) => g.color).text((g) => g.label);
    clusterSel = labelG.selectAll("text.cluster").data(clusters, (c) => c.tag).join("text")
      .attr("class", "cluster").text((c) => c.label)
      .style("fill", (c) => (c.weight > 0 ? "#9fe4c1" : "#ffb3b5"));

    nodeSel = nodeG.selectAll("g.node").data(nodes, (d) => d.id).join((enter) => {
      const g = enter.append("g").attr("class", "node").style("cursor", "pointer");
      g.append("circle").attr("class", "bg").attr("r", NODE).attr("fill", "#2c231c");
      g.append("image").attr("class", "img").attr("x", -NODE).attr("y", -NODE)
        .attr("width", NODE * 2).attr("height", NODE * 2).attr("clip-path", "url(#nodeclip)")
        .attr("preserveAspectRatio", "xMidYMid slice");
      g.append("circle").attr("class", "dot").attr("r", NODE * 0.62);
      g.append("circle").attr("class", "rim").attr("r", NODE + 1.5);
      g.append("text").attr("class", "lbl").attr("text-anchor", "middle");
      g.append("text").attr("class", "keeper-mark").attr("x", NODE * 0.62).attr("y", -NODE * 0.55).text("◆");
      g.append("text").attr("class", "sub").attr("text-anchor", "middle");
      return g;
    });
    nodeSel.select("image").attr("href", (d) => d.thumb || "");
    nodeSel.select(".dot").attr("fill", (d) => scoreColor(d.rank));
    nodeSel.select(".keeper-mark").style("display", (d) => (d.keeper ? null : "none"));
    nodeSel.select(".rim").attr("stroke", (d) => scoreColor(d.rank));
    nodeSel.select(".lbl").text((d) => (d.title || "").length > 24 ? d.title.slice(0, 23) + "…" : d.title);
    nodeSel.select(".sub").text((d) => d.price_text || (d.price != null ? "$" + Math.round(d.price) : ""));
    nodeSel.call(drag);

    sim.nodes(nodes);
    sim.force("link").links(links);
    sim.alpha(0.9).restart();
    applyZoomLevel();
  }

  function applyZoomLevel() {
    if (!nodeSel) return;
    const far = k < 0.95, near = k >= 1.9;
    nodeSel.select("image").style("display", far ? "none" : null);
    nodeSel.select(".dot").style("display", far ? null : "none");
    nodeSel.select(".bg").attr("fill", far ? "#1d1611" : "#2c231c");
    nodeSel.selectAll(".lbl, .sub").style("display", near ? null : "none")
      .style("font-size", function () { return (this.classList.contains("lbl") ? 12 : 11) / k + "px"; });
    nodeSel.select(".lbl").attr("y", NODE + 2 + 12 / k);
    nodeSel.select(".sub").attr("y", NODE + 4 + 25 / k);
    clusterSel.style("display", far ? null : "none").style("font-size", 15 / k + "px");
    if (far) tick();
    groupLabelSel.style("font-size", (near ? 12 : 15) / k + "px").style("display", null);
    hullSel.style("display", far ? "none" : null);
    ringsG.selectAll(".ring-label").style("font-size", 10 / k + "px");
    landmarkSel?.style("font-size", 14 / k + "px");
    // link reasons appear once you're zoomed in enough to read them
    linkLabelSel?.style("display", k >= 1.5 ? null : "none").style("font-size", 10 / k + "px");
    hitSel?.style("stroke-width", 14 / k + "px");
  }

  function tick() {
    linkSel?.attr("x1", (l) => l.source.x).attr("y1", (l) => l.source.y)
      .attr("x2", (l) => l.target.x).attr("y2", (l) => l.target.y);
    hitSel?.attr("x1", (l) => l.source.x).attr("y1", (l) => l.source.y)
      .attr("x2", (l) => l.target.x).attr("y2", (l) => l.target.y);
    linkLabelSel?.attr("x", (l) => (l.source.x + l.target.x) / 2).attr("y", (l) => (l.source.y + l.target.y) / 2);
    nodeSel?.attr("transform", (d) => `translate(${d.x},${d.y})`);
    const centroid = (ids) => {
      const pts = ids.map((id) => byId.get(id)).filter(Boolean);
      if (!pts.length) return null;
      return [d3.mean(pts, (p) => p.x), d3.mean(pts, (p) => p.y), pts];
    };
    if (clusterSel && k < 0.95) {
      // greedy de-overlap so trait labels stay readable when zoomed out
      const fs = 15 / k, placed = [];
      const items = [];
      clusterSel.each(function (c) {
        const ce = centroid(c.members);
        if (ce) items.push({ el: this, x: ce[0], y: ce[1], w: c.label.length * fs * 0.56 });
      });
      items.sort((a, b) => a.y - b.y);
      for (const it of items) {
        let y = it.y;
        for (let guard = 0; guard < 30; guard++) {
          const hit = placed.find((p) => Math.abs(p.x - it.x) < (p.w + it.w) / 2 && Math.abs(p.y - y) < fs * 1.05);
          if (!hit) break;
          y = hit.y + fs * 1.1;
        }
        placed.push({ ...it, y });
        d3.select(it.el).attr("x", it.x).attr("y", y);
      }
    }
    groupLabelSel?.each(function (g) {
      const ce = centroid(g.members);
      if (!ce) { d3.select(this).style("visibility", "hidden"); return; }
      d3.select(this).style("visibility", null);
      const top = d3.min(ce[2], (p) => p.y) - NODE - 8;
      d3.select(this).attr("x", ce[0]).attr("y", top);
    });
    hullSel?.attr("d", (g) => {
      const pts = g.members.map((id) => byId.get(id)).filter(Boolean);
      if (!pts.length) return null;
      const pad = NODE + 9, cloud = [];
      for (const p of pts) for (let a = 0; a < 8; a++)
        cloud.push([p.x + pad * Math.cos((a * Math.PI) / 4), p.y + pad * Math.sin((a * Math.PI) / 4)]);
      const hull = d3.polygonHull(cloud);
      return hull ? d3.line().curve(d3.curveCatmullRomClosed.alpha(0.6))(hull) : null;
    });
  }

  let dropTarget = null, dragging = null;
  const nearest = (d, x, y) => {
    let best = null, bd = NODE * 1.1;
    for (const n of nodes) {
      if (n === d) continue;
      const dist = Math.hypot(n.x - x, n.y - y);
      if (dist < bd) { bd = dist; best = n; }
    }
    return best;
  };
  const paintRims = (dragged, dragRank) => {
    nodeSel.select(".rim")
      .attr("stroke-width", (n) => (n === dropTarget ? 6 : n === dragged ? 4 : 3))
      .attr("stroke", (n) => (n === dropTarget ? "#ffd27a" : n === dragged && dragRank != null ? scoreColor(dragRank) : scoreColor(n.rank)));
  };
  const reseat = () => {  // radial targets are cached by d3, so re-read ranks after a change
    sim.force("radial").radius((n) => rankToR(n.rank));
    sim.alpha(0.5).restart();
  };

  const drag = d3.drag()
    .on("start", (ev, d) => {
      dragging = d;
      sim.force("collide").radius((n) => (n === dragging ? 0 : NODE + 3));  // let it pass over others
      d._moved = 0;
      d._sx = ev.x; d._sy = ev.y;
      if (!ev.active) sim.alphaTarget(0.15).restart();
      d.fx = d.x; d.fy = d.y;
    })
    .on("drag", (ev, d) => {
      d._moved = Math.max(d._moved, Math.hypot(ev.x - d._sx, ev.y - d._sy));
      d.fx = ev.x; d.fy = ev.y;
      dropTarget = d._moved > 6 ? nearest(d, ev.x, ev.y) : null;
      paintRims(d, rToRank(Math.hypot(ev.x, ev.y)));
    })
    .on("end", async (ev, d) => {
      if (!ev.active) sim.alphaTarget(0);
      const x = d.fx, y = d.fy, target = dropTarget;
      d.fx = null; d.fy = null; dropTarget = null; dragging = null;
      sim.force("collide").radius(NODE + 3);
      if (d._moved < 6) { paintRims(); onSelect?.(d.id); return; }
      if (target) {
        paintRims();
        const ok = await onGroup?.(d, target);
        if (ok) { refresh(); return; }
      }
      d.rank = rToRank(Math.hypot(x, y));
      d.x = x; d.y = y;
      paintRims();
      nodeSel.select(".dot").attr("fill", (n) => scoreColor(n.rank));
      reseat();
      await onRank?.(d.id, d.rank);
    });

  function placeLandmarks() {
    if (!landmarkSel) return;
    // nudge overlapping names apart (sizes in web units at the fitted zoom)
    const fs = 14 / fitK(), placed = [];
    const pos = landmarks.map((l) => ({ l, x: l.x * R, y: l.y * R, w: (l.label.length + 2) * fs * 0.55 }));
    pos.sort((a, b) => a.y - b.y);
    for (const p of pos) {
      for (let guard = 0; guard < 40; guard++) {
        const hit = placed.find((q) => Math.abs(q.x - p.x) < (q.w + p.w) / 2 && Math.abs(q.y - p.y) < fs * 1.1);
        if (!hit) break;
        p.y = hit.y + fs * 1.15;
      }
      placed.push(p);
    }
    const at = new Map(pos.map((p) => [p.l, p]));
    landmarkSel.attr("x", (l) => at.get(l).x).attr("y", (l) => at.get(l).y).attr("text-anchor", "middle");
  }

  // where each trait cluster sits right now, in web-radius units, for the crystal to remember
  function getLandmarks() {
    return allClusters.map((c) => {
      const pts = c.members.map((id) => byId.get(id)).filter(Boolean);
      if (!pts.length) return null;
      // average distance from the middle, in the average direction: a ring of listings stays a ring
      const r = d3.mean(pts, (p) => Math.hypot(p.x, p.y)) / R;
      const a = Math.atan2(d3.mean(pts, (p) => p.y), d3.mean(pts, (p) => p.x));
      return { label: c.label, weight: c.weight, x: r * Math.cos(a), y: r * Math.sin(a) };
    }).filter(Boolean);
  }

  async function refresh() {
    const data = await load();
    render(data);
  }

  const ro = new ResizeObserver(() => {
    const nr = Math.max(baseR(), 34 * Math.sqrt(nodes.length || 1));
    if (Math.abs(nr - R) > 4) {
      R = nr;
      drawRings();
      placeLandmarks();
      sim.force("radial").radius((d) => rankToR(d.rank));
      sim.alpha(0.4).restart();
      svg.call(zoom.transform, home());
    }
  });
  ro.observe(container);
  drawRings();

  return {
    refresh,
    getLandmarks,
    destroy() { sim.stop(); ro.disconnect(); container.innerHTML = ""; },
  };
}
