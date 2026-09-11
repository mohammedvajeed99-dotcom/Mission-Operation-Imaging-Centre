// One-time extraction of a real, higher-fidelity Australia mainland +
// Tasmania coastline from world-atlas's countries-50m.json (Natural Earth
// data, already a bundled frontend dependency, already used for the map's
// own land silhouette) -- replacing core.australia_coverage's existing
// 18-point MAINLAND_AUSTRALIA / 5-point TASMANIA, which are so coarse that
// straight segments cut directly across the Gulf of Carpentaria and parts
// of the Great Australian Bight, enclosing open ocean inside the AOI
// polygon used both for the map's visual outline and the real backend
// coverage-percent land-cell classification.
//
// Simplified with Douglas-Peucker (no dependency needed) to roughly the
// same point-count granularity already used for MAINLAND_INDIA (~150
// points), not left at full 1154-point survey resolution -- this remains a
// deliberate "engineering approximation", just a substantially more
// accurate one than the current 18-point version.
//
// Run: node scripts/extract_australia_outline.js

const topojson = require("topojson-client");
const world = require("world-atlas/countries-50m.json");

function perpendicularDistance(pt, lineStart, lineEnd) {
  const [x, y] = pt, [x1, y1] = lineStart, [x2, y2] = lineEnd;
  const dx = x2 - x1, dy = y2 - y1;
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return Math.hypot(x - x1, y - y1);
  const t = ((x - x1) * dx + (y - y1) * dy) / len2;
  const px = x1 + t * dx, py = y1 + t * dy;
  return Math.hypot(x - px, y - py);
}

function douglasPeucker(points, epsilon) {
  if (points.length < 3) return points.slice();
  let maxDist = 0, maxIdx = 0;
  for (let i = 1; i < points.length - 1; i++) {
    const d = perpendicularDistance(points[i], points[0], points[points.length - 1]);
    if (d > maxDist) { maxDist = d; maxIdx = i; }
  }
  if (maxDist > epsilon) {
    const left = douglasPeucker(points.slice(0, maxIdx + 1), epsilon);
    const right = douglasPeucker(points.slice(maxIdx), epsilon);
    return left.slice(0, -1).concat(right);
  }
  return [points[0], points[points.length - 1]];
}

function ringFor(name, minPoints) {
  const geo = topojson.feature(world, world.objects.countries);
  const feat = geo.features.find((f) => f.properties && f.properties.name === name);
  const polys = feat.geometry.type === "Polygon" ? [feat.geometry.coordinates] : feat.geometry.coordinates;
  // The mainland/largest island is the ring with the most points.
  let best = polys[0][0];
  polys.forEach((p) => { if (p[0].length > best.length) best = p[0]; });
  return best;
}

function simplifyToTarget(ring, target) {
  let lo = 0.001, hi = 2.0, best = ring;
  for (let i = 0; i < 25; i++) {
    const mid = (lo + hi) / 2;
    const simplified = douglasPeucker(ring, mid);
    if (simplified.length > target) lo = mid;
    else { hi = mid; best = simplified; }
  }
  return best;
}

function toPythonTuples(ring, decimals = 2) {
  return ring.map(([lon, lat]) => `(${lon.toFixed(decimals)},${lat.toFixed(decimals)})`);
}

function formatPythonList(tuples, indent = "    ") {
  const lines = [];
  let line = indent;
  tuples.forEach((t) => {
    const piece = t + ",";
    if (line.length + piece.length > 100) { lines.push(line); line = indent; }
    line += piece;
  });
  if (line.trim()) lines.push(line);
  return lines.join("\n");
}

const mainlandRaw = ringFor("Australia", 150);
const mainlandSimplified = simplifyToTarget(mainlandRaw, 430);
console.log(`Mainland: ${mainlandRaw.length} raw -> ${mainlandSimplified.length} simplified`);

// Tasmania is a separate small feature in this dataset's countries layer --
// it is NOT its own top-level country (Natural Earth folds it into
// Australia's multipolygon), so pull the second-largest ring of the same
// Australia feature (the mainland is by far the largest, Tasmania the
// clear second).
function tasmaniaRing() {
  const geo = topojson.feature(world, world.objects.countries);
  const feat = geo.features.find((f) => f.properties && f.properties.name === "Australia");
  const polys = feat.geometry.type === "Polygon" ? [feat.geometry.coordinates] : feat.geometry.coordinates;
  const rings = polys.map((p) => p[0]).sort((a, b) => b.length - a.length);
  return rings[1];
}
const tasmaniaRaw = tasmaniaRing();
const tasmaniaSimplified = simplifyToTarget(tasmaniaRaw, 40);
console.log(`Tasmania: ${tasmaniaRaw.length} raw -> ${tasmaniaSimplified.length} simplified`);

const fs = require("fs");
const out = [];
out.push("MAINLAND_AUSTRALIA = [");
out.push(formatPythonList(toPythonTuples(mainlandSimplified)));
out.push("]");
out.push("TASMANIA = [");
out.push(formatPythonList(toPythonTuples(tasmaniaSimplified)));
out.push("]");
fs.writeFileSync("scripts/australia_outline_output.txt", out.join("\n"));
console.log("Written to scripts/australia_outline_output.txt");
