/* Orbit's placing math: a line-for-line mirror of app/orbit_math.py (tests/fixtures/orbit_math.json pins both).
   Field units: field radius = 1, y grows downward, angle 0 = right, -PI/2 = up. Works in the browser and in node. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.OrbitMath = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const PX = 186;
  const SUN_R = 34 / PX, INNER_R = 80 / PX, FROST = 116 / PX, OUTER_R = 160 / PX;
  const ZONES = [["Sun", SUN_R], ["Inner", INNER_R], ["Mid", FROST], ["Outer", OUTER_R], ["Belt", 1.0]];
  const AXES = [["price", -Math.PI / 2], ["right", 0], ["guess", Math.PI / 2], ["wrong", Math.PI]];
  const AXIS_NAMES = AXES.map((a) => a[0]);
  const HALF_PI = Math.PI / 2;
  const KEEPER_DISPLAY_R = SUN_R * 0.55;
  const GOLDEN_ANGLE = 2.399963229728653;

  const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
  function zone(r) { for (const [n, e] of ZONES) if (r <= e) return n; return "Belt"; }
  const isLike = (r) => r <= FROST;
  function rating(r) {
    r = clamp(r, 0, 1);
    return r <= FROST ? 1 - 0.5 * r / FROST : 0.5 - 0.5 * (r - FROST) / (1 - FROST);
  }
  function rFromRating(x) {
    x = clamp(x, 0, 1);
    return x >= 0.5 ? 2 * FROST * (1 - x) : FROST + (1 - FROST) * 2 * (0.5 - x);
  }
  function polar(dx, dy) { return [Math.min(Math.hypot(dx, dy), 1), Math.atan2(dy, dx)]; }
  function angularDistance(a, b) {
    const t = 2 * Math.PI, d = Math.abs(a - b) % t;   // JS % keeps the sign of the dividend; operands are abs()
    return Math.min(d, t - d);
  }
  function reasonWeights(theta) {
    const raw = {}; let total = 0;
    for (const [n, ang] of AXES) { raw[n] = Math.max(0, 1 - angularDistance(theta, ang) / HALF_PI); total += raw[n]; }
    const out = {}; for (const n of AXIS_NAMES) out[n] = raw[n] / total;
    return out;
  }
  function percents(weights, step) {
    step = step || 5;
    const units = Math.floor(100 / step);
    const scaled = AXIS_NAMES.map((n) => [n, weights[n] * units]);
    const base = {}; let sum = 0;
    for (const [n, v] of scaled) { base[n] = Math.floor(v + 1e-9); sum += base[n]; }
    const order = scaled.slice().sort((a, b) => {
      const ra = a[1] - Math.floor(a[1] + 1e-9), rb = b[1] - Math.floor(b[1] + 1e-9);
      return (rb - ra) || (AXIS_NAMES.indexOf(a[0]) - AXIS_NAMES.indexOf(b[0]));
    });
    for (const [n] of order.slice(0, units - sum)) base[n] += 1;
    const out = {}; for (const n of AXIS_NAMES) out[n] = base[n] * step;
    return out;
  }
  function blend(r, theta) {
    const z = zone(r);
    const out = { r, zone: z, rating: rating(r), like: isLike(r), reasons: null, percents: null };
    if (z !== "Sun") { out.reasons = reasonWeights(theta); out.percents = percents(out.reasons); }
    return out;
  }
  function dominantAxis(w) {
    let best = AXIS_NAMES[0];
    for (const n of AXIS_NAMES) if (w[n] > w[best]) best = n;
    return best;
  }
  function fanOut(items, marker, maxVisible, spread) {
    maxVisible = maxVisible == null ? 12 : maxVisible; spread = spread == null ? 1.0 : spread;
    items = items.slice().sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    const parent = items.map((_, i) => i);
    const find = (a) => { while (parent[a] !== a) { parent[a] = parent[parent[a]]; a = parent[a]; } return a; };
    for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++)
      if (Math.hypot(items[i].x - items[j].x, items[i].y - items[j].y) < marker) parent[find(j)] = find(i);
    const groups = new Map();
    items.forEach((it, i) => { const k = find(i); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(it); });
    const placed = [], collapsed = [];
    for (const members of groups.values()) {
      const cx = members.reduce((s, m) => s + m.x, 0) / members.length;
      const cy = members.reduce((s, m) => s + m.y, 0) / members.length;
      for (let k = 0; k < members.length; k++) {
        const m = members[k];
        if (members.length > maxVisible && k >= maxVisible - 1) break;
        const off = marker * spread * Math.sqrt(k);
        const multi = members.length > 1;
        const x = multi ? cx + off * Math.cos(k * GOLDEN_ANGLE) : m.x, y = multi ? cy + off * Math.sin(k * GOLDEN_ANGLE) : m.y;
        placed.push({ id: m.id, x, y, true_x: m.x, true_y: m.y, leader: Math.hypot(x - m.x, y - m.y) > marker * 0.2 });
      }
      if (members.length > maxVisible)
        collapsed.push({ ids: members.slice(maxVisible - 1).map((m) => m.id), x: cx, y: cy });
    }
    placed.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    return { placed, collapsed };
  }
  return { SUN_R, INNER_R, FROST, OUTER_R, ZONES, AXES, AXIS_NAMES, KEEPER_DISPLAY_R, clamp, zone, isLike, rating,
           rFromRating, polar, angularDistance, reasonWeights, percents, blend, dominantAxis, fanOut };
});
