import React from "react";
import { createRoot } from "react-dom/client";
import jsPDF from "jspdf";
import autoTable from "jspdf-autotable";
import { feature } from "topojson-client";
import worldTopo from "world-atlas/land-110m.json";
import logoUrl from "../logo.jpeg";
/* Mission Image Center (v1.1) — additive module, no existing view changed. */
import { ImageCatalogView, ImageGalleryView } from "./imageCenter.jsx";
import {
  Activity,
  Antenna,
  Aperture,
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
  LayoutDashboard,
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

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:5001";

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
const asMinutes = (v) => `${number(v, 1)} min`;
const asHours = (v) => `${number(v, 2)} h`;
const asPct = (v) => `${number(v, 1)}%`;

function dateLabel(value) {
  if (!value) return "NA";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "NA";
  return new Intl.DateTimeFormat(undefined, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
function timeLabel(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(date);
}
const hueFor = (index) => `hsl(${(index * 47) % 360} 82% 62%)`;

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
          ring.forEach((pt, i) => {
            d += `${i === 0 ? "M" : "L"}${projX(pt[0]).toFixed(1)} ${projY(pt[1]).toFixed(1)}`;
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

const AOI_BOX = { lonMin: 110, lonMax: 160, latMin: -40, latMax: -10 };

/* Shared map base: ocean, graticule, land silhouette, AOI box */
function MapBase({ showAoi = true }) {
  const lonLines = [-150, -120, -90, -60, -30, 0, 30, 60, 90, 120, 150];
  const latLines = [-60, -30, 0, 30, 60];
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
        <rect
          x={projX(AOI_BOX.lonMin)}
          y={projY(AOI_BOX.latMax)}
          width={projX(AOI_BOX.lonMax) - projX(AOI_BOX.lonMin)}
          height={projY(AOI_BOX.latMin) - projY(AOI_BOX.latMax)}
          className="aoiRect"
        />
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
  const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getMonth()];
  return `${p(d.getDate())} ${mon} ${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function ConstellationSim({ series = {}, satellites = [], range, height = 520, defaultWindowMs = 60 * 60000 }) {
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
    (o) => o.head.lon >= AOI_BOX.lonMin && o.head.lon <= AOI_BOX.lonMax && o.head.lat >= AOI_BOX.latMin && o.head.lat <= AOI_BOX.latMax
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
          <MapBase />
          {sats.map((o) => (
            <path key={o.name} d={trail(o.pts)} fill="none" stroke={o.color} strokeWidth="1.1" strokeOpacity="0.85" strokeLinejoin="round" />
          ))}
          {heads.map((o) => {
            const x = projX(o.head.lon);
            const y = projY(o.head.lat);
            const inAoi = o.head.lon >= AOI_BOX.lonMin && o.head.lon <= AOI_BOX.lonMax && o.head.lat >= AOI_BOX.latMin && o.head.lat <= AOI_BOX.latMax;
            return (
              <g key={`h${o.name}`} transform={`translate(${x.toFixed(1)} ${y.toFixed(1)})`}>
                <circle r="4.5" fill={o.color} opacity="0.28" />
                <circle r="2.1" fill="#fff" stroke={o.color} strokeWidth="1.1" />
                {inAoi ? <text x="6" y="3" className="satTag" fill={o.color}>{o.name.replace("ASC_074_", "")}</text> : null}
                <title>{`${o.name} · ${number(o.head.lat, 2)}°, ${number(o.head.lon, 2)}°`}</title>
              </g>
            );
          })}
        </svg>
        <div className="simEpoch mono">Epoch: {fmtEpoch(now)}</div>
        <div className="mapLegend">
          <span><i className="dot blue" /> {sats.length} satellites</span>
          <span><i className="legLine" /> ground tracks</span>
          <span><i className="aoiSwatch" /> AOI (Australia)</span>
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

function useDashboard() {
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
        fetch(`${API_BASE}/api/dashboard`),
        fetch(`${API_BASE}/api/state`),
      ]);
      if (!dRes.ok) throw new Error(`API returned ${dRes.status}`);
      setData(await dRes.json());
      if (sRes.ok) setState(await sRes.json());
    } catch (err) {
      setError(err.message || "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }, []);

  const refresh = React.useCallback(async () => {
    setRefreshing(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/refresh`, { method: "POST" });
      if (!response.ok) throw new Error(`Refresh failed with ${response.status}`);
      await load();
    } catch (err) {
      setError(err.message || "Failed to refresh data");
    } finally {
      setRefreshing(false);
    }
  }, [load]);

  React.useEffect(() => {
    load();
  }, [load]);

  return { data, state, loading, error, refreshing, refresh };
}

/* ------------------------------ chrome -------------------------------- */

function Backdrop() {
  return (
    <>
      <div className="spaceBg" />
      <div className="gridOverlay" />
    </>
  );
}

/* nav model — Mission group + two duty-cycle phases (K1–K10) */
const K_DEFS = [
  { id: "k1", k: "K1", name: "Constellation Transit", subsystem: "Orbit", phase: 1 },
  { id: "k2", k: "K2", name: "Sensor Power Gating", subsystem: "Power", phase: 1 },
  { id: "k3", k: "K3", name: "Store & Downlink", subsystem: "Data", phase: 1 },
  { id: "k4", k: "K4", name: "Brisbane Downlink", subsystem: "GSN", phase: 1 },
  { id: "k5", k: "K5", name: "Command Uplink", subsystem: "Upload", phase: 1 },
  { id: "k6", k: "K6", name: "AOI Active Coverage", subsystem: "Orbit", phase: 2 },
  { id: "k7", k: "K7", name: "Power Duty Budget", subsystem: "Power", phase: 2 },
  { id: "k8", k: "K8", name: "Onboard Processing", subsystem: "Data", phase: 2 },
  { id: "k9", k: "K9", name: "Downlink Pipeline", subsystem: "GSN", phase: 2 },
  { id: "k10", k: "K10", name: "Orbit Management", subsystem: "Upload", phase: 2 },
];
const K_BY_ID = Object.fromEntries(K_DEFS.map((d) => [d.id, d]));

function Sidebar({ active, setActive }) {
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
  ];
  const phase1 = K_DEFS.filter((d) => d.phase === 1);
  const phase2 = K_DEFS.filter((d) => d.phase === 2);

  const KItem = (d) => {
    const sub = SUBSYS[d.subsystem];
    const Icon = sub.icon;
    return (
      <button
        key={d.id}
        className={active === d.id ? "navItem navK active" : "navItem navK"}
        onClick={() => setActive(d.id)}
        title={`${d.k} · ${d.name} (${d.subsystem})`}
        style={{ "--sub": sub.color }}
      >
        <span className="kBadge">
          <Icon size={15} />
          <i className="kNum">{d.k.replace("K", "")}</i>
        </span>
        <span className="kName">{d.name}</span>
        <i className="kDot" />
      </button>
    );
  };

  return (
    <aside className="sidebar">
      <div className="brand">
        <img className="brandLogo" src={logoUrl} alt="ANSUMI SPACE" />
        <span className="brandSub">Mission Operations Center · ASC-074</span>
      </div>

      <nav className="nav">
        <div className="navGroup">
          <p className="navGroupLabel">Mission</p>
          {mission.map(([id, Icon, label]) => (
            <button
              key={id}
              className={active === id ? "navItem active" : "navItem"}
              onClick={() => setActive(id)}
              title={label}
            >
              <Icon size={18} />
              <span>{label}</span>
            </button>
          ))}
        </div>

        <div className="navGroup">
          <p className="navGroupLabel">Mission Image Center</p>
          {imageCenter.map(([id, Icon, label]) => (
            <button
              key={id}
              className={active === id ? "navItem active" : "navItem"}
              onClick={() => setActive(id)}
              title={label}
            >
              <Icon size={18} />
              <span>{label}</span>
            </button>
          ))}
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

      <div className="sidebarStatus">
        <ShieldCheck size={18} />
        <div>
          <strong>GMAT ingest</strong>
          <span>Processed data online</span>
        </div>
      </div>
    </aside>
  );
}

function Header({ data, refresh, refreshing }) {
  return (
    <header className="topbar">
      <div>
        <p className="eyebrow">Configuration-driven orbital analytics</p>
        <h1>{data?.mission?.name || "Mission Operations Center"}</h1>
      </div>
      <div className="topbarActions">
        <span className="livePill">
          <i />
          LIVE
        </span>
        <div className="epoch">
          <span>Latest epoch</span>
          <strong className="mono">{dateLabel(data?.mission?.latestEpoch)}</strong>
        </div>
        <button className="iconButton" onClick={refresh} disabled={refreshing} title="Refresh GMAT data">
          <RefreshCw size={18} className={refreshing ? "spin" : ""} />
        </button>
      </div>
    </header>
  );
}

function Ticker({ data }) {
  const m = data.metrics;
  const c = data.constellation;
  const items = [
    ["FLEET", `${number(c.configuredSatellites)} sats`],
    ["ALT", `${number(c.altitudeKm)} km`],
    ["INC", `${number(c.inclinationDeg, 1)}°`],
    ["RF", `${number(m.rfEvents)} contacts`],
    ["OPTICAL", `${number(m.opticalEvents)} contacts`],
    ["ECLIPSE", `${number(m.eclipseEvents)} events`],
    ["STATE", `${compact(m.stateRows)} samples`],
    ["COVERAGE", `${number(data.coverage.percent, 2)}%`],
    ["AOI", "110°E–160°E · 10°S–40°S"],
  ];
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

function KpiCard({ icon: Icon, label, value, format, detail, accent = COLORS.blue, index = 0 }) {
  const isNumeric = typeof value === "number" && Number.isFinite(value);
  return (
    <section className="kpi reveal" style={{ "--accent": accent, "--i": index }}>
      <div className="kpiTop">
        <span>{label}</span>
        <span className="kpiIcon">
          <Icon size={17} />
        </span>
      </div>
      <strong>{isNumeric ? <Counter value={value} format={format} /> : value}</strong>
      <p>{detail}</p>
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
    ["Constellation", `${cfg.planes} x ${cfg.satellitesPerPlane}`],
    ["Altitude", `${number(cfg.altitudeKm, 0)} km`],
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

function WorldOrbitMap({ positions = [], tracks = [], maxTracks = 48 }) {
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
        <MapBase />
        {grouped.map(([sat, points], gi) => {
          const path = points
            .map((point, idx) => {
              const pos = project(point.lat, point.lon);
              return `${idx === 0 ? "M" : "L"}${pos.x.toFixed(1)} ${pos.y.toFixed(1)}`;
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

/* Coverage map — real Australia polygon, cells share the exact projection */
function AustraliaCoverageMap({ cells = [], outline = [], tasmania = [], aoi, percent }) {
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
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Australia coverage cells">
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
              AOI 110°E–160°E · 10°S–40°S
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
              <th key={col.key}>{col.label}</th>
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

function PdfButton({ mission, title, subtitle, columns, rows, fileName, label = "Export PDF" }) {
  return (
    <button className="btn primary" onClick={() => exportRowsPdf({ mission, title, subtitle, columns, rows, fileName })}>
      <Download size={15} /> {label}
    </button>
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
            {sat.replace("ASC_074_", "")}
          </button>
        ))}
      </div>
    </div>
  );
}

function useSatSelection(satellites, initialCount = null) {
  const [selected, setSelected] = React.useState([]);
  React.useEffect(() => {
    if (satellites.length && selected.length === 0) {
      setSelected(initialCount ? satellites.slice(0, initialCount) : [...satellites]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [satellites.length]);
  const toggle = (sat) => setSelected((cur) => (cur.includes(sat) ? cur.filter((s) => s !== sat) : [...cur, sat]));
  const selectAll = () => setSelected((cur) => (cur.length === satellites.length ? [] : [...satellites]));
  return [selected, toggle, selectAll];
}

/* -------------------------------- views ------------------------------- */

const OVERVIEW_METHODS = [
  { metric: "Configured fleet", meaning: "Satellites defined in Mission_Configuration.xlsx, compared against satellites actually seen in the processed GMAT files.", formula: "configured = planes × satellites/plane; detected = distinct satellites across RF/Optical/Eclipse/State files" },
  { metric: "RF / Optical contacts", meaning: "One row per continuous line-of-sight contact between a satellite and a ground station, across the full 48-satellite fleet.", formula: "events = row count in RF_Contacts.xlsx / Optical_Contacts.xlsx; minutes = Σ Duration(s) ÷ 60" },
  { metric: "Eclipse events", meaning: "One row per Sun-blocked interval (umbra or penumbra) for any satellite.", formula: "hours = Σ Duration(s) ÷ 3600, from All_Eclipse_Events.xlsx" },
  { metric: "Data coverage", meaning: "How much of the 48-satellite fleet has usable telemetry in the processed state file.", formula: "detected satellites ÷ configured satellites × 100" },
];

function Overview({ data, state }) {
  const m = data.metrics;
  const c = data.constellation;
  return (
    <div className="contentGrid">
      <MissionStrip data={data} />
      <div className="kpiGrid">
        <KpiCard index={0} icon={Satellite} label="Configured fleet" value={c.configuredSatellites} detail={`${number(c.detectedSatellites)} of ${number(c.configuredSatellites)} satellites detected in data`} accent={COLORS.blue} />
        <KpiCard index={1} icon={Antenna} label="RF contacts" value={m.rfEvents} detail={`${asMinutes(m.rfMinutes)} across the fleet`} accent={COLORS.cyan} />
        <KpiCard index={2} icon={Zap} label="Optical contacts" value={m.opticalEvents} detail={`${asMinutes(m.opticalMinutes)} across the fleet`} accent={COLORS.green} />
        <KpiCard index={3} icon={SunMedium} label="Eclipse events" value={m.eclipseEvents} detail={`${asHours(m.eclipseHours)} across the fleet`} accent={COLORS.amber} />
        <KpiCard index={4} icon={Gauge} label="Data coverage" value={m.fleetCoveragePercent} format={asPct} detail={`${compact(m.stateRows)} state samples, ${c.configuredSatellites} satellites`} accent={COLORS.red} />
      </div>
      <Panel index={5} title="Constellation Simulator" sub="Animated ground tracks over the analysis window · play, scrub and set the trail length" className="wide">
        {state ? (
          <ConstellationSim series={state.series} satellites={state.satellites} range={state.range} />
        ) : (
          <WorldOrbitMap positions={data.charts.latestPositions} tracks={data.charts.tracks} />
        )}
      </Panel>
      <Panel index={6} title="Events by Satellite" sub="RF, optical and eclipse events, per satellite">
        <EventMatrix rows={data.charts.eventMatrix} />
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
      <MethodNote items={OVERVIEW_METHODS} />
    </div>
  );
}

const COVERAGE_METHODS = [
  { metric: "Australia coverage %", meaning: "Australia is discretized into a 1° lat/lon grid over the mainland + Tasmania land boundary. A cell counts as covered if any of the 48 satellites' sub-points came within half the modeled ground swath of the cell center.", formula: "% = latitude-weighted covered cells ÷ total land cells × 100" },
  { metric: "All-sat observed", meaning: "Sum of each of the 48 satellites' own 'observing Australia' time. Overlapping satellites are each counted, so this can exceed the mission duration.", formula: "Σ (per-satellite Total Observation Seconds)" },
  { metric: "Max simultaneous", meaning: "The highest number of satellites (out of 48) flagged as observing Australia at the same shared timestamp.", formula: "max(count of satellites observing at time t)" },
  { metric: "Observation duty %", meaning: "Share of the whole analysis window where at least one of the 48 satellites was observing — this is the constellation's combined duty cycle.", formula: "Unique Constellation Observation Time ÷ Simulation Analysis Duration × 100" },
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
  const satellites = React.useMemo(() => coverage.observation.perSatellite.map((r) => r.satellite).sort(), [coverage.observation.perSatellite]);
  const [selected, toggle, selectAll] = useSatSelection(satellites);
  const filteredContribution = coverage.contribution.filter((r) => selected.includes(r.satellite));
  const filteredObs = coverage.observation.perSatellite.filter((r) => selected.includes(r.satellite));

  return (
    <div className="contentGrid">
      <div className="kpiGrid four">
        <KpiCard index={0} icon={Globe2} label="Australia coverage" value={coverage.percent} format={(v) => `${number(v, 2)}%`} detail={`${number(coverage.coveredCells)} of ${number(coverage.totalCells)} land cells, all 48 satellites`} accent={COLORS.cyan} />
        <KpiCard index={1} icon={Activity} label="All-sat observed" value={coverage.observation.overall["Summed Satellite Observation Time"] || "NA"} detail="combined effort-time summed across all 48 satellites" accent={COLORS.green} />
        <KpiCard index={2} icon={Satellite} label="Max simultaneous" value={coverage.observation.overall["Maximum Simultaneous Observing Satellites"] || 0} detail="of 48 satellites, observing at the same instant" accent={COLORS.blue} />
        <KpiCard index={3} icon={Gauge} label="Observation duty" value={Number(coverage.observation.overall["Overall Observation Duty Cycle (%)"]) || 0} format={(v) => `${number(v, 2)}%`} detail="constellation-wide timeline, ≥1 of 48 satellites" accent={COLORS.amber} />
      </div>
      <Panel index={4} title="Coverage Cell Map" sub="Analysis cells over the Australia land boundary, inside the mission AOI" className="wide">
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
            title="Australia Observation Duration"
            subtitle="Per-satellite observation windows over the Australia AOI"
            columns={COVERAGE_TABLE_COLUMNS}
            rows={filteredObs}
            fileName="observation_duration"
          />
        }
      >
        <DataTable rows={filteredObs.slice(0, 24)} columns={COVERAGE_TABLE_COLUMNS} />
      </Panel>
      <MethodNote items={COVERAGE_METHODS} />
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
  { metric: "Imaged distance", meaning: "How far along its ground track each satellite imaged while the sensor was ON (i.e. over the Australia AOI).", formula: "ground speed (km/s) × observed time over AOI (s)" },
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

function PayloadImagingView({ data }) {
  const camera = data.camera.model;
  const imaging = data.imaging;
  const satellites = React.useMemo(() => imaging.perSatellite.map((r) => r.satellite).sort(), [imaging.perSatellite]);
  const [selected, toggle, selectAll] = useSatSelection(satellites);
  const filtered = imaging.perSatellite.filter((r) => selected.includes(r.satellite));
  const chartRows = filtered
    .slice()
    .sort((a, b) => (b.estimatedScenes || 0) - (a.estimatedScenes || 0))
    .slice(0, 24)
    .map((r) => ({ ...r, satellite: r.satellite.replace("ASC_074_", "S") }));

  return (
    <div className="contentGrid">
      <div className="kpiGrid four">
        <KpiCard index={0} icon={Aperture} label="Ground swath" value={Number(camera["Ground Swath (km)"])} format={(v) => `${number(v, 2)} km`} detail={`${number(camera["GSD (m/pixel)"], 2)} m/pixel GSD · camera basis for all 48 satellites`} accent={COLORS.violet} />
        <KpiCard index={1} icon={Camera} label="Estimated scenes captured" value={Number(imaging.fleet.totalEstimatedScenes)} format={(v) => compact(v)} detail={`across ${imaging.fleet.satellitesWithImagery} of ${imaging.fleet.satelliteCount} satellites`} accent={COLORS.cyan} />
        <KpiCard index={2} icon={Activity} label="Imaged distance" value={Number(imaging.fleet.totalImagedDistanceKm)} format={(v) => `${compact(v)} km`} detail="combined along-track strip length, all satellites" accent={COLORS.green} />
        <KpiCard index={3} icon={Globe2} label="Imaged area (fleet-effort)" value={Number(imaging.fleet.totalImagedAreaKm2)} format={(v) => `${compact(v)} km²`} detail="summed per-satellite effort — overlaps counted, not a unique-area figure" accent={COLORS.amber} />
      </div>

      <NoticeBanner icon={Aperture} tone={COLORS.violet} title="What 'captured imagery' means here" index={4}>
        The onboard sensor is a pushbroom imager — it scans a continuous strip beneath the satellite rather than
        taking discrete photos. The figures above are an engineering estimate: how far and how much ground area
        each of the 48 satellites imaged while its sensor was powered ON over the Australia AOI, plus an equivalent
        "scene count" sized to the camera's own frame geometry. See the calculation notes below for the exact formulas.
      </NoticeBanner>

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
            subtitle="Estimated imaging distance, area and scene count per satellite over the Australia AOI"
            columns={IMAGING_TABLE_COLUMNS}
            rows={filtered}
            fileName="captured_imagery_report"
          />
        }
      >
        <DataTable rows={filtered} columns={IMAGING_TABLE_COLUMNS} />
      </Panel>

      <Panel index={7} title="Camera Configuration" sub="Mission payload model — shared across the fleet" className="wide">
        <DataTable
          rows={Object.entries(camera).map(([key, value]) => ({ key, value: Array.isArray(value) ? value.join(", ") : value }))}
          columns={[
            { key: "key", label: "Parameter" },
            { key: "value", label: "Value" },
          ]}
        />
      </Panel>

      <MethodNote items={IMAGING_METHODS} />
    </div>
  );
}

/* ---------------------------- Global Coverage ---------------------------- */

const GLOBAL_METHODS = [
  { metric: "Region classification", meaning: "Each state sample's sub-satellite Lat/Lon is bucketed into one of 14 coarse geographic regions using ordered bounding boxes — an engineering approximation for situational awareness, not authoritative GIS (same approach as the Australia land-boundary polygon).", formula: "first matching region wins, in priority order; unmatched points fall into 'Open Ocean / Transit'" },
  { metric: "Global reach (latitude span)", meaning: "The highest and lowest latitude any satellite's sub-point reached over the full analysis window — set by orbital inclination, not by AOI targeting.", formula: "min / max(Latitude) across all 48 satellites, all timestamps" },
  { metric: "AOI focus %", meaning: "Share of all fleet state samples (48 satellites × ~924 samples/day) whose sub-point falls inside the Australia AOI rectangle.", formula: "samples inside 110°E–160°E,10°S–40°S ÷ total fleet samples × 100" },
  { metric: "Global (non-AOI) share", meaning: "The complement — time the constellation spends over the rest of the globe. Sensors are capable of imaging here but are intentionally kept OFF to conserve power for the Australia mission (see K2 / K7).", formula: "100 − AOI focus %" },
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
            <Cell key={index} fill={row.region.startsWith("Australia") ? COLORS.cyan : hueFor(index + 3)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function GlobalCoverageView({ data, state }) {
  const global = data.globalCoverage;
  const satellites = React.useMemo(() => global.perSatellite.map((r) => r.satellite).sort(), [global.perSatellite]);
  const [selected, toggle, selectAll] = useSatSelection(satellites, 12);
  const filtered = global.perSatellite.filter((r) => selected.includes(r.satellite));

  return (
    <div className="contentGrid">
      <div className="kpiGrid four">
        <KpiCard index={0} icon={Compass} label="Global reach" value={`±${number(Math.max(Math.abs(global.fleet.minLatitude), Math.abs(global.fleet.maxLatitude)), 1)}°`} detail={`latitude span, all ${global.fleet.satelliteCount} satellites · set by 50° inclination`} accent={COLORS.blue} />
        <KpiCard index={1} icon={Globe2} label="Regions traversed" value={global.fleet.regionsTraversed} detail="of 14 approximate geographic buckets, fleet-wide" accent={COLORS.cyan} />
        <KpiCard index={2} icon={Gauge} label="AOI focus" value={Number(global.fleet.aoiSharePercent)} format={(v) => `${number(v, 2)}%`} detail="share of fleet time actually powered, over Australia" accent={COLORS.green} />
        <KpiCard index={3} icon={Aperture} label="Global capability, unused" value={Number(global.fleet.globalSharePercent)} format={(v) => `${number(v, 2)}%`} detail="time over the rest of the globe — sensors intentionally OFF" accent={COLORS.amber} />
      </div>

      <NoticeBanner icon={Compass} tone={COLORS.amber} title="Global capability, Australia-only focus" index={4}>
        Every one of the 48 crafts is physically capable of observing the whole globe as it orbits — the ground
        tracks below sweep from pole to pole across every longitude. Even so, the mission intentionally powers the
        sensor only while a craft is over the Australia AOI (110°E–160°E, 10°S–40°S): the other{" "}
        {number(global.fleet.globalSharePercent, 1)}% of each orbit is flown with the payload OFF, trading global
        imaging capability for a focused power and data budget on the mission's actual objective. This page exists
        purely for situational awareness of where the fleet passes — not as imagery that was actually captured.
      </NoticeBanner>

      <Panel index={5} title="Full-Globe Constellation Simulator" sub="Unrestricted ground tracks — the same 48 satellites, no AOI filter" className="wide">
        {state ? (
          <ConstellationSim series={state.series} satellites={state.satellites} range={state.range} defaultWindowMs={Infinity} />
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
            subtitle="Per-satellite geographic reach — where each craft passes over the globe, beyond the Australia AOI"
            columns={GLOBAL_TABLE_COLUMNS}
            rows={filtered}
            fileName="global_coverage_report"
          />
        }
      >
        <SatSelector satellites={satellites} selected={selected} onToggle={toggle} onSelectAll={selectAll} />
        <DataTable rows={filtered} columns={GLOBAL_TABLE_COLUMNS} />
      </Panel>

      <MethodNote items={GLOBAL_METHODS} />
    </div>
  );
}

const DATA_METHODS = [
  { metric: "Row counts", meaning: "Direct row counts of the processed Excel outputs the pipeline produces from raw GMAT reports — no rows are added, removed, or estimated for display.", formula: "len(dataframe) per file" },
  { metric: "Configuration issues", meaning: "Cross-checks Mission_Configuration.xlsx against itself and the detected fleet (e.g. planes × satellites/plane, missing payload/power values).", formula: "see core/config_loader.validate_configuration()" },
];

const ECLIPSE_TABLE_COLUMNS = [
  { key: "Satellite Name", label: "Satellite" },
  { key: "Eclipse Type", label: "Type" },
  { key: "Start UTC", label: "Start" },
  { key: "Duration (s)", label: "Duration", render: (v) => `${number(Number(v) / 60, 2)} min` },
];

function DataView({ data }) {
  return (
    <div className="contentGrid">
      <Panel index={0} title="Dataset Inventory" sub={`Processed GMAT outputs · ${data.constellation.configuredSatellites}-satellite fleet`} className="wide">
        <div className="inventory">
          <KpiCard index={0} icon={Radio} label="RF rows" value={data.metrics.rfEvents} detail="RF_Contacts.xlsx — 1 row per RF pass" accent={COLORS.blue} />
          <KpiCard index={1} icon={Antenna} label="Optical rows" value={data.metrics.opticalEvents} detail="Optical_Contacts.xlsx — 1 row per optical pass" accent={COLORS.green} />
          <KpiCard index={2} icon={SunMedium} label="Eclipse rows" value={data.metrics.eclipseEvents} detail="All_Eclipse_Events.xlsx — 1 row per eclipse interval" accent={COLORS.amber} />
          <KpiCard index={3} icon={HardDrive} label="State rows" value={data.metrics.stateRows} format={compact} detail={`Satellite_State_History.xlsx — ${data.constellation.configuredSatellites} satellites × samples/day`} accent={COLORS.cyan} />
        </div>
      </Panel>
      <Panel index={1} title="Configuration Issues">
        {data.configuration.issues.length ? (
          <div className="issueList">{data.configuration.issues.map((issue) => <span key={issue}>{issue}</span>)}</div>
        ) : (
          <div className="emptyState">No configuration validation issues reported.</div>
        )}
      </Panel>
      <Panel
        index={2}
        title="Top Eclipse Events"
        action={
          <PdfButton
            mission={data.mission}
            title="Top Eclipse Events"
            subtitle="Longest recorded eclipse intervals, all satellites"
            columns={ECLIPSE_TABLE_COLUMNS}
            rows={data.tables.eclipse}
            fileName="eclipse_events_report"
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
  { metric: "Altitude (min/mean/max)", meaning: "Range of the 'Altitude' column in Satellite_State_History.xlsx for this satellite across the analysis window.", formula: "min / mean / max(Altitude)" },
  { metric: "Mean eccentricity", meaning: "Average of the state file's 'ECC' column — how far the orbit deviates from a perfect circle (0 = circular).", formula: "mean(ECC)" },
  { metric: "Mean RMAG", meaning: "Average orbit radius from Earth's center (Earth radius + altitude), from the state file's 'RMAG' column.", formula: "mean(RMAG)" },
  { metric: "AOI dwell %", meaning: "Share of this satellite's state samples whose sub-point falls inside the mission AOI rectangle.", formula: "samples inside 110°E–160°E,10°S–40°S ÷ total samples × 100" },
];

function StateExplorer({ state, mission, stateLoading }) {
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

  return (
    <div className="contentGrid">
      <Panel
        index={0}
        title="Satellite State Explorer"
        sub={`${selected.length} of ${satellites.length} satellites selected (basis: full 48-satellite fleet) · window ${dateLabel(state.range?.start)} → ${dateLabel(state.range?.end)}`}
        className="wide"
        action={
          <PdfButton
            mission={mission}
            title="Satellite State Report"
            subtitle={`AOI 110E-160E / 10S-40S · window ${dateLabel(state.range?.start)} to ${dateLabel(state.range?.end)}`}
            columns={STATE_EXPLORER_COLUMNS}
            rows={state.summary}
            fileName="satellite_state_report"
          />
        }
      >
        <SatSelector satellites={satellites} selected={selected} onToggle={toggle} onSelectAll={selectAll} />
      </Panel>

      <Panel
        index={1}
        title="Telemetry Over Time"
        sub="All selected satellites overlaid across the analysis window"
        className="wide"
        action={
          <div className="fieldTabs">
            {fields.map((f) => (
              <button key={f[0]} className={field === f[0] ? "fieldTab on" : "fieldTab"} onClick={() => setField(f[0])}>
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
        <WorldOrbitMap positions={positions} tracks={tracks} maxTracks={selected.length} />
      </Panel>

      <Panel index={3} title="Per-Satellite Summary" sub="Full fleet — this is the data exported to PDF" className="wide">
        <DataTable
          rows={state.summary}
          columns={[
            { key: "satellite", label: "Satellite" },
            { key: "samples", label: "Samples", render: (v) => number(v) },
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
      "48 crafts move across Australia — each craft holds its designated SSO (50°) path. The orbit subsystem keeps the constellation transiting the country every revolution.",
    methods: [
      { metric: "Crafts in transit / Altitude", meaning: "Read directly from Mission_Configuration.xlsx (Constellation and Orbit tables) — not derived.", formula: "Total Satellites; Altitude (km)" },
      { metric: "Fleet AOI dwell", meaning: "Average, across all 48 satellites, of how much of the analysis window each spends with its sub-point inside the AOI rectangle.", formula: "mean( AOI samples ÷ total samples × 100 ) across satellites" },
      { metric: "Live subpoints", meaning: "Count of satellites with a recorded position at the single latest shared timestamp in the state file.", formula: "count(satellites at max(Timestamp))" },
    ],
    render: (data, state) => (
      <>
        <div className="kpiGrid four">
          <KpiCard index={0} icon={Satellite} label="Crafts in transit" value={data.constellation.configuredSatellites} detail="of 48 configured, SSO · 50° inclination" accent={SUBSYS.Orbit.color} />
          <KpiCard index={1} icon={Orbit} label="Altitude" value={Number(data.constellation.altitudeKm)} format={(v) => `${number(v, 0)} km`} detail="nominal orbit, shared by all satellites" accent={SUBSYS.Orbit.color} />
          <KpiCard index={2} icon={Globe2} label="Fleet AOI dwell" value={state ? state.summary.reduce((a, r) => a + r.aoiSharePercent, 0) / (state.summary.length || 1) : 0} format={(v) => `${number(v, 2)}%`} detail={`avg across ${state ? state.summary.length : 48} satellites, time over the AOI rectangle`} accent={SUBSYS.Orbit.color} />
          <KpiCard index={3} icon={Activity} label="Live subpoints" value={data.charts.latestPositions.length} detail={`of ${data.constellation.configuredSatellites} satellites, at the latest shared epoch`} accent={SUBSYS.Orbit.color} />
        </div>
        <Panel index={4} title="Constellation Transit Simulator" sub="Animated ground tracks — watch the 48 crafts transit Australia" className="wide">
          {state ? (
            <ConstellationSim series={state.series} satellites={state.satellites} range={state.range} />
          ) : (
            <WorldOrbitMap positions={data.charts.latestPositions} tracks={data.charts.tracks} />
          )}
        </Panel>
        {state ? (
          <Panel index={5} title="AOI Dwell per Satellite" sub="Share of the window each craft spends over 110°E–160°E / 10°S–40°S" className="wide">
            <SimpleBar rows={[...state.summary].sort((a, b) => b.aoiSharePercent - a.aoiSharePercent).slice(0, 24).map((r) => ({ satellite: r.satellite.replace("ASC_074_", "S"), aoiSharePercent: r.aoiSharePercent }))} x="satellite" y="aoiSharePercent" color={SUBSYS.Orbit.color} format={(v) => `${number(v, 2)}%`} />
          </Panel>
        ) : null}
      </>
    ),
  },
  k2: {
    requirement:
      "48 crafts use sensor power only while travelling over Australia. Payload ON/OFF is derived from the modeled camera swath crossing the country — power is spent on coverage, not idle flight.",
    methods: [
      { metric: "Fleet ON time / duty cycle", meaning: "A state sample counts as sensor ON when the modeled camera footprint (half the ground swath around the sub-satellite point) intersects the Australia land boundary, across all 48 satellites.", formula: "duty % = ON samples ÷ total samples × 100" },
      { metric: "AOI + eclipse", meaning: "Hours where a satellite is simultaneously ON (observing) and inside a recorded eclipse interval — power drawn from battery, not solar, during that overlap.", formula: "Σ duration where Observing = true AND In Eclipse = true" },
      { metric: "Sample cadence", meaning: "Median time between consecutive state samples — the telemetry resolution this whole page's timing is built on.", formula: "median(Δt) between consecutive Timestamp rows, per satellite" },
    ],
    render: (data) => (
      <>
        <div className="kpiGrid four">
          <KpiCard index={0} icon={Zap} label="Fleet ON time" value={Number(data.duty.metrics.fleetActiveHours)} format={asHours} detail={`sensors active over AOI, across ${data.constellation.configuredSatellites} satellites`} accent={SUBSYS.Power.color} />
          <KpiCard index={1} icon={Gauge} label="Fleet duty cycle" value={Number(data.duty.metrics.fleetDutyPercent)} format={(v) => `${number(v, 2)}%`} detail="active samples ÷ total samples, fleet-wide" accent={SUBSYS.Power.color} />
          <KpiCard index={2} icon={SunMedium} label="AOI + eclipse" value={Number(data.duty.metrics.aoiEclipseOverlapHours)} format={asHours} detail="observing while in eclipse, summed across the fleet" accent={SUBSYS.Power.color} />
          <KpiCard index={3} icon={Activity} label="Sample cadence" value={Number(data.duty.metrics.nominalStepSeconds)} format={(v) => `${number(v, 0)} s`} detail="median state step, per satellite" accent={SUBSYS.Power.color} />
        </div>
        <Panel index={4} title="Sensor Power Timeline" sub="Observing satellites (sensor power drawn) vs. eclipse, out of 48" className="wide">
          <DutyTimeline rows={data.duty.timeline} />
        </Panel>
        <Panel index={5} title="Active Payload Time per Satellite" sub="Minutes of sensor power over Australia, per craft" className="wide">
          <SimpleBar rows={data.duty.summary.slice(0, 24).map((r) => ({ ...r, satellite: r.satellite.replace("ASC_074_", "S") }))} x="satellite" y="activeMinutes" color={SUBSYS.Power.color} format={(v) => `${number(v, 1)} min`} />
        </Panel>
      </>
    ),
  },
  k3: {
    requirement:
      "48 crafts store the Australia data onboard and downlink it to Brisbane when passing through the GSN. This tracks the volume captured over the AOI and the contact opportunities to offload it.",
    methods: [
      { metric: "Observed time", meaning: "Same sensor-ON basis as K2 — this is the raw data being generated for onboard storage.", formula: "Σ ON duration, across all satellites" },
      { metric: "RF / Optical contacts", meaning: "One row per continuous line-of-sight contact between a satellite and Brisbane GSN — each is a downlink opportunity.", formula: "row count in RF_Contacts.xlsx / Optical_Contacts.xlsx" },
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
            ]} rows={data.tables.rf} fileName="downlink_passes" />
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
      "Brisbane GSN links to each craft and downloads the collected data for transmission. This view isolates the ground-station link budget: which stations carry the load and how long each pass lasts.",
    methods: [
      { metric: "RF / Optical contacts", meaning: "Pass counts and durations from the contact files — the downlink opportunities Brisbane GSN has with the fleet.", formula: "row count and Σ Duration(s) ÷ 60, per link type" },
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
        </Panel>
      </>
    ),
  },
  k5: {
    requirement:
      "Brisbane GSN uploads any data the craft needs for its operations. Each downlink pass is also a command-uplink opportunity — this view schedules those contact windows.",
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
            ]} rows={data.tables.rf} fileName="command_uplink_schedule" />
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
      "The 48 crafts must be 100% active while covering the Area between 110°E–160°E and 10°S–40°S. This is the core Australia coverage: which land cells are seen and by whom.",
    methods: COVERAGE_METHODS,
    render: (data) => (
      <>
        <div className="kpiGrid four">
          <KpiCard index={0} icon={Globe2} label="Australia coverage" value={Number(data.coverage.percent)} format={(v) => `${number(v, 2)}%`} detail={`${number(data.coverage.coveredCells)} / ${number(data.coverage.totalCells)} land cells, all 48 satellites`} accent={SUBSYS.Orbit.color} />
          <KpiCard index={1} icon={Activity} label="All-sat observed" value={data.coverage.observation.overall["Summed Satellite Observation Time"] || "NA"} detail="combined effort-time, summed across all satellites" accent={SUBSYS.Orbit.color} />
          <KpiCard index={2} icon={Satellite} label="Max simultaneous" value={data.coverage.observation.overall["Maximum Simultaneous Observing Satellites"] || 0} detail="of 48, observing at the same instant" accent={SUBSYS.Orbit.color} />
          <KpiCard index={3} icon={Gauge} label="Observation duty" value={Number(data.coverage.observation.overall["Overall Observation Duty Cycle (%)"]) || 0} format={(v) => `${number(v, 2)}%`} detail="constellation timeline, ≥1 of 48 satellites" accent={SUBSYS.Orbit.color} />
        </div>
        <Panel index={4} title="Coverage Cell Map" sub="Covered / uncovered cells over the Australia land boundary" className="wide">
          <AustraliaCoverageMap cells={data.coverage.cells} outline={data.coverage.outline} tasmania={data.coverage.tasmania} aoi={data.coverage.aoi} percent={data.coverage.percent} />
        </Panel>
        <Panel index={5} title="Coverage Contribution" sub="Covered analysis-cell centers per satellite" className="wide">
          <SimpleBar rows={data.coverage.contribution.slice(0, 24).map((r) => ({ ...r, satellite: r.satellite.replace("ASC_074_", "S") }))} x="satellite" y="coveredCells" color={SUBSYS.Orbit.color} />
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
          <KpiCard index={1} icon={Gauge} label="Fleet duty cycle" value={Number(data.duty.metrics.fleetDutyPercent)} format={(v) => `${number(v, 2)}%`} detail="power drawn for coverage, fleet average" accent={SUBSYS.Power.color} />
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
          <SimpleBar rows={data.duty.summary.slice(0, 20).map((r) => ({ ...r, satellite: r.satellite.replace("ASC_074_", "S") }))} x="satellite" y="dutyPercent" color={SUBSYS.Power.color} format={(v) => `${number(v, 2)}%`} height={280} />
        </Panel>
      </>
    ),
  },
  k8: {
    requirement:
      "When the craft is outside the Area of cover, the OBC uses that time for onboard processing, making pre-processed data ready for downlink at Brisbane. Processing time is the complement of AOI dwell.",
    methods: [
      { metric: "Processing share", meaning: "The onboard computer is assumed free to pre-process the previous pass's data whenever a satellite's sub-point is outside the AOI rectangle. This is the inverse of the K1 'Fleet AOI dwell' figure, averaged across all 48 satellites.", formula: "100 − mean(AOI dwell %) across satellites" },
      { metric: "Observed time", meaning: "Same sensor-ON basis as K2/K3 — the raw data volume the OBC has to work through.", formula: "Σ ON duration, all satellites" },
      { metric: "State samples", meaning: "Total telemetry rows across the fleet — the processing timeline's resolution.", formula: "row count in Satellite_State_History.xlsx" },
    ],
    render: (data, state) => (
      <>
        <div className="kpiGrid four">
          <KpiCard index={0} icon={Cpu} label="Processing share" value={state ? 100 - state.summary.reduce((a, r) => a + r.aoiSharePercent, 0) / (state.summary.length || 1) : 0} format={(v) => `${number(v, 2)}%`} detail={`time outside AOI (OBC busy), avg across ${state ? state.summary.length : 48} satellites`} accent={SUBSYS.Data.color} />
          <KpiCard index={1} icon={Database} label="Observed time" value={Number(data.duty.metrics.fleetActiveHours)} format={asHours} detail="raw data to process, summed across the fleet" accent={SUBSYS.Data.color} />
          <KpiCard index={2} icon={HardDrive} label="State samples" value={data.metrics.stateRows} format={compact} detail={`processing timeline, ${data.constellation.configuredSatellites} satellites`} accent={SUBSYS.Data.color} />
          <KpiCard index={3} icon={Gauge} label="Coverage duty" value={Number(data.coverage.observation.overall["Overall Observation Duty Cycle (%)"]) || 0} format={(v) => `${number(v, 2)}%`} detail="acquisition vs processing split, fleet timeline" accent={SUBSYS.Data.color} />
        </div>
        {state ? (
          <Panel index={4} title="Onboard Processing Window per Satellite" sub="Percent of the window outside the AOI — available for OBC processing" className="wide">
            <SimpleBar rows={[...state.summary].sort((a, b) => (b.samples - b.aoiSamples) - (a.samples - a.aoiSamples)).slice(0, 24).map((r) => ({ satellite: r.satellite.replace("ASC_074_", "S"), processing: 100 - r.aoiSharePercent }))} x="satellite" y="processing" color={SUBSYS.Data.color} format={(v) => `${number(v, 2)}%`} />
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
      { metric: "Downlink windows", meaning: "RF passes available to deliver the pre-processed data package to Brisbane GSN.", formula: "row count in RF_Contacts.xlsx, all satellites" },
      { metric: "Summed / max simultaneous observation", meaning: "Same basis as K6/Coverage — total and peak concurrent observing satellites, which sets the pipeline's input load.", formula: "Σ per-satellite observation time; max(concurrent observing count)" },
      { metric: "Analysis duration", meaning: "The full simulated window this whole pipeline view is measured over.", formula: "max(Timestamp) − min(Timestamp), shared grid" },
    ],
    render: (data) => (
      <>
        <div className="kpiGrid four">
          <KpiCard index={0} icon={Send} label="Downlink windows" value={data.tables.rf.length} detail="RF packages to GSN, fleet-wide" accent={SUBSYS.GSN.color} />
          <KpiCard index={1} icon={Activity} label="Summed observation" value={data.coverage.observation.overall["Summed Satellite Observation Time"] || "NA"} detail="total effort-time across all 48 satellites" accent={SUBSYS.GSN.color} />
          <KpiCard index={2} icon={Satellite} label="Max simultaneous" value={data.coverage.observation.overall["Maximum Simultaneous Observing Satellites"] || 0} detail="of 48, parallel acquisition" accent={SUBSYS.GSN.color} />
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
            ]} rows={data.coverage.observation.perSatellite} fileName="observation_windows" />
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
      { metric: "Mean altitude / eccentricity", meaning: "Averaged across all satellites at the latest shared epoch — deviation from the nominal 536 km, near-circular orbit signals a needed correction.", formula: "mean(Altitude), mean(ECC) at max(Timestamp)" },
      { metric: "Altitude envelope", meaning: "Min / mean / max altitude per satellite across the whole window — a wide spread indicates orbit decay or drift needing an uplinked correction.", formula: "min / mean / max(Altitude) per satellite, from Satellite_State_History.xlsx" },
      { metric: "Uplink windows", meaning: "RF passes available to deliver orbit-correction commands to each craft.", formula: "row count in RF_Contacts.xlsx" },
    ],
    render: (data, state) => (
      <>
        <div className="kpiGrid four">
          <KpiCard index={0} icon={Orbit} label="Mean altitude" value={Number(data.metrics.meanAltitude)} format={(v) => `${number(v, 2)} km`} detail={`fleet average, ${data.constellation.configuredSatellites} satellites, latest epoch`} accent={SUBSYS.Upload.color} />
          <KpiCard index={1} icon={Activity} label="Mean eccentricity" value={Number(data.metrics.meanEccentricity)} format={(v) => number(v, 6)} detail="fleet average, near-circular target = 0" accent={SUBSYS.Upload.color} />
          <KpiCard index={2} icon={Satellite} label="Crafts managed" value={data.constellation.configuredSatellites} detail="receiving orbit-control uploads" accent={SUBSYS.Upload.color} />
          <KpiCard index={3} icon={Upload} label="Uplink windows" value={data.tables.rf.length} detail="RF passes available for correction upload" accent={SUBSYS.Upload.color} />
        </div>
        <Panel index={4} title="Altitude Envelope" sub="Min / mean / max altitude per satellite — deviations flag corrections" className="wide">
          <AltitudeChart rows={data.charts.altitudeBands} />
        </Panel>
        {state ? (
          <Panel index={5} title="Mean Eccentricity per Satellite" sub="Orbit circularity — larger values need management uploads" className="wide">
            <SimpleBar rows={[...state.summary].sort((a, b) => b.meanEccentricity - a.meanEccentricity).slice(0, 24).map((r) => ({ satellite: r.satellite.replace("ASC_074_", "S"), ecc: r.meanEccentricity }))} x="satellite" y="ecc" color={SUBSYS.Upload.color} format={(v) => number(v, 6)} />
          </Panel>
        ) : null}
      </>
    ),
  },
};

function KView({ id, data, state }) {
  const def = K_BY_ID[id];
  const content = K_CONTENT[id];
  return (
    <div className="contentGrid">
      <KHero def={def} requirement={content.requirement} index={0} />
      {content.render(data, state)}
      <MethodNote items={content.methods || []} />
    </div>
  );
}

/* ----------------------------- app shell ------------------------------ */

function Dashboard() {
  const [active, setActive] = React.useState(() => (typeof window !== "undefined" && window.location.hash.slice(1)) || "overview");
  const { data, state, loading, error, refreshing, refresh } = useDashboard();

  React.useEffect(() => {
    const onHash = () => setActive(window.location.hash.slice(1) || "overview");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  React.useEffect(() => {
    if (window.location.hash.slice(1) !== active) window.location.hash = active;
  }, [active]);

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
    return (
      <>
        <Backdrop />
        <main className="loadingScreen error">
          <ShieldCheck size={30} />
          <span>{error}</span>
        </main>
      </>
    );
  }

  let view;
  if (active === "overview") view = <Overview data={data} state={state} />;
  else if (active === "explorer") view = <StateExplorer state={state} mission={data.mission} stateLoading={loading} />;
  else if (active === "coverage") view = <CoverageView data={data} />;
  else if (active === "imaging") view = <PayloadImagingView data={data} />;
  else if (active === "global") view = <GlobalCoverageView data={data} state={state} />;
  else if (active === "data") view = <DataView data={data} />;
  else if (active === "ic-catalog") view = <ImageCatalogView />;
  else if (active === "ic-gallery") view = <ImageGalleryView />;
  else if (K_BY_ID[active]) view = <KView id={active} data={data} state={state} />;
  else view = <Overview data={data} state={state} />;

  return (
    <>
      <Backdrop />
      <div className="appShell">
        <Sidebar active={active} setActive={setActive} />
        <main className="main">
          <Header data={data} refresh={refresh} refreshing={refreshing} />
          <Ticker data={data} />
          {error ? <div className="bannerError">{error}</div> : null}
          <div key={active}>{view}</div>
        </main>
      </div>
    </>
  );
}

createRoot(document.getElementById("root")).render(<Dashboard />);
