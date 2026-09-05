/* ------------------------------------------------------------------
   Mission Image Center
   Self-contained module: catalog, generation, gallery, detail and map.
   Imported by main.jsx; defines no component that existed before and
   mutates no existing state.
   ------------------------------------------------------------------ */

import React from "react";
import { feature } from "topojson-client";
import worldTopo from "world-atlas/land-110m.json";
import {
  Camera,
  CheckCircle2,
  Download,
  Filter,
  Grid3x3,
  Image as ImageIcon,
  Loader2,
  MapPin,
  Maximize2,
  Minimize2,
  RefreshCw,
  RotateCcw,
  Search,
  Satellite,
  ShieldCheck,
  Trash2,
  X,
  XCircle,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import "./imageCenter.css";
import { buildAccessUrl, useAccess } from "./access.jsx";
import { InfoPopover } from "./glossary.jsx";

// See the note in main.jsx: `??` so a production build's empty base yields
// same-origin requests instead of falling back to localhost.
const API = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:5001";
const IC = `${API}/api/imagecenter`;

/* ---------------------------- helpers ---------------------------- */

const num = (v, d = 2) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(d);

const bytes = (b) => {
  if (!b && b !== 0) return "—";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  let n = Number(b);
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i += 1; }
  return `${n.toFixed(n < 10 && i > 0 ? 1 : 0)} ${u[i]}`;
};

const coord = (v, pos, neg) =>
  v === null || v === undefined ? "—" : `${Math.abs(Number(v)).toFixed(4)}° ${Number(v) >= 0 ? pos : neg}`;

/* `fetcher` is the access-aware fetch from the AccessProvider. It is passed
   in rather than imported because getJSON is a plain module function, not a
   hook. Falls back to bare fetch only for callers outside the provider. */
async function getJSON(url, fetcher = fetch) {
  const r = await fetcher(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

/* Every Image Center endpoint is mission-scoped: append ?mission=<id> (or
   &mission=<id> if the path already carries a query string). */
function icUrl(path, missionId) {
  const sep = path.includes("?") ? "&" : "?";
  return `${IC}${path}${sep}mission=${encodeURIComponent(missionId || "asc074_6x8")}`;
}

/* ------------------- Region-focused footprint map -------------------
   Deliberately a separate, regionally-scaled map rather than the world
   MapBase used elsewhere: a 69 km footprint is sub-pixel on a world
   projection and would be invisible. Two mission AOI regions exist today
   (core.regions -- Australia and India); the region whose box actually
   contains the footprint being plotted is picked at render time, so this
   generalises to a new AOI region without the caller needing to know
   which mission it belongs to. */

const MW = 720;

function buildRegion(box, gratLons, gratLats) {
  const mh = (MW * (box.latMax - box.latMin)) / (box.lonMax - box.lonMin);
  const rx = (lon) => ((Number(lon) - box.lonMin) / (box.lonMax - box.lonMin)) * MW;
  const ry = (lat) => ((box.latMax - Number(lat)) / (box.latMax - box.latMin)) * mh;
  let land = "";
  try {
    const geo = feature(worldTopo, worldTopo.objects.land);
    const features = geo.features || [geo];
    features.forEach((f) => {
      const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
      polys.forEach((poly) =>
        poly.forEach((ring) => {
          // Cheap reject: skip rings entirely outside this region's window.
          const lons = ring.map((p) => p[0]);
          const lats = ring.map((p) => p[1]);
          if (Math.max(...lons) < box.lonMin || Math.min(...lons) > box.lonMax) return;
          if (Math.max(...lats) < box.latMin || Math.min(...lats) > box.latMax) return;
          ring.forEach((pt, i) => {
            land += `${i === 0 ? "M" : "L"}${rx(pt[0]).toFixed(1)} ${ry(pt[1]).toFixed(1)}`;
          });
          land += "Z";
        })
      );
    });
  } catch (err) {
    land = "";
  }
  return { box, mh, rx, ry, land, gratLons, gratLats };
}

const MAP_REGIONS = {
  australia: buildRegion({ lonMin: 108, lonMax: 158, latMin: -46, latMax: -8 }, [110, 120, 130, 140, 150], [-10, -20, -30, -40]),
  india: buildRegion({ lonMin: 63, lonMax: 103, latMin: 3, latMax: 43 }, [70, 80, 90, 100], [10, 20, 30, 40]),
};

function regionFor(lon, lat) {
  if (lon != null && lat != null) {
    const hit = Object.values(MAP_REGIONS).find(
      (r) => lon >= r.box.lonMin && lon <= r.box.lonMax && lat >= r.box.latMin && lat <= r.box.latMax
    );
    if (hit) return hit;
  }
  return MAP_REGIONS.australia;
}

function FootprintMap({ geometry, height = 380 }) {
  if (!geometry) return <div className="icMapEmpty">Select an image to plot its footprint</div>;

  const fp = geometry.footprint || [];
  const track = geometry.groundTrack || [];
  const pos = geometry.satellitePosition || {};
  const anchor = pos.lat !== undefined ? pos : fp[0] || track[0] || {};
  const region = regionFor(anchor.lon, anchor.lat);
  const { mh: MH, rx, ry, land: REGION_LAND } = region;

  const fpPath = fp.length
    ? fp.map((p, i) => `${i === 0 ? "M" : "L"}${rx(p.lon).toFixed(1)} ${ry(p.lat).toFixed(1)}`).join("") + "Z"
    : "";
  const trackPath = track.length
    ? track.map((p, i) => `${i === 0 ? "M" : "L"}${rx(p.lon).toFixed(1)} ${ry(p.lat).toFixed(1)}`).join("")
    : "";

  return (
    <svg className="icMap" viewBox={`0 0 ${MW} ${MH}`} style={{ height }} role="img"
         aria-label="Capture footprint location map">
      <defs>
        <radialGradient id="icOcean" cx="50%" cy="45%" r="70%">
          <stop offset="0%" stopColor="#102a4a" />
          <stop offset="100%" stopColor="#081426" />
        </radialGradient>
      </defs>
      <rect width={MW} height={MH} fill="url(#icOcean)" />
      {region.gratLons.map((lon) => (
        <g key={lon}>
          <line x1={rx(lon)} y1={0} x2={rx(lon)} y2={MH} className="icGrat" />
          <text x={rx(lon) + 3} y={MH - 5} className="icGratLabel">{lon}°E</text>
        </g>
      ))}
      {region.gratLats.map((lat) => (
        <g key={lat}>
          <line x1={0} y1={ry(lat)} x2={MW} y2={ry(lat)} className="icGrat" />
          <text x={4} y={ry(lat) - 4} className="icGratLabel">{lat}°</text>
        </g>
      ))}
      <path d={REGION_LAND} className="icLand" />
      {trackPath ? <path d={trackPath} className="icTrack" /> : null}
      {fpPath ? <path d={fpPath} className="icFootprint" /> : null}
      {pos.lat !== undefined ? (
        <g>
          <circle cx={rx(pos.lon)} cy={ry(pos.lat)} r={9} className="icSatHalo" />
          <circle cx={rx(pos.lon)} cy={ry(pos.lat)} r={3.4} className="icSat" />
        </g>
      ) : null}
      <g className="icLegend" transform={`translate(12 ${MH - 58})`}>
        <rect width={210} height={46} rx={8} />
        <circle cx={16} cy={16} r={3.5} className="icSat" />
        <text x={28} y={20}>Satellite sub-point</text>
        <rect x={10} y={30} width={12} height={8} className="icFootprint" />
        <text x={28} y={38}>Camera footprint</text>
      </g>
    </svg>
  );
}

/* --------------------------- status pill --------------------------- */

function StatusPill({ status }) {
  const map = {
    "Generated": "icPill icPillOk",
    "Not Generated": "icPill icPillIdle",
    "Generating": "icPill icPillBusy",
    "Failed": "icPill icPillBad",
  };
  return <span className={map[status] || "icPill icPillIdle"}>{status}</span>;
}

/* --------------------------- download menu --------------------------- */

/* Each format, and the product file it needs on disk. A deployment may ship
   previews and metadata without the full-resolution GeoTIFFs, so a format
   whose file is absent is shown disabled with the reason rather than being
   offered and then failing on click. `null` means always available -- the
   metadata formats are rendered from JSON, and the ZIP bundles whatever
   exists. */
const FORMATS = [
  ["png", "PNG", "png"],
  ["jpeg", "JPEG", "png"],
  ["geotiff", "GeoTIFF", "geotiff"],
  ["json", "Metadata JSON", null],
  ["csv", "Metadata CSV", null],
  ["zip", "ZIP bundle", null],
];

const MISSING_ASSET_HINT =
  "Not available on this deployment — regenerate this observation to rebuild it.";

// Image Center's two sections share one download gate, the same way they
// already share one view gate on the server (see IC_SECTIONS in
// api_image_center.py) -- whichever section's download code the person was
// given, either one unlocks downloading here.
const IC_DOWNLOAD_SECTIONS = ["ic-catalog", "ic-gallery"];

function DownloadMenu({ imageId, missionId, disabled, assets, onDownloaded }) {
  const { authFetch, requestDownload } = useAccess();
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef(null);

  React.useEffect(() => {
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);

  const grab = (kind) => {
    requestDownload(IC_DOWNLOAD_SECTIONS, (freshToken) => {
      // window.open cannot carry the auth header, so the signed token goes in
      // the query string, which the server also accepts.
      window.open(buildAccessUrl(icUrl(`/image/${imageId}/download/${kind}`, missionId), freshToken), "_blank");
      authFetch(icUrl(`/image/${imageId}/downloaded`, missionId), { method: "POST" })
        .then(() => onDownloaded && onDownloaded())
        .catch(() => {});
    });
    setOpen(false);
  };

  return (
    <div className="icDlWrap" ref={ref}>
      <button className="icBtn icBtnGhost" disabled={disabled} onClick={() => setOpen((v) => !v)}>
        <Download size={14} /> Download
      </button>
      {open && !disabled ? (
        <div className="icDlMenu">
          {FORMATS.map(([k, label, needs]) => {
            // Absent `assets` means the caller has not loaded them; assume
            // present rather than disabling everything on a slow response.
            const missing = needs && assets && assets[needs] === false;
            return (
              <button key={k} onClick={() => grab(k)} disabled={!!missing}
                      title={missing ? MISSING_ASSET_HINT : undefined}>
                {label}{missing ? <span className="icDlUnavail">unavailable</span> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

/* ---------------------------- detail view ---------------------------- */

/* Provenance of a single field, so a reader can tell a measurement from a
   modelled value at a glance rather than having to know the pipeline. */
const TAG_TITLE = {
  measured: "From GMAT telemetry or mission configuration",
  derived: "Computed from measured values",
  simulated: "Produced by the sensor/atmosphere simulation — not a measurement",
  assumed: "Representative value, not configured for this mission",
};

function Row({ label, value, tag, infoKey }) {
  return (
    <div className="icRow">
      <span>
        {label}
        {infoKey ? <InfoPopover infoKey={infoKey} /> : null}
      </span>
      <strong>
        {value ?? "—"}
        {tag ? <i className={`icTag icTag-${tag}`} title={TAG_TITLE[tag]}>{tag}</i> : null}
      </strong>
    </div>
  );
}

function QualityPill({ status, label }) {
  const cls = status === "unusable" ? "icPill icPillBad"
    : status === "quality_limited" ? "icPill icPillWarn"
    : "icPill icPillOk";
  return <span className={cls}>{label}</span>;
}

/* Zoom/pan viewer. CSS transform only -- no imaging library needed for
   inspecting a single raster. */
function ImageViewer({ src, alt }) {
  const [zoom, setZoom] = React.useState(1);
  const [pan, setPan] = React.useState({ x: 0, y: 0 });
  const [full, setFull] = React.useState(false);
  const drag = React.useRef(null);

  const reset = () => { setZoom(1); setPan({ x: 0, y: 0 }); };

  const onWheel = (e) => {
    e.preventDefault();
    setZoom((z) => Math.min(8, Math.max(1, z * (e.deltaY < 0 ? 1.15 : 1 / 1.15))));
  };
  const onDown = (e) => { drag.current = { x: e.clientX - pan.x, y: e.clientY - pan.y }; };
  const onMove = (e) => {
    if (!drag.current || zoom === 1) return;
    setPan({ x: e.clientX - drag.current.x, y: e.clientY - drag.current.y });
  };
  const onUp = () => { drag.current = null; };

  React.useEffect(() => {
    if (!full) return;
    const esc = (e) => { if (e.key === "Escape") setFull(false); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [full]);

  const frame = (
    <div
      className="icPreviewFrame"
      onWheel={onWheel}
      onMouseDown={onDown}
      onMouseMove={onMove}
      onMouseUp={onUp}
      onMouseLeave={onUp}
      style={{ cursor: zoom > 1 ? "grab" : "default" }}
    >
      <img
        className="icPreviewLarge"
        src={src}
        alt={alt}
        draggable={false}
        style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}
      />
      <span className="icSimBadge" title="Real Sentinel-2 surface reflectance, composited with a simulated ASC_074 sensor pass — not an unmodified archival scene">
        SIMULATED PRODUCT
      </span>
      <div className="icViewerTools">
        <button title="Zoom in" onClick={() => setZoom((z) => Math.min(8, z * 1.4))}><ZoomIn size={14} /></button>
        <button title="Zoom out" onClick={() => setZoom((z) => Math.max(1, z / 1.4))}><ZoomOut size={14} /></button>
        <button title="Reset view" onClick={reset}><RotateCcw size={14} /></button>
        <button title={full ? "Exit full screen (Esc)" : "Full screen"} onClick={() => { setFull((v) => !v); reset(); }}>
          {full ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
        </button>
        <span className="icZoomLabel">{zoom.toFixed(1)}×</span>
      </div>
    </div>
  );

  if (!full) return frame;
  return (
    <div className="icFullscreen" onClick={(e) => { if (e.target === e.currentTarget) setFull(false); }}>
      {frame}
    </div>
  );
}

function ImageDetail({ imageId, missionId, onClose, onChanged }) {
  const { authFetch, withAccess } = useAccess();
  const [detail, setDetail] = React.useState(null);
  const [geometry, setGeometry] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const load = React.useCallback(() => {
    setError("");
    Promise.all([
      getJSON(icUrl(`/image/${imageId}`, missionId), authFetch),
      getJSON(icUrl(`/image/${imageId}/geometry`, missionId), authFetch),
    ])
      .then(([d, g]) => { setDetail(d); setGeometry(g); })
      .catch((e) => setError(String(e.message || e)));
  }, [imageId, missionId, authFetch]);

  React.useEffect(load, [load]);

  const generate = async (regenerate = false) => {
    setBusy(true); setError("");
    try {
      const r = await authFetch(icUrl(`/image/${imageId}/generate`, missionId), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ regenerate }),
      });
      const j = await r.json();
      if (!j.ok) throw new Error(j.error || "Generation failed");
      load();
      onChanged && onChanged();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  if (error && !detail) return <div className="icDetail"><p className="icError">{error}</p></div>;
  if (!detail) return <div className="icDetail"><p className="icMuted">Loading image record…</p></div>;

  const generated = detail.generationStatus === "Generated";
  const p = detail.product || {};
  const sensor = p.sensor || {};
  const validation = p.validation || {};
  const quality = p.quality || {};
  const prov = p.provenance || {};
  const coordVal = p.coordinateValidation || null;
  const refMeta = p.reference || null;
  const solarMeta = p.solar || null;
  const geoVal = p.geospatialValidation || null;
  const spectral = p.spectral || null;
  const hasReferenceImage = detail?.assets?.reference !== false;

  const deliveredPx = Number(String(detail.deliveredResolution || "").split("x")[0]) || null;
  const deliveredGsd = deliveredPx && detail.swathWidthKm
    ? (detail.swathWidthKm * 1000) / deliveredPx
    : detail.gsdM;

  const qStatus = detail.qualityStatus || validation.status;
  const qLabel = detail.qualityLabel || validation.label;

  return (
    <div className="icDetail">
      <div className="icDetailHead">
        <div>
          <p className="icEyebrow">Simulated Earth Observation Product</p>
          <h3>{detail.imageId}</h3>
          <div className="icHeadPills">
            <StatusPill status={detail.generationStatus} />
            {generated && qLabel ? <QualityPill status={qStatus} label={qLabel} /> : null}
          </div>
        </div>
        <div className="icDetailActions">
          {generated ? (
            <>
              <DownloadMenu imageId={imageId} missionId={missionId} assets={detail?.assets} onDownloaded={load} />
              <button className="icBtn icBtnGhost" disabled={busy} onClick={() => generate(true)}>
                <RefreshCw size={14} /> Regenerate
              </button>
            </>
          ) : (
            <button className="icBtn icBtnPrimary" disabled={busy} onClick={() => generate(false)}>
              {busy ? <Loader2 size={14} className="icSpin" /> : <Camera size={14} />}
              {busy ? "Generating…" : "Generate image"}
            </button>
          )}
          {onClose ? <button className="icBtn icBtnGhost" onClick={onClose}><X size={14} /></button> : null}
        </div>
      </div>

      {error ? <p className="icError">{error}</p> : null}
      {busy ? (
        <p className="icNotice">
          Retrieving Sentinel-2 source imagery, mosaicking granules and simulating the
          pushbroom sensor. This typically takes 1–2 minutes.
        </p>
      ) : null}

      {generated && validation.issues?.length ? (
        <div className={`icValidation icValidation-${qStatus}`}>
          <strong>{qLabel}</strong>
          <ul>
            {validation.issues.map((i, n) => (
              <li key={n}><code>{i.check}</code> {i.detail}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="icDetailGrid">
        <div className="icPreviewPane">
          {generated ? (
            <ImageViewer
              src={withAccess(icUrl(`/image/${imageId}/preview`, missionId))}
              alt={detail.imageId}
            />
          ) : (
            <div className="icPreviewEmpty">
              <ImageIcon size={34} />
              <p>Not generated</p>
              <span>Generate to retrieve and simulate this scene</span>
            </div>
          )}
        </div>

        <div className="icFacts">
          <h4>Mission Observation Product</h4>
          <Row label="Observation ID" value={detail.imageId} tag="derived" />
          <Row label="Satellite" value={detail.satellite} tag="measured" />
          <Row label="Mission" value={String(detail.imageId || "").split("-")[0] || "—"} tag="measured" />
          <Row label="Acquisition (UTC)" value={`${detail.captureDate} ${detail.captureTimeUtc}`} tag="simulated" />
          <Row label="Instantaneous geodetic altitude" value={`${num(detail.altitudeKm, 1)} km`} tag="measured" infoKey="instantaneous_geodetic_altitude" />
          <Row label="Orbit number / pass" value={`${detail.orbit} / ${detail.orbitPass}`} tag="measured" />
          <Row label="Sensor" value="Multispectral optical (R, G, B, NIR)" tag="assumed" />
          <Row label="Observation mode" value={detail.cameraOrientation || "Nadir"} tag="assumed" />
          <Row label="Ground resolution" value={`${num(deliveredGsd, 1)} m/px delivered`} tag="derived" infoKey="estimated_ground_resolution" />
          <Row label="AOI / target" value={detail.aoiName} tag="derived" />

          <h4>Quality</h4>
          <Row label="Quality score" value={quality.score != null ? `${num(quality.score, 1)} / 100 · ${quality.grade}` : "—"} tag="derived" infoKey="image_quality_score" />
          <Row label="Cloud cover" value={detail.cloudCoverPercent == null ? "—" : `${num(detail.cloudCoverPercent, 2)} %`} tag="derived" infoKey="cloud_cover_percent" />
          <Row label="Usable image" value={validation.measurements?.validDataPercent != null ? `${num(validation.measurements.validDataPercent, 1)} %` : "—"} tag="derived" infoKey="usable_image_percent" />
          <Row label="Pure black / clipped white" value={validation.measurements ? `${num(validation.measurements.pureBlackPercent, 2)} % / ${num(validation.measurements.clippedWhitePercent, 2)} %` : "—"} tag="derived" />
          <Row label="Coverage area" value={`${num(detail.footprintAreaKm2, 0)} km²`} tag="derived" />
          <Row label="Observation geometry" value={`${num(detail.cameraHeadingDeg, 1)}° heading`} tag="measured" infoKey="observation_geometry" />

          <h4>Geometry</h4>
          <Row label="Latitude" value={coord(detail.latitude, "N", "S")} tag="measured" />
          <Row label="Longitude" value={coord(detail.longitude, "E", "W")} tag="measured" />
          <Row label="Swath width" value={`${num(detail.swathWidthKm, 2)} km`} tag="derived" />
          <Row label="Native resolution" value={detail.estimatedResolution} tag="derived" />
          <Row label="Delivered resolution" value={detail.deliveredResolution} tag="derived" />
          <Row label="Delivered volume" value={bytes(detail.deliveredSizeBytes)} tag="derived" />

          {generated && sensor.alongTrackSmearPx !== undefined ? (
            <>
              <h4>Sensor simulation</h4>
              <Row label="Along-track smear" value={`${num(sensor.alongTrackSmearPx, 2)} px`} tag="simulated" />
              <Row label="MTF sigma" value={`${num(sensor.mtfSigmaPx, 2)} px`} tag="assumed" />
              <Row label="Estimated SNR" value={num(sensor.estimatedSnr, 1)} tag="simulated" />
              <Row label="Bit depth" value={sensor.bitDepth} tag="assumed" />
              <Row label="No-data pixels" value={sensor.noDataPixelPercent != null ? `${num(sensor.noDataPixelPercent, 2)} %` : "—"} tag="measured" />
              {sensor.atmosphere ? (
                <Row label="Atmosphere" value={`Modelled · air mass ${num(sensor.atmosphere.airMass, 2)}`} tag="simulated" infoKey="simulated_atmosphere" />
              ) : null}
              {spectral ? (
                <Row
                  label="Spectral bands"
                  value="Sentinel-2 MSI proxy (not ASC_074 spec)"
                  tag="assumed"
                  infoKey="spectral_band_proxy"
                />
              ) : null}
            </>
          ) : null}
        </div>
      </div>

      <div className="icMapBlock">
        <h4><MapPin size={14} /> Capture location, footprint and ground track</h4>
        <FootprintMap geometry={geometry} />
      </div>

      {generated ? (
        <div className="icProvenance">
          <h4>Data provenance</h4>
          <div className="icProvGrid">
            <div><span>Simulated imagery</span><p>Sensor response, acquisition timing and geometry are modelled from GMAT telemetry and the mission camera configuration.</p></div>
            <div><span>Real source reflectance</span><p>{prov.sourceCollection || "Sentinel-2 L2A"}{prov.sourceDatetime ? ` · acquired ${String(prov.sourceDatetime).slice(0, 10)}` : ""}{prov.mosaicSceneCount ? ` · ${prov.mosaicSceneCount} granule(s) mosaicked` : ""}</p></div>
            <div><span>Assumed parameters</span><p>Integration time, read noise, full well, MTF sigma and the atmospheric model are representative values, not mission-configured data.</p></div>
            <div><span>Validated orbital data</span><p>Sub-satellite position, altitude, orbit and pass number come from the mission's GMAT state report.</p></div>
          </div>
          <p className="icProvNote">{prov.note}</p>
        </div>
      ) : null}

      {generated ? <GeospatialValidationPanel
        imageId={imageId}
        missionId={missionId}
        detail={detail}
        coordVal={coordVal}
        refMeta={refMeta}
        solarMeta={solarMeta}
        geoVal={geoVal}
        hasReferenceImage={hasReferenceImage}
      /> : null}
    </div>
  );
}

/* -------------------- Geospatial Validation panel -------------------- */

function GeoCheckItem({ ok, label }) {
  return (
    <div className={`icGeoCheckItem ${ok ? "icGeoCheckOk" : "icGeoCheckFail"}`}>
      {ok ? <CheckCircle2 size={15} /> : <XCircle size={15} />}
      <span>{label}</span>
    </div>
  );
}

function GeospatialValidationPanel({ imageId, missionId, detail, coordVal, refMeta, solarMeta, geoVal, hasReferenceImage }) {
  const { withAccess } = useAccess();
  const checklist = geoVal?.checklist || {
    coordinatesValidated: !!coordVal?.valid,
    footprintCalculated: true,
    sensorModelApplied: true,
    referenceSceneMatched: hasReferenceImage,
  };
  const landCover = geoVal?.landCoverSimilarity;
  const confidence = geoVal?.overallConfidence;

  return (
    <div className="icGeoValidation">
      <h4><ShieldCheck size={14} /> Geospatial Validation</h4>
      <p className="icGeoIntro">
        Checks that the simulated product is geographically and physically consistent with its real
        observation location, and compares it against the real Earth imagery it was derived from. This
        is an engineering self-check, not an independent scientific validation.
      </p>

      <div className="icGeoChecklist">
        <GeoCheckItem ok={!!checklist.coordinatesValidated} label="Coordinates Validated" />
        <GeoCheckItem ok={!!checklist.footprintCalculated} label="Footprint Calculated" />
        <GeoCheckItem ok={!!checklist.sensorModelApplied} label="Sensor Model Applied" />
        <GeoCheckItem ok={!!checklist.referenceSceneMatched} label="Reference Scene Matched" />
      </div>

      <div className="icGeoCompare">
        <div className="icGeoCompareCol">
          <p className="icGeoCompareLabel">Simulated Observation</p>
          <img
            className="icGeoCompareImg"
            src={withAccess(icUrl(`/image/${imageId}/preview`, missionId))}
            alt="Simulated observation"
          />
        </div>
        <div className="icGeoCompareCol">
          <p className="icGeoCompareLabel">Earth Reference</p>
          {hasReferenceImage ? (
            <img
              className="icGeoCompareImg"
              src={withAccess(icUrl(`/image/${imageId}/reference`, missionId))}
              alt="Real Earth reference, not an ASC_074 acquisition"
            />
          ) : (
            <div className="icGeoCompareMissing">
              No reference image for this product — regenerate to produce one.
            </div>
          )}
        </div>
      </div>
      <p className="icGeoCompareNote">
        Same footprint by construction: both images are rendered from the identical windowed read of the
        real Sentinel-2 scene, so geospatial alignment is guaranteed rather than separately measured.
      </p>

      <div className="icFacts">
        {refMeta ? (
          <>
            <Row label="Reference source" value={refMeta.source || "Sentinel-2 L2A"} tag="measured" />
            <Row label="Reference acquisition" value={refMeta.sourceDatetime ? String(refMeta.sourceDatetime).slice(0, 19).replace("T", " ") + " UTC" : "—"} tag="measured" />
            <Row label="Reference resolution" value={refMeta.deliveredWidthPx ? `${refMeta.deliveredWidthPx} × ${refMeta.deliveredHeightPx} px` : "—"} tag="derived" />
          </>
        ) : null}
        {landCover?.available ? (
          <Row
            label="Land-cover similarity"
            value={`${num(landCover.similarityPercent, 1)} %`}
            tag="derived"
            infoKey="land_cover_similarity"
          />
        ) : null}
        <Row label="Footprint alignment" value="Guaranteed by construction" tag="derived" infoKey="footprint_alignment" />
        {solarMeta ? (
          <Row
            label="Sun elevation"
            value={`${num(solarMeta.elevationDeg, 1)}° (${solarMeta.illuminationCondition})`}
            tag="derived"
            infoKey="solar_elevation"
          />
        ) : null}
        {confidence ? (
          <Row
            label="Overall validation confidence"
            value={`${num(confidence.score, 1)} / 100`}
            tag="simulated"
            infoKey="validation_confidence"
          />
        ) : null}
      </div>

      <div className="icGeoLimitations">
        <strong>Validation limitations</strong>
        <ul>
          <li>Land-cover similarity uses spectral-index classification (NDVI/NDWI thresholds), not a trained model — see the underlying classification for details.</li>
          <li>Footprint alignment is guaranteed by construction (both images share one windowed read), not an independently measured registration.</li>
          <li>Overall validation confidence is a disclosed weighted combination of the checks above — a simulated indicator, not a measured scientific result.</li>
          <li>Sun elevation uses a low-precision solar position formula (no equation-of-time or refraction correction), accurate to roughly ±2°.</li>
        </ul>
      </div>

      <span className="icSimBadge icSimBadgeStatic" title="Real Sentinel-2 surface reflectance, composited with a simulated ASC_074 sensor pass — not an unmodified archival scene">
        SIMULATED PRODUCT — not real imagery captured by ASC_074
      </span>
    </div>
  );
}

/* ----------------------------- catalog ----------------------------- */

const PAGE = 50;

/* Each generation pulls real Sentinel-2 granules and writes a multi-megabyte
   product, so a batch is deliberately bounded rather than "generate all
   5,000". Raise this only if you have the disk and the patience. */
const MAX_BATCH = 25;

export function ImageCatalogView({ missionId }) {
  const { authFetch, withAccess } = useAccess();
  const [rows, setRows] = React.useState([]);
  const [total, setTotal] = React.useState(0);
  const [offset, setOffset] = React.useState(0);
  const [facets, setFacets] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [selected, setSelected] = React.useState(null);
  const [busyId, setBusyId] = React.useState(null);
  const [showFilters, setShowFilters] = React.useState(false);

  const [picked, setPicked] = React.useState(() => new Set());
  const [batch, setBatch] = React.useState(null);
  const cancelRef = React.useRef(false);
  /* Delivered raster size drives almost all of the generation time: the
     source window is fetched at whatever overview level feeds it, so the
     bytes transferred scale with the square of this number. */
  const [maxPixels, setMaxPixels] = React.useState(2048);

  const [q, setQ] = React.useState("");
  const [f, setF] = React.useState({
    satellite: "", plane: "", orbit: "", state: "", status: "",
    timeFrom: "", timeTo: "", cloudMax: "", qualityMin: "",
    latMin: "", latMax: "", lonMin: "", lonMax: "",
  });

  const query = React.useMemo(() => {
    const p = new URLSearchParams({ limit: String(PAGE), offset: String(offset), mission: missionId || "asc074_6x8" });
    if (q.trim()) p.set("q", q.trim());
    Object.entries(f).forEach(([k, v]) => { if (String(v).trim()) p.set(k, v); });
    return p.toString();
  }, [q, f, offset, missionId]);

  const load = React.useCallback(() => {
    setLoading(true); setError("");
    getJSON(`${IC}/catalog?${query}`, authFetch)
      .then((d) => { setRows(d.images || []); setTotal(d.total || 0); })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, [query, authFetch]);

  React.useEffect(load, [load]);
  React.useEffect(() => { getJSON(icUrl("/facets", missionId), authFetch).then(setFacets).catch(() => {}); }, [missionId, authFetch]);
  React.useEffect(() => { setOffset(0); }, [missionId]);

  const generate = async (id) => {
    setBusyId(id);
    try {
      const r = await authFetch(icUrl(`/image/${id}/generate`, missionId), {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ maxPixels }),
      });
      const j = await r.json();
      if (!j.ok) throw new Error(j.error || "Generation failed");
      load();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusyId(null);
    }
  };

  const setFilter = (k, v) => { setOffset(0); setF((s) => ({ ...s, [k]: v })); };

  /* ------------------------- batch generation ------------------------- */

  const togglePick = (id) => setPicked((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const pageIds = rows.map((r) => r.imageId);
  const pageUngenerated = rows.filter((r) => r.generationStatus !== "Generated").map((r) => r.imageId);
  const allPagePicked = pageIds.length > 0 && pageIds.every((id) => picked.has(id));

  const togglePage = () => setPicked((prev) => {
    const next = new Set(prev);
    if (allPagePicked) pageIds.forEach((id) => next.delete(id));
    else pageIds.forEach((id) => next.add(id));
    return next;
  });

  /* Runs the queue one image at a time. Sequential on purpose: each item
     fetches Sentinel-2 granules over the network, and firing them in
     parallel would hammer the archive and the disk for no real speedup.
     A failure is recorded and the queue moves on rather than aborting. */
  const runBatch = async () => {
    const queue = [...picked].slice(0, MAX_BATCH);
    if (!queue.length) return;

    cancelRef.current = false;
    setError("");
    setBatch({ total: queue.length, done: 0, current: null, results: [], running: true, cancelled: false });

    for (let i = 0; i < queue.length; i += 1) {
      if (cancelRef.current) {
        setBatch((b) => ({ ...b, running: false, cancelled: true, current: null }));
        break;
      }
      const id = queue[i];
      setBatch((b) => ({ ...b, current: id, done: i }));
      try {
        const res = await authFetch(icUrl(`/image/${id}/generate`, missionId), {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ maxPixels }),
        });
        const j = await res.json();
        setBatch((b) => ({
          ...b,
          results: [...b.results, j.ok
            ? { id, ok: true, cached: !!j.cached }
            : { id, ok: false, error: j.error || `HTTP ${res.status}` }],
        }));
      } catch (e) {
        setBatch((b) => ({ ...b, results: [...b.results, { id, ok: false, error: String(e.message || e) }] }));
      }
    }

    if (!cancelRef.current) {
      setBatch((b) => (b ? { ...b, running: false, current: null, done: b.total } : b));
    }
    setPicked(new Set());
    load();
  };

  return (
    <section className="icWrap">
      <div className="icHead">
        <div>
          <p className="icEyebrow">Mission Image Center</p>
          <h2>Image Catalog</h2>
          <p className="icSub">
            Every imaging opportunity derived from GMAT telemetry. Images are generated
            on demand — nothing is pre-rendered.
          </p>
        </div>
        {facets ? (
          <div className="icCounts">
            <div><strong>{facets.counts.total.toLocaleString()}</strong><span>Opportunities</span></div>
            <div><strong>{facets.counts.generated.toLocaleString()}</strong><span>Generated</span></div>
            <div><strong>{num(facets.gsdM, 2)} m</strong><span>GSD</span></div>
            <div><strong>{num(facets.swathWidthKm, 1)} km</strong><span>Swath</span></div>
          </div>
        ) : null}
      </div>

      <div className="icToolbar">
        <label className="icSearch">
          <Search size={15} />
          <input
            value={q}
            placeholder="Search image ID, satellite, AOI, state, date, latitude or longitude…"
            onChange={(e) => { setOffset(0); setQ(e.target.value); }}
          />
        </label>
        <button className="icBtn icBtnGhost" onClick={() => setShowFilters((v) => !v)}>
          <Filter size={14} /> Filters
        </button>
        <button className="icBtn icBtnGhost" onClick={load}><RefreshCw size={14} /> Refresh</button>

        <label className="icResPick" title="Delivered raster size. Generation time scales with the square of this, because the source window is fetched at whatever overview level feeds it.">
          Resolution
          <select
            value={maxPixels}
            disabled={batch?.running}
            onChange={(e) => setMaxPixels(Number(e.target.value))}
          >
            <option value={512}>512 px · fastest</option>
            <option value={1024}>1024 px · balanced</option>
            <option value={2048}>2048 px · full</option>
          </select>
        </label>

        {pageUngenerated.length ? (
          <button
            className="icBtn icBtnGhost"
            disabled={batch?.running}
            onClick={() => setPicked((prev) => {
              const next = new Set(prev);
              pageUngenerated.slice(0, MAX_BATCH).forEach((id) => next.add(id));
              return next;
            })}
            title={`Select up to ${MAX_BATCH} not-yet-generated opportunities on this page`}
          >
            <CheckCircle2 size={14} /> Select ungenerated
          </button>
        ) : null}

        {picked.size > 0 ? (
          <>
            <button className="icBtn icBtnPrimary" disabled={batch?.running} onClick={runBatch}>
              <Camera size={14} />
              Generate {Math.min(picked.size, MAX_BATCH)} selected
              {picked.size > MAX_BATCH ? ` (of ${picked.size})` : ""}
            </button>
            <button className="icBtn icBtnGhost" disabled={batch?.running} onClick={() => setPicked(new Set())}>
              <X size={14} /> Clear
            </button>
          </>
        ) : null}
      </div>

      {showFilters && facets ? (
        <div className="icFilters">
          <label>Satellite
            <select value={f.satellite} onChange={(e) => setFilter("satellite", e.target.value)}>
              <option value="">All</option>
              {facets.satellites.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label>Plane
            <select value={f.plane} onChange={(e) => setFilter("plane", e.target.value)}>
              <option value="">All</option>
              {facets.planes.map((p) => <option key={p} value={p}>Plane {p}</option>)}
            </select>
          </label>
          <label>Orbit
            <input type="number" min="1" value={f.orbit} onChange={(e) => setFilter("orbit", e.target.value)} />
          </label>
          <label>State / territory
            <select value={f.state} onChange={(e) => setFilter("state", e.target.value)}>
              <option value="">All</option>
              {facets.states.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label>Status
            <select value={f.status} onChange={(e) => setFilter("status", e.target.value)}>
              <option value="">All</option>
              <option value="generated">Generated</option>
              <option value="notgenerated">Not Generated</option>
            </select>
          </label>
          <label>From (UTC)
            <input type="datetime-local" value={f.timeFrom} onChange={(e) => setFilter("timeFrom", e.target.value)} />
          </label>
          <label>To (UTC)
            <input type="datetime-local" value={f.timeTo} onChange={(e) => setFilter("timeTo", e.target.value)} />
          </label>
          <label>Max cloud %
            <input type="number" min="0" max="100" value={f.cloudMax} onChange={(e) => setFilter("cloudMax", e.target.value)} />
          </label>
          <label>Min quality
            <input type="number" min="0" max="100" value={f.qualityMin} onChange={(e) => setFilter("qualityMin", e.target.value)} />
          </label>
          <label>Min latitude
            <input type="number" step="0.01" min="-90" max="90" placeholder="-90" value={f.latMin} onChange={(e) => setFilter("latMin", e.target.value)} />
          </label>
          <label>Max latitude
            <input type="number" step="0.01" min="-90" max="90" placeholder="90" value={f.latMax} onChange={(e) => setFilter("latMax", e.target.value)} />
          </label>
          <label>Min longitude
            <input type="number" step="0.01" min="-180" max="180" placeholder="-180" value={f.lonMin} onChange={(e) => setFilter("lonMin", e.target.value)} />
          </label>
          <label>Max longitude
            <input type="number" step="0.01" min="-180" max="180" placeholder="180" value={f.lonMax} onChange={(e) => setFilter("lonMax", e.target.value)} />
          </label>
        </div>
      ) : null}

      {error ? <p className="icError">{error}</p> : null}

      {batch ? (
        <div className="icBatch">
          <div className="icBatchTop">
            <strong>
              {batch.running
                ? `Generating ${Math.min(batch.done + 1, batch.total)} of ${batch.total}`
                : batch.cancelled ? "Batch cancelled" : `Batch complete — ${batch.total} processed`}
            </strong>
            {batch.running ? (
              <button className="icBtn icBtnGhost icBtnSm" onClick={() => { cancelRef.current = true; }}>
                <X size={13} /> Cancel after current
              </button>
            ) : (
              <button className="icBtn icBtnGhost icBtnSm" onClick={() => setBatch(null)}>
                <X size={13} /> Dismiss
              </button>
            )}
          </div>

          <div className="icBatchBar">
            <div
              className="icBatchFill"
              style={{ width: `${batch.total ? (batch.results.length / batch.total) * 100 : 0}%` }}
            />
          </div>

          {batch.running ? (
            <p className="icBatchNote">
              <Loader2 size={12} className="icSpin" /> {batch.current}
              {" — retrieving Sentinel-2 source imagery and simulating the sensor pass. "}
              Each image takes 1–2 minutes; leaving this page stops the queue.
            </p>
          ) : null}

          {batch.results.length ? (
            <div className="icBatchResults">
              <span className="icBatchOk">
                {batch.results.filter((r) => r.ok).length} generated
                {batch.results.some((r) => r.cached) ? ` (${batch.results.filter((r) => r.cached).length} already cached)` : ""}
              </span>
              {batch.results.some((r) => !r.ok) ? (
                <span className="icBatchFail">{batch.results.filter((r) => !r.ok).length} failed</span>
              ) : null}
              {batch.results.filter((r) => !r.ok).slice(0, 4).map((r) => (
                <p key={r.id} className="icBatchErr"><code>{r.id}</code> — {r.error}</p>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="icTableWrap">
        <table className="icTable">
          <thead>
            <tr>
              <th className="icPickCol">
                <input
                  type="checkbox"
                  checked={allPagePicked}
                  disabled={batch?.running || rows.length === 0}
                  onChange={togglePage}
                  title="Select every opportunity on this page"
                />
              </th>
              <th>Image ID</th><th>Satellite</th><th>Orbit</th><th>Date</th><th>Time (UTC)</th>
              <th>Latitude</th><th>Longitude</th><th title="Instantaneous Geodetic Altitude at time of capture, not the fixed Nominal Orbit Altitude">Altitude</th><th>AOI</th>
              <th>Status</th><th>Preview</th><th>Generate</th><th>Download</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={14} className="icMuted">Loading catalog…</td></tr>
            ) : rows.length === 0 ? (
              <tr><td colSpan={14} className="icMuted">No opportunities match these filters.</td></tr>
            ) : rows.map((r) => {
              const gen = r.generationStatus === "Generated";
              return (
                <tr key={r.imageId} className={selected === r.imageId ? "icSelected" : ""}>
                  <td className="icPickCol">
                    <input
                      type="checkbox"
                      checked={picked.has(r.imageId)}
                      disabled={batch?.running}
                      onChange={() => togglePick(r.imageId)}
                      title={gen ? "Already generated — regenerating is not part of a batch" : "Queue for batch generation"}
                    />
                  </td>
                  <td><button className="icIdBtn" onClick={() => setSelected(r.imageId)}>{r.imageId}</button></td>
                  <td>{r.satellite}</td>
                  <td>{r.orbit}</td>
                  <td>{r.captureDate}</td>
                  <td>{r.captureTimeUtc}</td>
                  <td>{coord(r.latitude, "N", "S")}</td>
                  <td>{coord(r.longitude, "E", "W")}</td>
                  <td>{num(r.altitudeKm, 1)} km</td>
                  <td>{r.australianState}</td>
                  <td><StatusPill status={r.generationStatus} /></td>
                  <td>
                    {gen ? (
                      <img className="icThumbSm" src={withAccess(icUrl(`/image/${r.imageId}/preview?size=thumb`, missionId))} alt="" loading="lazy"
                           onClick={() => setSelected(r.imageId)} />
                    ) : <span className="icMuted">—</span>}
                  </td>
                  <td>
                    <button className="icBtn icBtnPrimary icBtnSm"
                            disabled={busyId === r.imageId || batch?.running}
                            onClick={() => generate(r.imageId)}>
                      {busyId === r.imageId || batch?.current === r.imageId
                        ? <Loader2 size={13} className="icSpin" />
                        : gen ? <CheckCircle2 size={13} /> : <Camera size={13} />}
                      {batch?.current === r.imageId ? "Queued" : busyId === r.imageId ? "Working" : gen ? "Done" : "Generate"}
                    </button>
                  </td>
                  <td><DownloadMenu imageId={r.imageId} missionId={missionId} disabled={!gen} assets={r.assets} onDownloaded={load} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="icPager">
        <span>{total.toLocaleString()} opportunities · showing {offset + 1}–{Math.min(offset + PAGE, total)}</span>
        <div>
          <button className="icBtn icBtnGhost" disabled={offset === 0}
                  onClick={() => setOffset(Math.max(offset - PAGE, 0))}>Previous</button>
          <button className="icBtn icBtnGhost" disabled={offset + PAGE >= total}
                  onClick={() => setOffset(offset + PAGE)}>Next</button>
        </div>
      </div>

      {selected ? (
        <div className="icModal" role="dialog" aria-modal="true">
          <div className="icModalInner">
            <ImageDetail imageId={selected} missionId={missionId} onClose={() => setSelected(null)} onChanged={load} />
          </div>
        </div>
      ) : null}
    </section>
  );
}

/* ----------------------------- gallery ----------------------------- */

export function ImageGalleryView({ missionId }) {
  const { authFetch, withAccess } = useAccess();
  const [images, setImages] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [selected, setSelected] = React.useState(null);
  const [error, setError] = React.useState("");

  const load = React.useCallback(() => {
    setLoading(true);
    getJSON(icUrl("/generated", missionId), authFetch)
      .then((d) => setImages(d.images || []))
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, [missionId, authFetch]);

  React.useEffect(load, [load]);

  const remove = async (id) => {
    await authFetch(icUrl(`/image/${id}`, missionId), { method: "DELETE" }).catch(() => {});
    load();
  };

  return (
    <section className="icWrap">
      <div className="icHead">
        <div>
          <p className="icEyebrow">Mission Image Center</p>
          <h2>Image Gallery</h2>
          <p className="icSub">Generated products, cached on disk and never rebuilt unless requested.</p>
        </div>
        <button className="icBtn icBtnGhost" onClick={load}><RefreshCw size={14} /> Refresh</button>
      </div>

      {error ? <p className="icError">{error}</p> : null}

      {loading ? (
        <p className="icMuted">Loading gallery…</p>
      ) : images.length === 0 ? (
        <div className="icEmpty">
          <Grid3x3 size={40} />
          <h3>No images generated yet</h3>
          <p>Open the Image Catalog and generate a scene to populate the gallery.</p>
        </div>
      ) : (
        <div className="icGrid">
          {images.map((im) => (
            <article className="icCard" key={im.imageId}>
              <button className="icCardImg" onClick={() => setSelected(im.imageId)}>
                <img src={withAccess(icUrl(`/image/${im.imageId}/preview?size=thumb`, missionId))} alt={im.imageId} loading="lazy" />
                <span className="icSimBadge icSimBadgeSm" title="Real Sentinel-2 reflectance, composited with a simulated ASC_074 sensor pass">SIM</span>
              </button>
              <div className="icCardBody">
                <h4>{im.satellite}</h4>
                <p className="icCardId">{im.imageId}</p>
                <div className="icCardMeta">
                  <span>{im.captureDate}</span><span>{im.captureTimeUtc} UTC</span>
                  <span>Orbit {im.orbit}</span><span>{im.australianState}</span>
                  <span>{coord(im.latitude, "N", "S")}</span><span>{coord(im.longitude, "E", "W")}</span>
                </div>
                <div className="icCardFoot">
                  <span className="icQuality">
                    Quality <strong>{im.imageQualityScore ?? "—"}</strong>
                  </span>
                  <div className="icCardActions">
                    <DownloadMenu imageId={im.imageId} missionId={missionId} assets={im.assets} onDownloaded={load} />
                    <button className="icBtn icBtnGhost icBtnSm" title="Delete product"
                            onClick={() => remove(im.imageId)}><Trash2 size={13} /></button>
                  </div>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      {selected ? (
        <div className="icModal" role="dialog" aria-modal="true">
          <div className="icModalInner">
            <ImageDetail imageId={selected} missionId={missionId} onClose={() => setSelected(null)} onChanged={load} />
          </div>
        </div>
      ) : null}
    </section>
  );
}

export default { ImageCatalogView, ImageGalleryView };
