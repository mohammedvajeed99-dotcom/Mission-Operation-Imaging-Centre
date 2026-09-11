import React from "react";
import { createRoot } from "react-dom/client";
import jsPDF from "jspdf";
import autoTable from "jspdf-autotable";
import { feature } from "topojson-client";
import worldTopo from "world-atlas/land-110m.json";
import logoUrl from "../logo.jpeg";
/* Mission Image Center (v1.1) — additive module, no existing view changed. */
import { GlobalLocationExplorer, ImageCatalogView, ImageGalleryView } from "./imageCenter.jsx";
import {
  ConstellationSummaryView,
  RevisitAnalyticsView,
  CoverageGapView,
  SatContributionView,
  DensityHeatmapsView,
  AoiAnalyticsView,
  SimulationDetailsView,
  ConstellationAnimationView,
  MissionAnalyticsView,
  MissionComparisonView,
  DashboardGuideView,
  GroundStationAnalysisView,
  SpacecraftVisualization,
} from "./analyticsViews.jsx";
import { GlossaryContext, InfoPopover } from "./glossary.jsx";
import { AccessGate, AccessProvider, buildAccessUrl, useAccess } from "./access.jsx";
import {
  Activity,
  AlertTriangle,
  Antenna,
  Aperture,
  ArrowLeft,
  Camera,
  CheckSquare,
  Compass,
  Cpu,
  Database,
  Download,
  Gauge,
  Globe2,
  HardDrive,
  Image as ImageIcon,
  Info,
  KeyRound,
  LayoutDashboard,
  Lock,
  LockOpen,
  MapPinned,
  Orbit,
  Pause,
  Play,
  Radio,
  RefreshCw,
  Satellite,
  Send,
  ShieldCheck,
  SunMedium,
  Square,
  Unlock,
  Upload,
  Zap,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import "./styles.css";

/* `??` not `||`: a production build sets VITE_API_BASE to an empty string so
   every request is same-origin (the API and the built UI are served together).
   With `||` the empty string would be treated as unset and fall back to
   localhost, which breaks for anyone opening the app from another machine. */
const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:5001";

const COLORS = {
  blue: "#3b82f6",
  cyan: "#22d3ee",
  green: "#34d399",
  amber: "#fbbf24",
  red: "#fb5c73",
  violet: "#a78bfa",
  pink: "#f472b6",
  axis: "#5f6d8c",
  grid: "rgba(120,150,220,.10)",
};
const PIE_COLORS = [COLORS.cyan, COLORS.amber, COLORS.green, COLORS.violet, COLORS.pink];

/* subsystem color language (matches the mission duty-cycle matrix) */
const SUBSYS = {
  Orbit: { color: COLORS.cyan, icon: Orbit },
  Power: { color: COLORS.amber, icon: Zap },
  Data: { color: COLORS.violet, icon: Database },
  GSN: { color: COLORS.green, icon: Antenna },
  Upload: { color: COLORS.pink, icon: Upload },
};

/* ----------------------------- formatting ----------------------------- */

function number(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "NA";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}
function compact(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "NA";
  return Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(Number(value));
}
/* Some prose/MethodNote copy was originally written against the 48-satellite
   mission and contains the literal fleet size. Substitute the active
   mission's real satellite count so it stays accurate for smaller missions
   (e.g. the 3x1 constellation) instead of a fixed "48". */
function swap48(str, satCount) {
  return satCount && typeof str === "string" ? str.replace(/\b48\b/g, String(satCount)) : str;
}
function swap48Methods(items, satCount) {
  return (items || []).map((m) => ({ ...m, meaning: swap48(m.meaning, satCount), formula: swap48(m.formula, satCount) }));
}
const asMinutes = (v) => `${number(v, 1)} min`;
const asHours = (v) => `${number(v, 2)} h`;
const asPct = (v) => `${number(v, 1)}%`;

/* AOI bounding box -> "68°E-98°E · 8°N-37°N" style label, from whatever box
   the active mission's dashboard payload actually carries (core.regions
   .aoi_box_for_mission), instead of a fixed Australia string. */
function fmtAoiBox(box) {
  if (!box) return "AOI";
  const deg = (v, posSuffix, negSuffix) => `${number(Math.abs(v), 0)}°${v < 0 ? negSuffix : posSuffix}`;
  return `${deg(box.lonMin, "E", "W")}–${deg(box.lonMax, "E", "W")} · ${deg(box.latMin, "N", "S")}–${deg(box.latMax, "N", "S")}`;
}

// Every timestamp here is a mission UTC value (GMAT UTCGregorian-derived,
// see core.time_utils on the backend) -- `timeZone: "UTC"` is required, not
// cosmetic: Intl.DateTimeFormat defaults to the *viewer's own* timezone
// when none is given, so without this a mission analyst outside UTC+0
// would silently see a shifted clock reading for the exact same instant
// a UTC+0 viewer sees, with nothing in the label to say so.
function dateLabel(value) {
  if (!value) return "NA";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "NA";
  return new Intl.DateTimeFormat(undefined, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(date) + " UTC";
}
function timeLabel(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", timeZone: "UTC" }).format(date) + " UTC";
}
const hueFor = (index) => `hsl(${(index * 47) % 360} 82% 62%)`;

// Compact chart-label form of a real satellite name (from mission telemetry
// -- see core.missions/state_parser). Two real conventions exist across
// this app's actual missions: "ASC_074_16" (underscore + zero-padded
// number, asc074_6x8/asc080_1x3/asc080_6x4) and "ASC_074A" (a bare letter
// suffix with no separating underscore, asc074_3x1's real GMAT-assigned
// names) -- a regex tuned only for the first form left the second
// undecorated in every chart that uses this (full "ASC_074A" instead of a
// short "A"), not wrong, just inconsistent with every mission that happens
// to use the other convention. `prefix` matches each call site's existing
// replacement (e.g. "S" for "S16"-style labels).
function shortSat(name, prefix = "") {
  const byDigitSuffix = name.replace(/^.*_(?=\d+$)/, prefix);
  if (byDigitSuffix !== name) return byDigitSuffix;
  return name.replace(/^.*\d(?=[A-Za-z]+$)/, prefix);
}

/* -------------------- world map (equirectangular) --------------------- */

const MAP_W = 1000;
const MAP_H = 500;
const projX = (lon) => ((Number(lon) + 180) / 360) * MAP_W;
const projY = (lat) => ((90 - Number(lat)) / 180) * MAP_H;

const LAND_PATH = (() => {
  try {
    const geo = feature(worldTopo, worldTopo.objects.land);
    const features = geo.features || [geo];
    let d = "";
    features.forEach((f) => {
      const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
      polys.forEach((poly) =>
        poly.forEach((ring) => {
          // A ring that crosses the antimeridian (e.g. Russia, Alaska, Fiji,
          // Antarctica) has consecutive points that jump from ~+180 to ~-180
          // in raw longitude. Drawing that as a normal line segment draws a
          // straight glitch line across the entire map; breaking into a new
          // subpath there, the same fix used for satellite ground tracks,
          // keeps each land fragment separate instead.
          let prevLon = null;
          ring.forEach((pt, i) => {
            const wrapped = prevLon !== null && Math.abs(pt[0] - prevLon) > 180;
            d += `${i === 0 || wrapped ? "M" : "L"}${projX(pt[0]).toFixed(1)} ${projY(pt[1]).toFixed(1)}`;
            prevLon = pt[0];
          });
          d += "Z";
        })
      );
    });
    return d;
  } catch (err) {
    return "";
  }
})();

const DEFAULT_AOI_BOX = { lonMin: 110, lonMax: 160, latMin: -40, latMax: -10 };

/* Builds an SVG path `d` from one or more closed lon/lat rings (the same
   real, coastline-derived land-boundary polygons -- core.australia_coverage
   .MAINLAND_AUSTRALIA/TASMANIA/MAINLAND_INDIA -- already sent to the
   frontend as data.coverage.outline/tasmania and already used to draw the
   Coverage Map's own AOI outline there). Used in place of the old
   rectangular AOI box: a lon/lat bounding rectangle necessarily includes
   whatever other territory sits in its corners (e.g. India's box, spanning
   the full 68-97.5E at its northernmost latitude, swept in a wide band of
   Tibet/western China that is nowhere near India's real border), which a
   real outline does not. */
function outlinePathD(rings = []) {
  let d = "";
  rings.forEach((ring) => {
    if (!ring || !ring.length) return;
    ring.forEach((pt, i) => {
      const lon = pt.lon ?? pt[0];
      const lat = pt.lat ?? pt[1];
      d += `${i === 0 ? "M" : "L"}${projX(lon).toFixed(1)} ${projY(lat).toFixed(1)}`;
    });
    d += "Z";
  });
  return d;
}

/* Shared map base: ocean, graticule, land silhouette, AOI outline */
function MapBase({ showAoi = true, aoiBox = DEFAULT_AOI_BOX, outline = [], secondary = [] }) {
  const lonLines = [-150, -120, -90, -60, -30, 0, 30, 60, 90, 120, 150];
  const latLines = [-60, -30, 0, 30, 60];
  const hasOutline = outline.length > 0;
  return (
    <g>
      <rect width={MAP_W} height={MAP_H} fill="#081426" />
      <rect width={MAP_W} height={MAP_H} fill="url(#oceanGlow)" />
      {lonLines.map((lon) => (
        <g key={`lon${lon}`}>
          <line x1={projX(lon)} y1={0} x2={projX(lon)} y2={MAP_H} className="graticule" />
          <text x={projX(lon) + 3} y={MAP_H - 6} className="graticuleLabel">{lon}</text>
        </g>
      ))}
      {latLines.map((lat) => (
        <g key={`lat${lat}`}>
          <line x1={0} y1={projY(lat)} x2={MAP_W} y2={projY(lat)} className="graticule" />
          {lat !== 0 ? <text x={4} y={projY(lat) - 4} className="graticuleLabel">{lat}</text> : null}
        </g>
      ))}
      <path d={LAND_PATH} className="landMass" />
      {showAoi ? (
        hasOutline ? (
          <path d={outlinePathD([outline, secondary])} className="aoiRect" fillRule="evenodd" />
        ) : (
          <rect
            x={projX(aoiBox.lonMin)}
            y={projY(aoiBox.latMax)}
            width={projX(aoiBox.lonMax) - projX(aoiBox.lonMin)}
            height={projY(aoiBox.latMin) - projY(aoiBox.latMax)}
            className="aoiRect"
          />
        )
      ) : null}
    </g>
  );
}

/* ------------------ animated constellation simulator ------------------ */

const SIM_WINDOWS = [
  ["15 min", 15 * 60000],
  ["1 hour", 60 * 60000],
  ["3 hours", 180 * 60000],
  ["6 hours", 360 * 60000],
  ["Full day", Infinity],
];
const SIM_SPEEDS = [
  ["0.5×", 0.5],
  ["1×", 1],
  ["2×", 2],
  ["4×", 4],
];

function fmtEpoch(ms) {
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "—";
  const p = (n) => String(n).padStart(2, "0");
  // UTC getters, not local (getDate/getHours/...) -- every epoch played
  // back here is a mission UTC timestamp (see core.time_utils), and the
  // local getters silently substitute the viewer's own timezone for it
  // with no indication anything shifted.
  const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getUTCMonth()];
  return `${p(d.getUTCDate())} ${mon} ${d.getUTCFullYear()} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())} UTC`;
}

function ConstellationSim({ series = {}, satellites = [], range, height = 520, defaultWindowMs = 60 * 60000, aoiBox = DEFAULT_AOI_BOX, aoiLabel = "Australia", outline = [], secondary = [] }) {
  const sats = React.useMemo(
    () =>
      satellites
        .map((s, i) => ({
          name: s,
          color: hueFor(i),
          pts: (series[s] || [])
            .map((p) => ({ t: Date.parse(p.t), lon: Number(p.lon), lat: Number(p.lat) }))
            .filter((p) => Number.isFinite(p.t) && Number.isFinite(p.lon) && Number.isFinite(p.lat)),
        }))
        .filter((o) => o.pts.length > 1),
    [series, satellites]
  );

  const [tMin, tMax] = React.useMemo(() => {
    const rs = range?.start ? Date.parse(range.start) : NaN;
    const re = range?.end ? Date.parse(range.end) : NaN;
    if (Number.isFinite(rs) && Number.isFinite(re)) return [rs, re];
    const all = sats.flatMap((o) => o.pts.map((p) => p.t));
    return all.length ? [Math.min(...all), Math.max(...all)] : [0, 1];
  }, [range, sats]);
  const span = Math.max(tMax - tMin, 1);

  const [now, setNow] = React.useState(tMin);
  const [playing, setPlaying] = React.useState(!reduceMotion);
  const [windowMs, setWindowMs] = React.useState(defaultWindowMs);
  const [speed, setSpeed] = React.useState(1);
  const nowRef = React.useRef(now);
  nowRef.current = now;

  React.useEffect(() => {
    setNow(tMin);
  }, [tMin]);

  React.useEffect(() => {
    if (!playing) return undefined;
    let raf;
    let last;
    const perMs = span / 60000; // full span plays in ~60s at 1x
    const step = (ts) => {
      if (last === undefined) last = ts;
      const dt = ts - last;
      last = ts;
      let n = nowRef.current + dt * perMs * speed;
      if (n > tMax) n = tMin;
      nowRef.current = n;
      setNow(n);
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, span, tMin, tMax]);

  const from = windowMs === Infinity ? tMin : now - windowMs;

  const trail = (pts) => {
    let d = "";
    let prev = null;
    for (const p of pts) {
      if (p.t < from || p.t > now) continue;
      const x = projX(p.lon);
      const y = projY(p.lat);
      if (prev && Math.abs(p.lon - prev.lon) > 180) d += `M${x.toFixed(1)} ${y.toFixed(1)}`;
      else d += `${prev ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
      prev = p;
    }
    return d;
  };

  const headAt = (pts) => {
    if (now <= pts[0].t) return pts[0];
    if (now >= pts[pts.length - 1].t) return pts[pts.length - 1];
    for (let i = 0; i < pts.length - 1; i++) {
      if (pts[i].t <= now && now < pts[i + 1].t) {
        const a = pts[i];
        const b = pts[i + 1];
        if (Math.abs(b.lon - a.lon) > 180) return a;
        const f = (now - a.t) / (b.t - a.t || 1);
        return { lon: a.lon + (b.lon - a.lon) * f, lat: a.lat + (b.lat - a.lat) * f };
      }
    }
    return pts[pts.length - 1];
  };

  const heads = sats.map((o) => ({ ...o, head: headAt(o.pts) }));
  const overAoi = heads.filter(
    (o) => o.head.lon >= aoiBox.lonMin && o.head.lon <= aoiBox.lonMax && o.head.lat >= aoiBox.latMin && o.head.lat <= aoiBox.latMax
  ).length;

  return (
    <div className="simWrap">
      <div className="simBar">
        <button className="simPlay" onClick={() => setPlaying((p) => !p)} title={playing ? "Pause" : "Play"}>
          {playing ? <Pause size={16} /> : <Play size={16} />}
        </button>
        <label className="simField">
          <span>Trail</span>
          <select value={windowMs} onChange={(e) => setWindowMs(Number(e.target.value))}>
            {SIM_WINDOWS.map(([label, ms]) => (
              <option key={label} value={ms}>{label}</option>
            ))}
          </select>
        </label>
        <label className="simField">
          <span>Speed</span>
          <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
            {SIM_SPEEDS.map(([label, v]) => (
              <option key={label} value={v}>{label}</option>
            ))}
          </select>
        </label>
        <input
          className="simScrub"
          type="range"
          min={tMin}
          max={tMax}
          value={Math.min(Math.max(now, tMin), tMax)}
          step={Math.max(span / 1000, 1)}
          onChange={(e) => setNow(Number(e.target.value))}
        />
        <span className="simAoi">{overAoi} over AOI</span>
      </div>

      <div className="orbitMap">
        <svg viewBox={`0 0 ${MAP_W} ${MAP_H}`} style={{ maxHeight: height }} role="img" aria-label="Animated constellation ground tracks">
          <defs>
            <radialGradient id="oceanGlow" cx="50%" cy="42%" r="70%">
              <stop offset="0%" stopColor="rgba(34,90,150,.55)" />
              <stop offset="100%" stopColor="rgba(6,16,32,.9)" />
            </radialGradient>
          </defs>
          <MapBase aoiBox={aoiBox} outline={outline} secondary={secondary} />
          {sats.map((o) => (
            <path key={o.name} d={trail(o.pts)} fill="none" stroke={o.color} strokeWidth="1.1" strokeOpacity="0.85" strokeLinejoin="round" />
          ))}
          {heads.map((o) => {
            const x = projX(o.head.lon);
            const y = projY(o.head.lat);
            const inAoi = o.head.lon >= aoiBox.lonMin && o.head.lon <= aoiBox.lonMax && o.head.lat >= aoiBox.latMin && o.head.lat <= aoiBox.latMax;
            return (
              <g key={`h${o.name}`} transform={`translate(${x.toFixed(1)} ${y.toFixed(1)})`}>
                <circle r="4.5" fill={o.color} opacity="0.28" />
                <circle r="2.1" fill="#fff" stroke={o.color} strokeWidth="1.1" />
                {inAoi ? <text x="6" y="3" className="satTag" fill={o.color}>{shortSat(o.name)}</text> : null}
                <title>{`${o.name} · ${number(o.head.lat, 2)}°, ${number(o.head.lon, 2)}°`}</title>
              </g>
            );
          })}
        </svg>
        <div className="simEpoch mono">Epoch: {fmtEpoch(now)}</div>
        <div className="mapLegend">
          <span><i className="dot blue" /> {sats.length} satellites</span>
          <span><i className="legLine" /> ground tracks</span>
          <span><i className="aoiSwatch" /> AOI ({aoiLabel})</span>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------- hooks -------------------------------- */

const reduceMotion =
  typeof window !== "undefined" &&
  window.matchMedia &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function useCountUp(target, duration = 950) {
  const [value, setValue] = React.useState(reduceMotion ? target : 0);
  React.useEffect(() => {
    if (reduceMotion || !Number.isFinite(target)) {
      setValue(target);
      return;
    }
    let raf;
    let start;
    const step = (ts) => {
      if (start === undefined) start = ts;
      const p = Math.min((ts - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      setValue(target * eased);
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);
  return value;
}

function Counter({ value, format }) {
  const animated = useCountUp(Number(value));
  return <span className="mono">{format ? format(animated) : number(animated)}</span>;
}

/* Circular gauge sweeping to `percent` (0-100) in step with the KPI card's
   own count-up (same hook, same easing) so the ring and the big number
   finish together instead of the ring looking like an unrelated decoration.
   Renders inside the KPI's own accent-coloured icon slot, replacing the
   plain flat swatch with an actual progress read -- the kind of at-a-glance
   gauge a finished analytics dashboard has and a first-pass one usually
   doesn't. */
function RadialProgress({ percent, size = 34, strokeWidth = 3, children }) {
  const clamped = Number.isFinite(percent) ? Math.max(0, Math.min(100, percent)) : 0;
  const animated = useCountUp(clamped, 950);
  const r = (size - strokeWidth) / 2;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - Math.max(0, Math.min(animated, 100)) / 100);
  return (
    <span className="kpiRing" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} className="kpiRingTrack" strokeWidth={strokeWidth} fill="none" />
        <circle
          cx={size / 2} cy={size / 2} r={r} className="kpiRingFill" strokeWidth={strokeWidth} fill="none"
          strokeDasharray={c} strokeDashoffset={offset} strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <span className="kpiRingIcon">{children}</span>
    </span>
  );
}

/* Small per-satellite bar sparkline for a KPI card. Deliberately bars, not
   a connected line: a line reads as a trend over time, but every caller of
   this passes one real value per satellite (rf/optical/eclipse counts,
   duty %, altitude) -- a discrete breakdown across the fleet, not a time
   series. Bars say "one bar per craft" at a glance instead of implying an
   x-axis that isn't there. Only ever fed real numbers already present in
   the fetched dashboard payload (see each KpiCard call site) -- never
   synthesized, matching this app's own no-fabricated-data rule for every
   other chart. Renders nothing rather than a misleading flat line when
   there is under 2 real points to compare. */
function Sparkline({ values, labels, accent = "currentColor", width = 72, height = 26 }) {
  const clean = (values || []).map((v) => (Number.isFinite(v) ? v : null));
  const real = clean.filter((v) => v !== null);
  if (real.length < 2) return null;
  const max = Math.max(...real, 0);
  const min = Math.min(...real, 0);
  const span = max - min || 1;
  const n = clean.length;
  const barW = width / n;
  const gap = Math.min(2, barW * 0.25);
  return (
    <svg
      className="kpiSpark"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      {clean.map((v, i) => {
        if (v === null) return null;
        const h = Math.max(((v - min) / span) * (height - 2), v === 0 ? 0 : 2);
        const x = i * barW + gap / 2;
        const w = Math.max(barW - gap, 1);
        return (
          <rect
            key={labels?.[i] ?? i}
            x={x} y={height - h} width={w} height={h}
            rx={Math.min(1.5, w / 2)}
            fill={accent}
            opacity={0.55 + 0.45 * ((v - min) / span || 0)}
          >
            {labels?.[i] ? <title>{`${labels[i]}: ${number(v, 2)}`}</title> : null}
          </rect>
        );
      })}
    </svg>
  );
}

function useMissions() {
  const [missions, setMissions] = React.useState([]);
  const [defaultMission, setDefaultMission] = React.useState("asc074_6x8");

  React.useEffect(() => {
    fetch(`${API_BASE}/api/missions`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!d) return;
        setMissions(d.missions || []);
        if (d.default) setDefaultMission(d.default);
      })
      .catch(() => {});
  }, []);

  return { missions, defaultMission };
}

function useGlossaryMapFetch() {
  const [glossaryMap, setGlossaryMap] = React.useState({});

  React.useEffect(() => {
    fetch(`${API_BASE}/api/glossary`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!d) return;
        const map = {};
        (d.terms || []).forEach((t) => { map[t.key] = t; });
        setGlossaryMap(map);
      })
      .catch(() => {});
  }, []);

  return glossaryMap;
}

function useDashboard(missionId) {
  const { authFetch } = useAccess();
  const [data, setData] = React.useState(null);
  const [state, setState] = React.useState(null);
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [refreshing, setRefreshing] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [dRes, sRes] = await Promise.all([
        authFetch(`${API_BASE}/api/dashboard?mission=${missionId}`),
        authFetch(`${API_BASE}/api/state?mission=${missionId}`),
      ]);
      if (!dRes.ok) throw new Error(`API returned ${dRes.status}`);
      setData(await dRes.json());
      // A 403 here just means no state-consuming section is unlocked yet;
      // the affected views render their own lock panel, so it is not an error.
      setState(sRes.ok ? await sRes.json() : null);
    } catch (err) {
      setError(err.message || "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }, [missionId, authFetch]);

  const refresh = React.useCallback(async () => {
    setRefreshing(true);
    setError("");
    try {
      const response = await authFetch(`${API_BASE}/api/refresh?mission=${missionId}`, { method: "POST" });
      if (response.status === 403) throw new Error("Refreshing mission data requires the Data & Config access code");
      if (!response.ok) throw new Error(`Refresh failed with ${response.status}`);
      await load();
    } catch (err) {
      setError(err.message || "Failed to refresh data");
    } finally {
      setRefreshing(false);
    }
  }, [load, missionId, authFetch]);

  React.useEffect(() => {
    load();
  }, [load]);

  // `retry` re-runs the same load, for the offline error screen. `refresh`
  // is different: it re-runs the processing pipeline on the server first.
  return { data, state, loading, error, refreshing, refresh, retry: load };
}

/* ------------------------------ chrome -------------------------------- */

/* Canvas starfield: hundreds of individually-varied stars across three
   parallax depth layers (far/mid/near), each drifting at its own slow
   constant velocity with a toroidal wrap so the field never visibly resets.
   A minority of stars twinkle on their own sine phase so the shimmer never
   reads as one synchronized pulse. Scroll nudges each layer's vertical
   offset by a different amount (near layer moves more than far layer),
   which is what gives scrolling its "drifting past the stars" feel.

   Runs its own rAF loop rather than relying on CSS animation because it
   needs to react to scroll and pause on tab-hide / prefers-reduced-motion
   itself -- a canvas redraw isn't something CSS can drive. */
function Starfield() {
  const canvasRef = React.useRef(null);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const ctx = canvas.getContext("2d");
    const reduceMotion =
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const LAYERS = [
      { density: 4400, rMin: 0.6, rMax: 1.3, aMin: 0.35, aMax: 0.7, speed: 3.5, parallax: 0.02, twinklePct: 0.2, glow: false },
      { density: 8000, rMin: 1.0, rMax: 1.9, aMin: 0.5, aMax: 0.85, speed: 7, parallax: 0.045, twinklePct: 0.3, glow: false },
      { density: 16000, rMin: 1.5, rMax: 2.6, aMin: 0.7, aMax: 1.0, speed: 13, parallax: 0.09, twinklePct: 0.4, glow: true },
    ];
    // A gentle constant drift direction (down-right), like slowly gliding
    // past the sky rather than stars randomly wandering.
    const DRIFT_ANGLE = 0.62; // radians

    let width = 0;
    let height = 0;
    let dpr = Math.min(window.devicePixelRatio || 1, 2);
    let stars = [];
    let raf = null;
    let running = false;
    let scrollY = window.scrollY || 0;
    let lastTs = 0;

    function buildStars() {
      stars = [];
      const mobileScale = width < 760 ? 0.55 : 1;
      LAYERS.forEach((layer, li) => {
        const count = Math.max(12, Math.floor(((width * height) / layer.density) * mobileScale));
        for (let i = 0; i < count; i++) {
          stars.push({
            layer: li,
            x: Math.random() * width,
            y: Math.random() * height,
            r: layer.rMin + Math.random() * (layer.rMax - layer.rMin),
            baseAlpha: layer.aMin + Math.random() * (layer.aMax - layer.aMin),
            twinkle: Math.random() < layer.twinklePct,
            twinkleSpeed: 0.6 + Math.random() * 1.4,
            twinklePhase: Math.random() * Math.PI * 2,
          });
        }
      });
    }

    function resize() {
      // Measure the canvas's own rendered box rather than trusting
      // window.innerWidth or documentElement.clientWidth: the element is
      // position:fixed + inset:0, so its actual on-screen size is whatever
      // the browser laid it out at, and those two other metrics can each
      // diverge from that under page zoom or some mobile emulation modes.
      // Sizing the drawing buffer to anything else stretches every star.
      const box = canvas.getBoundingClientRect();
      width = box.width;
      height = box.height;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      buildStars();
    }

    function draw(ts) {
      const dt = lastTs ? Math.min(ts - lastTs, 50) : 16;
      lastTs = ts;
      ctx.clearRect(0, 0, width, height);

      for (const s of stars) {
        const layer = LAYERS[s.layer];
        if (!reduceMotion) {
          s.x += Math.cos(DRIFT_ANGLE) * layer.speed * (dt / 1000);
          s.y += Math.sin(DRIFT_ANGLE) * layer.speed * (dt / 1000);
          if (s.x > width + 4) s.x = -4;
          if (s.x < -4) s.x = width + 4;
          if (s.y > height + 4) s.y = -4;
          if (s.y < -4) s.y = height + 4;
        }

        let alpha = s.baseAlpha;
        if (s.twinkle && !reduceMotion) {
          alpha *= 0.55 + 0.45 * Math.sin(ts * 0.001 * s.twinkleSpeed + s.twinklePhase);
        }
        const yOffset = reduceMotion ? 0 : (scrollY * layer.parallax) % (height + 40);
        const drawY = ((s.y - yOffset) % (height + 8) + (height + 8)) % (height + 8);

        ctx.beginPath();
        ctx.globalAlpha = Math.max(alpha, 0);
        ctx.fillStyle = "#eaf2ff";
        // Only the near layer's larger stars get a soft glow halo -- that's
        // what reads as "premium sparkle" rather than flat dots, and
        // shadowBlur has a real per-draw cost so it stays limited to the
        // ~50 stars in that one layer instead of every star on screen.
        if (layer.glow) {
          ctx.shadowBlur = s.r * 4;
          ctx.shadowColor = "rgba(160, 205, 255, 0.9)";
        } else {
          ctx.shadowBlur = 0;
        }
        ctx.arc(s.x, drawY, s.r, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.shadowBlur = 0;
      ctx.globalAlpha = 1;

      if (running) raf = requestAnimationFrame(draw);
    }

    function start() {
      if (running) return;
      running = true;
      lastTs = 0;
      raf = requestAnimationFrame(draw);
    }
    function stop() {
      running = false;
      if (raf) cancelAnimationFrame(raf);
      raf = null;
    }

    resize();
    // Reduced motion: render exactly one static frame, no loop at all.
    if (reduceMotion) {
      draw(0);
    } else {
      start();
    }

    const onResize = () => {
      resize();
    };
    const onScroll = () => {
      scrollY = window.scrollY || 0;
    };
    const onVisibility = () => {
      if (reduceMotion) return;
      if (document.hidden) stop();
      else start();
    };

    window.addEventListener("resize", onResize);
    window.addEventListener("scroll", onScroll, { passive: true });
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      stop();
      window.removeEventListener("resize", onResize);
      window.removeEventListener("scroll", onScroll);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return <canvas ref={canvasRef} className="starfieldCanvas" aria-hidden="true" />;
}

function Backdrop() {
  return (
    <>
      <div className="spaceBg" />
      <Starfield />
      <div className="gridOverlay" />
    </>
  );
}

/* Welcome screen background: plain scattered stars (no connecting lines,
   no highlighted/pulsing node -- that read as clutter), a few small
   decorative planets, and a handful of satellites drifting past. Static
   SVG (viewBox scaled to cover the viewport like the world map elsewhere,
   so circles never stretch into ellipses); satellites drift via CSS -- no
   JS animation loop. Decorative only: behind all real content, same
   stacking layer as .gridOverlay. */
const FIELD_W = 1600;
const FIELD_H = 900;
/* Mission-ops feel, not a space landing page: sparse stars, two small
   planets and a distant sun (kept smaller/dimmer than a landing-page hero
   would use), and one faint satellite trace. Everything renders at
   controlled opacity via CSS so it never competes with the mission cards. */
const STARS = [
  [70, 470], [1490, 90], [1180, 700], [420, 120], [760, 60],
  [1080, 380], [1400, 340], [220, 210], [1550, 620], [640, 830],
  [900, 850], [340, 880], [1250, 860], [60, 830], [1550, 830],
];

const PLANETS = [
  { cx: 150, cy: 730, r: 18, tone: "planetViolet" },
  { cx: 1440, cy: 170, r: 12, tone: "planetCyan", ring: true },
];
const SUN = { cx: 80, cy: 70, r: 5 };

const WELCOME_SATS = [
  { top: "24%", size: 26, dur: 55, delay: 0, rise: -18, tone: "cyan" },
];

/* A small satellite silhouette (body + two solar-panel wings + antenna) --
   more recognisable at a glance than an abstract icon glyph. Fixed
   viewBox/aspect ratio, sized via the `size` prop like a normal icon. */
function SatelliteGlyph({ size = 24, className, style }) {
  return (
    <svg
      className={className}
      style={style}
      width={size}
      height={size * 0.6}
      viewBox="0 0 64 38"
      fill="none"
    >
      <rect x="2" y="14" width="16" height="10" rx="1" stroke="currentColor" strokeOpacity="0.85" strokeWidth="1.5" />
      <line x1="4" y1="16.5" x2="16" y2="16.5" stroke="currentColor" strokeOpacity="0.5" strokeWidth="0.8" />
      <line x1="4" y1="21.5" x2="16" y2="21.5" stroke="currentColor" strokeOpacity="0.5" strokeWidth="0.8" />
      <rect x="46" y="14" width="16" height="10" rx="1" stroke="currentColor" strokeOpacity="0.85" strokeWidth="1.5" />
      <line x1="48" y1="16.5" x2="60" y2="16.5" stroke="currentColor" strokeOpacity="0.5" strokeWidth="0.8" />
      <line x1="48" y1="21.5" x2="60" y2="21.5" stroke="currentColor" strokeOpacity="0.5" strokeWidth="0.8" />
      <line x1="18" y1="19" x2="24" y2="19" stroke="currentColor" strokeWidth="1.5" />
      <line x1="40" y1="19" x2="46" y2="19" stroke="currentColor" strokeWidth="1.5" />
      <rect x="24" y="13" width="16" height="12" rx="2" fill="currentColor" />
      <line x1="32" y1="13" x2="32" y2="5" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="32" cy="4" r="2" fill="currentColor" />
    </svg>
  );
}

function ConstellationField() {
  return (
    <div className="welcomeSatField" aria-hidden="true">
      <svg className="welcomeConstMap" viewBox={`0 0 ${FIELD_W} ${FIELD_H}`} preserveAspectRatio="xMidYMid slice">
        <defs>
          <radialGradient id="planetViolet" cx="32%" cy="28%" r="80%">
            <stop offset="0%" stopColor="#e4d9ff" />
            <stop offset="30%" stopColor="#9d84e0" />
            <stop offset="100%" stopColor="#241a45" />
          </radialGradient>
          <radialGradient id="planetCyan" cx="32%" cy="28%" r="80%">
            <stop offset="0%" stopColor="#d4faff" />
            <stop offset="30%" stopColor="#3cc4dc" />
            <stop offset="100%" stopColor="#0a2e38" />
          </radialGradient>
          <radialGradient id="sunGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#eef6ff" />
            <stop offset="35%" stopColor="rgba(180, 210, 255, 0.3)" />
            <stop offset="100%" stopColor="rgba(180, 210, 255, 0)" />
          </radialGradient>
          {PLANETS.map((p, i) => (
            <clipPath id={`planetClip${i}`} key={i}>
              <circle cx={p.cx} cy={p.cy} r={p.r} />
            </clipPath>
          ))}
        </defs>

        <circle cx={SUN.cx} cy={SUN.cy} r={SUN.r * 8} fill="url(#sunGlow)" />
        <circle cx={SUN.cx} cy={SUN.cy} r={SUN.r} className="sunCore" />

        {STARS.map((p, i) => (
          <circle key={i} cx={p[0]} cy={p[1]} r={1.9} className="bgStar" style={{ "--i": i }} />
        ))}

        {PLANETS.map((p, i) => (
          <g key={i} className="planetGlow">
            {p.ring ? (
              <ellipse
                cx={p.cx}
                cy={p.cy}
                rx={p.r * 1.9}
                ry={p.r * 0.5}
                transform={`rotate(-18 ${p.cx} ${p.cy})`}
                className="planetRing"
              />
            ) : null}
            <circle cx={p.cx} cy={p.cy} r={p.r} fill={`url(#${p.tone})`} />
            <circle
              cx={p.cx + p.r * 0.55}
              cy={p.cy + p.r * 0.55}
              r={p.r * 1.05}
              fill="rgba(4, 6, 15, 0.6)"
              clipPath={`url(#planetClip${i})`}
            />
            <circle cx={p.cx} cy={p.cy} r={p.r} className="planetRim" />
          </g>
        ))}
      </svg>
      {WELCOME_SATS.map((s, i) => (
        <SatelliteGlyph
          key={i}
          size={s.size}
          className={`welcomeSat ${s.tone}`}
          style={{
            "--top": s.top,
            "--dur": reduceMotion ? "0s" : `${s.dur}s`,
            "--delay": `${s.delay}s`,
            "--rise": `${s.rise}px`,
          }}
        />
      ))}
    </div>
  );
}

/* nav model — Mission group + two duty-cycle phases (K1–K10) */
const K_DEFS = [
  { id: "k1", k: "K1", name: "Constellation Transit", subsystem: "Orbit", phase: 1 },
  { id: "k2", k: "K2", name: "Sensor Power Gating", subsystem: "Power", phase: 1 },
  { id: "k3", k: "K3", name: "Store & Downlink", subsystem: "Data", phase: 1 },
  { id: "k4", k: "K4", name: "Ground Station Downlink", subsystem: "GSN", phase: 1 },
  { id: "k5", k: "K5", name: "Command Uplink", subsystem: "Upload", phase: 1 },
  { id: "k6", k: "K6", name: "AOI Active Coverage", subsystem: "Orbit", phase: 2 },
  { id: "k7", k: "K7", name: "Power Duty Budget", subsystem: "Power", phase: 2 },
  { id: "k8", k: "K8", name: "Onboard Processing", subsystem: "Data", phase: 2 },
  { id: "k9", k: "K9", name: "Downlink Pipeline", subsystem: "GSN", phase: 2 },
  { id: "k10", k: "K10", name: "Orbit Management", subsystem: "Upload", phase: 2 },
];
const K_BY_ID = Object.fromEntries(K_DEFS.map((d) => [d.id, d]));

/* A single code that unlocks every section at once, for someone who needs
   the whole dashboard rather than the per-section codes handed out for
   restricted review -- a developer or a mission lead. Server-enforced the
   same way a single section's code is: this just calls the same unlock
   endpoint with section="*", which the backend recognises as the master
   code and grants every coded section in one token. */
function FullAccessBox() {
  const { unlock, relock, sections } = useAccess();
  const [code, setCode] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState(null);

  const coded = sections.filter((s) => !s.public);
  const allUnlocked = coded.length > 0 && coded.every((s) => s.unlocked);

  const submit = async (e) => {
    e.preventDefault();
    if (!code.trim() || busy) return;
    setBusy(true);
    setMsg(null);
    const r = await unlock("*", code.trim());
    setBusy(false);
    if (r.ok) {
      setCode("");
      setMsg({ ok: true, text: "Every section unlocked." });
    } else {
      setMsg({ ok: false, text: r.error || "Incorrect code" });
    }
  };

  const lockAll = async () => {
    setBusy(true);
    await relock("*");
    setBusy(false);
    setMsg(null);
  };

  if (allUnlocked) {
    return (
      <div className="fullAccessBox fullAccessBoxOpen">
        <Unlock size={14} />
        <span>Full access unlocked</span>
        <button type="button" className="fullAccessLockAll" onClick={lockAll} disabled={busy}
                title="Lock every section again">
          Lock all
        </button>
      </div>
    );
  }

  return (
    <form className="fullAccessBox" onSubmit={submit}>
      <div className="fullAccessLabel" title="One code that opens every section at once — for a developer or reviewer who needs the whole dashboard, not just a few sections">
        <KeyRound size={14} />
        <span>Developer / reviewer access</span>
      </div>
      <div className="fullAccessRow">
        <input
          type="text"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="Full-access code"
          disabled={busy}
          autoComplete="off"
        />
        <button type="submit" disabled={busy || !code.trim()}>
          Unlock all
        </button>
      </div>
      {msg ? <p className={msg.ok ? "fullAccessOk" : "fullAccessErr"}>{msg.text}</p> : null}
    </form>
  );
}

function Sidebar({ active, setActive, onHome }) {
  const guideItem = ["guide", Info, "How to Read This Dashboard"];
  const mission = [
    ["overview", LayoutDashboard, "Mission Overview"],
    ["explorer", Satellite, "State Explorer"],
    ["coverage", Globe2, "Coverage Map"],
    ["imaging", Aperture, "Payload & Imaging"],
    ["global", Compass, "Global Coverage"],
    ["data", Database, "Data & Config"],
  ];
  const imageCenter = [
    ["ic-catalog", Camera, "Image Catalog"],
    ["ic-gallery", ImageIcon, "Image Gallery"],
    ["ic-location", MapPinned, "Global Location Explorer"],
  ];
  const analytics = [
    ["summary", LayoutDashboard, "Constellation Summary"],
    ["revisit", Activity, "Revisit Analytics"],
    ["gap-analysis", Gauge, "Coverage Gap Analysis"],
    ["ground-stations", Antenna, "Ground Station Analysis"],
    ["sat-contribution", Satellite, "Satellite Contribution"],
    ["heatmaps", Globe2, "Constellation Heatmaps"],
    ["aoi-analytics", Compass, "AOI Analytics"],
    ["sim-details", Cpu, "Simulation Details"],
    ["constellation-anim", Orbit, "Constellation Animation"],
    ["mission-analytics", ShieldCheck, "Mission Analytics"],
    ["comparison", Compass, "Mission Comparison"],
  ];
  const phase1 = K_DEFS.filter((d) => d.phase === 1);
  const phase2 = K_DEFS.filter((d) => d.phase === 2);

  const { isUnlocked, isPublic, relock } = useAccess();

  /* A locked section stays listed and clickable — the operator needs to see
     what exists in order to request its code — it just carries a lock mark
     and opens the gate instead of the view. An unlocked section gets an
     unlock mark that doubles as the control to hand that access back.
     The toggle is a sibling of the nav button, never nested inside it. */
  const LockToggle = ({ id, label }) => {
    if (isPublic(id)) return null;
    if (!isUnlocked(id)) return <Lock size={13} className="navLock" />;
    return (
      <button
        className="navRelock"
        title={`Lock “${label}” again — you will need the code to reopen it`}
        aria-label={`Lock ${label}`}
        onClick={(e) => {
          e.stopPropagation();
          relock(id);
        }}
      >
        <LockOpen size={13} />
      </button>
    );
  };

  const NavItem = ([id, Icon, label]) => (
    <div className={active === id ? "navRow active" : "navRow"} key={id}>
      <button
        className={active === id ? "navItem active" : "navItem"}
        onClick={() => setActive(id)}
        title={isUnlocked(id) ? label : `${label} — access code required`}
      >
        <Icon size={18} />
        <span>{label}</span>
      </button>
      <LockToggle id={id} label={label} />
    </div>
  );

  const KItem = (d) => {
    const sub = SUBSYS[d.subsystem];
    const Icon = sub.icon;
    const locked = !isUnlocked(d.id);
    return (
      <div className={active === d.id ? "navRow active" : "navRow"} key={d.id}>
        <button
          className={active === d.id ? "navItem navK active" : "navItem navK"}
          onClick={() => setActive(d.id)}
          title={locked ? `${d.k} · ${d.name} — access code required` : `${d.k} · ${d.name} (${d.subsystem})`}
          style={{ "--sub": sub.color }}
        >
          <span className="kBadge">
            <Icon size={15} />
            <i className="kNum">{d.k.replace("K", "")}</i>
          </span>
          <span className="kName">{d.name}</span>
        </button>
        <LockToggle id={d.id} label={`${d.k} · ${d.name}`} />
      </div>
    );
  };

  return (
    <aside className="sidebar">
      <button className="homeButton" onClick={onHome} title="Back to the Ansumi Orbital Hub home page">
        <ArrowLeft size={13} />
        <span>Home</span>
      </button>
      <div className="brand">
        <img className="brandLogo" src={logoUrl} alt="ANSUMI SPACE" />
        <span className="brandSub">Ansumi Orbital Hub</span>
      </div>

      <FullAccessBox />

      <nav className="nav">
        <div className="navGroup">
          <p className="navGroupLabel">Start Here</p>
          {NavItem(guideItem)}
        </div>

        <div className="navGroup">
          <p className="navGroupLabel">Mission</p>
          {mission.map(NavItem)}
        </div>

        <div className="navGroup">
          <p className="navGroupLabel">Constellation Analytics</p>
          {analytics.map(NavItem)}
        </div>

        <div className="navGroup">
          <p className="navGroupLabel">Mission Image Center</p>
          {imageCenter.map(NavItem)}
        </div>

        <div className="navGroup">
          <p className="navGroupLabel">Duty cycle · Phase 1 — Acquisition</p>
          {phase1.map(KItem)}
        </div>

        <div className="navGroup">
          <p className="navGroupLabel">Duty cycle · Phase 2 — Area Ops</p>
          {phase2.map(KItem)}
        </div>
      </nav>
    </aside>
  );
}

/* "Supreme" here means the session's token grants every coded section AND
   every download at once -- exactly what the master/developer code issues
   (core.access_control.access_unlock, section="*"). A token built up one
   section-download-code at a time never satisfies this, by design: the
   full, all-sections report is a reviewer/developer capability, not
   something a partially-unlocked normal viewer can reach a step at a time. */
function useIsSupremeAccess() {
  const { sections, downloads } = useAccess();
  return React.useMemo(
    () => sections.length > 0 && downloads.length > 0
      && sections.every((s) => s.unlocked) && downloads.every((d) => d.unlocked),
    [sections, downloads]
  );
}

/* Top-of-dashboard entry point for the consolidated multi-mission-report
   PDF (see generateFullMissionReportPdf / REPORT_CHAPTER_DEFS above): every
   dashboard section except the Mission Image Center (Catalog/Gallery/on-
   demand generation are explicitly excluded -- those are per-image
   artefacts, not dashboard pages, and are already downloadable individually
   from the Image Center itself). Restricted to Supreme Access, with a flat
   refusal rather than a code prompt -- see useIsSupremeAccess above for why
   a normal, section-by-section unlock can never satisfy this. */
function FullReportLauncher({ data, glossaryMap, quality, missions, missionId }) {
  const { authFetch } = useAccess();
  const isSupreme = useIsSupremeAccess();
  const [open, setOpen] = React.useState(false);
  const [picking, setPicking] = React.useState(false);
  const [picked, setPicked] = React.useState(() => new Set(REPORT_CHAPTER_DEFS.map((d) => d.id)));
  const [generating, setGenerating] = React.useState(false);

  const closeAll = () => { setOpen(false); setPicking(false); };

  const runReport = async (selectedIds) => {
    setGenerating(true);
    try {
      await generateFullMissionReportPdf({
        data, glossaryMap, quality, apiBase: API_BASE, authFetch,
        allMissionIds: (missions || []).map((m) => m.id),
        selectedIds,
      });
    } finally {
      setGenerating(false);
      closeAll();
    }
  };

  const grouped = React.useMemo(() => {
    const g = new Map();
    REPORT_CHAPTER_DEFS.forEach((d) => {
      if (!g.has(d.group)) g.set(d.group, []);
      g.get(d.group).push(d);
    });
    return [...g.entries()];
  }, []);

  const togglePicked = (id) => setPicked((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  return (
    <>
      <button className="iconButton" onClick={() => setOpen(true)} title="Download the full mission report (every dashboard section, this mission)">
        <Download size={18} />
      </button>
      {open ? (
        <div className="missionGateOverlay" onClick={closeAll}>
          <div
            className={`missionGatePanel reportGatePanel${picking ? " reportGatePanelWide" : ""}`}
            onClick={(e) => e.stopPropagation()}
          >
            {!isSupreme ? (
              <>
                <ShieldCheck size={28} color="#fb5c73" />
                <h3>Operation restricted</h3>
                <p className="reportRestrictedNote">
                  Downloading the full mission report needs Supreme Access — unlock every
                  section with the developer/reviewer code first. A normal, section-by-
                  section unlock does not grant this.
                </p>
                <div className="missionGateActions">
                  <button className="btn ghost" onClick={closeAll}>Close</button>
                </div>
              </>
            ) : !picking ? (
              <>
                <ShieldCheck size={26} />
                <h3>Download Full Report — {data?.mission?.name || "Mission"}</h3>
                <p className="reportRestrictedNote">
                  Every dashboard section for this mission — Mission Report and Duty
                  Cycle K1–K10 — as one PDF. The Mission Image Center (Catalog, Gallery,
                  on-demand image generation) is not included; those are downloaded
                  individually from there.
                </p>
                <div className="missionGateActions">
                  <button className="btn primary" disabled={generating} onClick={() => runReport(null)}>
                    <Download size={14} /> {generating ? "Generating…" : "Download all sections"}
                  </button>
                  <button className="btn ghost" disabled={generating} onClick={() => setPicking(true)}>
                    Select sections…
                  </button>
                </div>
              </>
            ) : (
              <>
                <h3>Select sections</h3>
                <div className="reportPickerToolbar">
                  <button className="btn ghost" onClick={() => setPicked(new Set(REPORT_CHAPTER_DEFS.map((d) => d.id)))}>Select all</button>
                  <button className="btn ghost" onClick={() => setPicked(new Set())}>Clear</button>
                </div>
                <div className="reportPickerList">
                  {grouped.map(([group, defs]) => (
                    <div key={group} className="reportPickerGroup">
                      <p className="reportPickerGroupLabel">{group}</p>
                      {defs.map((d) => (
                        <label key={d.id} className="reportPickerItem">
                          <input type="checkbox" checked={picked.has(d.id)} onChange={() => togglePicked(d.id)} />
                          {d.label}
                        </label>
                      ))}
                    </div>
                  ))}
                </div>
                <div className="missionGateActions">
                  <button className="btn ghost" disabled={generating} onClick={() => setPicking(false)}>Back</button>
                  <button className="btn primary" disabled={generating || picked.size === 0} onClick={() => runReport(picked)}>
                    <Download size={14} /> {generating ? "Generating…" : `Download ${picked.size} selected`}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      ) : null}
    </>
  );
}

function Header({ data, refresh, refreshing, missions, missionId, setMissionId, glossaryMap, quality }) {
  /* Switching to a mission other than the default one is gated the same way
     opening a section is: its own code. Picking a locked mission in the
     dropdown does not switch -- it reverts the select and opens a small
     inline prompt instead, so the mission never changes without the code
     actually being verified by the server. */
  const { isMissionUnlocked, unlockMission } = useAccess();
  const [pendingMission, setPendingMission] = React.useState(null);
  const [code, setCode] = React.useState("");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const pick = (id) => {
    if (id === missionId) return;
    if (isMissionUnlocked(id)) {
      setMissionId(id);
      return;
    }
    setPendingMission(id);
    setCode("");
    setError("");
  };

  const cancelPending = () => {
    setPendingMission(null);
    setCode("");
    setError("");
  };

  const submitMissionCode = async (e) => {
    e.preventDefault();
    if (!code.trim() || busy) return;
    setBusy(true);
    setError("");
    const res = await unlockMission(pendingMission, code.trim());
    setBusy(false);
    if (res.ok) {
      setMissionId(pendingMission);
      setPendingMission(null);
      setCode("");
    } else {
      setError(res.error || "Incorrect access code");
    }
  };

  return (
    <header className="topbar">
      <div>
        <p className="eyebrow">Configuration-driven orbital analytics</p>
        <h1>{data?.mission?.name || "Ansumi Orbital Hub"}</h1>
      </div>
      <div className="topbarActions">
        {missions && missions.length > 0 ? (
          <select
            className="missionSelect"
            value={missionId}
            onChange={(e) => pick(e.target.value)}
            title="Select mission — switching to a mission other than the current one requires its own access code"
          >
            {missions.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}{m.id !== missionId && !isMissionUnlocked(m.id) ? " — code required" : ""}
              </option>
            ))}
          </select>
        ) : null}
        <span className="livePill">
          <i />
          LIVE
        </span>
        <div className="epoch">
          <span>Latest epoch</span>
          <strong className="mono">{dateLabel(data?.mission?.latestEpoch)}</strong>
        </div>
        <button className="iconButton" onClick={refresh} disabled={refreshing} title="Refresh mission data">
          <RefreshCw size={18} className={refreshing ? "spin" : ""} />
        </button>
        <FullReportLauncher data={data} glossaryMap={glossaryMap} quality={quality} missions={missions} missionId={missionId} />
      </div>

      {pendingMission ? (
        <div className="missionGateOverlay" onClick={cancelPending}>
          <form className="missionGatePanel" onClick={(e) => e.stopPropagation()} onSubmit={submitMissionCode}>
            <div className="gateIcon">
              <Lock size={22} />
            </div>
            <p className="gateEyebrow">Restricted mission</p>
            <h3>{missions.find((m) => m.id === pendingMission)?.label || pendingMission}</h3>
            <p className="gateSub">
              Switching to this mission needs its own access code, separate from any section codes already
              unlocked. Nothing for this mission has been requested from the server yet.
            </p>
            <label className="gateField">
              <KeyRound size={15} />
              <input
                type="text"
                value={code}
                autoComplete="off"
                spellCheck="false"
                placeholder="Enter mission access code"
                onChange={(e) => setCode(e.target.value)}
                autoFocus
              />
            </label>
            <div className="missionGateActions">
              <button type="button" className="btn ghost" onClick={cancelPending}>Cancel</button>
              <button className="btn primary" type="submit" disabled={busy || !code.trim()}>
                <ShieldCheck size={15} /> {busy ? "Checking…" : "Switch mission"}
              </button>
            </div>
            {error ? <p className="gateError">{error}</p> : null}
          </form>
        </div>
      ) : null}
    </header>
  );
}

function Ticker({ data }) {
  /* Every field here belongs to a gated section, so any of them can be
     absent when that section is locked. Each entry is dropped rather than
     shown as a placeholder — the ticker only reports what the viewer is
     actually entitled to see. */
  const m = data?.metrics;
  const c = data?.constellation;
  const items = [
    c?.configuredSatellites != null && ["FLEET", `${number(c.configuredSatellites)} sats`],
    c?.altitudeKm != null && ["ALT", `${number(c.altitudeKm)} km`],
    c?.inclinationDeg != null && ["INC", `${number(c.inclinationDeg, 1)}°`],
    m?.rfEvents != null && ["RF", `${number(m.rfEvents)} contacts`],
    m?.opticalEvents != null && ["OPTICAL", `${number(m.opticalEvents)} contacts`],
    m?.eclipseEvents != null && ["ECLIPSE", `${number(m.eclipseEvents)} events`],
    m?.stateRows != null && ["STATE", `${compact(m.stateRows)} samples`],
    data?.coverage?.percent != null && ["COVERAGE", `${number(data.coverage.percent, 2)}%`],
    data?.coverage?.aoi != null && ["AOI", fmtAoiBox(data.coverage.aoi)],
  ].filter(Boolean);

  const row = items.map(([k, v]) => (
    <span key={k}>
      <i />
      {k} <b>{v}</b>
    </span>
  ));
  return (
    <div className="ticker">
      <span className="tickerLabel">
        <Activity size={13} /> TELEMETRY
      </span>
      <div className="tickerViewport">
        <div className="tickerTrack">
          {row}
          {row}
        </div>
      </div>
    </div>
  );
}

/* ---------------------------- primitives ------------------------------ */

function KpiCard({ icon: Icon, label, value, format, detail, accent = COLORS.blue, index = 0, infoKey = null, trend = null, trendLabels = null }) {
  const isNumeric = typeof value === "number" && Number.isFinite(value);
  /* A metric this mission's own source data genuinely doesn't have (e.g.
     asc074_3x1's Satellite_State_History.xlsx has no ECC/RMAG columns,
     unlike asc074_6x8's) arrives here as null, not a fabricated number --
     say so plainly rather than rendering blank or, worse, letting a caller
     coerce it to 0 and print a fake "measured" value. */
  const isMissing = value === null || value === undefined;

  // Detected from the formatter's own output rather than a prop every KPI
  // call site would need to set: every percent-valued KPI in this app
  // already formats as `(v) => \`${number(v, N)}%\`` (dozens of call
  // sites, no two the same closure), so probing what format(0) renders
  // catches all of them uniformly instead of relying on each one opting in.
  const isPercent = React.useMemo(() => {
    if (!format) return false;
    try {
      const sample = format(0);
      return typeof sample === "string" && sample.trim().endsWith("%");
    } catch {
      return false;
    }
  }, [format]);

  // The small ⓘ icon is the click target InfoPopover actually owns (its
  // open/close state lives inside that component, not here) -- clicking
  // anywhere else on the card just forwards a synthetic click to that same
  // button rather than duplicating its state, so there is exactly one
  // source of truth for whether the popover is open. The button's own
  // handler already stops propagation, so this never double-toggles.
  const infoBtnRef = React.useRef(null);
  const cardRef = React.useRef(null);
  const openInfo = infoKey ? () => infoBtnRef.current?.click() : undefined;

  return (
    <section
      ref={cardRef}
      className={`kpi reveal${infoKey ? " kpiHasInfo" : ""}`}
      style={{ "--accent": accent, "--i": index }}
      onClick={openInfo}
      role={infoKey ? "button" : undefined}
      tabIndex={infoKey ? 0 : undefined}
      onKeyDown={infoKey ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openInfo(); } } : undefined}
    >
      <div className="kpiTop">
        <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          {label}
          {infoKey ? <InfoPopover infoKey={infoKey} triggerRef={infoBtnRef} containerRef={cardRef} /> : null}
        </span>
        {isPercent && isNumeric ? (
          <RadialProgress percent={value}>
            <Icon size={14} />
          </RadialProgress>
        ) : (
          <span className="kpiIcon">
            <Icon size={17} />
          </span>
        )}
      </div>
      <strong>{isNumeric ? <Counter value={value} format={format} /> : isMissing ? "NA" : value}</strong>
      <p>{isMissing ? "Not in this mission's source data" : detail}</p>
      {trend ? (
        <Sparkline values={trend} labels={trendLabels} accent={`var(--accent, ${accent})`} />
      ) : null}
    </section>
  );
}

function Panel({ title, sub, action, children, className = "", index = 0 }) {
  return (
    <section className={`panel reveal ${className}`} style={{ "--i": index }}>
      <div className="panelHead">
        <div>
          <h2>{title}</h2>
          {sub ? <p>{sub}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function MissionStrip({ data }) {
  const cfg = data.constellation;
  const metrics = data.metrics;
  const items = [
    ["Mission type", data.mission.type],
    ["AOI", data.mission.aoi],
    // "6x8" etc. is the shorthand for planes x satellites-per-plane -- spelled
    // out here so the number pair is never ambiguous between missions.
    ["Constellation", `${cfg.planes} planes x ${cfg.satellitesPerPlane} sats/plane`],
    ["Nominal orbit altitude", `${number(cfg.altitudeKm, 0)} km`],
    ["Mean eccentricity", number(metrics.meanEccentricity, 6)],
  ];
  return (
    <div className="missionStrip reveal">
      {items.map(([label, value]) => (
        <div key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  );
}

/* K hero header — requirement narrative straight from the matrix */
function KHero({ def, requirement, index = 0 }) {
  const sub = SUBSYS[def.subsystem];
  const Icon = sub.icon;
  return (
    <section className="kHero reveal wide" style={{ "--sub": sub.color, "--i": index }}>
      <div className="kHeroBadge">
        <Icon size={28} strokeWidth={1.8} />
        <i className="kHeroNum">{def.k.replace("K", "")}</i>
      </div>
      <div className="kHeroBody">
        <div className="kHeroTags">
          <span className="subsysTag">
            <Icon size={13} /> {def.subsystem}
          </span>
          <span className="phaseTag">Phase {def.phase} · Step {def.k.replace("K", "")} of 10</span>
        </div>
        <h2>{def.name}</h2>
        <p>{requirement}</p>
      </div>
    </section>
  );
}

/* ------------------------------- maps --------------------------------- */

function WorldOrbitMap({ positions = [], tracks = [], maxTracks = 48, aoiBox, outline, secondary }) {
  const project = (lat, lon) => ({ x: projX(lon), y: projY(lat) });
  const grouped = React.useMemo(() => {
    const map = new Map();
    tracks.forEach((point) => {
      if (!Number.isFinite(Number(point.lat)) || !Number.isFinite(Number(point.lon))) return;
      if (!map.has(point.satellite)) map.set(point.satellite, []);
      map.get(point.satellite).push(point);
    });
    return [...map.entries()].slice(0, maxTracks);
  }, [tracks, maxTracks]);

  return (
    <div className="orbitMap">
      <svg viewBox={`0 0 ${MAP_W} ${MAP_H}`} role="img" aria-label="Satellite ground tracks">
        <defs>
          <radialGradient id="oceanGlow2" cx="50%" cy="42%" r="70%">
            <stop offset="0%" stopColor="rgba(34,90,150,.5)" />
            <stop offset="100%" stopColor="rgba(6,16,32,.9)" />
          </radialGradient>
        </defs>
        <MapBase aoiBox={aoiBox} outline={outline} secondary={secondary} />
        {grouped.map(([sat, points], gi) => {
          // Same antimeridian fix as the land outline and the animated
          // simulator's trail: a track crossing +-180 deg longitude jumps
          // from one edge of the map to the other in raw coordinates, and
          // drawing that as a normal line segment draws a spurious straight
          // line across the whole map instead of leaving the track split in
          // two. Starting a new subpath there keeps each real segment real.
          let prevLon = null;
          const path = points
            .map((point, idx) => {
              const pos = project(point.lat, point.lon);
              const lon = Number(point.lon);
              const wrapped = prevLon !== null && Math.abs(lon - prevLon) > 180;
              prevLon = lon;
              return `${idx === 0 || wrapped ? "M" : "L"}${pos.x.toFixed(1)} ${pos.y.toFixed(1)}`;
            })
            .join(" ");
          return <path key={sat} d={path} fill="none" stroke={hueFor(gi)} strokeWidth="1.1" strokeOpacity={grouped.length > 12 ? 0.6 : 0.9} />;
        })}
        {positions.map((point, pi) => {
          const pos = project(point.lat, point.lon);
          return (
            <g key={point.satellite} transform={`translate(${pos.x} ${pos.y})`}>
              <circle r="4.5" fill={hueFor(pi)} opacity="0.28" />
              <circle r="2.1" fill="#fff" stroke={hueFor(pi)} strokeWidth="1.1" />
              <title>{`${point.satellite} | ${number(point.altitude, 2)} km`}</title>
            </g>
          );
        })}
      </svg>
      <div className="mapLegend">
        <span><i className="dot blue" /> {positions.length} live fleet</span>
        <span><i className="legLine" /> ground tracks</span>
      </div>
    </div>
  );
}

/* Coverage map — real AOI land polygon, cells share the exact projection */
function AustraliaCoverageMap({ cells = [], outline = [], tasmania = [], aoi, percent }) {
  const aoiLabelText = aoi ? `AOI ${fmtAoiBox(aoi)}` : "AOI";
  const W = 780;
  const { project, H, aoiRect } = React.useMemo(() => {
    const pts = [...outline, ...tasmania];
    if (!pts.length) {
      return { project: () => ({ x: 0, y: 0 }), H: 460, aoiRect: null };
    }
    const lons = pts.map((p) => p.lon);
    const lats = pts.map((p) => p.lat);
    const pad = 2.5;
    const lonMin = Math.min(...lons) - pad;
    const lonMax = Math.max(...lons) + pad;
    const latMin = Math.min(...lats) - pad;
    const latMax = Math.max(...lats) + pad;
    const geoW = lonMax - lonMin;
    const geoH = latMax - latMin;
    const h = W * (geoH / geoW);
    const proj = (lat, lon) => ({
      x: ((Number(lon) - lonMin) / geoW) * W,
      y: ((latMax - Number(lat)) / geoH) * h,
    });
    let rect = null;
    if (aoi) {
      const a = proj(aoi.latMax, aoi.lonMin);
      const b = proj(aoi.latMin, aoi.lonMax);
      rect = { x: a.x, y: a.y, w: b.x - a.x, h: b.y - a.y };
    }
    return { project: proj, H: h, aoiRect: rect };
  }, [outline, tasmania, aoi]);

  const poly = (points) => points.map((p, i) => `${i === 0 ? "M" : "L"}${project(p.lat, p.lon).x.toFixed(1)} ${project(p.lat, p.lon).y.toFixed(1)}`).join(" ") + " Z";

  return (
    <div className="coverageMap">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="AOI coverage cells">
        <defs>
          <pattern id="covGrid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(120,150,220,.07)" strokeWidth="1" />
          </pattern>
        </defs>
        <rect width={W} height={H} fill="#060a14" />
        <rect width={W} height={H} fill="url(#covGrid)" />
        {aoiRect ? (
          <g>
            <rect x={aoiRect.x} y={aoiRect.y} width={aoiRect.w} height={aoiRect.h} className="aoiRect" />
            <text x={Math.max(aoiRect.x, 0) + 8} y={Math.max(aoiRect.y, 0) + 16} className="aoiLabel">
              {aoiLabelText}
            </text>
          </g>
        ) : null}
        {outline.length ? <path className="ausShape" d={poly(outline)} /> : null}
        {tasmania.length ? <path className="ausShape" d={poly(tasmania)} /> : null}
        {cells.map((cell, index) => {
          const pos = project(cell.lat, cell.lon);
          return (
            <circle
              key={`${cell.lat}-${cell.lon}-${index}`}
              cx={pos.x}
              cy={pos.y}
              r="3"
              className={cell.covered ? "cell covered" : "cell uncovered"}
            />
          );
        })}
      </svg>
      <div className="coverageBadge">
        <span>Modeled coverage</span>
        <strong className="mono">{number(percent, 2)}%</strong>
      </div>
      <div className="mapLegend">
        <span><i className="dot green" /> covered</span>
        <span><i className="dot red" /> uncovered</span>
      </div>
    </div>
  );
}

/* ------------------------------ charts -------------------------------- */

const axisTick = { fontSize: 10, fill: COLORS.axis };

function EventMatrix({ rows }) {
  return (
    <ResponsiveContainer height={330}>
      <BarChart data={rows.slice(0, 48)} margin={{ top: 10, right: 8, left: -24, bottom: 50 }}>
        <CartesianGrid vertical={false} stroke={COLORS.grid} />
        <XAxis dataKey="satellite" tick={axisTick} angle={-55} textAnchor="end" interval={1} height={68} stroke={COLORS.grid} />
        <YAxis tick={axisTick} stroke={COLORS.grid} />
        <Tooltip cursor={{ fill: "rgba(34,211,238,.08)" }} />
        <Bar dataKey="rf" name="RF" stackId="a" fill={COLORS.blue} radius={[0, 0, 3, 3]} />
        <Bar dataKey="optical" name="Optical" stackId="a" fill={COLORS.green} />
        <Bar dataKey="eclipse" name="Eclipse" stackId="a" fill={COLORS.amber} radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/* Bars with no amber (eclipse) segment are not missing data -- some
   satellites genuinely pass through zero eclipses in a given window,
   because their ascending node keeps them on the sunlit side of every orbit
   they complete during it. Named here by real, ascending-node-derived plane
   (core.image_center.derive_planes on the backend), not assumed from the
   satellite's number. */
function NoEclipseNote({ rows }) {
  const noEclipse = (rows || []).filter((r) => !r.eclipse);
  if (!noEclipse.length) return null;

  const byPlane = new Map();
  noEclipse.forEach((r) => {
    if (r.plane == null) return;
    if (!byPlane.has(r.plane)) byPlane.set(r.plane, []);
    byPlane.get(r.plane).push(r.satellite);
  });

  return (
    <p className="panelFootnote">
      <strong>{noEclipse.length} of {rows.length} satellites</strong> show no eclipse bar above ({noEclipse.map((r) => shortSat(r.satellite, "S")).join(", ")}).
      {byPlane.size ? (
        <> That is not missing data: {[...byPlane.entries()].sort((a, b) => a[0] - b[0]).map(([plane, sats], i, arr) => (
          <span key={plane}>{i > 0 ? (i === arr.length - 1 ? " and " : ", ") : ""}<strong>Plane {plane}</strong> ({sats.length} satellite{sats.length === 1 ? "" : "s"})</span>
        ))} {byPlane.size > 1 ? "have" : "has"} an ascending node positioned so its orbit stays on the sunlit side of Earth for this entire analysis window — every satellite in {byPlane.size > 1 ? "those planes" : "that plane"} shares the same result because they fly the same ground track offset by phase, not by chance.</>
      ) : (
        " Plane assignment could not be derived for this window (insufficient state samples)."
      )}
      {" "}A longer simulation window would eventually show eclipses for every plane as Earth's shadow geometry rotates relative to the orbit.
    </p>
  );
}

function EclipsePie({ data }) {
  return (
    <ResponsiveContainer height={250}>
      <PieChart>
        <Pie data={data} dataKey="events" nameKey="type" innerRadius={64} outerRadius={94} paddingAngle={3} stroke="none">
          {data.map((_, index) => (
            <Cell key={index} fill={PIE_COLORS[index % PIE_COLORS.length]} />
          ))}
        </Pie>
        <Tooltip />
      </PieChart>
    </ResponsiveContainer>
  );
}

function GroundStationBars({ rf = [], optical = [] }) {
  const merged = [
    ...rf.slice(0, 6).map((row) => ({ ...row, type: "RF" })),
    ...optical.slice(0, 6).map((row) => ({ ...row, type: "Optical" })),
  ];
  return (
    <ResponsiveContainer height={280}>
      <BarChart data={merged} layout="vertical" margin={{ top: 6, right: 12, left: 60, bottom: 6 }}>
        <CartesianGrid horizontal={false} stroke={COLORS.grid} />
        <XAxis type="number" tick={axisTick} stroke={COLORS.grid} />
        <YAxis dataKey="Ground Station" type="category" tick={{ ...axisTick, fontSize: 11 }} width={92} stroke={COLORS.grid} />
        <Tooltip formatter={(value) => asMinutes(value)} cursor={{ fill: "rgba(34,211,238,.06)" }} />
        <Bar dataKey="durationMinutes" radius={[0, 4, 4, 0]}>
          {merged.map((row, index) => (
            <Cell key={index} fill={row.type === "RF" ? COLORS.blue : COLORS.green} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function DutyTimeline({ rows }) {
  return (
    <ResponsiveContainer height={250}>
      <AreaChart data={rows} margin={{ top: 12, right: 10, left: -20, bottom: 6 }}>
        <defs>
          <linearGradient id="activeFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={COLORS.green} stopOpacity={0.5} />
            <stop offset="100%" stopColor={COLORS.green} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} stroke={COLORS.grid} />
        <XAxis dataKey="Timestamp" hide />
        <YAxis tick={axisTick} stroke={COLORS.grid} />
        <Tooltip labelFormatter={dateLabel} />
        <Area type="monotone" dataKey="observingSatellites" name="Observing" stroke={COLORS.green} fill="url(#activeFill)" strokeWidth={2} />
        <Line type="monotone" dataKey="eclipseSatellites" name="In eclipse" stroke={COLORS.amber} strokeWidth={2} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function SimpleBar({ rows, x, y, color = COLORS.cyan, height = 300, format }) {
  return (
    <ResponsiveContainer height={height}>
      <BarChart data={rows} margin={{ top: 8, right: 10, left: -18, bottom: 56 }}>
        <defs>
          <linearGradient id={`g-${x}-${y}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} />
            <stop offset="100%" stopColor={color} stopOpacity={0.45} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} stroke={COLORS.grid} />
        <XAxis dataKey={x} tick={axisTick} angle={-55} textAnchor="end" height={66} stroke={COLORS.grid} />
        <YAxis tick={axisTick} stroke={COLORS.grid} />
        <Tooltip cursor={{ fill: "rgba(34,211,238,.06)" }} formatter={format} />
        <Bar dataKey={y} fill={`url(#g-${x}-${y})`} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function AltitudeChart({ rows }) {
  return (
    <ResponsiveContainer height={360}>
      <BarChart data={rows} margin={{ top: 10, right: 10, left: -12, bottom: 60 }}>
        <CartesianGrid vertical={false} stroke={COLORS.grid} />
        <XAxis dataKey="satellite" angle={-55} textAnchor="end" height={72} tick={axisTick} stroke={COLORS.grid} />
        <YAxis tick={axisTick} domain={["dataMin - 1", "dataMax + 1"]} stroke={COLORS.grid} />
        <Tooltip cursor={{ fill: "rgba(34,211,238,.06)" }} />
        <Bar dataKey="minAltitude" name="Min" fill="#475b82" radius={[4, 4, 0, 0]} />
        <Bar dataKey="meanAltitude" name="Mean" fill={COLORS.blue} radius={[4, 4, 0, 0]} />
        <Bar dataKey="maxAltitude" name="Max" fill={COLORS.cyan} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/* multi-satellite time-series line chart (State Explorer) */
function MultiLine({ selected = [], series = {}, field, height = 340, unit = "" }) {
  const rows = React.useMemo(() => {
    const maxLen = Math.max(0, ...selected.map((s) => series[s]?.length || 0));
    const ref = selected[0] ? series[selected[0]] : [];
    const out = [];
    for (let i = 0; i < maxLen; i++) {
      const row = { i, t: ref[i]?.t };
      selected.forEach((s) => {
        const p = series[s]?.[i];
        if (p) row[s] = p[field];
      });
      out.push(row);
    }
    return out;
  }, [selected, series, field]);

  const showLegend = selected.length <= 8;

  return (
    <ResponsiveContainer height={height}>
      <LineChart data={rows} margin={{ top: 12, right: 14, left: -8, bottom: 6 }}>
        <CartesianGrid vertical={false} stroke={COLORS.grid} />
        <XAxis dataKey="t" tickFormatter={timeLabel} tick={axisTick} stroke={COLORS.grid} minTickGap={40} />
        <YAxis tick={axisTick} stroke={COLORS.grid} unit={unit} width={54} domain={["auto", "auto"]} />
        <Tooltip labelFormatter={dateLabel} contentStyle={{ maxHeight: 220, overflow: "auto" }} />
        {showLegend ? <Legend wrapperStyle={{ fontSize: 11 }} /> : null}
        {selected.map((s, idx) => (
          <Line key={s} type="monotone" dataKey={s} stroke={hueFor(idx)} strokeWidth={1.6} dot={false} isAnimationActive={!reduceMotion && selected.length <= 12} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

/* ------------------------------- table -------------------------------- */

function DataTable({ rows = [], columns }) {
  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key}>
                {col.infoKey ? (
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                    {col.label}
                    <InfoPopover infoKey={col.infoKey} />
                  </span>
                ) : (
                  col.label
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {columns.map((col) => (
                <td key={col.key}>{col.render ? col.render(row[col.key], row) : row[col.key] ?? "NA"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* --------------------------- methodology note -------------------------- */

function MethodNote({ items = [], title = "How these numbers are calculated" }) {
  if (!items.length) return null;
  return (
    <details className="methodNote reveal wide">
      <summary>
        <Info size={13} /> {title}
      </summary>
      <div className="methodList">
        {items.map((it) => (
          <div className="methodRow" key={it.metric}>
            <strong>{it.metric}</strong>
            <span>{it.meaning}</span>
            {it.formula ? <code>{it.formula}</code> : null}
          </div>
        ))}
      </div>
    </details>
  );
}

/* ------------------------- generic PDF export --------------------------- */

function exportRowsPdf({ mission, title, subtitle, columns, rows, fileName }) {
  if (!rows || !rows.length) return;
  const doc = new jsPDF({ orientation: "landscape", unit: "pt", format: "a4" });
  const now = new Date();

  doc.setFillColor(6, 10, 20);
  doc.rect(0, 0, doc.internal.pageSize.getWidth(), 70, "F");
  doc.setTextColor(34, 211, 238);
  doc.setFontSize(18);
  doc.text(`${mission?.name || "Mission"} — ${title}`, 40, 34);
  doc.setTextColor(180, 190, 210);
  doc.setFontSize(9);
  doc.text(`${subtitle || ""}   ·   ${rows.length} rows   ·   generated ${now.toLocaleString()}`, 40, 52);

  autoTable(doc, {
    startY: 84,
    head: [columns.map((c) => c.label)],
    body: rows.map((row) => columns.map((c) => (c.render ? c.render(row[c.key], row) : row[c.key] ?? "NA"))),
    styles: { fontSize: 7.5, cellPadding: 3 },
    headStyles: { fillColor: [34, 130, 238], textColor: 255, fontSize: 8 },
    alternateRowStyles: { fillColor: [240, 244, 251] },
    margin: { left: 40, right: 40 },
  });

  doc.save(`${(mission?.name || "mission").replace(/\s+/g, "_")}_${fileName}.pdf`);
}

function PdfButton({ mission, title, subtitle, columns, rows, fileName, label = "Export PDF", section }) {
  const { requestDownload } = useAccess();
  const run = () => exportRowsPdf({ mission, title, subtitle, columns, rows, fileName });
  return (
    <button className="btn primary" onClick={() => (section ? requestDownload(section, run) : run())}>
      <Download size={15} /> {label}
    </button>
  );
}

/* ------------------------ consolidated mission report ------------------------ */

/* Static chapter metadata (id, label, group), independent of any fetched
   mission data -- the section-picker UI renders this list directly, so it
   does not need a live data object just to show checkboxes. Every id here
   must have a matching entry in the `chapters` array generateFullMissionReportPdf
   builds, or a selection including it silently produces nothing for that id. */
const REPORT_CHAPTER_DEFS = [
  { id: "exec-summary", label: "1. Executive Summary", group: "Mission Report" },
  { id: "mission-config", label: "2. Mission Configuration", group: "Mission Report" },
  { id: "coverage", label: "3. Coverage Analysis", group: "Mission Report" },
  { id: "gap-analysis", label: "4. Coverage Gap Analysis", group: "Mission Report" },
  { id: "revisit", label: "5. Revisit Analysis", group: "Mission Report" },
  { id: "rf-contact", label: "6. RF Contact Analysis", group: "Mission Report" },
  { id: "ground-stations", label: "7. Ground Station Analysis", group: "Mission Report" },
  { id: "eclipse", label: "8. Eclipse Analysis", group: "Mission Report" },
  { id: "observation", label: "9. Observation Analysis", group: "Mission Report" },
  { id: "sat-contribution", label: "10. Satellite Contribution", group: "Mission Report" },
  { id: "comparison", label: "11. Mission Comparison", group: "Mission Report" },
  { id: "sim-details", label: "12. Simulation Details", group: "Mission Report" },
  { id: "glossary-def", label: "13. Parameter Definitions & Methodology", group: "Mission Report" },
  { id: "glossary-source", label: "14. Data Sources", group: "Mission Report" },
  { id: "data-quality", label: "15. Data Quality & Validation", group: "Mission Report" },
  { id: "engineering-obs", label: "16. Engineering Observations", group: "Mission Report" },
  { id: "conclusions", label: "17. Conclusions", group: "Mission Report" },
  ...K_DEFS.map((d, i) => ({
    id: d.id,
    label: `${18 + i}. Duty Cycle — ${d.k} ${d.name}`,
    group: "Duty Cycle (K1–K10)",
  })),
];

async function generateFullMissionReportPdf({ data, glossaryMap, quality, apiBase, allMissionIds, authFetch, selectedIds = null }) {
  const doc = new jsPDF({ orientation: "portrait", unit: "pt", format: "a4" });
  const pageW = doc.internal.pageSize.getWidth();
  const mission = data.mission || {};
  const aoiLabel = mission.aoiRegionLabel || "Australia";
  const c = data.constellation || {};
  const m = data.metrics || {};
  const a = data.analytics || {};
  const summary = a.summary || {};
  const gap = a.gapAnalysis || {};
  const revisit = a.revisit || {};
  const sim = a.simulationDetails || {};
  const duty = data.duty || {};
  const verified = new Set(sim.verifiedFields || []);
  const glossaryTerms = Object.values(glossaryMap || {});

  let compareRows = [];
  let observations = [];
  try {
    const ids = (allMissionIds || []).join(",");
    const r = await authFetch(`${apiBase}/api/compare?missions=${encodeURIComponent(ids)}`);
    if (r.ok) {
      const j = await r.json();
      compareRows = j.missions || [];
      observations = j.observations || [];
    }
  } catch (err) { /* comparison section is best-effort */ }

  let y = 90;

  function header(title, subtitle) {
    doc.addPage();
    doc.setFillColor(6, 10, 20);
    doc.rect(0, 0, pageW, 70, "F");
    doc.setTextColor(34, 211, 238);
    doc.setFontSize(15);
    doc.text(title, 40, 32);
    doc.setTextColor(180, 190, 210);
    doc.setFontSize(9);
    doc.text(subtitle || "", 40, 50);
    y = 90;
  }

  function kvTable(rows) {
    autoTable(doc, {
      startY: y,
      head: [["Parameter", "Value"]],
      body: rows.map(([k, v]) => [String(k), v === null || v === undefined || v === "" ? "Not Available" : String(v)]),
      styles: { fontSize: 8, cellPadding: 4 },
      headStyles: { fillColor: [34, 130, 238] },
      alternateRowStyles: { fillColor: [240, 244, 251] },
      margin: { left: 40, right: 40 },
    });
    y = doc.lastAutoTable.finalY + 24;
  }

  function tableRows(columns, rows, limit = 40) {
    autoTable(doc, {
      startY: y,
      head: [columns.map((col) => col.label)],
      body: (rows || []).slice(0, limit).map((row) => columns.map((col) => (row[col.key] ?? "NA"))),
      styles: { fontSize: 7, cellPadding: 3 },
      headStyles: { fillColor: [34, 130, 238] },
      alternateRowStyles: { fillColor: [240, 244, 251] },
      margin: { left: 40, right: 40 },
    });
    y = doc.lastAutoTable.finalY + 24;
  }

  // Each chapter is self-contained (header() always starts a fresh page), so
  // "download selected sections" is just running a subset of this list --
  // nothing here depends on a chapter that ran before it, except the shared
  // `y` cursor header() itself resets on every call.
  const chapters = {
    "exec-summary": () => {
      header("1. Executive Summary", `${mission.name} — key mission metrics, from this mission's own processed mission data`);
      kvTable([
        ["Mission", mission.name], ["Configuration", `${c.planes} × ${c.satellitesPerPlane}`],
        ["Total Satellites", c.configuredSatellites], ["Altitude (km)", c.altitudeKm], ["Inclination (deg)", c.inclinationDeg],
        ["Area of Interest", mission.aoi], [`${aoiLabel} Coverage (%)`, number(data.coverage?.percent, 2)],
        ["Mean Revisit (min)", number(summary.meanRevisitMin, 1)], ["Largest Coverage Gap (min)", number(gap.largestGapMin, 1)],
        ["RF Contact Events", m.rfEvents], ["Optical Contact Events", m.opticalEvents], ["Eclipse Events", m.eclipseEvents],
      ]);
    },
    "mission-config": () => {
      header("2. Mission Configuration", "Source: this mission's own Mission_Configuration.xlsx");
      kvTable([
        ...(data.configuration?.mission || []).map((r) => [r.Parameter, r.Value]),
        ...(data.configuration?.constellation || []).map((r) => [r.Parameter, r.Value]),
        ...(data.configuration?.orbit || []).map((r) => [r.Parameter, r.Value]),
      ]);
    },
    "coverage": () => {
      header("3. Coverage Analysis", "Source: State Report (ground track) + camera swath model");
      kvTable([
        [`${aoiLabel} Coverage (%)`, number(data.coverage?.percent, 2)],
        ["Covered Cells", data.coverage?.coveredCells], ["Total Cells", data.coverage?.totalCells],
      ]);
    },
    "gap-analysis": () => {
      header("4. Coverage Gap Analysis", "Derived from the same real per-cell pass data as Revisit Analysis");
      kvTable([
        ["Largest Gap (min)", number(gap.largestGapMin, 1)], ["Mean Gap (min)", number(gap.meanGapMin, 1)],
        ["Median Gap (min)", number(gap.medianGapMin, 1)], ["Max Gap (min)", number(gap.maxGapMin, 1)],
        ["95th Percentile Gap (min)", number(gap.p95GapMin, 1)],
        ["% Grid Cells Satisfying Requirement", number(gap.pctSatisfyingRequirement, 1)],
        ["Data-bearing Grid Cells", `${gap.dataBearingCells ?? 0} of ${gap.totalCells ?? 0}`],
      ]);
    },
    "revisit": () => {
      header("5. Revisit Analysis", "Source: State Report, densified ground track");
      kvTable([
        ["Mean Revisit (min)", number(revisit.mean_revisit, 1)], ["Minimum Revisit (min)", number(revisit.min_revisit, 1)],
        ["Maximum Revisit (min)", number(revisit.max_revisit, 1)], ["Median Revisit (min)", number(revisit.median_revisit, 1)],
        ["95th Percentile Revisit (min)", number(revisit.p95_revisit, 1)],
      ]);
    },
    "rf-contact": () => {
      header("6. RF Contact Analysis", "Source: ground-contact log (RF)");
      tableRows(
        [{ key: "Satellite Name", label: "Satellite" }, { key: "Ground Station", label: "Ground Station" }, { key: "Start UTC", label: "Start UTC" }, { key: "Duration (s)", label: "Duration (s)" }],
        data.tables?.rf
      );
    },
    "ground-stations": () => {
      header("7. Ground Station Analysis", "The mission's real ground segments — RF (5° mask) and Optical (20° mask)");
      tableRows(
        [{ key: "stationName", label: "Station" }, { key: "linkType", label: "Link" }, { key: "minElevationDeg", label: "Min Elev (deg)" }, { key: "passCount", label: "Passes" }, { key: "totalDurationSec", label: "Total (s)" }, { key: "longestGapMin", label: "Longest Gap (min)" }],
        a.groundStations
      );
    },
    "eclipse": () => {
      header("8. Eclipse Analysis", "Source: eclipse log");
      tableRows(
        [{ key: "Satellite Name", label: "Satellite" }, { key: "Eclipse Type", label: "Type" }, { key: "Start UTC", label: "Start UTC" }, { key: "Duration (s)", label: "Duration (s)" }],
        data.tables?.eclipse
      );
    },
    "observation": () => {
      header("9. Observation Analysis", "Source: State Report + camera swath model");
      kvTable([
        ["Summed Satellite Observation Time", data.coverage?.observation?.overall?.["Summed Satellite Observation Time"]],
        ["Maximum Simultaneous Observing Satellites", data.coverage?.observation?.overall?.["Maximum Simultaneous Observing Satellites"]],
        ["Overall Observation Duty Cycle (%)", number(data.coverage?.observation?.overall?.["Overall Observation Duty Cycle (%)"], 2)],
      ]);
    },
    "sat-contribution": () => {
      header("10. Satellite Contribution", "Per-satellite coverage / contact / duty-cycle breakdown");
      tableRows(
        [{ key: "satellite", label: "Satellite" }, { key: "coverageContributionPct", label: "Coverage %" }, { key: "rfContacts", label: "RF" }, { key: "opticalContacts", label: "Optical" }, { key: "meanDutyCyclePct", label: "Duty %" }],
        a.satelliteContributions
      );
    },
    "comparison": () => {
      header("11. Mission Comparison", "Live metrics computed independently from each mission's own data — see the Mission column for each configuration");
      tableRows(
        [{ key: "label", label: "Mission" }, { key: "coveragePercent", label: "Coverage %" }, { key: "meanRevisitMin", label: "Mean Revisit" }, { key: "largestGapMin", label: "Largest Gap" }, { key: "rfEvents", label: "RF Events" }, { key: "eclipseEvents", label: "Eclipse Events" }],
        compareRows
      );
    },
    "sim-details": () => {
      header("12. Simulation Details", "Verified = derived from this mission's own data. Assumed = standard reference value, not parsed from this mission's mission script.");
      kvTable(Object.entries(sim).filter(([k]) => k !== "verifiedFields").map(([k, v]) => [`${k}${verified.has(k) ? " (Verified)" : " (Assumed)"}`, v]));
    },
    "glossary-def": () => {
      header("13. Parameter Definitions & Methodology", "Full parameter glossary — definition, unit, source, calculation");
      tableRows(
        [{ key: "name", label: "Parameter" }, { key: "definition", label: "Definition" }, { key: "calculation", label: "Calculation" }],
        glossaryTerms, 60
      );
    },
    "glossary-source": () => {
      header("14. Data Sources", "Where each parameter's value originates");
      tableRows(
        [{ key: "name", label: "Parameter" }, { key: "source", label: "Source" }],
        glossaryTerms, 60
      );
    },
    "data-quality": () => {
      header("15. Data Quality & Validation", "Per-dataset parsing diagnostics for this mission");
      tableRows(
        [{ key: "dataset", label: "Dataset" }, { key: "status", label: "Status" }, { key: "detail", label: "Detail" }],
        quality?.checks
      );
    },
    "engineering-obs": () => {
      header("16. Engineering Observations", "Factual deltas between missions — not a recommendation of which to choose");
      autoTable(doc, {
        startY: y,
        body: (observations || []).map((o) => [o]),
        styles: { fontSize: 8, cellPadding: 6 },
        margin: { left: 40, right: 40 },
      });
      y = doc.lastAutoTable.finalY + 24;
    },
    "conclusions": () => {
      header("17. Conclusions", "Summary of findings for this mission");
      const conclusionLines = [
        `This report covers the ${mission.name} mission in its ${c.planes} × ${c.satellitesPerPlane} (${c.configuredSatellites}-satellite) configuration.`,
        `${aoiLabel} coverage over the analysis window was ${number(data.coverage?.percent, 2)}%, with a mean revisit time of ${number(summary.meanRevisitMin, 1)} minutes.`,
        `The largest single coverage gap observed in the analysis grid was ${number(gap.largestGapMin, 1)} minutes${gap.dataBearingCells ? ` (based on ${gap.dataBearingCells} of ${gap.totalCells} grid cells with sufficient real data)` : ""}.`,
        `The RF ground segment recorded ${m.rfEvents} contacts (${number(m.rfMinutes, 1)} minutes total); the optical segment recorded ${m.opticalEvents} contacts (${number(m.opticalMinutes, 1)} minutes total).`,
        observations[0] || "",
      ].filter(Boolean);
      doc.setFontSize(10);
      doc.setTextColor(230, 230, 230);
      let cy = y;
      conclusionLines.forEach((line) => {
        const split = doc.splitTextToSize(line, pageW - 80);
        doc.text(split, 40, cy);
        cy += split.length * 14 + 10;
      });
    },
  };

  // Duty Cycle K1-K10: each phase's own live view draws its metrics from a
  // mix of data.duty, data.metrics, data.constellation and data.charts (see
  // the Kx view components above) -- this mirrors that same real, per-
  // mission data rather than any fixed narrative, so it stays correct for
  // every mission (satellite count, AOI label, ground-station set) instead
  // of a copied description that would misname the mission for anyone but
  // the one it was first written for.
  K_DEFS.forEach((def, i) => {
    chapters[def.id] = () => {
      header(
        `${18 + i}. Duty Cycle — ${def.k} ${def.name}`,
        `Phase ${def.phase} of 2 · ${def.subsystem} subsystem · ${c.configuredSatellites ?? "?"}-satellite ${mission.name || "mission"} over ${mission.aoi || aoiLabel}`
      );
      kvTable([
        ["Subsystem", def.subsystem], ["Phase", `${def.phase} of 2`],
        ["Configured satellites", c.configuredSatellites],
        ["Fleet duty cycle (%)", number(duty.metrics?.fleetDutyPercent, 2)],
        ["Fleet active hours", number(duty.metrics?.fleetActiveHours, 2)],
        [`${aoiLabel} coverage (%)`, number(data.coverage?.percent, 2)],
        ["RF contacts / minutes", `${m.rfEvents ?? "NA"} / ${number(m.rfMinutes, 1)}`],
        ["Optical contacts / minutes", `${m.opticalEvents ?? "NA"} / ${number(m.opticalMinutes, 1)}`],
        ["Eclipse events / hours", `${m.eclipseEvents ?? "NA"} / ${number(m.eclipseHours, 1)}`],
      ]);
      if (def.subsystem === "GSN" && (data.charts?.groundStationsRf?.length || data.charts?.groundStationsOptical?.length)) {
        tableRows(
          [{ key: "Ground Station", label: "Ground Station" }, { key: "Satellite Name", label: "Satellite" }, { key: "Duration (s)", label: "Duration (s)" }],
          [...(data.charts?.groundStationsRf || []), ...(data.charts?.groundStationsOptical || [])]
        );
      } else if (duty.summary?.length) {
        tableRows(
          [{ key: "satellite", label: "Satellite" }, { key: "dutyPercent", label: "Duty %" }, { key: "activeMinutes", label: "Active (min)" }, { key: "samples", label: "Samples" }],
          duty.summary
        );
      }
    };
  });

  const idsToRun = selectedIds && selectedIds.size ? [...selectedIds].filter((id) => chapters[id]) : Object.keys(chapters);

  // Cover page
  doc.setFillColor(6, 10, 20);
  doc.rect(0, 0, pageW, doc.internal.pageSize.getHeight(), "F");
  doc.setTextColor(34, 211, 238);
  doc.setFontSize(24);
  doc.text("Satellite Mission Analysis Report", 40, 130);
  doc.setFontSize(16);
  doc.setTextColor(255, 255, 255);
  doc.text(mission.name || "Mission", 40, 165);
  doc.setFontSize(10);
  doc.setTextColor(180, 190, 210);
  doc.text(`Configuration: ${c.planes} × ${c.satellitesPerPlane}  ·  ${c.configuredSatellites} satellites  ·  ${c.altitudeKm} km, ${number(c.inclinationDeg, 1)}°`, 40, 190);
  doc.text(`Area of Interest: ${mission.aoi || "Not configured"}`, 40, 206);
  doc.text(`Generated ${new Date().toLocaleString()}`, 40, 222);
  if (selectedIds && selectedIds.size) {
    doc.text(`Selected sections: ${idsToRun.length} of ${Object.keys(chapters).length}`, 40, 238);
  }

  // REPORT_CHAPTER_DEFS fixes the canonical order; idsToRun (a plain array
  // for "all", a Set-derived array for "selected") may not match it, so the
  // PDF's page order always follows the canonical list rather than
  // whatever order the caller's selection happened to be in.
  REPORT_CHAPTER_DEFS
    .map((d) => d.id)
    .filter((id) => idsToRun.includes(id))
    .forEach((id) => chapters[id]());

  doc.save(`${(mission.name || "mission").replace(/\s+/g, "_")}_Full_Mission_Report.pdf`);
}

function FullReportPanel({ data, glossaryMap, quality, apiBase, missions, missionId }) {
  const { authFetch, requestDownload } = useAccess();
  const [generating, setGenerating] = React.useState(false);
  return (
    <Panel
      index={0}
      title="Full Mission Analysis Report"
      sub="A single consolidated report — executive summary through conclusions — built entirely from this mission's own processed data. Selecting a different mission changes what gets exported."
      className="wide"
    >
      <div className="reportBtnRow">
        <button
          className="btn primary"
          disabled={generating}
          onClick={() => requestDownload("data", async () => {
            setGenerating(true);
            try {
              await generateFullMissionReportPdf({
                data, glossaryMap, quality, apiBase, authFetch,
                allMissionIds: missions.map((m) => m.id),
              });
            } finally {
              setGenerating(false);
            }
          })}
        >
          <Download size={15} /> {generating ? "Generating…" : "Full Report — PDF"}
        </button>
        {/* A plain anchor cannot carry the auth header, so the signed token
            rides along as a query parameter the server also accepts -- and
            since a locked-download token would 403 at the server anyway,
            the code prompt is required here before the tab even opens. */}
        <button
          className="btn ghost"
          onClick={() => requestDownload("data", (freshToken) => {
            window.open(buildAccessUrl(`${apiBase}/api/report/excel?mission=${missionId}`, freshToken), "_blank");
          })}
        >
          <Download size={15} /> Full Report — Excel
        </button>
      </div>
    </Panel>
  );
}

/* --------------------------- satellite selector -------------------------- */

function SatSelector({ satellites = [], selected = [], onToggle, onSelectAll }) {
  const allSelected = selected.length === satellites.length && satellites.length > 0;
  return (
    <div className="satSelectorBar">
      <button className="btn ghost" onClick={onSelectAll}>
        {allSelected ? <Square size={15} /> : <CheckSquare size={15} />}
        {allSelected ? "Clear all" : `Select all (${satellites.length})`}
      </button>
      <div className="satChips">
        {satellites.map((sat, idx) => (
          <button
            key={sat}
            className={selected.includes(sat) ? "chip on" : "chip"}
            onClick={() => onToggle(sat)}
            style={{ "--c": hueFor(selected.indexOf(sat) >= 0 ? selected.indexOf(sat) : idx) }}
          >
            <i />
            {shortSat(sat)}
          </button>
        ))}
      </div>
    </div>
  );
}

function useSatSelection(satellites, initialCount = null) {
  const [selected, setSelected] = React.useState([]);
  // Keyed on the actual roster, not just its length: switching mission
  // in-session (the header dropdown, no page reload) can swap in a
  // same-size roster with different satellite names (e.g. "ASC_074A" ->
  // "01"), which used to leave `selected` holding names absent from the
  // new roster -- every map/chart reading `selected` then silently
  // rendered empty instead of picking a fresh default.
  const rosterKey = satellites.join("|");
  React.useEffect(() => {
    if (satellites.length) {
      setSelected(initialCount ? satellites.slice(0, initialCount) : [...satellites]);
    } else {
      setSelected([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rosterKey]);
  const toggle = (sat) => setSelected((cur) => (cur.includes(sat) ? cur.filter((s) => s !== sat) : [...cur, sat]));
  const selectAll = () => setSelected((cur) => (cur.length === satellites.length ? [] : [...satellites]));
  return [selected, toggle, selectAll];
}

/* -------------------------------- views ------------------------------- */

const OVERVIEW_METHODS = [
  { metric: "Configured fleet", meaning: "Satellites defined in Mission_Configuration.xlsx, compared against satellites actually seen in the processed telemetry files.", formula: "configured = planes × satellites/plane; detected = distinct satellites across RF/Optical/Eclipse/State files" },
  { metric: "RF / Optical contacts", meaning: "One row per continuous line-of-sight contact between a satellite and a ground station, across the full 48-satellite fleet.", formula: "events = row count in RF_Contacts.xlsx / Optical_Contacts.xlsx; minutes = Σ Duration(s) ÷ 60" },
  { metric: "Eclipse events", meaning: "One row per Sun-blocked interval (umbra or penumbra) for any satellite.", formula: "hours = Σ Duration(s) ÷ 3600, from All_Eclipse_Events.xlsx" },
  { metric: "Data coverage", meaning: "How much of the 48-satellite fleet has usable telemetry in the processed state file.", formula: "detected satellites ÷ configured satellites × 100" },
];

function Overview({ data, state }) {
  const m = data.metrics;
  const c = data.constellation;
  // Real per-satellite breakdown, already fetched for the Events by
  // Satellite panel below -- reused here for each KPI's sparkline rather
  // than invented, so the bars are the same fleet split shown in that
  // panel's own table, just visualised at a glance.
  const em = data.charts.eventMatrix || [];
  const emLabels = em.map((r) => r.satellite);
  return (
    <div className="contentGrid">
      <MissionStrip data={data} />
      <div className="kpiGrid">
        <KpiCard index={0} icon={Satellite} label="Configured fleet" value={c.configuredSatellites} detail={`${number(c.detectedSatellites)} of ${number(c.configuredSatellites)} satellites detected in data`} accent={COLORS.blue} />
        <KpiCard index={1} icon={Antenna} label="RF contacts" value={m.rfEvents} detail={`${asMinutes(m.rfMinutes)} across the fleet`} accent={COLORS.cyan} trend={em.map((r) => r.rf)} trendLabels={emLabels} />
        <KpiCard index={2} icon={Zap} label="Optical contacts" value={m.opticalEvents} detail={`${asMinutes(m.opticalMinutes)} across the fleet`} accent={COLORS.green} trend={em.map((r) => r.optical)} trendLabels={emLabels} />
        <KpiCard index={3} icon={SunMedium} label="Eclipse events" value={m.eclipseEvents} detail={`${asHours(m.eclipseHours)} across the fleet`} accent={COLORS.amber} trend={em.map((r) => r.eclipse)} trendLabels={emLabels} />
        <KpiCard index={4} icon={Gauge} label="Data coverage" value={m.fleetCoveragePercent} format={asPct} detail={`${compact(m.stateRows)} state samples, ${c.configuredSatellites} satellites`} accent={COLORS.red} />
      </div>
      <Panel index={5} title="Constellation Simulator" sub="Animated ground tracks over the analysis window · play, scrub and set the trail length" className="wide">
        {state ? (
          <ConstellationSim series={state.series} satellites={state.satellites} range={state.range} aoiBox={state.aoi || data.coverage.aoi} outline={data.coverage.outline} secondary={data.coverage.tasmania} aoiLabel={data.mission.aoiRegionLabel} />
        ) : (
          <WorldOrbitMap positions={data.charts.latestPositions} tracks={data.charts.tracks} aoiBox={data.coverage.aoi} outline={data.coverage.outline} secondary={data.coverage.tasmania} />
        )}
      </Panel>
      <Panel index={6} title="Events by Satellite" sub="RF, optical and eclipse events, per satellite">
        <EventMatrix rows={data.charts.eventMatrix} />
        <NoEclipseNote rows={data.charts.eventMatrix} />
      </Panel>
      <Panel index={7} title="Eclipse Mix" sub="Event type distribution, fleet-wide">
        <EclipsePie data={data.charts.eclipseTypes} />
        <div className="legendStack">
          {data.charts.eclipseTypes.map((item, index) => (
            <span key={item.type}>
              <i style={{ background: PIE_COLORS[index % PIE_COLORS.length], color: PIE_COLORS[index % PIE_COLORS.length] }} />
              {item.type}: {number(item.events)}
            </span>
          ))}
        </div>
      </Panel>
      <SpacecraftVisualization data={data} />
      <MethodNote items={swap48Methods(OVERVIEW_METHODS, c.configuredSatellites)} />
    </div>
  );
}

const COVERAGE_METHODS = [
  { metric: "AOI coverage %", meaning: "The mission's AOI land area is discretized into a 1° lat/lon grid over its mainland (+ Tasmania for the Australia AOI) land boundary. A cell counts as covered if any of the 48 satellites' sub-points came within half the modeled ground swath of the cell center.", formula: "% = latitude-weighted covered cells ÷ total land cells × 100" },
  { metric: "All-sat observed", meaning: "Sum of each of the 48 satellites' own 'observing AOI' time. Overlapping satellites are each counted, so this can exceed the mission duration.", formula: "Σ (per-satellite Total Observation Seconds)" },
  { metric: "Max simultaneous", meaning: "The highest number of satellites (out of 48) flagged as observing the AOI at the same shared timestamp.", formula: "max(count of satellites observing at time t)" },
  { metric: "Observation Windows (table column)", meaning: "A 'window' is one continuous pass: it opens the moment a satellite's sensor footprint first touches the AOI, and closes the moment it leaves (a gap longer than 1.5x that satellite's normal reporting interval). A satellite that crosses the AOI three separate times in the analysis window has 3 windows, each with its own start, end and duration -- they are never merged.", formula: "count of continuous in-AOI intervals per satellite, from core.observation_duration.observation_duration_analysis()" },
  { metric: "Avg window (table column)", meaning: "The mean length of that satellite's own passes -- add up every window's duration and divide by how many windows it had. A satellite with a short average window sees the AOI only glancingly each time (e.g. a corner of its swath clips the coast); a long average window means a fuller crossing.", formula: "mean(per-window Observation Duration) for that satellite" },
  { metric: "Duty % (KPI and table column) -- what 'duty' means here", meaning: "The literal question this answers is: 'of all the time in the analysis window, what fraction did this satellite (or, for the KPI card, the whole constellation) actually spend observing the AOI?' 75% duty for the constellation KPI means the AOI had at least one satellite over it for three-quarters of the day; a satellite-row duty of 2% means that satellite personally spent about 29 minutes of the 24-hour window over the AOI, and the rest of its orbit was elsewhere on Earth (which is expected and correct -- a single LEO satellite is over any one country only a small fraction of each day). The constellation KPI is nearly always far higher than any single satellite's row, because different satellites cover the gap.", formula: "Satellite row: (that satellite's Total Observation Seconds ÷ its own simulated seconds) × 100. Constellation KPI: (union of every satellite's observing intervals ÷ whole analysis window) × 100 -- overlapping coverage is only counted once." },
];

const COVERAGE_TABLE_COLUMNS = [
  { key: "satellite", label: "Satellite" },
  { key: "Total Observation Time", label: "Observed" },
  { key: "Observation Windows", label: "Windows" },
  { key: "Average Window", label: "Avg window" },
  { key: "Observation Duty Cycle (%)", label: "Duty %", render: (v) => `${number(v, 2)}%` },
];

function CoverageView({ data }) {
  const coverage = data.coverage;
  const aoiLabel = data.mission.aoiRegionLabel || "Australia";
  const satellites = React.useMemo(() => coverage.observation.perSatellite.map((r) => r.satellite).sort(), [coverage.observation.perSatellite]);
  const [selected, toggle, selectAll] = useSatSelection(satellites);
  const filteredContribution = coverage.contribution.filter((r) => selected.includes(r.satellite));
  const filteredObs = coverage.observation.perSatellite.filter((r) => selected.includes(r.satellite));

  return (
    <div className="contentGrid">
      <div className="kpiGrid four">
        <KpiCard index={0} icon={Globe2} label={`${aoiLabel} coverage`} value={coverage.percent} format={(v) => `${number(v, 2)}%`} detail={`${number(coverage.coveredCells)} of ${number(coverage.totalCells)} land cells, all ${number(data.constellation.configuredSatellites)} satellites`} accent={COLORS.cyan} infoKey="coverage_percent" />
        <KpiCard index={1} icon={Activity} label="All-sat observed" value={coverage.observation.overall["Summed Satellite Observation Time"] || "NA"} detail={`combined effort-time summed across all ${number(data.constellation.configuredSatellites)} satellites`} accent={COLORS.green} />
        <KpiCard index={2} icon={Satellite} label="Max simultaneous" value={coverage.observation.overall["Maximum Simultaneous Observing Satellites"] || 0} detail={`of ${number(data.constellation.configuredSatellites)} satellites, observing at the same instant`} accent={COLORS.blue} />
        <KpiCard index={3} icon={Gauge} label="Observation duty" value={Number(coverage.observation.overall["Overall Observation Duty Cycle (%)"]) || 0} format={(v) => `${number(v, 2)}%`} detail={`constellation-wide timeline, ≥1 of ${number(data.constellation.configuredSatellites)} satellites`} accent={COLORS.amber} infoKey="duty_cycle" />
      </div>
      <Panel index={4} title="Coverage Cell Map" sub={`Analysis cells over the ${aoiLabel} land boundary, inside the mission AOI`} className="wide">
        <AustraliaCoverageMap
          cells={coverage.cells}
          outline={coverage.outline}
          tasmania={coverage.tasmania}
          aoi={coverage.aoi}
          percent={coverage.percent}
        />
      </Panel>
      <Panel
        index={5}
        title="Satellite Contribution"
        sub={`Covered analysis-cell centers · ${selected.length} of ${satellites.length} satellites shown`}
      >
        <SatSelector satellites={satellites} selected={selected} onToggle={toggle} onSelectAll={selectAll} />
        <SimpleBar rows={filteredContribution.slice(0, 20)} x="satellite" y="coveredCells" color={COLORS.cyan} height={290} />
      </Panel>
      <Panel
        index={6}
        title="Observation Duration"
        className="wide"
        action={
          <PdfButton
            mission={data.mission}
            title={`${aoiLabel} Observation Duration`}
            subtitle={`Per-satellite observation windows over the ${aoiLabel} AOI`}
            columns={COVERAGE_TABLE_COLUMNS}
            rows={filteredObs}
            fileName="observation_duration"
            section="coverage"
          />
        }
      >
        <DataTable rows={filteredObs.slice(0, 24)} columns={COVERAGE_TABLE_COLUMNS} />
        <p className="panelFootnote">
          <strong>Windows</strong> = separate passes over {aoiLabel} (a satellite crossing three times has 3, each timed independently). <strong>Avg window</strong> = the mean length of that satellite&apos;s own passes. <strong>Duty %</strong> = the share of the whole day that satellite spent over {aoiLabel} at all -- a few percent per satellite is expected for a single LEO craft; see &quot;How these analytics are calculated&quot; below for the exact formulas and why the constellation-wide Duty % KPI above is so much higher.
        </p>
      </Panel>
      <MethodNote items={swap48Methods(COVERAGE_METHODS, data.constellation.configuredSatellites)} />
    </div>
  );
}

/* ------------------------- notice banner (narrative) -------------------- */

function NoticeBanner({ icon: Icon, tone = COLORS.cyan, title, children, index = 0 }) {
  return (
    <section className="noticeBanner reveal wide" style={{ "--sub": tone, "--i": index }}>
      <div className="kHeroBadge">
        <Icon size={26} strokeWidth={1.8} />
      </div>
      <div className="kHeroBody">
        <h2>{title}</h2>
        <p>{children}</p>
      </div>
    </section>
  );
}

/* --------------------------- Payload & Imaging -------------------------- */

const IMAGING_METHODS = [
  { metric: "Ground swath / GSD", meaning: "Derived purely from camera geometry (focal length, sensor size, image width) and orbit altitude — not assumed.", formula: "HFOV = 2·atan(sensor width ÷ 2f); Swath = 2·altitude·tan(HFOV/2); GSD = Swath×1000 ÷ image width (px)" },
  { metric: "Ground speed", meaning: "Median ground-track speed per satellite, from consecutive fixes in Satellite_State_History.xlsx.", formula: "haversine distance between consecutive Lat/Lon fixes ÷ Δt, median per satellite, clipped to plausible LEO speeds" },
  { metric: "Imaged distance", meaning: "How far along its ground track each satellite imaged while the sensor was ON (i.e. over the mission's AOI).", formula: "ground speed (km/s) × observed time over AOI (s)" },
  { metric: "Imaged area (fleet-effort)", meaning: "Sum across all satellites — overlapping ground tracks are each counted, so this is total imaging effort, not a unique-area figure.", formula: "Σ (imaged distance × ground swath), all satellites" },
  { metric: "Estimated scenes", meaning: "A pushbroom sensor captures a continuous strip, not discrete photos. This is an engineering estimate of equivalent scene count, using the camera's own along-track frame footprint.", formula: "imaged distance ÷ (GSD × Image Height px ÷ 1000)" },
];

const IMAGING_TABLE_COLUMNS = [
  { key: "satellite", label: "Satellite" },
  { key: "observedSeconds", label: "Observed (s)", render: (v) => number(v, 0) },
  { key: "groundSpeedKmS", label: "Ground speed (km/s)", render: (v) => number(v, 3) },
  { key: "imagedDistanceKm", label: "Imaged distance (km)", render: (v) => number(v, 1) },
  { key: "imagedAreaKm2", label: "Imaged area (km²)", render: (v) => number(v, 0) },
  { key: "estimatedScenes", label: "Est. scenes", render: (v) => number(v, 0) },
];

function PayloadImagingView({ data, state }) {
  const camera = data.camera.model;
  const imaging = data.imaging;
  const satCount = data.constellation.configuredSatellites;
  const satellites = React.useMemo(() => imaging.perSatellite.map((r) => r.satellite).sort(), [imaging.perSatellite]);
  const [selected, toggle, selectAll] = useSatSelection(satellites);
  const filtered = imaging.perSatellite.filter((r) => selected.includes(r.satellite));
  const chartRows = filtered
    .slice()
    .sort((a, b) => (b.estimatedScenes || 0) - (a.estimatedScenes || 0))
    .slice(0, 24)
    .map((r) => ({ ...r, satellite: shortSat(r.satellite, "S") }));

  // The window these figures cover, read from the same state telemetry range
  // shown elsewhere (State Explorer, etc.) rather than assumed to be "a day" --
  // this view has looked like a single fixed snapshot with no stated time
  // scope, which is exactly what these figures are NOT: they scale with
  // however long the loaded simulation run actually covers.
  const rangeStart = state?.range?.start ? new Date(state.range.start) : null;
  const rangeEnd = state?.range?.end ? new Date(state.range.end) : null;
  const windowDays = rangeStart && rangeEnd
    ? Math.max((rangeEnd - rangeStart) / 86400000, 1 / 24)
    : null;
  const windowLabel = windowDays == null
    ? "the loaded analysis window"
    : windowDays < 1.5
      ? `a single ${number(windowDays * 24, 1)}-hour analysis window`
      : `a ${number(windowDays, windowDays < 10 ? 1 : 0)}-day analysis window`;

  return (
    <div className="contentGrid">
      <NoticeBanner icon={Aperture} tone={COLORS.violet} title="What 'captured imagery' means here" index={0}>
        The onboard sensor is a pushbroom imager — it scans a continuous strip beneath the satellite rather than
        taking discrete photos. Every figure on this page is <strong>calculated</strong> from real camera geometry
        and real mission telemetry, for <strong>{windowLabel}</strong> across <strong>all {satCount} satellites</strong> --
        not a fabricated or placeholder number, and not per-satellite-per-day unless stated. Longer or shorter simulation
        runs change every total here proportionally; see the calculation notes below for the exact formulas and a
        column-by-column trace of what feeds each one.
      </NoticeBanner>

      <div className="kpiGrid four">
        <KpiCard index={1} icon={Aperture} label="Ground swath" value={Number(camera["Ground Swath (km)"])} format={(v) => `${number(v, 2)} km`} detail={`${number(camera["GSD (m/pixel)"], 2)} m/pixel GSD · camera basis for all ${satCount} satellites · calculated from geometry, not measured`} accent={COLORS.violet} infoKey="ground_swath" />
        <KpiCard index={2} icon={Camera} label="Estimated scenes captured" value={Number(imaging.fleet.totalEstimatedScenes)} format={(v) => compact(v)} detail={`across ${imaging.fleet.satellitesWithImagery} of ${imaging.fleet.satelliteCount} satellites, over ${windowLabel}`} accent={COLORS.cyan} infoKey="estimated_scenes_captured" />
        <KpiCard index={3} icon={Activity} label="Imaged distance" value={Number(imaging.fleet.totalImagedDistanceKm)} format={(v) => `${compact(v)} km`} detail={`combined along-track strip length, all ${satCount} satellites, over ${windowLabel}`} accent={COLORS.green} infoKey="imaged_distance" />
        <KpiCard index={4} icon={Globe2} label="Imaged area (fleet-effort)" value={Number(imaging.fleet.totalImagedAreaKm2)} format={(v) => `${compact(v)} km²`} detail="summed per-satellite effort — overlaps counted, not a unique-area figure" accent={COLORS.amber} infoKey="imaged_area_fleet_effort" />
      </div>

      <Panel
        index={5}
        title="Estimated Scenes per Satellite"
        sub={`Along-track imaging estimate · ${selected.length} of ${satellites.length} satellites shown`}
        className="wide"
      >
        <SatSelector satellites={satellites} selected={selected} onToggle={toggle} onSelectAll={selectAll} />
        <SimpleBar rows={chartRows} x="satellite" y="estimatedScenes" color={COLORS.violet} height={300} />
      </Panel>

      <Panel
        index={6}
        title="Per-Satellite Imaging Summary"
        className="wide"
        action={
          <PdfButton
            mission={data.mission}
            title="Captured Imagery Report"
            subtitle={`Estimated imaging distance, area and scene count per satellite over the ${data.mission.aoiRegionLabel || "Australia"} AOI`}
            columns={IMAGING_TABLE_COLUMNS}
            rows={filtered}
            fileName="captured_imagery_report"
            section="imaging"
          />
        }
      >
        <DataTable rows={filtered} columns={IMAGING_TABLE_COLUMNS} />
      </Panel>

      <Panel index={7} title="Camera Configuration" sub="Mission payload model — shared across the fleet" className="wide">
        <DataTable
          rows={Object.entries(camera).filter(([key]) => key !== "_meta").map(([key, value]) => ({ key, value: Array.isArray(value) ? value.join(", ") : value }))}
          columns={[
            { key: "key", label: "Parameter" },
            { key: "value", label: "Value" },
          ]}
        />
        {camera._meta ? (
          <p className="panelFootnote">
            <strong>{camera._meta.configSourceSummary}.</strong> None of these optical parameters are
            ASC_074's real, validated payload specifications — they are representative small-satellite
            values used so the imaging pipeline has something physically self-consistent to run on. The
            mission's own configuration file currently has no matching entries for them (see &quot;Payload
            Type&quot; on the Data &amp; Config page). Sensor dimensions are checked against pixel count ×
            pixel pitch for internal consistency:{" "}
            {camera._meta.geometryValidation.consistent
              ? "consistent."
              : `inconsistent — ${camera._meta.geometryValidation.issues.join(" ")}`}
          </p>
        ) : null}
      </Panel>

      <MethodNote items={swap48Methods(IMAGING_METHODS, satCount)} />
    </div>
  );
}

/* ---------------------------- Global Coverage ---------------------------- */

const GLOBAL_METHODS = [
  { metric: "Region classification", meaning: "Each state sample's sub-satellite Lat/Lon is bucketed into one of 14 coarse geographic regions using ordered bounding boxes — an engineering approximation for situational awareness, not authoritative GIS (same approach as the mission's AOI land-boundary polygon).", formula: "first matching region wins, in priority order; unmatched points fall into 'Open Ocean / Transit'" },
  { metric: "Global reach (latitude span)", meaning: "The highest and lowest latitude any satellite's sub-point reached over the full analysis window — set by orbital inclination, not by AOI targeting.", formula: "min / max(Latitude) across all 48 satellites, all timestamps" },
  { metric: "AOI focus %", meaning: "Share of all fleet state samples (48 satellites × ~924 samples/day) whose sub-point falls inside the mission's AOI rectangle.", formula: "samples inside the AOI bounds ÷ total fleet samples × 100" },
  { metric: "Global (non-AOI) share", meaning: "The complement — time the constellation spends over the rest of the globe. Sensors are capable of imaging here but are intentionally kept OFF to conserve power for the mission's AOI (see K2 / K7).", formula: "100 − AOI focus %" },
];

const GLOBAL_TABLE_COLUMNS = [
  { key: "satellite", label: "Satellite" },
  { key: "minLatitude", label: "Min lat", render: (v) => `${number(v, 1)}°` },
  { key: "maxLatitude", label: "Max lat", render: (v) => `${number(v, 1)}°` },
  { key: "aoiSharePercent", label: "AOI share", render: (v) => `${number(v, 2)}%` },
  { key: "regionsVisited", label: "Regions visited" },
  { key: "topRegion", label: "Top region outside AOI" },
  { key: "topRegionPercent", label: "Top region %", render: (v) => `${number(v, 1)}%` },
];

function RegionBars({ rows = [] }) {
  return (
    <ResponsiveContainer height={Math.max(rows.length * 28, 220)}>
      <BarChart data={rows} layout="vertical" margin={{ top: 6, right: 30, left: 10, bottom: 6 }}>
        <CartesianGrid horizontal={false} stroke={COLORS.grid} />
        <XAxis type="number" tick={axisTick} stroke={COLORS.grid} unit="%" />
        <YAxis dataKey="region" type="category" tick={{ ...axisTick, fontSize: 10.5 }} width={190} stroke={COLORS.grid} />
        <Tooltip formatter={(v) => `${number(v, 2)}%`} cursor={{ fill: "rgba(34,211,238,.06)" }} />
        <Bar dataKey="percent" radius={[0, 4, 4, 0]}>
          {rows.map((row, index) => (
            <Cell key={index} fill={row.region.includes("(mission focus)") ? COLORS.cyan : hueFor(index + 3)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function GlobalCoverageView({ data, state }) {
  const global = data.globalCoverage;
  const aoiLabel = data.mission.aoiRegionLabel || "Australia";
  const aoiBox = data.coverage.aoi || DEFAULT_AOI_BOX;
  const aoiBoxLabel = fmtAoiBox(aoiBox);
  const satellites = React.useMemo(() => global.perSatellite.map((r) => r.satellite).sort(), [global.perSatellite]);
  const [selected, toggle, selectAll] = useSatSelection(satellites, 12);
  const filtered = global.perSatellite.filter((r) => selected.includes(r.satellite));

  return (
    <div className="contentGrid">
      <div className="kpiGrid four">
        <KpiCard index={0} icon={Compass} label="Global reach" value={`±${number(Math.max(Math.abs(global.fleet.minLatitude), Math.abs(global.fleet.maxLatitude)), 1)}°`} detail={`latitude span, all ${global.fleet.satelliteCount} satellites · set by 50° inclination`} accent={COLORS.blue} />
        <KpiCard index={1} icon={Globe2} label="Regions traversed" value={global.fleet.regionsTraversed} detail="of 14 approximate geographic buckets, fleet-wide" accent={COLORS.cyan} />
        <KpiCard index={2} icon={Gauge} label="AOI focus" value={Number(global.fleet.aoiSharePercent)} format={(v) => `${number(v, 2)}%`} detail={`share of fleet time actually powered, over ${aoiLabel}`} accent={COLORS.green} />
        <KpiCard index={3} icon={Aperture} label="Global capability, unused" value={Number(global.fleet.globalSharePercent)} format={(v) => `${number(v, 2)}%`} detail="time over the rest of the globe — sensors intentionally OFF" accent={COLORS.amber} />
      </div>

      <NoticeBanner icon={Compass} tone={COLORS.amber} title={`Global capability, ${aoiLabel}-only focus`} index={4}>
        Every craft in the fleet is physically capable of observing the whole globe as it orbits — the ground
        tracks below sweep from pole to pole across every longitude. Even so, the mission intentionally powers the
        sensor only while a craft is over the {aoiLabel} AOI ({aoiBoxLabel}): the other{" "}
        {number(global.fleet.globalSharePercent, 1)}% of each orbit is flown with the payload OFF, trading global
        imaging capability for a focused power and data budget on the mission's actual objective. This page exists
        purely for situational awareness of where the fleet passes — not as imagery that was actually captured.
      </NoticeBanner>

      <Panel index={5} title="Full-Globe Constellation Simulator" sub={`Unrestricted ground tracks — the same ${data.constellation.configuredSatellites} satellites, no AOI filter`} className="wide">
        {state ? (
          <ConstellationSim series={state.series} satellites={state.satellites} range={state.range} defaultWindowMs={Infinity} aoiBox={state.aoi || data.coverage.aoi} outline={data.coverage.outline} secondary={data.coverage.tasmania} aoiLabel={aoiLabel} />
        ) : (
          <div className="emptyState">Loading full-fleet ground tracks…</div>
        )}
      </Panel>

      <Panel index={6} title="Fleet Time by Region" sub="Share of all state samples, fleet-wide, per approximate region" className="wide">
        <RegionBars rows={global.regions} />
      </Panel>

      <Panel
        index={7}
        title="Per-Satellite Global Reach"
        className="wide"
        sub={`${selected.length} of ${satellites.length} satellites shown`}
        action={
          <PdfButton
            mission={data.mission}
            title="Global Coverage Report"
            subtitle={`Per-satellite geographic reach — where each craft passes over the globe, beyond the ${aoiLabel} AOI`}
            columns={GLOBAL_TABLE_COLUMNS}
            rows={filtered}
            fileName="global_coverage_report"
            section="global"
          />
        }
      >
        <SatSelector satellites={satellites} selected={selected} onToggle={toggle} onSelectAll={selectAll} />
        <DataTable rows={filtered} columns={GLOBAL_TABLE_COLUMNS} />
      </Panel>

      <MethodNote items={swap48Methods(GLOBAL_METHODS, data.constellation.configuredSatellites)} />
    </div>
  );
}

const DATA_METHODS = [
  { metric: "Row counts", meaning: "Direct row counts of the processed Excel outputs the pipeline produces from raw raw mission reports — no rows are added, removed, or estimated for display.", formula: "len(dataframe) per file" },
  { metric: "Configuration issues", meaning: "Cross-checks Mission_Configuration.xlsx against itself and the detected fleet (e.g. planes × satellites/plane, missing payload/power values).", formula: "see core/config_loader.validate_configuration()" },
];

const ECLIPSE_TABLE_COLUMNS = [
  { key: "Satellite Name", label: "Satellite" },
  { key: "Eclipse Type", label: "Type" },
  { key: "Start UTC", label: "Start" },
  { key: "Duration (s)", label: "Duration", render: (v) => `${number(Number(v) / 60, 2)} min` },
];

function useDataQuality(missionId) {
  const { authFetch } = useAccess();
  const [quality, setQuality] = React.useState(null);
  React.useEffect(() => {
    if (!missionId) return;
    authFetch(`${API_BASE}/api/dataquality?mission=${missionId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setQuality)
      .catch(() => {});
  }, [missionId, authFetch]);
  return quality;
}

const DQ_ICON = { ok: CheckSquare, warning: AlertTriangle, missing: ShieldCheck };
const DQ_LABEL = { ok: "Parsed", warning: "Partial", missing: "Not Available" };

function DataView({ data, missionId, missions, glossaryMap }) {
  const quality = useDataQuality(missionId);
  return (
    <div className="contentGrid">
      <FullReportPanel data={data} glossaryMap={glossaryMap} quality={quality} apiBase={API_BASE} missions={missions} missionId={missionId} />
      <Panel
        index={1}
        title="Data Quality & Validation"
        sub={quality ? `${quality.summary.ok} OK · ${quality.summary.warning} partial · ${quality.summary.missing} not available, out of ${quality.summary.total} datasets checked` : "Checking parsed processed outputs…"}
        className="wide"
      >
        {quality ? (
          <div className="dqList">
            {quality.checks.map((c) => {
              const Icon = DQ_ICON[c.status] || AlertTriangle;
              return (
                <div key={c.dataset} className={`dqRow dq-${c.status}`}>
                  <Icon size={16} />
                  <div>
                    <strong>{c.dataset}</strong>
                    <span className={`dqBadge dq-${c.status}`}>{DQ_LABEL[c.status] || c.status}</span>
                    <p>{c.detail}</p>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="emptyState">Loading validation results…</div>
        )}
      </Panel>
      <Panel index={1} title="Dataset Inventory" sub={`Processed processed outputs · ${data.constellation.configuredSatellites}-satellite fleet`} className="wide">
        <div className="inventory">
          <KpiCard index={0} icon={Radio} label="RF rows" value={data.metrics.rfEvents} detail="RF_Contacts.xlsx — 1 row per RF pass" accent={COLORS.blue} />
          <KpiCard index={1} icon={Antenna} label="Optical rows" value={data.metrics.opticalEvents} detail="Optical_Contacts.xlsx — 1 row per optical pass" accent={COLORS.green} />
          <KpiCard index={2} icon={SunMedium} label="Eclipse rows" value={data.metrics.eclipseEvents} detail="All_Eclipse_Events.xlsx — 1 row per eclipse interval" accent={COLORS.amber} />
          <KpiCard index={3} icon={HardDrive} label="State rows" value={data.metrics.stateRows} format={compact} detail={`Satellite_State_History.xlsx — ${data.constellation.configuredSatellites} satellites × samples/day`} accent={COLORS.cyan} />
        </div>
      </Panel>
      <Panel index={2} title="Configuration Issues">
        {data.configuration.issues.length ? (
          <div className="issueList">{data.configuration.issues.map((issue) => <span key={issue}>{issue}</span>)}</div>
        ) : (
          <div className="emptyState">No configuration validation issues reported.</div>
        )}
      </Panel>
      <Panel
        index={3}
        title="Top Eclipse Events"
        action={
          <PdfButton
            mission={data.mission}
            title="Top Eclipse Events"
            subtitle="Longest recorded eclipse intervals, all satellites"
            columns={ECLIPSE_TABLE_COLUMNS}
            rows={data.tables.eclipse}
            fileName="eclipse_events_report"
            section="data"
          />
        }
      >
        <DataTable rows={data.tables.eclipse.slice(0, 16)} columns={ECLIPSE_TABLE_COLUMNS} />
      </Panel>
      <MethodNote items={DATA_METHODS} />
    </div>
  );
}

/* ----------------------- Satellite State Explorer --------------------- */

const STATE_EXPLORER_COLUMNS = [
  { key: "satellite", label: "Satellite" },
  { key: "samples", label: "Samples", render: (v) => number(v) },
  { key: "minAltitude", label: "Min Alt (km)", render: (v) => number(v, 2) },
  { key: "meanAltitude", label: "Mean Alt (km)", render: (v) => number(v, 2) },
  { key: "maxAltitude", label: "Max Alt (km)", render: (v) => number(v, 2) },
  { key: "meanEccentricity", label: "Mean Ecc", render: (v) => number(v, 6) },
  { key: "meanRmag", label: "Mean RMAG (km)", render: (v) => number(v, 1) },
  { key: "aoiSharePercent", label: "AOI Dwell %", render: (v) => number(v, 2) },
  { key: "aoiSamples", label: "AOI Samples", render: (v) => number(v) },
];

const STATE_EXPLORER_METHODS = [
  { metric: "Samples (same value for every satellite)", meaning: "raw mission reports on one shared UTC time grid: every row is one timestamp, with every satellite's own fields as separate columns on that row. All satellites are therefore sampled exactly as many times as there are rows in the state report, by construction — not because the number happened to come out equal.", formula: "Samples = row count of Satellite_State_History.xlsx for the loaded window (identical for every satellite)" },
  { metric: "Instantaneous Geodetic Altitude (min/mean/max)", meaning: "Range of the 'Altitude' column in Satellite_State_History.xlsx for this satellite across the analysis window: the actual propagated altitude at each timestep, not the fixed Nominal Orbit Altitude.", formula: "min / mean / max(Altitude)" },
  { metric: "Mean eccentricity", meaning: "Average of the state file's 'ECC' column — how far the orbit deviates from a perfect circle (0 = circular).", formula: "mean(ECC)" },
  { metric: "Mean RMAG", meaning: "Average orbit radius from Earth's center (Earth radius + altitude), from the state file's 'RMAG' column.", formula: "mean(RMAG)" },
  { metric: "AOI dwell %", meaning: "Share of this satellite's state samples whose sub-point falls inside the mission AOI rectangle.", formula: "samples inside the AOI bounds ÷ total samples × 100" },
];

function StateExplorer({ state, mission, stateLoading, coverage }) {
  const satellites = state?.satellites || [];
  const [selected, toggle, selectAll] = useSatSelection(satellites, 6);
  const [field, setField] = React.useState("alt");

  if (stateLoading || !state) {
    return (
      <div className="contentGrid">
        <Panel title="Satellite State Explorer" className="wide">
          <div className="emptyState">Loading per-satellite state telemetry…</div>
        </Panel>
      </div>
    );
  }

  const tracks = selected.flatMap((s) => (state.series[s] || []).map((p) => ({ satellite: s, lat: p.lat, lon: p.lon })));
  const positions = selected
    .map((s) => {
      const arr = state.series[s] || [];
      const last = arr[arr.length - 1];
      return last ? { satellite: s, lat: last.lat, lon: last.lon, altitude: last.alt } : null;
    })
    .filter(Boolean);

  const fields = [
    ["alt", "Altitude (km)", "km"],
    ["ecc", "Eccentricity", ""],
    ["rmag", "Orbit radius RMAG (km)", "km"],
    ["lat", "Latitude (°)", "°"],
  ];
  const activeField = fields.find((f) => f[0] === field);
  // The one field here that is a live, continuously changing value rather than
  // a fixed configuration number, worth naming explicitly since the
  // constellation also has a fixed Nominal Orbit Altitude shown elsewhere.
  const FIELD_TITLES = {
    alt: "Instantaneous Geodetic Altitude: the actual propagated altitude at this timestep, which varies continuously (the fixed Nominal Orbit Altitude is shown on Mission Overview and Data and Config)",
  };

  return (
    <div className="contentGrid">
      <Panel
        index={0}
        title="Satellite State Explorer"
        sub={`${selected.length} of ${satellites.length} satellites selected (basis: full ${satellites.length}-satellite fleet) · window ${dateLabel(state.range?.start)} → ${dateLabel(state.range?.end)}`}
        className="wide"
        action={
          <PdfButton
            mission={mission}
            title="Satellite State Report"
            subtitle={`AOI ${fmtAoiBox(state.aoi)} · window ${dateLabel(state.range?.start)} to ${dateLabel(state.range?.end)}`}
            columns={STATE_EXPLORER_COLUMNS}
            rows={state.summary}
            fileName="satellite_state_report"
            section="explorer"
          />
        }
      >
        <SatSelector satellites={satellites} selected={selected} onToggle={toggle} onSelectAll={selectAll} />
      </Panel>

      <Panel
        index={1}
        title="Telemetry Over Time"
        sub={field === "alt"
          ? "Instantaneous Geodetic Altitude: varies continuously as each satellite orbits, not the fixed Nominal Orbit Altitude"
          : "All selected satellites overlaid across the analysis window"}
        className="wide"
        action={
          <div className="fieldTabs">
            {fields.map((f) => (
              <button key={f[0]} className={field === f[0] ? "fieldTab on" : "fieldTab"} onClick={() => setField(f[0])}
                      title={FIELD_TITLES[f[0]] || f[1]}>
                {f[1].split(" ")[0]}
              </button>
            ))}
          </div>
        }
      >
        {selected.length ? (
          <MultiLine selected={selected} series={state.series} field={field} unit={activeField[2]} height={360} />
        ) : (
          <div className="emptyState">Select one or more satellites to plot telemetry.</div>
        )}
      </Panel>

      <Panel index={2} title="Ground Tracks" sub="Sub-satellite paths for the selected fleet" className="wide">
        <WorldOrbitMap positions={positions} tracks={tracks} maxTracks={selected.length} aoiBox={coverage?.aoi} outline={coverage?.outline} secondary={coverage?.tasmania} />
      </Panel>

      <Panel index={3} title="Per-Satellite Summary" sub="Full fleet — this is the data exported to PDF" className="wide">
        <DataTable
          rows={state.summary}
          columns={[
            { key: "satellite", label: "Satellite" },
            { key: "samples", label: "Samples", infoKey: "samples_per_satellite", render: (v) => number(v) },
            { key: "minAltitude", label: "Min alt", render: (v) => `${number(v, 1)} km` },
            { key: "meanAltitude", label: "Mean alt", render: (v) => `${number(v, 1)} km` },
            { key: "maxAltitude", label: "Max alt", render: (v) => `${number(v, 1)} km` },
            { key: "meanEccentricity", label: "Mean ecc", render: (v) => number(v, 6) },
            { key: "aoiSharePercent", label: "AOI dwell", render: (v) => `${number(v, 2)}%` },
          ]}
        />
      </Panel>

      <MethodNote items={STATE_EXPLORER_METHODS} />
    </div>
  );
}

/* --------------------------- K1–K10 views ----------------------------- */

const K_CONTENT = {
  k1: {
    requirement:
      "48 crafts move across the mission's AOI — each craft holds its designated SSO (50°) path. The orbit subsystem keeps the constellation transiting the region every revolution.",
    methods: [
      { metric: "Crafts in transit / Nominal Orbit Altitude", meaning: "Read directly from Mission_Configuration.xlsx (Constellation and Orbit tables) — not derived.", formula: "Total Satellites; Altitude (km)" },
      { metric: "Fleet AOI dwell", meaning: "Average, across all 48 satellites, of how much of the analysis window each spends with its sub-point inside the AOI rectangle.", formula: "mean( AOI samples ÷ total samples × 100 ) across satellites" },
      { metric: "Live subpoints", meaning: "Count of satellites with a recorded position at the single latest shared timestamp in the state file.", formula: "count(satellites at max(Timestamp))" },
    ],
    render: (data, state) => (
      <>
        <div className="kpiGrid four">
          <KpiCard index={0} icon={Satellite} label="Crafts in transit" value={data.constellation.configuredSatellites} detail={`of ${data.constellation.configuredSatellites} configured, ${number(data.constellation.inclinationDeg, 1)}° inclination`} accent={SUBSYS.Orbit.color} />
          <KpiCard index={1} icon={Orbit} label="Nominal Orbit Altitude" value={Number(data.constellation.altitudeKm)} format={(v) => `${number(v, 0)} km`} detail="fixed design value, shared by all satellites" accent={SUBSYS.Orbit.color} infoKey="nominal_orbit_altitude" />
          <KpiCard index={2} icon={Globe2} label="Fleet AOI dwell" value={state ? state.summary.reduce((a, r) => a + r.aoiSharePercent, 0) / (state.summary.length || 1) : 0} format={(v) => `${number(v, 2)}%`} detail={`avg across ${state ? state.summary.length : data.constellation.configuredSatellites} satellites, time over the AOI rectangle`} accent={SUBSYS.Orbit.color} />
          <KpiCard index={3} icon={Activity} label="Live subpoints" value={data.charts.latestPositions.length} detail={`of ${data.constellation.configuredSatellites} satellites, at the latest shared epoch`} accent={SUBSYS.Orbit.color} />
        </div>
        <Panel index={4} title="Constellation Transit Simulator" sub={`Animated ground tracks — watch the ${data.constellation.configuredSatellites} crafts transit ${data.mission.aoiRegionLabel || "Australia"}`} className="wide">
          {state ? (
            <ConstellationSim series={state.series} satellites={state.satellites} range={state.range} aoiBox={state.aoi || data.coverage.aoi} outline={data.coverage.outline} secondary={data.coverage.tasmania} aoiLabel={data.mission.aoiRegionLabel} />
          ) : (
            <WorldOrbitMap positions={data.charts.latestPositions} tracks={data.charts.tracks} aoiBox={data.coverage.aoi} outline={data.coverage.outline} secondary={data.coverage.tasmania} />
          )}
        </Panel>
        {state ? (
          <Panel index={5} title="AOI Dwell per Satellite" sub={`Share of the window each craft spends over the ${data.mission.aoiRegionLabel || "Australia"} AOI`} className="wide">
            <SimpleBar rows={[...state.summary].sort((a, b) => b.aoiSharePercent - a.aoiSharePercent).slice(0, 24).map((r) => ({ satellite: shortSat(r.satellite, "S"), aoiSharePercent: r.aoiSharePercent }))} x="satellite" y="aoiSharePercent" color={SUBSYS.Orbit.color} format={(v) => `${number(v, 2)}%`} />
          </Panel>
        ) : null}
      </>
    ),
  },
  k2: {
    requirement:
      "48 crafts use sensor power only while travelling over the mission's AOI. Payload ON/OFF is derived from the modeled camera swath crossing the region — power is spent on coverage, not idle flight.",
    methods: [
      { metric: "Fleet ON time / duty cycle", meaning: "A state sample counts as sensor ON when the modeled camera footprint (half the ground swath around the sub-satellite point) intersects the mission's AOI land boundary, across all 48 satellites.", formula: "duty % = ON samples ÷ total samples × 100" },
      { metric: "AOI + eclipse", meaning: "Hours where a satellite is simultaneously ON (observing) and inside a recorded eclipse interval — power drawn from battery, not solar, during that overlap.", formula: "Σ duration where Observing = true AND In Eclipse = true" },
      { metric: "Sample cadence", meaning: "Median time between consecutive state samples — the telemetry resolution this whole page's timing is built on.", formula: "median(Δt) between consecutive Timestamp rows, per satellite" },
    ],
    render: (data) => (
      <>
        <div className="kpiGrid four">
          <KpiCard index={0} icon={Zap} label="Fleet ON time" value={Number(data.duty.metrics.fleetActiveHours)} format={asHours} detail={`sensors active over AOI, across ${data.constellation.configuredSatellites} satellites`} accent={SUBSYS.Power.color} />
          <KpiCard index={1} icon={Gauge} label="Fleet duty cycle" value={Number(data.duty.metrics.fleetDutyPercent)} format={(v) => `${number(v, 2)}%`} detail="active samples ÷ total samples, fleet-wide" accent={SUBSYS.Power.color} trend={data.duty.summary?.map((s) => s.dutyPercent)} trendLabels={data.duty.summary?.map((s) => s.satellite)} />
          <KpiCard index={2} icon={SunMedium} label="AOI + eclipse" value={Number(data.duty.metrics.aoiEclipseOverlapHours)} format={asHours} detail="observing while in eclipse, summed across the fleet" accent={SUBSYS.Power.color} />
          <KpiCard index={3} icon={Activity} label="Sample cadence" value={Number(data.duty.metrics.nominalStepSeconds)} format={(v) => `${number(v, 0)} s`} detail="median state step, per satellite" accent={SUBSYS.Power.color} />
        </div>
        <Panel index={4} title="Sensor Power Timeline" sub={`Observing satellites (sensor power drawn) vs. eclipse, out of ${data.constellation.configuredSatellites}`} className="wide">
          <DutyTimeline rows={data.duty.timeline} />
        </Panel>
        <Panel index={5} title="Active Payload Time per Satellite" sub={`Minutes of sensor power over ${data.mission.aoiRegionLabel || "Australia"}, per craft`} className="wide">
          <SimpleBar rows={data.duty.summary.slice(0, 24).map((r) => ({ ...r, satellite: shortSat(r.satellite, "S") }))} x="satellite" y="activeMinutes" color={SUBSYS.Power.color} format={(v) => `${number(v, 1)} min`} />
        </Panel>
      </>
    ),
  },
  k3: {
    requirement:
      "48 crafts store the AOI data onboard and downlink it to the mission's ground station when passing through the GSN. This tracks the volume captured over the AOI and the contact opportunities to offload it.",
    methods: [
      { metric: "Observed time", meaning: "Same sensor-ON basis as K2 — this is the raw data being generated for onboard storage.", formula: "Σ ON duration, across all satellites" },
      { metric: "RF / Optical contacts", meaning: "One row per continuous line-of-sight contact between a satellite and the mission's GSN — each is a downlink opportunity.", formula: "row count in RF_Contacts.xlsx / Optical_Contacts.xlsx" },
      { metric: "Downlink windows", meaning: "Total pass count (RF + optical) available to offload stored data, across the full fleet.", formula: "RF rows + Optical rows" },
    ],
    render: (data) => (
      <>
        <div className="kpiGrid four">
          <KpiCard index={0} icon={HardDrive} label="Observed time" value={Number(data.duty.metrics.fleetActiveHours)} format={asHours} detail={`data captured over AOI, across ${data.constellation.configuredSatellites} satellites`} accent={SUBSYS.Data.color} />
          <KpiCard index={1} icon={Antenna} label="RF contacts" value={data.metrics.rfEvents} detail={`${asMinutes(data.metrics.rfMinutes)}, fleet-wide`} accent={SUBSYS.Data.color} />
          <KpiCard index={2} icon={Radio} label="Optical contacts" value={data.metrics.opticalEvents} detail={`${asMinutes(data.metrics.opticalMinutes)}, fleet-wide`} accent={SUBSYS.Data.color} />
          <KpiCard index={3} icon={Gauge} label="Downlink windows" value={data.tables.rf.length + data.tables.optical.length} detail="total RF + optical pass count" accent={SUBSYS.Data.color} />
        </div>
        <Panel index={4} title="Downlink Contact Time by Station" sub="Cumulative downlink windows (RF + optical)" className="wide">
          <GroundStationBars rf={data.charts.groundStationsRf} optical={data.charts.groundStationsOptical} />
        </Panel>
        <Panel
          index={5}
          title="Recent Downlink Passes"
          className="wide"
          action={
            <PdfButton mission={data.mission} title="Downlink Passes" subtitle="RF contact windows, all satellites" columns={[
              { key: "Satellite Name", label: "Satellite" },
              { key: "Ground Station", label: "Station" },
              { key: "Start UTC", label: "Start" },
              { key: "Duration (s)", label: "Duration", render: (v) => `${number(Number(v) / 60, 2)} min` },
            ]} rows={data.tables.rf} fileName="downlink_passes" section="k3" />
          }
        >
          <DataTable
            rows={data.tables.rf.slice(0, 18)}
            columns={[
              { key: "Satellite Name", label: "Satellite" },
              { key: "Ground Station", label: "Station" },
              { key: "Start UTC", label: "Start" },
              { key: "Duration (s)", label: "Duration", render: (v) => `${number(Number(v) / 60, 2)} min` },
            ]}
          />
        </Panel>
      </>
    ),
  },
  k4: {
    requirement:
      "The mission's GSN links to each craft and downloads the collected data for transmission. This view isolates the ground-station link budget: which stations carry the load and how long each pass lasts.",
    methods: [
      { metric: "RF / Optical contacts", meaning: "Pass counts and durations from the contact files — the downlink opportunities the mission's GSN has with the fleet.", formula: "row count and Σ Duration(s) ÷ 60, per link type" },
      { metric: "Ground stations", meaning: "Distinct 'Ground Station' values seen across both contact files.", formula: "count(unique Ground Station)" },
      { metric: "Total link time", meaning: "Combined RF and optical contact minutes, summed across the fleet.", formula: "RF minutes + Optical minutes" },
    ],
    render: (data) => (
      <>
        <div className="kpiGrid four">
          <KpiCard index={0} icon={Antenna} label="RF contacts" value={data.metrics.rfEvents} detail={`${asMinutes(data.metrics.rfMinutes)}, fleet-wide`} accent={SUBSYS.GSN.color} />
          <KpiCard index={1} icon={Radio} label="Optical contacts" value={data.metrics.opticalEvents} detail={`${asMinutes(data.metrics.opticalMinutes)}, fleet-wide`} accent={SUBSYS.GSN.color} />
          <KpiCard index={2} icon={Gauge} label="Ground stations" value={new Set([...data.charts.groundStationsRf, ...data.charts.groundStationsOptical].map((r) => r["Ground Station"])).size} detail="active in the contact plan" accent={SUBSYS.GSN.color} />
          <KpiCard index={3} icon={Activity} label="Total link time" value={Number(data.metrics.rfMinutes) + Number(data.metrics.opticalMinutes)} format={(v) => `${number(v, 0)} min`} detail="RF + optical, all satellites" accent={SUBSYS.GSN.color} />
        </div>
        <Panel index={4} title="Ground Station Contact Time" sub="Highest cumulative downlink windows" className="wide">
          <GroundStationBars rf={data.charts.groundStationsRf} optical={data.charts.groundStationsOptical} />
        </Panel>
        <Panel index={5} title="Contacts by Satellite" sub="RF, optical and eclipse composition, per craft" className="wide">
          <EventMatrix rows={data.charts.eventMatrix} />
          <NoEclipseNote rows={data.charts.eventMatrix} />
        </Panel>
      </>
    ),
  },
  k5: {
    requirement:
      "The mission's GSN uploads any data the craft needs for its operations. Each downlink pass is also a command-uplink opportunity — this view schedules those contact windows.",
    methods: [
      { metric: "Uplink windows / time", meaning: "Every RF pass is treated as a bidirectional contact — the same window used for downlink is available for command uplink.", formula: "uplink windows = RF row count; uplink time = Σ RF Duration(s) ÷ 60" },
      { metric: "Crafts reachable", meaning: "Distinct satellites with at least one RF pass in the contact file — these are commandable during this window.", formula: "count(unique Satellite Name in RF_Contacts.xlsx)" },
    ],
    render: (data) => (
      <>
        <div className="kpiGrid four">
          <KpiCard index={0} icon={Send} label="Uplink windows" value={data.tables.rf.length} detail="RF passes usable for uplink, fleet-wide" accent={SUBSYS.Upload.color} />
          <KpiCard index={1} icon={Upload} label="Uplink time" value={Number(data.metrics.rfMinutes)} format={(v) => `${number(v, 0)} min`} detail="cumulative RF contact, all satellites" accent={SUBSYS.Upload.color} />
          <KpiCard index={2} icon={Satellite} label="Crafts reachable" value={new Set(data.tables.rf.map((r) => r["Satellite Name"])).size} detail={`of ${data.constellation.configuredSatellites}, have ≥1 RF pass`} accent={SUBSYS.Upload.color} />
          <KpiCard index={3} icon={Antenna} label="Stations" value={new Set(data.tables.rf.map((r) => r["Ground Station"])).size} detail="uplink sites in the contact plan" accent={SUBSYS.Upload.color} />
        </div>
        <Panel
          index={4}
          title="Command Uplink Schedule"
          sub="RF contact windows available for command upload"
          className="wide"
          action={
            <PdfButton mission={data.mission} title="Command Uplink Schedule" subtitle="RF windows usable for uplink, all satellites" columns={[
              { key: "Satellite Name", label: "Satellite" },
              { key: "Ground Station", label: "Station" },
              { key: "Start UTC", label: "Window start" },
              { key: "Duration (s)", label: "Available", render: (v) => `${number(Number(v) / 60, 2)} min` },
            ]} rows={data.tables.rf} fileName="command_uplink_schedule" section="k5" />
          }
        >
          <DataTable
            rows={data.tables.rf.slice(0, 22)}
            columns={[
              { key: "Satellite Name", label: "Satellite" },
              { key: "Ground Station", label: "Station" },
              { key: "Start UTC", label: "Window start" },
              { key: "Duration (s)", label: "Available", render: (v) => `${number(Number(v) / 60, 2)} min` },
            ]}
          />
        </Panel>
      </>
    ),
  },
  k6: {
    requirement:
      "The 48 crafts must be 100% active while covering the mission's AOI rectangle. This is the core area coverage: which land cells are seen and by whom.",
    methods: COVERAGE_METHODS,
    render: (data) => (
      <>
        <div className="kpiGrid four">
          <KpiCard index={0} icon={Globe2} label={`${data.mission.aoiRegionLabel || "Australia"} coverage`} value={Number(data.coverage.percent)} format={(v) => `${number(v, 2)}%`} detail={`${number(data.coverage.coveredCells)} / ${number(data.coverage.totalCells)} land cells, all ${data.constellation.configuredSatellites} satellites`} accent={SUBSYS.Orbit.color} infoKey="coverage_percent" />
          <KpiCard index={1} icon={Activity} label="All-sat observed" value={data.coverage.observation.overall["Summed Satellite Observation Time"] || "NA"} detail="combined effort-time, summed across all satellites" accent={SUBSYS.Orbit.color} />
          <KpiCard index={2} icon={Satellite} label="Max simultaneous" value={data.coverage.observation.overall["Maximum Simultaneous Observing Satellites"] || 0} detail={`of ${data.constellation.configuredSatellites}, observing at the same instant`} accent={SUBSYS.Orbit.color} />
          <KpiCard index={3} icon={Gauge} label="Observation duty" value={Number(data.coverage.observation.overall["Overall Observation Duty Cycle (%)"]) || 0} format={(v) => `${number(v, 2)}%`} detail={`constellation timeline, ≥1 of ${data.constellation.configuredSatellites} satellites`} accent={SUBSYS.Orbit.color} infoKey="duty_cycle" />
        </div>
        <Panel index={4} title="Coverage Cell Map" sub={`Covered / uncovered cells over the ${data.mission.aoiRegionLabel || "Australia"} land boundary`} className="wide">
          <AustraliaCoverageMap cells={data.coverage.cells} outline={data.coverage.outline} tasmania={data.coverage.tasmania} aoi={data.coverage.aoi} percent={data.coverage.percent} />
        </Panel>
        <Panel index={5} title="Coverage Contribution" sub="Covered analysis-cell centers per satellite" className="wide">
          <SimpleBar rows={data.coverage.contribution.slice(0, 24).map((r) => ({ ...r, satellite: shortSat(r.satellite, "S") }))} x="satellite" y="coveredCells" color={SUBSYS.Orbit.color} />
        </Panel>
      </>
    ),
  },
  k7: {
    requirement:
      "Sensors don't need to work when out of the Area rectangle, so onboard power targets coverage only. Medium solar panels charge and store power between passes — eclipse and duty define the budget.",
    methods: [
      { metric: "Eclipse events", meaning: "Sun-blocked intervals (umbra + penumbra) across the fleet — the constraint the power budget is built around.", formula: "hours = Σ Duration(s) ÷ 3600, all satellites" },
      { metric: "Fleet duty cycle", meaning: "Same ON-time basis as K2 — the share of each orbit power is actually drawn for the payload.", formula: "ON samples ÷ total samples × 100" },
      { metric: "Idle share", meaning: "The complement of duty cycle — the share of each orbit available to charge and store power for the next AOI pass.", formula: "100 − fleet duty cycle %" },
    ],
    render: (data) => (
      <>
        <div className="kpiGrid four">
          <KpiCard index={0} icon={SunMedium} label="Eclipse events" value={data.metrics.eclipseEvents} detail={`${asHours(data.metrics.eclipseHours)}, across the fleet`} accent={SUBSYS.Power.color} />
          <KpiCard index={1} icon={Gauge} label="Fleet duty cycle" value={Number(data.duty.metrics.fleetDutyPercent)} format={(v) => `${number(v, 2)}%`} detail="power drawn for coverage, fleet average" accent={SUBSYS.Power.color} trend={data.duty.summary?.map((s) => s.dutyPercent)} trendLabels={data.duty.summary?.map((s) => s.satellite)} />
          <KpiCard index={2} icon={Zap} label="Idle share" value={100 - Number(data.duty.metrics.fleetDutyPercent)} format={(v) => `${number(v, 2)}%`} detail="charge / store window, fleet average" accent={SUBSYS.Power.color} />
          <KpiCard index={3} icon={Activity} label="ON time" value={Number(data.duty.metrics.fleetActiveHours)} format={asHours} detail="sensor active, summed across all satellites" accent={SUBSYS.Power.color} />
        </div>
        <Panel index={4} title="Eclipse Mix" sub="Umbra / penumbra split drives the power budget, fleet-wide">
          <EclipsePie data={data.charts.eclipseTypes} />
          <div className="legendStack">
            {data.charts.eclipseTypes.map((item, index) => (
              <span key={item.type}>
                <i style={{ background: PIE_COLORS[index % PIE_COLORS.length], color: PIE_COLORS[index % PIE_COLORS.length] }} />
                {item.type}: {number(item.events)}
              </span>
            ))}
          </div>
        </Panel>
        <Panel index={5} title="Duty Cycle per Satellite" sub="Active coverage share — the rest is charge/store time, per craft">
          <SimpleBar rows={data.duty.summary.slice(0, 20).map((r) => ({ ...r, satellite: shortSat(r.satellite, "S") }))} x="satellite" y="dutyPercent" color={SUBSYS.Power.color} format={(v) => `${number(v, 2)}%`} height={280} />
        </Panel>
      </>
    ),
  },
  k8: {
    requirement:
      "When the craft is outside the Area of cover, the OBC uses that time for onboard processing, making pre-processed data ready for downlink at the mission's ground station. Processing time is the complement of AOI dwell.",
    methods: [
      { metric: "Processing share", meaning: "The onboard computer is assumed free to pre-process the previous pass's data whenever a satellite's sub-point is outside the AOI rectangle. This is the inverse of the K1 'Fleet AOI dwell' figure, averaged across all 48 satellites.", formula: "100 − mean(AOI dwell %) across satellites" },
      { metric: "Observed time", meaning: "Same sensor-ON basis as K2/K3 — the raw data volume the OBC has to work through.", formula: "Σ ON duration, all satellites" },
      { metric: "State samples", meaning: "Total telemetry rows across the fleet — the processing timeline's resolution.", formula: "row count in Satellite_State_History.xlsx" },
    ],
    render: (data, state) => (
      <>
        <div className="kpiGrid four">
          <KpiCard index={0} icon={Cpu} label="Processing share" value={state ? 100 - state.summary.reduce((a, r) => a + r.aoiSharePercent, 0) / (state.summary.length || 1) : 0} format={(v) => `${number(v, 2)}%`} detail={`time outside AOI (OBC busy), avg across ${state ? state.summary.length : data.constellation.configuredSatellites} satellites`} accent={SUBSYS.Data.color} />
          <KpiCard index={1} icon={Database} label="Observed time" value={Number(data.duty.metrics.fleetActiveHours)} format={asHours} detail="raw data to process, summed across the fleet" accent={SUBSYS.Data.color} />
          <KpiCard index={2} icon={HardDrive} label="State samples" value={data.metrics.stateRows} format={compact} detail={`processing timeline, ${data.constellation.configuredSatellites} satellites`} accent={SUBSYS.Data.color} />
          <KpiCard index={3} icon={Gauge} label="Coverage duty" value={Number(data.coverage.observation.overall["Overall Observation Duty Cycle (%)"]) || 0} format={(v) => `${number(v, 2)}%`} detail="acquisition vs processing split, fleet timeline" accent={SUBSYS.Data.color} />
        </div>
        {state ? (
          <Panel index={4} title="Onboard Processing Window per Satellite" sub="Percent of the window outside the AOI — available for OBC processing" className="wide">
            <SimpleBar rows={[...state.summary].sort((a, b) => (b.samples - b.aoiSamples) - (a.samples - a.aoiSamples)).slice(0, 24).map((r) => ({ satellite: shortSat(r.satellite, "S"), processing: 100 - r.aoiSharePercent }))} x="satellite" y="processing" color={SUBSYS.Data.color} format={(v) => `${number(v, 2)}%`} />
          </Panel>
        ) : null}
        <Panel index={5} title="Acquisition vs Processing Timeline" sub="Observing satellites (acquiring) — the inverse is processing" className="wide">
          <DutyTimeline rows={data.duty.timeline} />
        </Panel>
      </>
    ),
  },
  k9: {
    requirement:
      "The pre-processed package from the OBC is downlinked to the GSN. While sensors cover the Area, the OBC waits; once coverage stops it processes. This view maps the observation windows feeding the pipeline.",
    methods: [
      { metric: "Downlink windows", meaning: "RF passes available to deliver the pre-processed data package to the mission's GSN.", formula: "row count in RF_Contacts.xlsx, all satellites" },
      { metric: "Summed / max simultaneous observation", meaning: "Same basis as K6/Coverage — total and peak concurrent observing satellites, which sets the pipeline's input load.", formula: "Σ per-satellite observation time; max(concurrent observing count)" },
      { metric: "Analysis duration", meaning: "The full simulated window this whole pipeline view is measured over.", formula: "max(Timestamp) − min(Timestamp), shared grid" },
    ],
    render: (data) => (
      <>
        <div className="kpiGrid four">
          <KpiCard index={0} icon={Send} label="Downlink windows" value={data.tables.rf.length} detail="RF packages to GSN, fleet-wide" accent={SUBSYS.GSN.color} />
          <KpiCard index={1} icon={Activity} label="Summed observation" value={data.coverage.observation.overall["Summed Satellite Observation Time"] || "NA"} detail={`total effort-time across all ${data.constellation.configuredSatellites} satellites`} accent={SUBSYS.GSN.color} />
          <KpiCard index={2} icon={Satellite} label="Max simultaneous" value={data.coverage.observation.overall["Maximum Simultaneous Observing Satellites"] || 0} detail={`of ${data.constellation.configuredSatellites}, parallel acquisition`} accent={SUBSYS.GSN.color} />
          <KpiCard index={3} icon={Gauge} label="Analysis duration" value={data.coverage.observation.overall["Simulation Analysis Duration"] || "NA"} detail="shared pipeline window, all satellites" accent={SUBSYS.GSN.color} />
        </div>
        <Panel
          index={4}
          title="Observation Windows"
          sub="Per-satellite observation cycles feeding the downlink pipeline"
          className="wide"
          action={
            <PdfButton mission={data.mission} title="Observation Windows" subtitle="Per-satellite observation cycles feeding the downlink pipeline" columns={[
              { key: "satellite", label: "Satellite" },
              { key: "Total Observation Time", label: "Observed" },
              { key: "Observation Windows", label: "Windows" },
              { key: "Average Window", label: "Avg window" },
              { key: "Longest Window", label: "Longest" },
            ]} rows={data.coverage.observation.perSatellite} fileName="observation_windows" section="k9" />
          }
        >
          <DataTable
            rows={data.coverage.observation.perSatellite.slice(0, 24)}
            columns={[
              { key: "satellite", label: "Satellite" },
              { key: "Total Observation Time", label: "Observed" },
              { key: "Observation Windows", label: "Windows" },
              { key: "Average Window", label: "Avg window" },
              { key: "Longest Window", label: "Longest" },
            ]}
          />
        </Panel>
      </>
    ),
  },
  k10: {
    requirement:
      "Orbital management of each craft's path and any corrections are uploaded to the 48 crafts for critical orbit control. This view tracks orbit stability — altitude envelope and eccentricity per craft.",
    methods: [
      { metric: "Mean Instantaneous Geodetic Altitude / eccentricity", meaning: "Averaged across all satellites at the latest shared epoch — deviation from the Nominal Orbit Altitude (536 km), near-circular orbit signals a needed correction.", formula: "mean(Altitude), mean(ECC) at max(Timestamp)" },
      { metric: "Instantaneous Geodetic Altitude envelope", meaning: "Min / mean / max Instantaneous Geodetic Altitude per satellite across the whole window — a wide spread indicates orbit decay or drift needing an uplinked correction.", formula: "min / mean / max(Altitude) per satellite, from Satellite_State_History.xlsx" },
      { metric: "Uplink windows", meaning: "RF passes available to deliver orbit-correction commands to each craft.", formula: "row count in RF_Contacts.xlsx" },
    ],
    render: (data, state) => (
      <>
        <div className="kpiGrid four">
          <KpiCard index={0} icon={Orbit} label="Mean Instantaneous Altitude" value={Number(data.metrics.meanAltitude)} format={(v) => `${number(v, 2)} km`} detail={`fleet average, ${data.constellation.configuredSatellites} satellites, latest epoch, vs ${number(data.constellation.altitudeKm, 0)} km nominal`} accent={SUBSYS.Upload.color} infoKey="instantaneous_geodetic_altitude" />
          <KpiCard index={1} icon={Activity} label="Mean eccentricity" value={data.metrics.meanEccentricity} format={(v) => number(v, 6)} detail="fleet average, near-circular target = 0" accent={SUBSYS.Upload.color} />
          <KpiCard index={2} icon={Satellite} label="Crafts managed" value={data.constellation.configuredSatellites} detail="receiving orbit-control uploads" accent={SUBSYS.Upload.color} />
          <KpiCard index={3} icon={Upload} label="Uplink windows" value={data.tables.rf.length} detail="RF passes available for correction upload" accent={SUBSYS.Upload.color} />
        </div>
        <Panel index={4} title="Instantaneous Geodetic Altitude Envelope" sub="Min / mean / max per satellite — deviation from the Nominal Orbit Altitude flags corrections" className="wide">
          <AltitudeChart rows={data.charts.altitudeBands} />
        </Panel>
        {state ? (
          <Panel index={5} title="Mean Eccentricity per Satellite" sub="Orbit circularity — larger values need management uploads" className="wide">
            {data.metrics.meanEccentricity === null ? (
              <div className="emptyState">
                Not available — this mission's own Satellite_State_History.xlsx has no ECC column
                (asc074_6x8's does). Not shown as zero, since that would claim a perfectly circular
                orbit was measured when nothing was.
              </div>
            ) : (
              <SimpleBar rows={[...state.summary].sort((a, b) => b.meanEccentricity - a.meanEccentricity).slice(0, 24).map((r) => ({ satellite: shortSat(r.satellite, "S"), ecc: r.meanEccentricity }))} x="satellite" y="ecc" color={SUBSYS.Upload.color} format={(v) => number(v, 6)} />
            )}
          </Panel>
        ) : null}
      </>
    ),
  },
};

function KView({ id, data, state }) {
  const def = K_BY_ID[id];
  const content = K_CONTENT[id];
  const satCount = data?.constellation?.configuredSatellites;
  const requirement = swap48(content.requirement, satCount);
  const methods = swap48Methods(content.methods, satCount);
  return (
    <div className="contentGrid">
      <KHero def={def} requirement={requirement} index={0} />
      {content.render(data, state)}
      <MethodNote items={methods} />
    </div>
  );
}

/* ------------------------------ welcome -------------------------------- */

/* First screen on a fresh page load (no URL hash yet). An about page plus
   the mission picker, ahead of the sidebar/dashboard shell. Picking a
   locked mission reuses the exact same server-verified code gate as the
   header's mission switcher (see Header.pick/submitMissionCode below) --
   two independent gates that could drift apart would be worse than one
   shared pattern. */
function WelcomeScreen({ missions, setMissionId, onEnter }) {
  const { isMissionUnlocked, unlockMission, unlock } = useAccess();
  // Display order only: the smaller ASC_074 configuration (3x1) reads first
  // in the top row, larger (6x8) second. Every other card -- the ASC_080
  // row included -- keeps its existing position; this only ever swaps
  // those two specific cards with each other, never reorders anything else.
  const displayMissions = React.useMemo(() => {
    const arr = [...missions];
    const i6x8 = arr.findIndex((m) => m.id === "asc074_6x8");
    const i3x1 = arr.findIndex((m) => m.id === "asc074_3x1");
    if (i6x8 !== -1 && i3x1 !== -1) {
      [arr[i6x8], arr[i3x1]] = [arr[i3x1], arr[i6x8]];
    }
    return arr;
  }, [missions]);
  const [pendingMission, setPendingMission] = React.useState(null);
  const [code, setCode] = React.useState("");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  /* Picking a mission never enters the dashboard directly -- it first asks
     which access level to enter with. Supreme is the same master code
     FullAccessBox already uses (unlock("*", code)); Standard is exactly
     today's default -- in with nothing pre-unlocked, each section gated
     individually. A mission that also carries its own mission-level code
     (see missionCodes in access_control.py) resolves that gate first,
     same as it always has, then still asks the access-level question. */
  const [accessChoice, setAccessChoice] = React.useState(null);
  const [supremeGate, setSupremeGate] = React.useState(false);
  const [supremeCode, setSupremeCode] = React.useState("");
  const [supremeError, setSupremeError] = React.useState("");
  const [supremeBusy, setSupremeBusy] = React.useState(false);

  const pick = (id) => {
    if (isMissionUnlocked(id)) {
      setMissionId(id);
      setAccessChoice(id);
      return;
    }
    setPendingMission(id);
    setCode("");
    setError("");
  };

  const cancelPending = () => {
    setPendingMission(null);
    setCode("");
    setError("");
  };

  const submitMissionCode = async (e) => {
    e.preventDefault();
    if (!code.trim() || busy) return;
    setBusy(true);
    setError("");
    const res = await unlockMission(pendingMission, code.trim());
    setBusy(false);
    if (res.ok) {
      setMissionId(pendingMission);
      setAccessChoice(pendingMission);
      setPendingMission(null);
      setCode("");
    } else {
      setError(res.error || "Incorrect access code");
    }
  };

  const cancelAccessChoice = () => {
    setAccessChoice(null);
    setSupremeGate(false);
    setSupremeCode("");
    setSupremeError("");
  };

  const submitSupreme = async (e) => {
    e.preventDefault();
    if (!supremeCode.trim() || supremeBusy) return;
    setSupremeBusy(true);
    setSupremeError("");
    const res = await unlock("*", supremeCode.trim());
    setSupremeBusy(false);
    if (res.ok) {
      onEnter();
    } else {
      setSupremeError(res.error || "Incorrect access code");
    }
  };

  const accessChoiceMission = missions.find((m) => m.id === accessChoice);

  return (
    <>
      <div className="welcomeRoot">
        <Backdrop />
        <ConstellationField />
        <main className="welcomeScreen">
        <header className="welcomeHero reveal" style={{ "--i": 0 }}>
          <img className="welcomeLogo" src={logoUrl} alt="ANSUMI SPACE" />
          <p className="welcomeWordmark">
            ANSUMI SPACE <span>ORBITAL HUB</span>
          </p>
          <p className="welcomeTagline">Mission Operations &amp; Constellation Analysis</p>
          <p className="welcomeLede">
            Converts real orbital telemetry into mission-level operational insight — constellation
            state, ground-contact windows, coverage and payload duty cycle — for the ASC_074 Earth
            observation constellation. Select a configuration to open its live dashboard.
          </p>
        </header>

        <div className="welcomeMissions">
          {missions.length === 0 ? (
            <p className="welcomeMissionsEmpty">Loading missions…</p>
          ) : (
            displayMissions.map((m, i) => {
              const unlocked = isMissionUnlocked(m.id);
              return (
                <button
                  key={m.id}
                  className="missionProfileCard reveal"
                  style={{ "--i": i + 1 }}
                  onClick={() => pick(m.id)}
                >
                  <div className="mpHead">
                    <div>
                      <span className="mpEyebrow">{m.missionType || "Mission"} · Mission Profile</span>
                      <h3 className="mpName">{m.missionName || "Mission"}</h3>
                    </div>
                    <span className={`mpStatus ${unlocked ? "ready" : "locked"}`}>
                      <i />
                      {unlocked ? "READY" : "CODE REQUIRED"}
                    </span>
                  </div>

                  <p className="mpConfig">
                    {m.planes} × {m.satellitesPerPlane} <span>CONSTELLATION</span>
                  </p>

                  <div className="mpKpiRow">
                    <div className="mpKpi">
                      <strong>{m.totalSatellites ?? "—"}</strong>
                      <span>Total Spacecraft</span>
                    </div>
                    <div className="mpKpi">
                      <strong>{m.planes ?? "—"}</strong>
                      <span>Orbital Planes</span>
                    </div>
                    <div className="mpKpi">
                      <strong>{m.satellitesPerPlane ?? "—"}</strong>
                      <span>Satellites / Plane</span>
                    </div>
                  </div>

                  <div className="mpSpecRow">
                    <div>
                      <span>Altitude</span>
                      <strong>{m.altitudeKm != null ? `${m.altitudeKm} km` : "—"}</strong>
                    </div>
                    <div>
                      <span>Inclination</span>
                      <strong>{m.inclinationDeg != null ? `${m.inclinationDeg}°` : "—"}</strong>
                    </div>
                    <div>
                      <span>Ground Region</span>
                      <strong>{(m.areaOfInterest || "—").split(",").pop().trim()}</strong>
                    </div>
                  </div>

                  <span className="mpCta">
                    Open Mission <span aria-hidden="true">→</span>
                  </span>
                </button>
              );
            })
          )}
        </div>
        </main>
      </div>

      {pendingMission ? (
        <div className="missionGateOverlay" onClick={cancelPending}>
          <form className="missionGatePanel" onClick={(e) => e.stopPropagation()} onSubmit={submitMissionCode}>
            <div className="gateIcon">
              <Lock size={22} />
            </div>
            <p className="gateEyebrow">Restricted mission</p>
            <h3>{missions.find((m) => m.id === pendingMission)?.label || pendingMission}</h3>
            <p className="gateSub">
              Opening this mission needs its own access code, separate from any section codes
              already unlocked. Nothing for this mission has been requested from the server yet.
            </p>
            <label className="gateField">
              <KeyRound size={15} />
              <input
                type="text"
                value={code}
                autoComplete="off"
                spellCheck="false"
                placeholder="Enter mission access code"
                onChange={(e) => setCode(e.target.value)}
                autoFocus
              />
            </label>
            <div className="missionGateActions">
              <button type="button" className="btn ghost" onClick={cancelPending}>Cancel</button>
              <button className="btn primary" type="submit" disabled={busy || !code.trim()}>
                <ShieldCheck size={15} /> {busy ? "Checking…" : "Open mission"}
              </button>
            </div>
            {error ? <p className="gateError">{error}</p> : null}
          </form>
        </div>
      ) : null}

      {accessChoice && !supremeGate ? (
        <div className="missionGateOverlay" onClick={cancelAccessChoice}>
          <div className="missionGatePanel" onClick={(e) => e.stopPropagation()}>
            <div className="gateIcon">
              <ShieldCheck size={22} />
            </div>
            <p className="gateEyebrow">Choose access level</p>
            <h3>{accessChoiceMission?.label || accessChoice}</h3>
            <p className="gateSub">
              Supreme Access opens every section immediately with one developer/reviewer code.
              Standard Access opens the mission with nothing unlocked yet — you enter each
              section's own code individually, as you need it.
            </p>
            <div className="accessLevelChoice">
              <button type="button" className="accessLevelBtn" onClick={() => setSupremeGate(true)}>
                <ShieldCheck size={18} />
                <span className="accessLevelBtnText">
                  <span className="accessLevelBtnLabel">Supreme Access</span>
                  <span className="accessLevelBtnSub">Developer / reviewer code — unlocks every section</span>
                </span>
              </button>
              <button type="button" className="accessLevelBtn" onClick={onEnter}>
                <Unlock size={18} />
                <span className="accessLevelBtnText">
                  <span className="accessLevelBtnLabel">Standard Access</span>
                  <span className="accessLevelBtnSub">No code to enter — unlock each section as you go</span>
                </span>
              </button>
            </div>
            <button type="button" className="btn ghost" onClick={cancelAccessChoice}>Back</button>
          </div>
        </div>
      ) : null}

      {accessChoice && supremeGate ? (
        <div className="missionGateOverlay" onClick={cancelAccessChoice}>
          <form className="missionGatePanel" onClick={(e) => e.stopPropagation()} onSubmit={submitSupreme}>
            <div className="gateIcon">
              <KeyRound size={22} />
            </div>
            <p className="gateEyebrow">Supreme access</p>
            <h3>Developer / reviewer code</h3>
            <p className="gateSub">
              The same full-access code as the dashboard's "Developer / reviewer access" box —
              unlocks every section in this mission at once.
            </p>
            <label className="gateField">
              <KeyRound size={15} />
              <input
                type="text"
                value={supremeCode}
                autoComplete="off"
                spellCheck="false"
                placeholder="Full-access code"
                onChange={(e) => setSupremeCode(e.target.value)}
                autoFocus
              />
            </label>
            <div className="missionGateActions">
              <button type="button" className="btn ghost" onClick={() => setSupremeGate(false)}>Back</button>
              <button className="btn primary" type="submit" disabled={supremeBusy || !supremeCode.trim()}>
                <ShieldCheck size={15} /> {supremeBusy ? "Checking…" : "Unlock all & enter"}
              </button>
            </div>
            {supremeError ? <p className="gateError">{supremeError}</p> : null}
          </form>
        </div>
      ) : null}
    </>
  );
}

/* ----------------------------- app shell ------------------------------ */

function Dashboard() {
  const [active, setActive] = React.useState(() => (typeof window !== "undefined" && window.location.hash.slice(1)) || "overview");
  /* Every fresh browser tab opens on the welcome/about screen first, before
     the dashboard. This used to key off the URL hash, but Chrome (and most
     browsers) restore the last hash you had in that tab on reload/reopen,
     so a returning visitor's address bar almost always already has one --
     the welcome screen would then never show. sessionStorage instead: it
     is empty for a genuinely new tab regardless of what the address bar
     remembers. The stored value always mirrors the CURRENT screen (kept in
     sync below), not just "has this tab ever entered a mission" -- that
     distinction matters because pressing the sidebar's Home button comes
     back to this same screen, and a reload right after must land here
     again too, not jump back into the dashboard from a stale flag. */
  const [showWelcome, setShowWelcome] = React.useState(
    () => typeof window !== "undefined" && window.sessionStorage.getItem("welcomeSeen") !== "1"
  );
  React.useEffect(() => {
    if (typeof window !== "undefined") {
      window.sessionStorage.setItem("welcomeSeen", showWelcome ? "0" : "1");
    }
  }, [showWelcome]);
  const { missions, defaultMission } = useMissions();
  const [missionId, setMissionId] = React.useState(
    () => (typeof window !== "undefined" && window.localStorage.getItem("missionId")) || "asc074_6x8"
  );
  React.useEffect(() => {
    if (typeof window !== "undefined") window.localStorage.setItem("missionId", missionId);
  }, [missionId]);
  React.useEffect(() => {
    if (!missionId && defaultMission) setMissionId(defaultMission);
  }, [defaultMission]); // eslint-disable-line react-hooks/exhaustive-deps

  const { data, state, loading, error, refreshing, refresh, retry } = useDashboard(missionId);
  const glossaryMap = useGlossaryMapFetch();
  // Also fetched separately inside DataView's own FullReportPanel -- this
  // duplicate is intentional and cheap (a small, fast endpoint) rather than
  // lifting that state, so the top-of-dashboard report launcher (which
  // renders in the Header, outside DataView) has its own quality data
  // regardless of which section is currently open.
  const quality = useDataQuality(missionId);

  React.useEffect(() => {
    const onHash = () => setActive(window.location.hash.slice(1) || "overview");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  React.useEffect(() => {
    if (window.location.hash.slice(1) !== active) window.location.hash = active;
  }, [active]);

  if (showWelcome) {
    return (
      <WelcomeScreen
        missions={missions}
        setMissionId={setMissionId}
        onEnter={() => setShowWelcome(false)}
      />
    );
  }

  if (loading && !data) {
    return (
      <>
        <Backdrop />
        <main className="loadingScreen">
          <div className="loaderRing" />
          <span>Establishing telemetry link…</span>
        </main>
      </>
    );
  }

  if (error && !data) {
    /* "Failed to fetch" almost always means the API process is not up (or was
       restarted while this tab was open). Previously this screen was a dead
       end that could only be escaped by reloading the page by hand, so it
       offers a retry and says what to check. */
    const offline = /failed to fetch|networkerror|load failed/i.test(error);
    return (
      <>
        <Backdrop />
        <main className="loadingScreen error">
          <ShieldCheck size={30} />
          <span>{offline ? "Cannot reach the mission API" : error}</span>
          {offline ? (
            <p className="loadingHint">
              The dashboard could not contact <code>{API_BASE}</code>. Start the backend with{" "}
              <code>python api.py</code> and retry — nothing is lost, this tab just needs to
              reconnect.
            </p>
          ) : null}
          <button className="btn primary" onClick={retry} disabled={loading}>
            <RefreshCw size={15} className={loading ? "spin" : ""} />
            {loading ? "Reconnecting…" : "Retry"}
          </button>
        </main>
      </>
    );
  }

  /* Unlocking a section flips the gate open immediately, but the dashboard
     payload in hand was fetched before the token widened and is still
     missing that section's keys. The payload reports which sections it was
     built for, so hold the view until a refetch reflecting this section
     lands -- otherwise a view renders against data it expects to exist. */
  const sectionDataReady =
    Array.isArray(data?.unlockedSections) && data.unlockedSections.includes(active);

  let view;
  if (active === "overview") view = <Overview data={data} state={state} />;
  else if (active === "explorer") view = <StateExplorer state={state} mission={data.mission} stateLoading={loading} coverage={data.coverage} />;
  else if (active === "coverage") view = <CoverageView data={data} />;
  else if (active === "imaging") view = <PayloadImagingView data={data} state={state} />;
  else if (active === "global") view = <GlobalCoverageView data={data} state={state} />;
  else if (active === "data") view = <DataView data={data} missionId={missionId} missions={missions} glossaryMap={glossaryMap} />;
  else if (active === "ic-catalog") view = <ImageCatalogView missionId={missionId} />;
  else if (active === "ic-gallery") view = <ImageGalleryView missionId={missionId} />;
  else if (active === "ic-location") view = <GlobalLocationExplorer />;
  else if (active === "summary") view = <ConstellationSummaryView data={data} />;
  else if (active === "revisit") view = <RevisitAnalyticsView data={data} />;
  else if (active === "gap-analysis") view = <CoverageGapView data={data} />;
  else if (active === "ground-stations") view = <GroundStationAnalysisView data={data} />;
  else if (active === "sat-contribution") view = <SatContributionView data={data} missionId={missionId} apiBase={API_BASE} />;
  else if (active === "heatmaps") view = <DensityHeatmapsView data={data} />;
  else if (active === "aoi-analytics") view = <AoiAnalyticsView data={data} />;
  else if (active === "sim-details") view = <SimulationDetailsView data={data} />;
  else if (active === "constellation-anim") view = <ConstellationAnimationView data={data} state={state} />;
  else if (active === "mission-analytics") view = <MissionAnalyticsView data={data} />;
  else if (active === "comparison") view = <MissionComparisonView missions={missions} currentMissionId={missionId} apiBase={API_BASE} />;
  else if (active === "guide") view = <DashboardGuideView glossaryMap={glossaryMap} />;
  else if (K_BY_ID[active]) view = <KView id={active} data={data} state={state} />;
  // No silent fallback to Overview: an unrecognised hash must not become a
  // way around the gate. AccessGate reports the unknown section instead.
  else view = null;

  return (
    <GlossaryContext.Provider value={glossaryMap}>
      <Backdrop />
      <div className="appShell">
        <Sidebar active={active} setActive={setActive} onHome={() => setShowWelcome(true)} />
        <main className="main">
          <Header
            data={data}
            refresh={refresh}
            refreshing={refreshing}
            missions={missions}
            missionId={missionId}
            setMissionId={setMissionId}
            glossaryMap={glossaryMap}
            quality={quality}
          />
          <Ticker data={data} />
          {error ? <div className="bannerError">{error}</div> : null}
          <div key={`${missionId}:${active}`}>
            <AccessGate section={active}>
              {sectionDataReady ? view : (
                <div className="contentGrid">
                  <Panel index={0} title="Loading section data…" sub="Fetching the data this section was just granted." className="wide">
                    <div className="emptyState">Unlocked — retrieving this section's data from the server.</div>
                  </Panel>
                </div>
              )}
            </AccessGate>
          </div>
        </main>
      </div>
    </GlossaryContext.Provider>
  );
}

createRoot(document.getElementById("root")).render(
  <AccessProvider apiBase={API_BASE}>
    <Dashboard />
  </AccessProvider>
);
