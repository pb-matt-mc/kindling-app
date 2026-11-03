// node tests/js_math_check.js  ->  prints mismatches between static/orbit-math.js and the Python-made fixtures
const M = require("../static/orbit-math.js");
const F = require("./fixtures/orbit_math.json");
const bad = [];
const near = (a, b) => Math.abs(a - b) <= 1e-9;
const eq = (path, a, b) => {
  if (typeof a === "number" && typeof b === "number") { if (!near(a, b)) bad.push(`${path}: ${a} vs ${b}`); }
  else if (a === null || b === null) { if (a !== b) bad.push(`${path}: ${a} vs ${b}`); }
  else if (typeof a === "object" && typeof b === "object") {
    const ka = Object.keys(a).sort(), kb = Object.keys(b).sort();
    if (ka.join() !== kb.join()) bad.push(`${path}: keys ${ka} vs ${kb}`);
    for (const k of kb) eq(`${path}.${k}`, a[k], b[k]);
  } else if (a !== b) bad.push(`${path}: ${JSON.stringify(a)} vs ${JSON.stringify(b)}`);
};
for (const k of Object.keys(F.constants)) eq("const." + k, M[k], F.constants[k]);
F.blend.forEach((c, i) => eq(`blend[${i}] r=${c.r} t=${c.theta}`, M.blend(c.r, c.theta), c.out));
F.ratings.forEach((c, i) => { eq(`rFromRating[${i}]`, M.rFromRating(c.x), c.r); eq(`rating[${i}]`, M.rating(M.rFromRating(c.x)), c.back); });
F.polar.forEach((c, i) => eq(`polar[${i}]`, M.polar(c.dx, c.dy), c.out));
F.fan_out.forEach((c) => eq(`fan_out ${c.name}`, M.fanOut(c.items, c.marker), c.out));
console.log(JSON.stringify({ checked: F.blend.length + F.ratings.length * 2 + F.polar.length + F.fan_out.length, mismatches: bad.slice(0, 20), total: bad.length }));
process.exit(bad.length ? 1 : 0);
