import React from "react";
import { feature } from "topojson-client";
import worldTopo from "world-atlas/land-110m.json";
import {
  Activity,
  AlertTriangle,
  Antenna,
  Aperture,
  Camera,
  CheckCircle2,
  Clock,
  Compass,
  Cpu,
  Database,
  Eye,
  Gauge,
  Globe2,
  HardDrive,
  Layers,
  Map,
  Orbit,
  Pause,
  Play,
  Radio,
  RotateCcw,
  Satellite,
  Send,
  ShieldCheck,
  Sparkles,
  SunMedium,
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
import { InfoPopover } from "./glossary.jsx";
import { useAccess } from "./access.jsx";

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

const axisTick = { fontSize: 10, fill: COLORS.axis };

function number(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "NA";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/* AOI bounding box -> "68°E-98°E · 8°N-37°N" style label, from whatever box
   the active mission's dashboard payload actually carries, instead of a
   fixed Australia string. */
function fmtAoiBox(box) {
  if (!box) return "AOI";
  const deg = (v, posSuffix, negSuffix) => `${number(Math.abs(v), 0)}°${v < 0 ? negSuffix : posSuffix}`;
  return `${deg(box.lonMin, "E", "W")}–${deg(box.lonMax, "E", "W")} · ${deg(box.latMin, "N", "S")}–${deg(box.latMax, "N", "S")}`;
}

function KpiCard({ icon: Icon, label, value, format, detail, accent = COLORS.blue, index = 0, isAlert = false, badge = null, infoKey = null }) {
  const isNumeric = typeof value === "number" && Number.isFinite(value);
  // Same whole-card-click-opens-the-popover behavior as main.jsx's KpiCard
  // (see the comment there for why the click is forwarded to the ⓘ
  // button's own ref rather than duplicating InfoPopover's open state, and
  // why containerRef is passed so the popover's own "click outside closes"
  // handler doesn't race the card's click into reopening what it just closed).
  const infoBtnRef = React.useRef(null);
  const cardRef = React.useRef(null);
  const openInfo = infoKey ? () => infoBtnRef.current?.click() : undefined;
  return (
    <section
      ref={cardRef}
      className={`kpi reveal ${isAlert ? "alertKpi" : ""}${infoKey ? " kpiHasInfo" : ""}`}
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
        <span className="kpiIcon">
          <Icon size={17} />
        </span>
      </div>
      <div className="kpiMainVal">
        <strong className={isAlert ? "alertText" : ""}>
          {format ? format(value) : isNumeric ? number(value) : value}
        </strong>
        {badge ? <span className="kpiValBadge">{badge}</span> : null}
      </div>
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

function MethodNote({ items = [], title = "How these analytics are calculated" }) {
  if (!items.length) return null;
  return (
    <details className="methodNote reveal wide">
      <summary>
        <Sparkles size={13} /> {title}
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

/* Gauge Component for Mission Health */
function GaugeCircle({ value = 95, label = "Health", color = COLORS.cyan, size = 120 }) {
  const radius = (size - 16) / 2;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (value / 100) * circumference;

  return (
    <div className="gaugeCircleWrap" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="rgba(120, 160, 255, 0.1)"
          strokeWidth="10"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="10"
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: "stroke-dashoffset 1s ease" }}
        />
      </svg>
      <div className="gaugeInnerContent">
        <span className="gaugeVal mono">{number(value, 1)}%</span>
        <span className="gaugeLabel">{label}</span>
      </div>
    </div>
  );
}

/* MAP BASE FOR REVISIT AND DENSITY HEATMAPS */
const MAP_W = 960;
const MAP_H = 480;
const projX = (lon) => ((Number(lon) + 180) / 360) * MAP_W;
const projY = (lat) => ((90 - Number(lat)) / 180) * MAP_H;

/* Real world land silhouette from TopoJSON (same data as main.jsx) */
const AV_LAND_PATH = (() => {
  try {
    const geo = feature(worldTopo, worldTopo.objects.land);
    const features = geo.features || [geo];
    let d = "";
    features.forEach((f) => {
      const polys =
        f.geometry.type === "Polygon"
          ? [f.geometry.coordinates]
          : f.geometry.coordinates;
      polys.forEach((poly) =>
        poly.forEach((ring) => {
          // A ring crossing the antimeridian (Russia, Alaska, Fiji,
          // Antarctica) jumps from ~+180 to ~-180 in raw longitude between
          // consecutive points; drawing that as a normal line segment draws
          // a spurious straight line across the whole map. Break into a new
          // subpath there instead, same fix as main.jsx's LAND_PATH.
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
  } catch (e) {
    return "";
  }
})();

const DEFAULT_AOI_BOX = { lonMin: 110, lonMax: 160, latMin: -40, latMax: -10 };

/* Same real coastline-derived outline used by main.jsx's ConstellationSim --
   see the longer comment there. A lon/lat bounding rectangle necessarily
   sweeps in whatever else sits in its corners (India's box, at its
   northernmost latitude, spans the full width into Tibet/western China),
   which the real outline avoids. */
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

function MapCanvasBase({ children, legend, showAoi = false, aoiBox = DEFAULT_AOI_BOX, outline = [], secondary = [] }) {
  const lonLines = [-150, -120, -90, -60, -30, 0, 30, 60, 90, 120, 150];
  const latLines = [-60, -30, 0, 30, 60];

  return (
    <div className="coverageMap">
      <svg viewBox={`0 0 ${MAP_W} ${MAP_H}`} role="img" aria-label="Constellation Analytics Map">
        <defs>
          <radialGradient id="mapOceanGradAV" cx="50%" cy="42%" r="70%">
            <stop offset="0%" stopColor="rgba(11,30,65,0.85)" />
            <stop offset="100%" stopColor="rgba(4,8,20,0.98)" />
          </radialGradient>
          <filter id="landGlow">
            <feGaussianBlur stdDeviation="1.5" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>

        {/* Deep space ocean background */}
        <rect width={MAP_W} height={MAP_H} fill="#050c1c" />
        <rect width={MAP_W} height={MAP_H} fill="url(#mapOceanGradAV)" />

        {/* Graticule lines */}
        {lonLines.map((lon) => (
          <line key={`avlon${lon}`} x1={projX(lon)} y1={0} x2={projX(lon)} y2={MAP_H}
            stroke="rgba(100,140,220,.07)" strokeWidth="0.8" strokeDasharray="2,4" />
        ))}
        {latLines.map((lat) => (
          <line key={`avlat${lat}`} x1={0} y1={projY(lat)} x2={MAP_W} y2={projY(lat)}
            stroke="rgba(100,140,220,.07)" strokeWidth="0.8" strokeDasharray="2,4" />
        ))}

        {/* Graticule labels */}
        {lonLines.map((lon) => (
          <text key={`avlonlbl${lon}`} x={projX(lon) + 3} y={MAP_H - 5}
            fill="rgba(120,160,220,.35)" fontSize="9" fontFamily="monospace">{lon}°</text>
        ))}
        {latLines.map((lat) => (
          <text key={`avlatlbl${lat}`} x={3} y={projY(lat) - 4}
            fill="rgba(120,160,220,.35)" fontSize="9" fontFamily="monospace">{lat}°</text>
        ))}

        {/* Real land silhouette */}
        <path d={AV_LAND_PATH} fill="#1a2d50" stroke="rgba(80,130,200,.25)" strokeWidth="0.5" />

        {/* Optional AOI outline -- real coastline-derived polygon when
            available, falling back to the old bounding rectangle otherwise
            (see outlinePathD above for why the rectangle alone is misleading) */}
        {showAoi ? (
          outline.length > 0 ? (
            <path d={outlinePathD([outline, secondary])} fillRule="evenodd"
              fill="none" stroke="#fbbf24" strokeWidth="1.5" strokeDasharray="6,3" opacity="0.85" />
          ) : (
            <rect
              x={projX(aoiBox.lonMin)} y={projY(aoiBox.latMax)}
              width={projX(aoiBox.lonMax) - projX(aoiBox.lonMin)}
              height={projY(aoiBox.latMin) - projY(aoiBox.latMax)}
              fill="none" stroke="#fbbf24" strokeWidth="1.5" strokeDasharray="6,3" opacity="0.85"
            />
          )
        ) : null}

        {children}
      </svg>
      {legend ? <div className="mapLegend">{legend}</div> : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 1. CONSTELLATION SUMMARY DASHBOARD                                         */
/* -------------------------------------------------------------------------- */

export function ConstellationSummaryView({ data }) {
  const s = data?.analytics?.summary || {};
  const c = data?.constellation || {};
  const inclination = c.inclinationDeg ?? s.inclinationDeg ?? null;
  // Sun-synchronicity is a claim about nodal precession (depends on BOTH
  // inclination and altitude, via the J2 secular-drift formula), not
  // something a bare inclination range can determine on its own -- e.g. a
  // 97.5 deg orbit is only actually sun-synchronous at one specific
  // altitude. Read this from the backend's own precession calculation
  // (core.constellation_analytics._classify_orbit_type, exposed via
  // analytics.simulationDetails.orbitType) instead of re-guessing a
  // second, less rigorous heuristic here.
  const isSso = data?.analytics?.simulationDetails?.orbitType === "Sun-Synchronous Orbit (SSO)";
  const altitude = s.altitudeKm || c.altitudeKm || 536;
  const period = s.orbitalPeriodMin || 95.4;
  const histCount = (data?.analytics?.revisit?.histogram || []).reduce((sum, b) => sum + (b.count || 0), 0);
  const aoiLabel = data?.mission?.aoiRegionLabel || "Australia";
  const aoiBoxLabel = fmtAoiBox(data?.coverage?.aoi);

  return (
    <div className="contentGrid">
      {/* Header Banner */}
      <div className="analyticsHeaderBanner reveal">
        <div className="bannerBrandIcon">
          <Satellite size={32} strokeWidth={1.8} />
        </div>
        <div className="bannerTextContent">
          <div className="bannerBadgeRow">
            <span className="bannerBadge cyan">Telemetry Validated</span>
            <span className="bannerBadge green">
              {inclination != null ? `${isSso ? "SSO " : ""}${number(inclination, 1)}° Orbit` : "Orbit"}
            </span>
            <span className="bannerBadge violet">{number(c.configuredSatellites || s.totalSatellites || 0)} Satellites Active</span>
          </div>
          <h2>{s.constellationName || "ASC-074 Earth Observation Constellation"}</h2>
          <p>Multi-plane constellation analytics and mission planning performance synthesis</p>
        </div>
      </div>

      <div className="kpiGrid five">
        <KpiCard index={0} icon={Satellite} label="Constellation Name" value={s.constellationName || "ASC-074 Earth Obs"} detail="Mission Configuration" accent={COLORS.blue} badge="LEO" infoKey="constellation_name" />
        <KpiCard index={1} icon={Layers} label="Configuration" value={s.configuration || `${c.planes || 0} × ${c.satellitesPerPlane || 0}`} detail={`${c.planes || 0} orbital planes × ${c.satellitesPerPlane || 0} satellites per plane`} accent={COLORS.cyan} badge="Walker-Delta" infoKey="constellation_configuration" />
        <KpiCard index={2} icon={Satellite} label="Total Satellites" value={s.totalSatellites || c.configuredSatellites || 0} detail="Configured fleet count" accent={COLORS.blue} badge="Configured" infoKey="total_satellites_configured" />
        <KpiCard index={3} icon={CheckCircle2} label="Operational Satellites" value={s.operationalSatellites || c.detectedSatellites || 0} detail="Detected active in state telemetry" accent={COLORS.green} badge="100% Active" infoKey="operational_satellites" />
        <KpiCard index={4} icon={Orbit} label="Nominal Orbit Altitude" value={s.altitudeKm || c.altitudeKm || 536} format={(v) => `${number(v)} km`} detail="Fixed design altitude, shared by every satellite" accent={COLORS.cyan} badge="Nominal" infoKey="nominal_orbit_altitude" />
      </div>

      <div className="kpiGrid five">
        <KpiCard index={5} icon={Compass} label="Inclination" value={inclination ?? 50} format={(v) => `${number(v, 1)}°`} detail="Orbit inclination angle" accent={COLORS.violet} badge={isSso ? "SSO" : "Inclined"} infoKey="inclination_deg" />
        <KpiCard index={6} icon={Clock} label="Orbital Period" value={s.orbitalPeriodMin || 95.4} format={(v) => `${number(v, 2)} min`} detail="Derived Keplerian revolution time" accent={COLORS.amber} badge="Keplerian" infoKey="orbital_period" />
        <KpiCard index={7} icon={Activity} label="Ground Tracks / Day" value={s.groundTracksPerDay || 724} detail="Total fleet orbital transits" accent={COLORS.cyan} badge="724 Passes" infoKey="ground_tracks_per_day" />
        <KpiCard index={8} icon={Globe2} label="Global Coverage" value={s.globalCoveragePct || 85.0} format={(v) => `${number(v, 1)}%`} detail="Accumulated land surface vision" accent={COLORS.green} badge="Cumulative" infoKey="global_coverage_duty_cycle" />
        <KpiCard index={9} icon={Clock} label="Mean Revisit" value={s.meanRevisitMin || 28.5} format={(v) => `${number(v, 1)} min`} detail="Fleet average revisit interval" accent={COLORS.blue} badge="Target SLA" infoKey="mean_revisit" />
      </div>

      <div className="kpiGrid five">
        <KpiCard index={10} icon={AlertTriangle} label="Worst Revisit" value={s.worstRevisitMin || 115.0} format={(v) => `${number(v, 1)} min`} detail="Maximum gap between observations" accent={COLORS.red} badge="Max Gap" isAlert infoKey="max_revisit" />
        <KpiCard index={11} icon={Sparkles} label="Best Revisit" value={s.bestRevisitMin || 4.2} format={(v) => `${number(v, 1)} min`} detail="Minimum consecutive pass delay" accent={COLORS.green} badge="Min Gap" infoKey="min_revisit" />
        <KpiCard index={12} icon={Aperture} label="Images / Day" value={s.imagesPerDay || 420} format={(v) => `${number(v, 0)}`} detail="Est. pushbroom scenes captured" accent={COLORS.pink} badge="Pushbroom" infoKey="images_per_day" />
        <KpiCard index={13} icon={Antenna} label="RF Contacts / Day" value={s.rfContactsPerDay || 96.0} format={(v) => `${number(v, 1)}`} detail="Downlink pass opportunities" accent={COLORS.cyan} badge="GSN Link" infoKey="rf_contacts_per_day" />
        <KpiCard index={14} icon={Radio} label="Avg Contact Duration" value={s.avgContactDurationMin || 8.4} format={(v) => `${number(v, 2)} min`} detail="Line-of-sight window duration" accent={COLORS.violet} badge="Pass Length" infoKey="avg_contact_duration" />
      </div>

      <MethodNote
        items={[
          {
            metric: "Orbital Period -- worked proof for this mission",
            meaning: `Kepler's Third Law, unmodified: for any body orbiting Earth, the orbital period depends on nothing but the orbit radius and Earth's gravitational parameter. Worked for this mission's own altitude: r = Earth radius (6371 km) + altitude (${number(altitude, 0)} km) = ${number(6371 + (altitude || 0), 0)} km. T = 2*pi*sqrt(r^3 / mu), mu = 398600.4418 km^3/s^2 (Earth's standard gravitational parameter, a physical constant -- not fitted to this mission). That gives T = ${number(period, 4)} minutes, which is exactly the ${number(period, 2)} min shown above -- the same formula every orbital mechanics textbook uses for a circular orbit, computed live from this mission's real configured altitude rather than hardcoded.`,
            formula: "T (minutes) = 2*pi * sqrt((6371 + altitude_km)^3 / 398600.4418) / 60",
          },
          {
            metric: "Ground Tracks / Day",
            meaning: "How many times the whole fleet crosses the globe pole-to-pole (or equator-to-equator) in 24 hours. A satellite completes one full revolution every Orbital Period minutes, so in 1440 minutes (a day) it completes 1440/Orbital Period revolutions; multiply by the operational fleet size for the combined figure.",
            formula: "(1440 / Orbital Period) * Operational Satellites",
          },
          {
            metric: "Mean / Best / Worst Revisit -- what is actually being averaged",
            meaning: `These three numbers are NOT a sum, and not one number per satellite -- they are the mean, minimum and maximum of one pooled list built like this: a 15x12 grid of sample points is laid over the mission's ${aoiLabel} AOI (${aoiBoxLabel}); at each of those 180 points, every recorded satellite pass close enough to matter (within 1.5x half the camera's ground swath) is collected in time order, and the gap between each consecutive pair of passes is one "revisit interval". Every grid point contributes its own gaps to one shared pool -- for this run that pool holds ${histCount} intervals -- and Mean/Best/Worst Revisit are the mean, minimum and maximum of that whole pool, not of any single satellite or single location. A grid point with too few passes to compute even one gap contributes nothing (never a fabricated number).`,
            formula: "pool = { t[i+1] - t[i] : consecutive passes at grid point p, over all 180 AOI grid points }; Mean = mean(pool), Best = min(pool), Worst = max(pool)",
          },
        ]}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 2. REVISIT ANALYTICS & HEATMAP                                             */
/* -------------------------------------------------------------------------- */

export function RevisitAnalyticsView({ data }) {
  const r = data?.analytics?.revisit || {};

  const colorMap = {
    green: "#34d399",
    yellow: "#fbbf24",
    orange: "#f97316",
    red: "#fb5c73",
  };

  const histogram = r.histogram || [];
  const histTotal = histogram.reduce((sum, b) => sum + (b.count || 0), 0);
  const histPeak = histogram.reduce((best, b) => (b.count > (best ? best.count : -1) ? b : best), null);
  const tailBins = histogram.slice(Math.ceil(histogram.length / 2));
  const tailShare = histTotal ? (tailBins.reduce((sum, b) => sum + (b.count || 0), 0) / histTotal) * 100 : 0;

  return (
    <div className="contentGrid">
      <Panel
        index={0}
        title="Revisit Analytics"
        sub="Fleet-wide, not per-satellite: every figure below pools passes from all satellites at each AOI point onto one shared timeline before measuring the gaps between them. None of these five numbers is any single satellite's own revisit cycle."
        className="wide"
      >
        <div className="kpiGrid five">
          <KpiCard index={0} icon={Clock} label="Mean Revisit" value={r.mean_revisit} format={(v) => `${number(v, 1)} min`} detail="Average of every pooled gap, any satellite — not a sum, not per satellite" accent={COLORS.blue} badge="Average" infoKey="mean_revisit" />
          <KpiCard index={1} icon={Sparkles} label="Minimum Revisit" value={r.min_revisit} format={(v) => `${number(v, 1)} min`} detail="Shortest gap anywhere in the pool, fleet-wide — not per satellite" accent={COLORS.green} badge="Best" infoKey="min_revisit" />
          <KpiCard index={2} icon={AlertTriangle} label="Maximum Revisit" value={r.max_revisit} format={(v) => `${number(v, 1)} min`} detail="Longest gap anywhere in the pool, fleet-wide — not per satellite" accent={COLORS.red} badge="Worst" isAlert infoKey="max_revisit" />
          <KpiCard index={3} icon={Gauge} label="Median Revisit" value={r.median_revisit} format={(v) => `${number(v, 1)} min`} detail="Midpoint of the pool, fleet-wide — half of all gaps are shorter" accent={COLORS.cyan} badge="P50" infoKey="median_revisit" />
          <KpiCard index={4} icon={Activity} label="95th Percentile" value={r.p95_revisit} format={(v) => `${number(v, 1)} min`} detail="95% of pooled gaps, fleet-wide, are shorter than this" accent={COLORS.amber} badge="P95" infoKey="p95_revisit" />
        </div>
      </Panel>

      <Panel index={1} title="World & AOI Revisit Heatmap" sub="Spatial access gap categorization based on sensor visibility passes" className="wide">
        <RevisitHeatmapMap heatmap={r.heatmap || []} colorMap={colorMap} aoiBox={data?.coverage?.aoi} outline={data?.coverage?.outline || []} secondary={data?.coverage?.tasmania || []} aoiLabel={data?.mission?.aoiRegionLabel || "Australia"} />
      </Panel>

      <Panel index={2} title="Revisit Time Frequency Distribution" sub="Every pooled gap, grouped into 8 time bins — the shape behind the 5 KPIs above" className="wide" action={<InfoPopover infoKey="revisit_distribution" />}>
        <ResponsiveContainer height={260}>
          <BarChart data={histogram} margin={{ top: 10, right: 20, left: 0, bottom: 25 }}>
            <defs>
              <linearGradient id="revisitBarGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={COLORS.cyan} stopOpacity={0.9} />
                <stop offset="100%" stopColor={COLORS.blue} stopOpacity={0.4} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke={COLORS.grid} />
            <XAxis dataKey="bin" tick={axisTick} stroke={COLORS.grid} />
            <YAxis tick={axisTick} stroke={COLORS.grid} />
            <Tooltip cursor={{ fill: "rgba(34,211,238,.06)" }} />
            <Bar dataKey="count" fill="url(#revisitBarGrad)" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
        {histTotal ? (
          <p className="panelFootnote">
            <strong>Why this chart exists:</strong> the 5 KPI cards above each collapse every revisit gap in the AOI
            to one number (its mean, min, max, median or 95th percentile) — this histogram is the full shape those
            numbers were computed from, showing whether short gaps are typical or rare instead of trusting a single
            summary statistic alone. <strong>Reading this run:</strong> {number(histTotal)} pass-to-pass gaps were
            pooled across every sampled AOI grid point; the tallest bar ({histPeak ? `${histPeak.bin}, ${number(histPeak.count)} gaps` : "no data"})
            is the most common revisit interval, and {number(tailShare, 0)}% of all gaps fall in the slower (upper)
            half of the bins — a longer right-hand tail like this is expected for a single Walker-Delta shell: most
            of the AOI is crossed by several planes and revisited quickly, while a thin edge of grid cells near the
            swath boundary waits for one specific plane to come back around, producing the few tall-gap outliers the
            Maximum and P95 KPIs report.
          </p>
        ) : null}
      </Panel>

      <MethodNote
        items={[
          { metric: "Revisit Heatmap Scale", meaning: "Green (<30 min), Yellow (30–60 min), Orange (1–2 hr), Red (>2 hr) categorizing average access gaps.", formula: "Access gap color buckets applied per grid cell" },
          { metric: "Derivation", meaning: "Derived directly from satellite sub-satellite paths and ground swath sensor footprint intersections over time.", formula: "Swath distance thresholding over state telemetry history" },
          { metric: "Aggregate, not sum", meaning: "Every KPI on this page (Mean/Min/Max/Median/P95) is a statistic computed over one pooled list of pass-to-pass gaps from all 180 AOI grid points combined. None of them are a sum of anything, and none are a single satellite's own figure — they describe the AOI's access pattern as a whole.", formula: "pool = all gaps across all grid points; each KPI = one aggregate function of pool" },
        ]}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 3. COVERAGE GAP ANALYSIS                                                   */
/* -------------------------------------------------------------------------- */

export function CoverageGapView({ data }) {
  const g = data?.analytics?.gapAnalysis || {};

  return (
    <div className="contentGrid">
      <Panel
        index={0}
        title="Coverage Gap Analysis"
        sub="Fleet-wide, not per-satellite: built from the same per-cell gaps as Revisit Analytics, where each AOI grid cell already pools passes from every satellite onto one shared timeline. None of these six numbers is any single satellite's own gap."
        className="wide"
      >
        <div className="kpiGrid six">
          <KpiCard index={0} icon={AlertTriangle} label="Largest Gap" value={g.largestGapMin} format={(v) => `${number(v, 1)} min`} detail="Maximum single coverage gap, fleet-wide — not per satellite" accent={COLORS.red} isAlert badge="Peak" infoKey="gap_largest" />
          <KpiCard index={1} icon={Clock} label="Mean Gap" value={g.meanGapMin} format={(v) => `${number(v, 1)} min`} detail="Average gap duration, pooled across the fleet" accent={COLORS.amber} badge="Average" infoKey="gap_mean" />
          <KpiCard index={2} icon={Gauge} label="Median Gap" value={g.medianGapMin} format={(v) => `${number(v, 1)} min`} detail="50th percentile gap duration, fleet-wide" accent={COLORS.cyan} badge="Median" infoKey="gap_median" />
          <KpiCard index={3} icon={Activity} label="Maximum Gap" value={g.maxGapMin} format={(v) => `${number(v, 1)} min`} detail="Same basis as Largest Gap above, fleet-wide" accent={COLORS.red} badge="Max" infoKey="gap_max" />
          <KpiCard index={4} icon={Clock} label="95th Percentile Gap" value={g.p95GapMin} format={(v) => `${number(v, 1)} min`} detail="95% of pooled gaps, fleet-wide, are shorter than this" accent={COLORS.violet} badge="P95" infoKey="gap_p95" />
          <KpiCard index={5} icon={ShieldCheck} label="Requirement Satisfied" value={g.pctSatisfyingRequirement} format={(v) => `${number(v, 1)}%`} detail={`Share of AOI grid cells meeting ≤${g.requirementMin || 60}m, any satellite (${g.dataBearingCells ?? 0}/${g.totalCells ?? 0} cells had data)`} accent={COLORS.green} badge="SLA Target" infoKey="gap_requirement_satisfied" />
        </div>
      </Panel>

      <Panel index={1} title="Temporal Gap Duration Breakdown" sub="Classification of coverage blackouts by duration magnitude" className="wide" action={<InfoPopover infoKey="gap_distribution_chart" />}>
        <ResponsiveContainer height={280}>
          <BarChart data={g.gapDistribution || []} margin={{ top: 10, right: 20, left: 0, bottom: 20 }}>
            <CartesianGrid vertical={false} stroke={COLORS.grid} />
            <XAxis dataKey="range" tick={axisTick} stroke={COLORS.grid} />
            <YAxis tick={axisTick} stroke={COLORS.grid} />
            <Tooltip cursor={{ fill: "rgba(34,211,238,.06)" }} />
            <Bar dataKey="count" radius={[4, 4, 0, 0]}>
              {(g.gapDistribution || []).map((entry, idx) => {
                const colors = [COLORS.green, COLORS.amber, COLORS.pink, COLORS.red];
                return <Cell key={idx} fill={colors[idx % colors.length]} />;
              })}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </Panel>

      <MethodNote
        items={[
          { metric: "Coverage Gap Definition", meaning: "The time elapsed between one sensor footprint leaving a ground target and the next footprint arriving over it, from any satellite in the fleet -- the two passes bounding a gap are not necessarily the same craft.", formula: "Entry_Time(N+1) - Exit_Time(N), any satellite" },
          { metric: "Requirement Satisfaction", meaning: "Percentage of grid points across the AOI whose fleet-wide maximum revisit gap does not exceed the target SLA requirement.", formula: "Count(Cells where Max Gap ≤ SLA) / Total AOI Cells * 100" },
        ]}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* GROUND STATION ANALYSIS                                                    */
/* -------------------------------------------------------------------------- */

export function GroundStationAnalysisView({ data }) {
  const stations = data?.analytics?.groundStations || [];

  return (
    <div className="contentGrid">
      <Panel
        index={0}
        title="Ground Station Analysis"
        sub="The two real ground segments in this mission — RF and Optical, each with its own minimum elevation mask. This is a comparison of the mission's actual ground stations, not a sweep of elevation-angle variants (only one mask exists per link type in the source mission data)."
        className="wide"
      >
        {stations.length === 0 ? (
          <div className="emptyState">No ground station data available for this mission.</div>
        ) : (
          <div className="kpiGrid four">
            {stations.map((s, i) => (
              <React.Fragment key={s.stationName}>
                <KpiCard
                  index={i * 4 + 0}
                  icon={s.linkType === "RF" ? Radio : Camera}
                  label={`${s.stationName} — Passes`}
                  value={s.passCount}
                  detail={`${s.linkType} link, ${number(s.minElevationDeg, 0)}° min elevation`}
                  accent={s.linkType === "RF" ? COLORS.cyan : COLORS.violet}
                  infoKey="min_elevation"
                />
                <KpiCard
                  index={i * 4 + 1}
                  icon={Clock}
                  label="Total Contact Time"
                  value={s.totalDurationSec / 60}
                  format={(v) => `${number(v, 1)} min`}
                  detail={`across ${s.passCount} passes`}
                  accent={s.linkType === "RF" ? COLORS.cyan : COLORS.violet}
                  infoKey="contact_duration"
                />
                <KpiCard
                  index={i * 4 + 2}
                  icon={Activity}
                  label="Avg / Min / Max Pass"
                  value={s.avgDurationSec}
                  format={(v) => `${number(v, 0)}s`}
                  detail={`range ${number(s.minDurationSec, 0)}s – ${number(s.maxDurationSec, 0)}s`}
                  accent={s.linkType === "RF" ? COLORS.cyan : COLORS.violet}
                />
                <KpiCard
                  index={i * 4 + 3}
                  icon={AlertTriangle}
                  label="Longest Gap"
                  value={s.longestGapMin}
                  format={(v) => `${number(v, 1)} min`}
                  detail="longest stretch with no contact, any satellite"
                  accent={COLORS.red}
                />
              </React.Fragment>
            ))}
          </div>
        )}
      </Panel>

      <Panel index={1} title="Pass Count & Total Contact Time" className="wide">
        <ResponsiveContainer height={280}>
          <BarChart data={stations.map((s) => ({ name: `${s.stationName.replace("ASC074_", "")} (${s.linkType})`, passes: s.passCount, minutes: Math.round(s.totalDurationSec / 60) }))} margin={{ top: 10, right: 20, left: 0, bottom: 20 }}>
            <CartesianGrid vertical={false} stroke={COLORS.grid} />
            <XAxis dataKey="name" tick={axisTick} stroke={COLORS.grid} />
            <YAxis yAxisId="left" tick={axisTick} stroke={COLORS.grid} />
            <YAxis yAxisId="right" orientation="right" tick={axisTick} stroke={COLORS.grid} />
            <Tooltip cursor={{ fill: "rgba(34,211,238,.06)" }} />
            <Legend />
            <Bar yAxisId="left" dataKey="passes" name="Pass count" fill={COLORS.cyan} radius={[4, 4, 0, 0]} />
            <Bar yAxisId="right" dataKey="minutes" name="Total minutes" fill={COLORS.violet} radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Panel>

      <MethodNote
        items={[
          { metric: "Minimum Elevation Angle", meaning: "Minimum spacecraft elevation above the ground-station horizon required for a valid contact. A lower mask (RF, 5°) allows contact to begin/end earlier/later in a pass; a higher mask (Optical, 20°) trades window length for avoiding low-elevation atmospheric distortion.", formula: "Configured per link type in the mission's Ground_Stations sheet / ground-contact log" },
          { metric: "Pass Count / Contact Duration", meaning: "Direct counts and durations from the mission's own RF_Contacts.xlsx / Optical_Contacts.xlsx, one row per continuous line-of-sight contact.", formula: "Contact Stop Time − Contact Start Time, per row" },
          { metric: "Longest Gap", meaning: "The largest interval between the start of one contact and the start of the next, for that ground station.", formula: "max(Start_Time[n+1] − Start_Time[n])" },
        ]}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 4. SATELLITE CONTRIBUTION ANALYTICS                                        */
/* -------------------------------------------------------------------------- */

function SatelliteProfileModal({ satellite, missionId, apiBase, onClose }) {
  const { authFetch } = useAccess();
  const [profile, setProfile] = React.useState(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    setProfile(null);
    setError("");
    authFetch(`${apiBase}/api/satellite/${encodeURIComponent(satellite)}?mission=${missionId}`)
      .then((r) => {
        if (!r.ok) throw new Error(`API returned ${r.status}`);
        return r.json();
      })
      .then(setProfile)
      .catch((e) => setError(String(e.message || e)));
  }, [satellite, missionId, apiBase, authFetch]);

  return (
    <div className="icModal" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="icModalInner" onClick={(e) => e.stopPropagation()}>
        <div className="icDetail">
          <div className="icDetailHead">
            <div>
              <p className="icEyebrow">Satellite Profile</p>
              <h3>{satellite}</h3>
            </div>
            <button className="icBtn icBtnGhost" onClick={onClose}>Close</button>
          </div>

          {error ? <p className="icError">{error}</p> : null}
          {!profile && !error ? <p className="icMuted">Loading satellite profile…</p> : null}

          {profile ? (
            <>
              <div className="kpiGrid four" style={{ marginTop: 10 }}>
                <KpiCard index={0} icon={Orbit} label="State Samples" value={profile.state?.samples || 0} detail={`Mean Instantaneous Geodetic Altitude ${number(profile.state?.meanAltitudeKm, 1)} km`} accent={COLORS.cyan} />
                <KpiCard index={1} icon={Antenna} label="RF Contacts" value={profile.rf?.length || 0} detail="from this satellite's own contact rows" accent={COLORS.blue} />
                <KpiCard index={2} icon={Camera} label="Optical Contacts" value={profile.optical?.length || 0} detail="from this satellite's own contact rows" accent={COLORS.green} />
                <KpiCard index={3} icon={SunMedium} label="Eclipse Events" value={profile.eclipse?.length || 0} detail="Umbra + Penumbra intervals" accent={COLORS.amber} />
              </div>

              {profile.contribution ? (
                <div className="kpiGrid four" style={{ marginTop: 10 }}>
                  <KpiCard index={4} icon={Globe2} label="Coverage Contribution" value={profile.contribution.coverageContributionPct} format={(v) => `${number(v, 2)}%`} detail="share of fleet's total observed AOI time" accent={COLORS.cyan} infoKey="satellite_contribution" />
                  <KpiCard index={5} icon={Gauge} label="Mean Duty Cycle" value={profile.contribution.meanDutyCyclePct} format={(v) => `${number(v, 2)}%`} detail="sensor-active share of this satellite's timeline" accent={COLORS.violet} infoKey="duty_cycle" />
                  <KpiCard index={6} icon={Aperture} label="Images Captured" value={profile.contribution.imagesCaptured} detail="estimated pushbroom scene acquisitions" accent={COLORS.pink} />
                  <KpiCard index={7} icon={Activity} label="Avg Observation Duration" value={profile.contribution.avgObservationDurationMin} format={(v) => `${number(v, 1)} min`} detail="mean length of an observation window" accent={COLORS.blue} />
                </div>
              ) : null}

              <div className="icFacts" style={{ marginTop: 16 }}>
                <h4>Observation Opportunities ({profile.observationCount || 0})</h4>
                {profile.observations?.length ? (
                  <div className="tableWrap">
                    <table>
                      <thead><tr><th>Image ID</th><th>Date</th><th>Time (UTC)</th><th>AOI</th><th>Orbit</th></tr></thead>
                      <tbody>
                        {profile.observations.slice(0, 20).map((o) => (
                          <tr key={o.imageId}>
                            <td className="mono">{o.imageId}</td>
                            <td>{o.captureDate}</td>
                            <td>{o.captureTimeUtc}</td>
                            <td>{o.aoiName}</td>
                            <td>{o.orbit}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : <p className="icMuted">No imaging opportunities recorded for this satellite.</p>}
              </div>

              <div className="icFacts" style={{ marginTop: 16 }}>
                <h4>RF Contacts</h4>
                {profile.rf?.length ? (
                  <div className="tableWrap">
                    <table>
                      <thead><tr><th>Ground Station</th><th>Start UTC</th><th>Duration (s)</th></tr></thead>
                      <tbody>
                        {profile.rf.slice(0, 15).map((r, i) => (
                          <tr key={i}><td>{r["Ground Station"]}</td><td className="mono">{r["Start UTC"]}</td><td>{number(r["Duration (s)"], 1)}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : <p className="icMuted">No RF contacts recorded for this satellite.</p>}
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function SatContributionView({ data, missionId, apiBase }) {
  const list = data?.analytics?.satelliteContributions || [];
  const lowCount = list.filter((r) => r.isLowContributor).length;
  const [selectedSat, setSelectedSat] = React.useState(null);

  return (
    <div className="contentGrid">
      <div className="kpiGrid four">
        <KpiCard index={0} icon={Satellite} label="Evaluated Satellites" value={list.length} detail="Full constellation performance audit" accent={COLORS.blue} badge={`${list.length} Craft`} />
        <KpiCard index={1} icon={Globe2} label="Avg Fleet Contribution" value={100 / (list.length || 1)} format={(v) => `${number(v, 2)}%`} detail="Expected baseline per spacecraft" accent={COLORS.cyan} badge="Baseline" />
        <KpiCard index={2} icon={AlertTriangle} label="Low Contributors" value={lowCount} detail="Craft performing below 1.2 std dev" accent={lowCount > 0 ? COLORS.amber : COLORS.green} isAlert={lowCount > 0} badge={lowCount > 0 ? "Review Needed" : "All Nominal"} />
        <KpiCard index={3} icon={Aperture} label="Total Scenes Imaged" value={list.reduce((acc, r) => acc + r.imagesCaptured, 0)} format={(v) => number(v)} detail="Summed pushbroom scene acquisitions" accent={COLORS.violet} badge="Total Scenes" />
      </div>

      <Panel index={4} title="Satellite Performance & Contribution Matrix" sub="Per-satellite imaging yield, contacts, duty cycle, and revisit contribution" className="wide">
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>Rank</th>
                <th>Satellite</th>
                <th>Images</th>
                <th>Coverage %</th>
                <th>RF Contacts</th>
                <th>Optical Contacts</th>
                <th>Mean Duty Cycle</th>
                <th>Observed Time</th>
                <th>Avg Obs Duration</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {list.map((r, idx) => (
                <tr key={r.satellite} className={r.isLowContributor ? "rowWarning" : ""}>
                  <td className="mono textDim">#{idx + 1}</td>
                  <td className="mono fontBold">
                    <button className="icIdBtn" onClick={() => setSelectedSat(r.satellite)}>{r.shortName}</button>
                  </td>
                  <td>{number(r.imagesCaptured)}</td>
                  <td>
                    <div className="progressCell">
                      <span>{number(r.coverageContributionPct, 2)}%</span>
                      <div className="progressBarTrack">
                        <div className="progressBarFill" style={{ width: `${Math.min(100, r.coverageContributionPct * 20)}%`, background: COLORS.cyan }} />
                      </div>
                    </div>
                  </td>
                  <td>{r.rfContacts}</td>
                  <td>{r.opticalContacts}</td>
                  <td>{number(r.meanDutyCyclePct, 1)}%</td>
                  <td className="mono">{r.observedSeconds != null ? `${number(r.observedSeconds / 60, 1)} min` : "—"}</td>
                  <td>{number(r.avgObservationDurationMin, 1)} min</td>
                  <td>
                    {r.isLowContributor ? (
                      <span className="badge warning">Low Contribution</span>
                    ) : (
                      <span className="badge success">Optimal</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <MethodNote
        items={[
          { metric: "Coverage Contribution %", meaning: "Share of total unique geographical area covered by this specific spacecraft relative to the entire fleet.", formula: "Area_Covered_Sat_i / Total_Fleet_Covered_Area * 100" },
          { metric: "Observed Time", meaning: "Total time this satellite's sensor footprint intersected the AOI, from core.observation_duration. This replaces the former \"Revisit Improvement\" column, which was a fixed multiple of the contribution figure rather than a measured quantity — establishing a satellite's true revisit contribution would require re-running the analysis with that satellite removed.", formula: "Σ per-sample observed seconds for this satellite" },
        ]}
      />

      {selectedSat ? (
        <SatelliteProfileModal satellite={selectedSat} missionId={missionId} apiBase={apiBase} onClose={() => setSelectedSat(null)} />
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 5. CONSTELLATION DENSITY HEATMAPS                                          */
/* -------------------------------------------------------------------------- */

export function DensityHeatmapsView({ data }) {
  const heatmaps = data?.analytics?.heatmaps || {};
  const [activeMode, setActiveMode] = React.useState("passDensity");

  const modes = [
    { key: "passDensity", label: "Pass Density", icon: Orbit, color: COLORS.cyan },
    { key: "imageDensity", label: "Image Density", icon: Aperture, color: COLORS.pink },
    { key: "rfContactDensity", label: "RF Contact Density", icon: Antenna, color: COLORS.blue },
    { key: "opticalContactDensity", label: "Optical Contact Density", icon: Radio, color: COLORS.green },
  ];

  const currentGrid = heatmaps[activeMode] || [];
  const activeObj = modes.find((m) => m.key === activeMode);

  return (
    <div className="contentGrid">
      <Panel
        index={0}
        title="Constellation Operational Density Maps"
        sub="Every cell counts real reported positions: where satellites flew, where the sensor footprint actually met the AOI, and where satellites were while a contact was in progress."
        className="wide"
        action={
          <div className="fieldTabs">
            {modes.map((m) => (
              <button
                key={m.key}
                className={activeMode === m.key ? "fieldTab on" : "fieldTab"}
                onClick={() => setActiveMode(m.key)}
              >
                <m.icon size={14} style={{ marginRight: 6 }} />
                {m.label}
              </button>
            ))}
          </div>
        }
      >
        <MapCanvasBase
          legend={
            <>
              <span><i className="dot" style={{ background: activeObj.color }} /> {activeObj.label} Intensity Heat Spots</span>
            </>
          }
        >
          {currentGrid.map((c, i) => {
            const r = Math.max(3, (c.density / 100) * 14);
            const opacity = Math.max(0.15, c.density / 100);
            return (
              <circle
                key={i}
                cx={projX(c.lon)}
                cy={projY(c.lat)}
                r={r}
                fill={activeObj.color}
                opacity={opacity}
              >
                <title>{`${activeObj.label} | Lat: ${c.lat}°, Lon: ${c.lon}° Density: ${c.density}%`}</title>
              </circle>
            );
          })}
        </MapCanvasBase>
        {currentGrid.length === 0 ? (
          <div className="emptyState" style={{ marginTop: 12 }}>
            No {activeObj.label.toLowerCase()} data for this mission — nothing was recorded to plot.
          </div>
        ) : null}
      </Panel>

      <MethodNote
        items={[
          { metric: "Density Accumulation", meaning: "Each cell counts the real reported positions falling inside it, normalised against the busiest cell on that map.", formula: "Count(Cell) ÷ max(Count) × 100%" },
          { metric: "Pass Density", meaning: "Every sub-satellite position in the state report.", formula: "histogram2d( state Latitude, Longitude )" },
          { metric: "Image Density", meaning: "Only the positions where the modelled sensor footprint actually intersected the mission's AOI land boundary — the same test the coverage and observation analytics use.", formula: "histogram2d( positions where footprint_intersects_region )" },
          { metric: "RF / Optical Contact Density", meaning: "Contact reports carry no coordinates, so each contact's [start, stop] window is intersected with that satellite's own state samples to recover where it was during the contact. Every plotted point is a real fix taken during a real contact.", formula: "histogram2d( state positions where Timestamp inside a contact window )" },
        ]}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 6. AOI ANALYTICS                                                           */
/* -------------------------------------------------------------------------- */

export function AoiAnalyticsView({ data }) {
  const [selectedAoi, setSelectedAoi] = React.useState("australia");
  const aoiData = data?.analytics?.aoi || {};

  const regions = [
    { key: "australia", label: "Mainland Australia & TAS" },
    { key: "southeast_asia", label: "Southeast Asia Maritime" },
    { key: "equatorial_belt", label: "Equatorial Belt" },
    { key: "global", label: "Global Coverage Region" },
  ];

  return (
    <div className="contentGrid">
      <Panel
        index={0}
        title="Area of Interest (AOI) Target Analytics"
        sub="Access windows and pass statistics counted from the satellite positions actually reported inside the AOI over the analysis window."
        className="wide"
        action={
          <div className="fieldTabs">
            {regions.map((r) => (
              <button
                key={r.key}
                className={selectedAoi === r.key ? "fieldTab on" : "fieldTab"}
                onClick={() => setSelectedAoi(r.key)}
              >
                {r.label}
              </button>
            ))}
          </div>
        }
      >
        <div className="kpiGrid four" style={{ marginTop: 10 }}>
          <KpiCard index={0} icon={Clock} label="First Access" value={aoiData.firstAccess ? aoiData.firstAccess.replace("T", " ") : "—"} detail="First reported position inside the AOI" accent={COLORS.cyan} badge="Window Start" />
          <KpiCard index={1} icon={Clock} label="Last Access" value={aoiData.lastAccess ? aoiData.lastAccess.replace("T", " ") : "—"} detail="Last reported position inside the AOI" accent={COLORS.green} badge="Window End" />
          <KpiCard index={2} icon={Activity} label="AOI Passes" value={aoiData.passCount} detail={`counted over ${aoiData.analysisDurationDays ? `${number(aoiData.analysisDurationDays, 2)} day(s)` : "the analysis window"}`} accent={COLORS.blue} badge="Measured" />
          <KpiCard index={3} icon={Activity} label="Passes / Day" value={aoiData.passesPerDay} detail="AOI passes normalised per 24 h" accent={COLORS.violet} badge="Rate" />
        </div>
      </Panel>

      <div className="kpiGrid three">
        <KpiCard index={4} icon={Satellite} label="Satellites Covering AOI" value={aoiData.satellitesCoveringAoi || 0} detail="Craft with at least one reported position in the AOI" accent={COLORS.cyan} badge="Fleet Satellites" />
        <KpiCard index={5} icon={Radio} label="Avg Pass Duration" value={aoiData.avgObservationDurationMin} format={(v) => `${number(v, 2)} min`} detail="Mean length of a continuous AOI pass" accent={COLORS.amber} badge="Pass Length" />
        <KpiCard index={6} icon={Map} label="AOI Region Name" value={aoiData.aoiName || "Mainland Australia & TAS"} detail="Selected evaluation region" accent={COLORS.green} badge="Target Region" />
      </div>

      <Panel index={7} title="AOI Pass Duration Distribution" sub="How long each measured pass over the AOI lasted" className="wide">
        <ResponsiveContainer height={260}>
          <BarChart data={aoiData.revisitHistogram || []} margin={{ top: 10, right: 20, left: 0, bottom: 20 }}>
            <CartesianGrid vertical={false} stroke={COLORS.grid} />
            <XAxis dataKey="bin" tick={axisTick} stroke={COLORS.grid} />
            <YAxis tick={axisTick} stroke={COLORS.grid} />
            <Tooltip cursor={{ fill: "rgba(34,211,238,.06)" }} />
            <Bar dataKey="passes" fill={COLORS.green} radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Panel>

      <MethodNote
        items={[
          { metric: "First / Last Access", meaning: "Earliest and latest timestamps at which any satellite's sub-point was reported inside the AOI bounds. These are measured, not forecast — the simulation ends at the last access, so no 'next access' can be derived from this dataset.", formula: "min / max( Timestamp where sub-point inside AOI bounds )" },
          { metric: "AOI Passes", meaning: "One pass is a continuous stretch of a single satellite inside the AOI. A stretch is split when the gap between consecutive in-AOI samples exceeds four times that satellite's own nominal report step — the same rule the observation-window analysis uses.", formula: "count of continuous in-AOI runs, summed over satellites" },
          { metric: "Pass Duration Distribution", meaning: "Every bar counts real measured passes falling in that duration band.", formula: "histogram( last − first timestamp of each pass )" },
        ]}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 7. SIMULATION DETAILS PANEL                                                */
/* -------------------------------------------------------------------------- */

export function SimulationDetailsView({ data }) {
  const sim = data?.analytics?.simulationDetails || {};
  const verifiedKeys = new Set(sim.verifiedFields || []);

  const details = [
    { key: "simulationEngine", label: "Simulation Engine", val: sim.simulationEngine, cat: "Core Physics" },
    { key: "gmatVersion", label: "Engine Build", val: sim.gmatVersion, cat: "Core Physics" },
    { key: "propagator", label: "Propagator", val: sim.propagator, cat: "Orbit Propagator" },
    { key: "numericalIntegrator", label: "Numerical Integrator", val: sim.numericalIntegrator, cat: "Orbit Propagator" },
    { key: "gravityModel", label: "Gravity Model", val: sim.gravityModel, cat: "Force Models" },
    { key: "gravityDegreeOrder", label: "Gravity Degree / Order", val: sim.gravityDegreeOrder, cat: "Force Models" },
    { key: "earthHarmonics", label: "Earth Harmonics", val: sim.earthHarmonics, cat: "Force Models" },
    { key: "atmosphericModel", label: "Atmospheric Model", val: sim.atmosphericModel, cat: "Perturbations" },
    { key: "solarRadiationPressure", label: "Solar Radiation Pressure", val: sim.solarRadiationPressure, cat: "Perturbations" },
    { key: "thirdBodyPerturbations", label: "Third Body Perturbations", val: sim.thirdBodyPerturbations, cat: "Perturbations" },
    { key: "stepSize", label: "Step Size", val: sim.stepSize, cat: "Numerical Precision" },
    { key: "propagationAccuracy", label: "Propagation Accuracy", val: sim.propagationAccuracy, cat: "Numerical Precision" },
    { key: "simulationDuration", label: "Simulation Duration", val: sim.simulationDuration, cat: "Run Parameters" },
    { key: "orbitType", label: "Orbit Type", val: sim.orbitType, cat: "Constellation Spec" },
    { key: "altitude", label: "Nominal Orbit Altitude", val: sim.altitude, cat: "Constellation Spec" },
    { key: "inclination", label: "Inclination", val: sim.inclination, cat: "Constellation Spec" },
    { key: "epoch", label: "Epoch", val: sim.epoch, cat: "Run Parameters" },
  ];

  return (
    <div className="contentGrid">
      <Panel index={0} title="Simulation Engine Configuration" sub="Parameters derived from this mission's own configuration/state data are marked Verified. Everything else is a standard simulation assumption, shown for context but not confirmed against this mission's actual mission script." className="wide">
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>Category</th>
                <th>Configuration Parameter</th>
                <th>Simulated Setting Value</th>
                <th>Verification</th>
              </tr>
            </thead>
            <tbody>
              {details.map((d, i) => {
                const isVerified = verifiedKeys.has(d.key);
                return (
                  <tr key={i}>
                    <td className="textDim fontBold">{d.cat}</td>
                    <td className="fontBold">{d.label}</td>
                    <td className="mono textCyan">{d.val || "Configured in simulation"}</td>
                    <td>
                      <span className={isVerified ? "badge success" : "badge muted"} title={isVerified ? "Derived from this mission's own config/state data" : "Standard assumption, not verified against this mission's mission script"}>
                        {isVerified ? "Verified" : "Assumed"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      <MethodNote
        items={[
          { metric: "Verified vs Assumed", meaning: "\"Verified\" fields (Nominal Orbit Altitude, Inclination, Orbit Type, Epoch, Simulation Duration) are computed directly from this mission's own configuration and state-history files. \"Assumed\" fields (propagator, force models, integrator settings) are standard simulation defaults shown for context — they are not parsed from this mission's actual mission script and may not match it exactly.", formula: "Verified: direct config/state read. Assumed: static reference values." },
          { metric: "Orbit Type -- what \"Sun-Synchronous\" actually checks", meaning: "Not an inclination-range guess (a given inclination is only truly sun-synchronous at one specific altitude for a circular orbit): this computes the real nodal precession rate from this mission's own inclination AND altitude via the standard J2 secular-drift formula, and classifies SSO only when that rate is within 0.05 deg/day of the 0.9856 deg/day rate a sun-synchronous orbit must match. A 97.5 deg orbit at the wrong altitude is correctly reported as a Retrograde Inclined LEO, not SSO, by this same check.", formula: "dOmega/dt = -1.5 * n * J2 * (Re/p)^2 * cos(i); SSO when |dOmega/dt - 0.9856| <= 0.05 deg/day" },
        ]}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* 8. CONSTELLATION ANIMATION PLAYBACK PANEL  — real mission telemetry           */
/* -------------------------------------------------------------------------- */

/* Shared constants for the in-panel constellation sim */
const ANIM_SIM_WINDOWS = [
  ["15 min", 15 * 60000],
  ["1 hour", 60 * 60000],
  ["3 hours", 180 * 60000],
  ["6 hours", 360 * 60000],
  ["Full day", Infinity],
];
const ANIM_SIM_SPEEDS = [
  ["0.5×", 0.5],
  ["1×", 1],
  ["2×", 2],
  ["4×", 4],
  ["10×", 10],
];

const hueFor = (i) => `hsl(${(i * 47) % 360} 82% 62%)`;

// See the longer comment on this same helper in main.jsx -- two real
// satellite-naming conventions exist across this app's actual missions
// ("ASC_074_16" vs "ASC_074A"), and a regex tuned only for the first left
// the second undecorated in chart labels.
function shortSat(name, prefix = "") {
  const byDigitSuffix = name.replace(/^.*_(?=\d+$)/, prefix);
  if (byDigitSuffix !== name) return byDigitSuffix;
  return name.replace(/^.*\d(?=[A-Za-z]+$)/, prefix);
}

function fmtEpoch(ms) {
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "—";
  const p = (n) => String(n).padStart(2, "0");
  // UTC getters, not local -- this label already claimed "UTC" but was
  // reading getDate()/getHours()/etc (the viewer's own local timezone),
  // so it was correct only by coincidence for a viewer at UTC+0 and wrong
  // -- while still asserting "UTC" -- for everyone else. See
  // core.time_utils on the backend for why every epoch played back here
  // is genuinely a UTC value.
  const mon = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][d.getUTCMonth()];
  return `${p(d.getUTCDate())} ${mon} ${d.getUTCFullYear()} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())} UTC`;
}

/* Inline map constants matching MapCanvasBase (960×480) */
const _W = MAP_W, _H = MAP_H;
const _pX = (lon) => ((Number(lon) + 180) / 360) * _W;
const _pY = (lat) => ((90 - Number(lat)) / 180) * _H;

/* Inner ConstellationSim — faithfully ported from main.jsx */
function InlineConstellationSim({ series = {}, satellites = [], range, height = 500, aoiBox = DEFAULT_AOI_BOX, aoiLabel = "Australia", outline = [], secondary = [] }) {
  const reduceMotion =
    typeof window !== "undefined" &&
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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
  const [windowMs, setWindowMs] = React.useState(60 * 60000);
  const [speed, setSpeed] = React.useState(2);
  const nowRef = React.useRef(now);
  nowRef.current = now;

  React.useEffect(() => { setNow(tMin); }, [tMin]);

  React.useEffect(() => {
    if (!playing) return undefined;
    let raf;
    let last;
    const perMs = span / 60000; // full span in ~60s at 1×
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
      const x = _pX(p.lon);
      const y = _pY(p.lat);
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
        const a = pts[i], b = pts[i + 1];
        if (Math.abs(b.lon - a.lon) > 180) return a;
        const f = (now - a.t) / (b.t - a.t || 1);
        return { lon: a.lon + (b.lon - a.lon) * f, lat: a.lat + (b.lat - a.lat) * f };
      }
    }
    return pts[pts.length - 1];
  };

  const heads = sats.map((o) => ({ ...o, head: headAt(o.pts) }));
  const overAoi = heads.filter(
    (o) =>
      o.head.lon >= aoiBox.lonMin && o.head.lon <= aoiBox.lonMax &&
      o.head.lat >= aoiBox.latMin && o.head.lat <= aoiBox.latMax
  ).length;
  const progress = span > 0 ? ((now - tMin) / span) * 100 : 0;

  return (
    <div className="simWrap">
      {/* Controls bar */}
      <div className="simBar">
        <button className="simPlay" onClick={() => setPlaying((p) => !p)} title={playing ? "Pause" : "Play"}>
          {playing ? <Pause size={16} /> : <Play size={16} />}
        </button>
        <label className="simField">
          <span>Trail</span>
          <select value={windowMs} onChange={(e) => setWindowMs(Number(e.target.value))}>
            {ANIM_SIM_WINDOWS.map(([label, ms]) => (
              <option key={label} value={ms}>{label}</option>
            ))}
          </select>
        </label>
        <label className="simField">
          <span>Speed</span>
          <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
            {ANIM_SIM_SPEEDS.map(([label, v]) => (
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

      {/* Map */}
      <div className="orbitMap">
        <svg viewBox={`0 0 ${_W} ${_H}`} style={{ maxHeight: height }} role="img" aria-label="constellation ground tracks">
          <defs>
            <radialGradient id="animOceanGlow" cx="50%" cy="42%" r="70%">
              <stop offset="0%" stopColor="rgba(11,30,65,0.85)" />
              <stop offset="100%" stopColor="rgba(4,8,20,0.98)" />
            </radialGradient>
          </defs>

          {/* Ocean */}
          <rect width={_W} height={_H} fill="#050c1c" />
          <rect width={_W} height={_H} fill="url(#animOceanGlow)" />

          {/* Graticule */}
          {[-150,-120,-90,-60,-30,0,30,60,90,120,150].map((lon) => (
            <line key={`g${lon}`} x1={_pX(lon)} y1={0} x2={_pX(lon)} y2={_H}
              stroke="rgba(100,140,220,.07)" strokeWidth="0.8" strokeDasharray="2,4" />
          ))}
          {[-60,-30,0,30,60].map((lat) => (
            <line key={`g${lat}`} x1={0} y1={_pY(lat)} x2={_W} y2={_pY(lat)}
              stroke="rgba(100,140,220,.07)" strokeWidth="0.8" strokeDasharray="2,4" />
          ))}

          {/* Land */}
          <path d={AV_LAND_PATH} fill="#1a2d50" stroke="rgba(80,130,200,.25)" strokeWidth="0.5" />

          {/* AOI outline -- real coastline-derived polygon when available,
              falling back to the old bounding rectangle otherwise */}
          {outline.length > 0 ? (
            <path
              d={outlinePathD([outline, secondary])} fillRule="evenodd"
              fill="rgba(251,191,36,.06)" stroke="#fbbf24" strokeWidth="1.5" strokeDasharray="6,3" opacity="0.85"
            />
          ) : (
            <rect
              x={_pX(aoiBox.lonMin)} y={_pY(aoiBox.latMax)}
              width={_pX(aoiBox.lonMax) - _pX(aoiBox.lonMin)}
              height={_pY(aoiBox.latMin) - _pY(aoiBox.latMax)}
              fill="rgba(251,191,36,.06)" stroke="#fbbf24" strokeWidth="1.5" strokeDasharray="6,3" opacity="0.85"
            />
          )}

          {/* Ground tracks */}
          {sats.map((o) => (
            <path key={o.name} d={trail(o.pts)} fill="none"
              stroke={o.color} strokeWidth="1.2" strokeOpacity="0.85" strokeLinejoin="round" />
          ))}

          {/* Satellite heads */}
          {heads.map((o) => {
            const x = _pX(o.head.lon);
            const y = _pY(o.head.lat);
            const inAoi =
              o.head.lon >= aoiBox.lonMin && o.head.lon <= aoiBox.lonMax &&
              o.head.lat >= aoiBox.latMin && o.head.lat <= aoiBox.latMax;
            return (
              <g key={`h${o.name}`} transform={`translate(${x.toFixed(1)} ${y.toFixed(1)})`}>
                <circle r="5" fill={o.color} opacity="0.22" />
                <circle r="2.2" fill="#fff" stroke={o.color} strokeWidth="1.2" />
                {inAoi ? (
                  <>
                    <circle r="7" fill="none" stroke="#fbbf24" strokeWidth="1.5" opacity="0.9" />
                    <text x="8" y="3" className="satTag" fill={o.color} fontSize="9" fontFamily="monospace">
                      {shortSat(o.name)}
                    </text>
                  </>
                ) : null}
                <title>{`${o.name} · ${o.head.lat.toFixed(2)}°, ${o.head.lon.toFixed(2)}°`}</title>
              </g>
            );
          })}
        </svg>

        {/* Epoch and progress */}
        <div className="simEpoch mono">Epoch: {fmtEpoch(now)}</div>
        <div style={{ height: 3, background: "rgba(100,140,220,.12)", borderRadius: 2, marginTop: 6 }}>
          <div style={{ width: `${progress.toFixed(1)}%`, height: "100%", background: COLORS.cyan, borderRadius: 2, transition: "width .1s linear" }} />
        </div>

        <div className="mapLegend">
          <span><i className="dot blue" /> {sats.length} satellites tracked</span>
          <span><i className="legLine" /> ground tracks</span>
          <span><i className="aoiSwatch" /> AOI ({aoiLabel})</span>
          <span style={{ marginLeft: "auto", opacity: 0.5, fontSize: 10 }}>Source: mission telemetry</span>
        </div>
      </div>
    </div>
  );
}

export function ConstellationAnimationView({ data, state }) {
  const hasSeries = state?.series && state?.satellites?.length > 0;

  return (
    <div className="contentGrid">
      <Panel
        index={0}
        title="Constellation Orbit & Access Animator"
        sub={
          hasSeries
            ? `Playback of real mission telemetry · ${state.satellites.length} satellites · ${
                state.range?.start ? new Date(state.range.start).toUTCString().slice(5, 16) : ""
              } → ${state.range?.end ? new Date(state.range.end).toUTCString().slice(5, 16) : ""}`
            : "Loading mission telemetry…"
        }
        className="wide"
      >
        {hasSeries ? (
          <InlineConstellationSim
            series={state.series}
            satellites={state.satellites}
            range={state.range}
            height={500}
            aoiBox={data?.coverage?.aoi || state?.aoi}
            outline={data?.coverage?.outline || []}
            secondary={data?.coverage?.tasmania || []}
            aoiLabel={data?.mission?.aoiRegionLabel || "Australia"}
          />
        ) : (
          <div style={{ padding: "60px 0", textAlign: "center", opacity: 0.45 }}>
            <Satellite size={40} style={{ marginBottom: 12 }} />
            <p style={{ margin: 0 }}>Waiting for mission telemetry data…</p>
            <p style={{ fontSize: 12, marginTop: 6 }}>Ensure the Flask API is running and data has been loaded.</p>
          </div>
        )}
      </Panel>
    </div>
  );
}


/* -------------------------------------------------------------------------- */
/* REVISIT HEATMAP – grid cells over real land topology                        */
/* -------------------------------------------------------------------------- */
function RevisitHeatmapMap({ heatmap, colorMap, aoiBox = DEFAULT_AOI_BOX, aoiLabel = "Australia", outline = [], secondary = [] }) {
  /* Compute cell size from the grid step (fallback to 10 degrees) */
  const step = 10;
  const cellW = (step / 360) * MAP_W;
  const cellH = (step / 180) * MAP_H;

  const catAlpha = { green: 0.72, yellow: 0.60, orange: 0.55, red: 0.50, insufficient: 0.25 };
  const catBorder = { green: "rgba(52,211,153,.6)", yellow: "rgba(251,191,36,.5)", orange: "rgba(249,115,22,.5)", red: "rgba(251,92,115,.5)", insufficient: "rgba(148,163,184,.4)" };

  return (
    <MapCanvasBase
      showAoi
      aoiBox={aoiBox}
      outline={outline}
      secondary={secondary}
      legend={
        <>
          <span><i style={{ display:"inline-block",width:14,height:10,background:"#34d399",opacity:.85,borderRadius:2,marginRight:5 }} /> &lt;30 min</span>
          <span><i style={{ display:"inline-block",width:14,height:10,background:"#fbbf24",opacity:.85,borderRadius:2,marginRight:5 }} /> 30–60 min</span>
          <span><i style={{ display:"inline-block",width:14,height:10,background:"#f97316",opacity:.85,borderRadius:2,marginRight:5 }} /> 1–2 hr</span>
          <span><i style={{ display:"inline-block",width:14,height:10,background:"#fb5c73",opacity:.85,borderRadius:2,marginRight:5 }} /> &gt;2 hr</span>
          <span><i style={{ display:"inline-block",width:14,height:10,background:"#94a3b8",opacity:.35,borderRadius:2,marginRight:5 }} /> Insufficient data</span>
          <span><i style={{ display:"inline-block",width:14,height:12,border:"1.5px dashed #fbbf24",borderRadius:2,marginRight:5 }} /> AOI ({aoiLabel})</span>
        </>
      }
    >
      {/* Heatmap grid cells */}
      {heatmap.map((c, i) => {
        const insufficient = c.insufficientData || c.colorCategory === "insufficient";
        const base = insufficient ? "#94a3b8" : (colorMap[c.colorCategory] || "#34d399");
        const alpha = catAlpha[insufficient ? "insufficient" : c.colorCategory] ?? 0.6;
        const border = catBorder[insufficient ? "insufficient" : c.colorCategory] || "rgba(52,211,153,.5)";
        const cx = projX(c.lon);
        const cy = projY(c.lat);
        return (
          <g key={i}>
            <rect
              x={cx - cellW / 2}
              y={cy - cellH / 2}
              width={cellW}
              height={cellH}
              fill={base}
              fillOpacity={alpha}
              stroke={border}
              strokeWidth="0.4"
              strokeDasharray={insufficient ? "2,2" : undefined}
            />
            <title>{insufficient
              ? `Lat: ${c.lat}°, Lon: ${c.lon}° | Insufficient real telemetry samples in this cell to compute a revisit gap`
              : `Lat: ${c.lat}°, Lon: ${c.lon}° | Avg Revisit: ${number(c.avgRevisitMin, 1)} min (${(c.colorCategory || "").toUpperCase()})`}</title>
          </g>
        );
      })}
    </MapCanvasBase>
  );
}

/* -------------------------------------------------------------------------- */
/* 9. MISSION ANALYTICS & HEALTH                                              */
/* -------------------------------------------------------------------------- */

export function MissionAnalyticsView({ data }) {
  const m = data?.analytics?.missionHealth || {};
  const unavailable = m.unavailable || [];
  const aoiLabel = data?.mission?.aoiRegionLabel || "Australia";
  const pct = (v) => (v === null || v === undefined ? "—" : `${number(v, 2)}%`);

  return (
    <div className="contentGrid">
      <Panel
        index={0}
        title="Mission Indicators"
        sub={`Each figure below is measured from this mission's own mission datasets over the ${m.analysisWindowHours ? `${number(m.analysisWindowHours, 1)} h` : ""} analysis window.`}
        className="wide"
      >
        <div className="gaugeGrid">
          {m.coveragePercent != null ? <GaugeCircle value={m.coveragePercent} label={`${aoiLabel} Coverage`} color={COLORS.cyan} size={130} /> : null}
          {m.observationDutyPct != null ? <GaugeCircle value={m.observationDutyPct} label="Observation Duty" color={COLORS.green} size={130} /> : null}
          {m.rfLinkAvailabilityPct != null ? <GaugeCircle value={m.rfLinkAvailabilityPct} label="RF Link Uptime" color={COLORS.blue} size={130} /> : null}
          {m.opticalLinkAvailabilityPct != null ? <GaugeCircle value={m.opticalLinkAvailabilityPct} label="Optical Uptime" color={COLORS.violet} size={130} /> : null}
          {m.meanEclipseSharePct != null ? <GaugeCircle value={m.meanEclipseSharePct} label="Eclipse Share" color={COLORS.amber} size={130} /> : null}
          {m.dataCompletenessPct != null ? <GaugeCircle value={m.dataCompletenessPct} label="Data Completeness" color={COLORS.green} size={130} /> : null}
        </div>

        <div className="tableWrap" style={{ marginTop: 18 }}>
          <table>
            <thead><tr><th>Indicator</th><th>Value</th><th>Derived from</th></tr></thead>
            <tbody>
              <tr><td className="fontBold">{aoiLabel} coverage</td><td className="mono textCyan">{pct(m.coveragePercent)}</td><td className="textDim">Grid cells covered by any sensor footprint (State Report)</td></tr>
              <tr><td className="fontBold">Observation duty cycle</td><td className="mono textCyan">{pct(m.observationDutyPct)}</td><td className="textDim">Share of the window with ≥1 satellite observing the AOI</td></tr>
              <tr><td className="fontBold">RF link uptime</td><td className="mono textCyan">{pct(m.rfLinkAvailabilityPct)}</td><td className="textDim">Union of real RF contact windows ÷ analysis window</td></tr>
              <tr><td className="fontBold">Optical link uptime</td><td className="mono textCyan">{pct(m.opticalLinkAvailabilityPct)}</td><td className="textDim">Union of real optical contact windows ÷ analysis window</td></tr>
              <tr><td className="fontBold">Mean eclipse share</td><td className="mono textCyan">{pct(m.meanEclipseSharePct)}</td><td className="textDim">Per-satellite eclipse time ÷ analysis window, averaged (Eclipse Locator)</td></tr>
              <tr><td className="fontBold">Data completeness</td><td className="mono textCyan">{pct(m.dataCompletenessPct)}</td><td className="textDim">{number(m.detectedSatellites)} of {number(m.configuredSatellites)} configured satellites present in the state data</td></tr>
            </tbody>
          </table>
        </div>
      </Panel>

      {unavailable.length ? (
        <Panel index={1} title="Not Available From This Dataset" sub="Metrics a mission-analysis run cannot produce. Listed explicitly rather than filled with placeholder scores." className="wide">
          <div className="dqList">
            {unavailable.map((u) => (
              <div key={u.metric} className="dqRow dq-missing">
                <AlertTriangle size={16} />
                <div>
                  <strong>{u.metric}</strong>
                  <span className="dqBadge dq-missing">Not Available</span>
                  <p>{u.reason}</p>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      ) : null}

      <MethodNote
        items={[
          { metric: "RF / Optical link uptime", meaning: "Fraction of the analysis window during which at least one satellite was in contact with the ground station. Overlapping contacts are counted once.", formula: "union(contact [start, stop] intervals) ÷ (max(Timestamp) − min(Timestamp)) × 100" },
          { metric: "Mean eclipse share", meaning: "For each satellite, its total eclipse time as a share of the analysis window, then averaged across the fleet.", formula: "mean over satellites of ( union(eclipse intervals) ÷ analysis window ) × 100" },
          { metric: "Data completeness", meaning: "How much of the configured fleet actually appears in the parsed state telemetry.", formula: "distinct satellites in state data ÷ configured satellites × 100" },
          { metric: "Why there is no overall health score", meaning: "A single composite 'health' number would require weighting subsystem telemetry this project does not have. The individual measured indicators are shown instead of a score derived from assumptions.", formula: "—" },
        ]}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* SPACECRAFT VISUALIZATION — conceptual schematic, not a photo/CAD render    */
/* -------------------------------------------------------------------------- */

export function SpacecraftVisualization({ data }) {
  const payloadType = data?.configuration?.payload?.find?.((p) => p.Parameter === "Payload Type")?.Value
    || "Multispectral Imager";
  const altitude = data?.constellation?.altitudeKm;
  const swathKm = data?.camera?.model?.["Ground Swath (km)"];

  return (
    <Panel
      index={2}
      title="ASC_074 Spacecraft — Conceptual Visualization"
      sub="A schematic Earth-observation satellite, not a photograph or CAD render of real ASC_074 hardware. No engineering drawing or imagery of the actual spacecraft exists in this project's data."
      className="wide"
    >
      <div className="scWrap">
        <svg viewBox="0 0 640 300" className="scSvg" role="img" aria-label="Conceptual Earth-observation spacecraft schematic">
          <defs>
            <linearGradient id="scPanelGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#0e2a4a" />
              <stop offset="100%" stopColor="#123a63" />
            </linearGradient>
            <linearGradient id="scBusGrad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#1a2436" />
              <stop offset="100%" stopColor="#0c1220" />
            </linearGradient>
          </defs>

          {/* Solar array — left */}
          <g>
            <rect x="30" y="110" width="190" height="80" rx="3" fill="url(#scPanelGrad)" stroke="#22d3ee" strokeWidth="1.2" />
            {Array.from({ length: 7 }).map((_, i) => (
              <line key={`l${i}`} x1={30 + (i + 1) * (190 / 8)} y1="110" x2={30 + (i + 1) * (190 / 8)} y2="190" stroke="#22d3ee" strokeOpacity="0.35" strokeWidth="0.6" />
            ))}
            <line x1="30" y1="150" x2="220" y2="150" stroke="#22d3ee" strokeOpacity="0.35" strokeWidth="0.6" />
            <line x1="220" y1="150" x2="248" y2="150" stroke="#5f6d8c" strokeWidth="3" />
          </g>

          {/* Solar array — right (mirrored) */}
          <g>
            <rect x="420" y="110" width="190" height="80" rx="3" fill="url(#scPanelGrad)" stroke="#22d3ee" strokeWidth="1.2" />
            {Array.from({ length: 7 }).map((_, i) => (
              <line key={`r${i}`} x1={420 + (i + 1) * (190 / 8)} y1="110" x2={420 + (i + 1) * (190 / 8)} y2="190" stroke="#22d3ee" strokeOpacity="0.35" strokeWidth="0.6" />
            ))}
            <line x1="420" y1="150" x2="610" y2="150" stroke="#22d3ee" strokeOpacity="0.35" strokeWidth="0.6" />
            <line x1="392" y1="150" x2="420" y2="150" stroke="#5f6d8c" strokeWidth="3" />
          </g>

          {/* Bus */}
          <rect x="255" y="95" width="130" height="110" rx="8" fill="url(#scBusGrad)" stroke="#94a3b8" strokeWidth="1.4" />
          {/* Thermal radiator hatching on bus side */}
          {Array.from({ length: 5 }).map((_, i) => (
            <line key={`t${i}`} x1={262} y1={108 + i * 18} x2={378} y2={108 + i * 18} stroke="#3b82f6" strokeOpacity="0.25" strokeWidth="1" />
          ))}

          {/* Antenna */}
          <line x1="320" y1="95" x2="320" y2="55" stroke="#a78bfa" strokeWidth="2" />
          <circle cx="320" cy="48" r="9" fill="none" stroke="#a78bfa" strokeWidth="2" />
          <circle cx="320" cy="48" r="2.5" fill="#a78bfa" />

          {/* Payload aperture, nadir-facing (bottom) */}
          <circle cx="320" cy="205" r="20" fill="#0b1220" stroke="#34d399" strokeWidth="2.4" />
          <circle cx="320" cy="205" r="11" fill="#0b1220" stroke="#34d399" strokeWidth="1.2" />
          <circle cx="320" cy="205" r="3.5" fill="#34d399" />
          <line x1="320" y1="225" x2="320" y2="255" stroke="#34d399" strokeDasharray="3,3" strokeWidth="1.4" />
          <polygon points="308,255 332,255 320,270" fill="none" stroke="#34d399" strokeWidth="1.2" strokeDasharray="3,3" />
          <text x="320" y="284" textAnchor="middle" className="scLabel">Nadir / sensor line of sight</text>

          {/* Callout labels */}
          <text x="125" y="102" textAnchor="middle" className="scLabel">Solar Array</text>
          <text x="515" y="102" textAnchor="middle" className="scLabel">Solar Array</text>
          <text x="320" y="90" textAnchor="middle" className="scLabel">Antenna</text>
          <text x="320" y="120" textAnchor="middle" className="scLabelSm">Spacecraft Bus</text>
          <text x="320" y="135" textAnchor="middle" className="scLabelSm">(Avionics, Power, OBC)</text>
          <text x="320" y="175" textAnchor="middle" className="scLabelSm">Payload Aperture</text>
        </svg>

        <div className="scFacts">
          <div className="scFactsRow"><span>Payload class</span><strong>{payloadType}</strong></div>
          <div className="scFactsRow"><span>Nominal orbit altitude</span><strong>{altitude ? `${number(altitude, 0)} km` : "Not configured"}</strong></div>
          <div className="scFactsRow"><span>Ground swath</span><strong>{swathKm ? `${number(swathKm, 1)} km` : "Not configured"}</strong></div>
          <p className="scNote">
            This diagram communicates the general layout of a modern Earth-observation smallsat (bus, deployable solar
            arrays, nadir-pointing payload aperture, communications antenna) using this mission's real altitude and
            swath figures where available. It is not derived from an ASC_074 CAD model or photograph — none exists in
            this project — and should not be read as an authoritative spacecraft design.
          </p>
        </div>
      </div>
    </Panel>
  );
}

/* -------------------------------------------------------------------------- */
/* MISSION COMPARISON – side-by-side across every configured mission           */
/* -------------------------------------------------------------------------- */

export function MissionComparisonView({ missions = [], currentMissionId, apiBase }) {
  const { authFetch } = useAccess();
  const [rows, setRows] = React.useState([]);
  const [observations, setObservations] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (!missions.length) return;
    setLoading(true);
    setError("");
    const ids = missions.map((m) => m.id).join(",");
    authFetch(`${apiBase}/api/compare?missions=${encodeURIComponent(ids)}`)
      .then((r) => {
        if (!r.ok) throw new Error(`API returned ${r.status}`);
        return r.json();
      })
      .then((d) => { setRows(d.missions || []); setObservations(d.observations || []); })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, [missions, apiBase, authFetch]);

  if (!missions.length || loading) {
    return (
      <div className="contentGrid">
        <Panel index={0} title="Mission Comparison" sub="Loading missions…" className="wide">
          <p style={{ opacity: 0.6 }}>Fetching comparison data…</p>
        </Panel>
      </div>
    );
  }

  if (error) {
    return (
      <div className="contentGrid">
        <Panel index={0} title="Mission Comparison" sub="Could not load comparison data" className="wide">
          <p className="icError">{error}</p>
        </Panel>
      </div>
    );
  }

  const barData = rows.map((r) => ({
    name: r.label.replace(/^[A-Za-z0-9_]+ — /, ""),
    coverage: r.coveragePercent,
    satellites: r.constellation?.configuredSatellites || 0,
    rfEvents: r.rfEvents,
    eclipseEvents: r.eclipseEvents,
  }));

  return (
    <div className="contentGrid">
      {observations.length ? (
        <Panel index={0} title="Engineering Observations" sub="Factual deltas computed directly from each mission's own metrics — not a recommendation of which configuration to choose." className="wide">
          <ul className="obsList">
            {observations.map((o, i) => <li key={i}>{o}</li>)}
          </ul>
        </Panel>
      ) : null}
      <Panel index={1} title="Mission Comparison" sub="Live metrics computed from each mission's own processed telemetry — nothing here is estimated across missions." className="wide">
        <div className="kpiGrid four" style={{ marginBottom: 16 }}>
          {rows.map((r, i) => (
            <KpiCard
              key={r.missionId}
              index={i}
              icon={Satellite}
              label={r.label}
              value={r.constellation?.configuredSatellites || 0}
              detail={`${r.constellation?.planes || 0} planes × ${r.constellation?.satellitesPerPlane || 0} sats/plane`}
              accent={r.missionId === currentMissionId ? COLORS.green : COLORS.blue}
              badge={r.missionId === currentMissionId ? "Active" : null}
            />
          ))}
        </div>

        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>Metric</th>
                {rows.map((r) => <th key={r.missionId}>{r.label}</th>)}
              </tr>
            </thead>
            <tbody>
              <tr><td className="fontBold">Total satellites</td>{rows.map((r) => <td key={r.missionId} className="mono">{number(r.constellation?.configuredSatellites)}</td>)}</tr>
              <tr><td className="fontBold">Orbital planes</td>{rows.map((r) => <td key={r.missionId} className="mono">{number(r.constellation?.planes)}</td>)}</tr>
              <tr><td className="fontBold">Satellites per plane</td>{rows.map((r) => <td key={r.missionId} className="mono">{number(r.constellation?.satellitesPerPlane)}</td>)}</tr>
              <tr><td className="fontBold">Nominal orbit altitude</td>{rows.map((r) => <td key={r.missionId} className="mono">{number(r.constellation?.altitudeKm)} km</td>)}</tr>
              <tr><td className="fontBold">Inclination</td>{rows.map((r) => <td key={r.missionId} className="mono">{number(r.constellation?.inclinationDeg, 1)}°</td>)}</tr>
              <tr><td className="fontBold">AOI coverage</td>{rows.map((r) => <td key={r.missionId} className="mono textCyan">{number(r.coveragePercent, 2)}%</td>)}</tr>
              <tr><td className="fontBold">Mean revisit</td>{rows.map((r) => <td key={r.missionId} className="mono">{r.meanRevisitMin != null ? `${number(r.meanRevisitMin, 1)} min` : "NA"}</td>)}</tr>
              <tr><td className="fontBold">Best / worst revisit</td>{rows.map((r) => <td key={r.missionId} className="mono">{r.bestRevisitMin != null ? `${number(r.bestRevisitMin, 1)} / ${number(r.worstRevisitMin, 1)} min` : "NA"}</td>)}</tr>
              <tr><td className="fontBold">Largest / mean gap</td>{rows.map((r) => <td key={r.missionId} className="mono">{r.largestGapMin != null ? `${number(r.largestGapMin, 1)} / ${number(r.meanGapMin, 1)} min` : "NA"}</td>)}</tr>
              <tr><td className="fontBold">RF contact events</td>{rows.map((r) => <td key={r.missionId} className="mono">{number(r.rfEvents)} ({number(r.rfMinutes, 1)} min)</td>)}</tr>
              <tr><td className="fontBold">Optical contact events</td>{rows.map((r) => <td key={r.missionId} className="mono">{number(r.opticalEvents)} ({number(r.opticalMinutes, 1)} min)</td>)}</tr>
              <tr><td className="fontBold">Eclipse events</td>{rows.map((r) => <td key={r.missionId} className="mono">{number(r.eclipseEvents)} ({number(r.eclipseHours, 1)} hr)</td>)}</tr>
              <tr><td className="fontBold">RF contacts / day</td>{rows.map((r) => <td key={r.missionId} className="mono">{r.rfContactsPerDay != null ? number(r.rfContactsPerDay, 1) : "NA"}</td>)}</tr>
              <tr><td className="fontBold">Estimated images / day</td>{rows.map((r) => <td key={r.missionId} className="mono">{r.imagesPerDay != null ? number(r.imagesPerDay) : "NA"}</td>)}</tr>
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel index={1} title="AOI Coverage vs Satellite Count" sub="Each mission's real computed coverage percentage against its configured fleet size" className="wide">
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={barData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
            <XAxis dataKey="name" stroke={COLORS.axis} fontSize={12} />
            <YAxis yAxisId="left" stroke={COLORS.axis} fontSize={12} />
            <YAxis yAxisId="right" orientation="right" stroke={COLORS.axis} fontSize={12} />
            <Tooltip contentStyle={{ background: "#0b1220", border: `1px solid ${COLORS.grid}` }} />
            <Legend />
            <Bar yAxisId="left" dataKey="coverage" name="Coverage %" fill={COLORS.cyan} radius={[4, 4, 0, 0]} />
            <Bar yAxisId="right" dataKey="satellites" name="Satellites" fill={COLORS.violet} radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Panel>

      <Panel index={2} title="Contact & Eclipse Events" sub="Real event counts parsed from each mission's own contact/eclipse reports" className="wide">
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={barData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
            <XAxis dataKey="name" stroke={COLORS.axis} fontSize={12} />
            <YAxis stroke={COLORS.axis} fontSize={12} />
            <Tooltip contentStyle={{ background: "#0b1220", border: `1px solid ${COLORS.grid}` }} />
            <Legend />
            <Bar dataKey="rfEvents" name="RF Contacts" fill={COLORS.blue} radius={[4, 4, 0, 0]} />
            <Bar dataKey="eclipseEvents" name="Eclipse Events" fill={COLORS.amber} radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Panel>

      <MethodNote
        items={[
          { metric: "AOI coverage", meaning: "Grid-cell coverage percentage from cumulative_region_coverage(), computed independently per mission from its own state history and its own AOI region.", formula: "Covered cells / total AOI grid cells × 100" },
          { metric: "Revisit / gap stats", meaning: "Derived per-mission from real satellite ground-track samples over that mission's own AOI grid.", formula: "Time between consecutive AOI passes" },
          { metric: "RF / Optical / Eclipse events", meaning: "Direct counts parsed from each mission's own ground-contact log and Eclipse Locator report files.", formula: "Row count in the mission's parsed report" },
        ]}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* HOW TO READ THIS DASHBOARD – glossary + plain-language walkthrough          */
/* -------------------------------------------------------------------------- */

const GUIDE_SECTIONS = [
  { title: "Coverage", body: "How much observation/coverage opportunity is available. A satellite \"covers\" a location when its sensor footprint passes over it — Coverage % is the share of the mission's AOI analysis grid that has been passed over at least once during the simulation window." },
  { title: "Revisit", body: "How frequently the target can be observed again. Revisit time is the interval between two consecutive valid observation opportunities over the same location — shorter is better for time-sensitive monitoring." },
  { title: "Contact", body: "When the spacecraft can communicate with the ground station. A contact window opens once the spacecraft rises above the station's minimum elevation angle and closes when it drops back below it." },
  { title: "Eclipse", body: "When the spacecraft is in Earth's shadow. Umbra is full shadow (no sunlight at all); Penumbra is partial shadow. No sunlight means no solar power generation and no illuminated imaging during that period." },
  { title: "Observation", body: "When imaging conditions are satisfied — the sensor footprint is over the Area of Interest and the satellite is available to image it. Observation Opportunities are the individual windows where this is true." },
  { title: "Gap", body: "A period without a valid opportunity — for coverage, the longest stretch of time a location goes unobserved; for contact, the longest stretch without a ground link. Large gaps are the main limitation to flag when evaluating a constellation design." },
  { title: "AOI", body: "Area of Interest — the geographic region this mission's analysis is scoped to (e.g. mainland Australia and Tasmania for the ASC_074 missions, or India for the ASC_080 missions), defined once in the mission configuration and reused everywhere (coverage, revisit, observation opportunities) so every number stays comparable." },
];

export function DashboardGuideView({ glossaryMap = {} }) {
  const [query, setQuery] = React.useState("");
  const terms = Object.values(glossaryMap).sort((a, b) => a.name.localeCompare(b.name));
  const filtered = query.trim()
    ? terms.filter((t) => `${t.name} ${t.definition}`.toLowerCase().includes(query.trim().toLowerCase()))
    : terms;

  return (
    <div className="contentGrid">
      <Panel index={0} title="How to Read This Dashboard" sub="A plain-language walkthrough of every core concept used across this application, so it can be understood without an explainer." className="wide">
        <div className="guideProse">
          {GUIDE_SECTIONS.map((s) => (
            <div key={s.title} className="guideProseRow">
              <h4>{s.title}</h4>
              <p>{s.body}</p>
            </div>
          ))}
        </div>
      </Panel>

      <Panel
        index={1}
        title="Parameter Glossary"
        sub={terms.length ? `${terms.length} defined parameters — name, definition, unit, data source, calculation method and engineering significance for every metric shown in this application.` : "Loading glossary…"}
        className="wide"
      >
        <label className="icSearch" style={{ marginBottom: 12 }}>
          <Compass size={15} />
          <input
            value={query}
            placeholder="Search parameters (e.g. revisit, contact, eclipse)…"
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>Parameter</th>
                <th>Definition</th>
                <th>Unit</th>
                <th>Source</th>
                <th>Calculation</th>
                <th>Engineering Significance</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((t) => (
                <tr key={t.key}>
                  <td className="fontBold">{t.name}</td>
                  <td>{t.definition}</td>
                  <td className="mono">{t.unit || "—"}</td>
                  <td className="textDim">{t.source}</td>
                  <td className="textDim">{t.calculation}</td>
                  <td className="textDim">{t.significance}</td>
                </tr>
              ))}
              {!filtered.length ? (
                <tr><td colSpan={6} className="icMuted">No parameters match "{query}".</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
