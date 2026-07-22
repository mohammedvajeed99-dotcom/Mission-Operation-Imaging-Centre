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
  RefreshCw,
  Search,
  Satellite,
  Trash2,
  X,
} from "lucide-react";
import "./imageCenter.css";

const API = import.meta.env.VITE_API_BASE || "http://127.0.0.1:5001";
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

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

/* ------------------- Australia-focused footprint map -------------------
   Deliberately a separate, regionally-scaled map rather than the world
   MapBase used elsewhere: a 69 km footprint is sub-pixel on a world
   projection and would be invisible.                                     */

const REGION = { lonMin: 108, lonMax: 158, latMin: -46, latMax: -8 };
const MW = 720;
const MH = (MW * (REGION.latMax - REGION.latMin)) / (REGION.lonMax - REGION.lonMin);

const rx = (lon) => ((Number(lon) - REGION.lonMin) / (REGION.lonMax - REGION.lonMin)) * MW;
const ry = (lat) => ((REGION.latMax - Number(lat)) / (REGION.latMax - REGION.latMin)) * MH;

const REGION_LAND = (() => {
  try {
    const geo = feature(worldTopo, worldTopo.objects.land);
    const features = geo.features || [geo];
    let d = "";
    features.forEach((f) => {
      const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
      polys.forEach((poly) =>
        poly.forEach((ring) => {
          // Cheap reject: skip rings entirely outside the Australian window.
          const lons = ring.map((p) => p[0]);
          const lats = ring.map((p) => p[1]);
          if (Math.max(...lons) < REGION.lonMin || Math.min(...lons) > REGION.lonMax) return;
          if (Math.max(...lats) < REGION.latMin || Math.min(...lats) > REGION.latMax) return;
          ring.forEach((pt, i) => {
            d += `${i === 0 ? "M" : "L"}${rx(pt[0]).toFixed(1)} ${ry(pt[1]).toFixed(1)}`;
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

function FootprintMap({ geometry, height = 380 }) {
  if (!geometry) return <div className="icMapEmpty">Select an image to plot its footprint</div>;

  const fp = geometry.footprint || [];
  const track = geometry.groundTrack || [];
  const pos = geometry.satellitePosition || {};
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
      {[110, 120, 130, 140, 150].map((lon) => (
        <g key={lon}>
          <line x1={rx(lon)} y1={0} x2={rx(lon)} y2={MH} className="icGrat" />
          <text x={rx(lon) + 3} y={MH - 5} className="icGratLabel">{lon}°E</text>
        </g>
      ))}
      {[-10, -20, -30, -40].map((lat) => (
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

const FORMATS = [
  ["png", "PNG"],
  ["jpeg", "JPEG"],
  ["geotiff", "GeoTIFF"],
  ["json", "Metadata JSON"],
  ["csv", "Metadata CSV"],
  ["zip", "ZIP bundle"],
];

function DownloadMenu({ imageId, disabled, onDownloaded }) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef(null);

  React.useEffect(() => {
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);

  const grab = (kind) => {
    window.open(`${IC}/image/${imageId}/download/${kind}`, "_blank");
    fetch(`${IC}/image/${imageId}/downloaded`, { method: "POST" })
      .then(() => onDownloaded && onDownloaded())
      .catch(() => {});
    setOpen(false);
  };

  return (
    <div className="icDlWrap" ref={ref}>
      <button className="icBtn icBtnGhost" disabled={disabled} onClick={() => setOpen((v) => !v)}>
        <Download size={14} /> Download
      </button>
      {open && !disabled ? (
        <div className="icDlMenu">
          {FORMATS.map(([k, label]) => (
            <button key={k} onClick={() => grab(k)}>{label}</button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/* ---------------------------- detail view ---------------------------- */

function Row({ label, value }) {
  return (
    <div className="icRow">
      <span>{label}</span>
      <strong>{value ?? "—"}</strong>
    </div>
  );
}

function ImageDetail({ imageId, onClose, onChanged }) {
  const [detail, setDetail] = React.useState(null);
  const [geometry, setGeometry] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const load = React.useCallback(() => {
    setError("");
    Promise.all([getJSON(`${IC}/image/${imageId}`), getJSON(`${IC}/image/${imageId}/geometry`)])
      .then(([d, g]) => { setDetail(d); setGeometry(g); })
      .catch((e) => setError(String(e.message || e)));
  }, [imageId]);

  React.useEffect(load, [load]);

  const generate = async (regenerate = false) => {
    setBusy(true); setError("");
    try {
      const r = await fetch(`${IC}/image/${imageId}/generate`, {
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

  return (
    <div className="icDetail">
      <div className="icDetailHead">
        <div>
          <p className="icEyebrow">Image detail</p>
          <h3>{detail.imageId}</h3>
          <StatusPill status={detail.generationStatus} />
        </div>
        <div className="icDetailActions">
          {generated ? (
            <>
              <DownloadMenu imageId={imageId} onDownloaded={load} />
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

      <div className="icDetailGrid">
        <div className="icPreviewPane">
          {generated ? (
            <img className="icPreviewLarge" src={`${IC}/image/${imageId}/preview`} alt={detail.imageId} />
          ) : (
            <div className="icPreviewEmpty">
              <ImageIcon size={34} />
              <p>Not generated</p>
              <span>Generate to retrieve and simulate this scene</span>
            </div>
          )}
        </div>

        <div className="icFacts">
          <h4>Acquisition</h4>
          <Row label="Satellite" value={detail.satellite} />
          <Row label="Plane" value={`Plane ${detail.plane}`} />
          <Row label="Orbit number" value={detail.orbit} />
          <Row label="Orbit pass" value={detail.orbitPass} />
          <Row label="Capture date" value={detail.captureDate} />
          <Row label="Capture time (UTC)" value={detail.captureTimeUtc} />
          <Row label="Mission elapsed time" value={detail.missionElapsedTime} />

          <h4>Geometry</h4>
          <Row label="Latitude" value={coord(detail.latitude, "N", "S")} />
          <Row label="Longitude" value={coord(detail.longitude, "E", "W")} />
          <Row label="Altitude" value={`${num(detail.altitudeKm, 2)} km`} />
          <Row label="Camera heading" value={`${num(detail.cameraHeadingDeg, 1)}°`} />
          <Row label="Camera orientation" value={detail.cameraOrientation} />
          <Row label="Swath width" value={`${num(detail.swathWidthKm, 2)} km`} />
          <Row label="Ground footprint" value={`${num(detail.footprintAreaKm2, 0)} km²`} />
          <Row label="AOI" value={detail.aoiName} />

          <h4>Product</h4>
          <Row label="GSD" value={`${num(detail.gsdM, 2)} m/px`} />
          <Row label="Native resolution" value={detail.estimatedResolution} />
          <Row label="Delivered resolution" value={detail.deliveredResolution} />
          <Row label="Native data volume" value={bytes(detail.estimatedSizeBytes)} />
          <Row label="Delivered data volume" value={bytes(detail.deliveredSizeBytes)} />
          <Row label="Quality score" value={detail.imageQualityScore ?? "—"} />
          <Row label="Cloud cover" value={detail.cloudCoverPercent === null || detail.cloudCoverPercent === undefined ? "—" : `${num(detail.cloudCoverPercent, 2)} %`} />
          <Row label="Generated" value={detail.generatedTimestamp ?? "—"} />
          <Row label="Download status" value={detail.downloadStatus} />

          {generated && sensor.alongTrackSmearPx !== undefined ? (
            <>
              <h4>Sensor simulation</h4>
              <Row label="Along-track smear" value={`${num(sensor.alongTrackSmearPx, 2)} px`} />
              <Row label="MTF sigma" value={`${num(sensor.mtfSigmaPx, 2)} px`} />
              <Row label="Estimated SNR" value={num(sensor.estimatedSnr, 1)} />
              <Row label="Bit depth" value={sensor.bitDepth} />
            </>
          ) : null}
        </div>
      </div>

      <div className="icMapBlock">
        <h4><MapPin size={14} /> Capture location, footprint and ground track</h4>
        <FootprintMap geometry={geometry} />
      </div>

      <div className="icGmat">
        <h4>Associated GMAT record</h4>
        <pre>{JSON.stringify(detail.gmatRecord, null, 2)}</pre>
      </div>
    </div>
  );
}

/* ----------------------------- catalog ----------------------------- */

const PAGE = 50;

export function ImageCatalogView() {
  const [rows, setRows] = React.useState([]);
  const [total, setTotal] = React.useState(0);
  const [offset, setOffset] = React.useState(0);
  const [facets, setFacets] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [selected, setSelected] = React.useState(null);
  const [busyId, setBusyId] = React.useState(null);
  const [showFilters, setShowFilters] = React.useState(false);

  const [q, setQ] = React.useState("");
  const [f, setF] = React.useState({
    satellite: "", plane: "", orbit: "", state: "", status: "",
    timeFrom: "", timeTo: "", cloudMax: "", qualityMin: "",
  });

  const query = React.useMemo(() => {
    const p = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    if (q.trim()) p.set("q", q.trim());
    Object.entries(f).forEach(([k, v]) => { if (String(v).trim()) p.set(k, v); });
    return p.toString();
  }, [q, f, offset]);

  const load = React.useCallback(() => {
    setLoading(true); setError("");
    getJSON(`${IC}/catalog?${query}`)
      .then((d) => { setRows(d.images || []); setTotal(d.total || 0); })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, [query]);

  React.useEffect(load, [load]);
  React.useEffect(() => { getJSON(`${IC}/facets`).then(setFacets).catch(() => {}); }, []);

  const generate = async (id) => {
    setBusyId(id);
    try {
      const r = await fetch(`${IC}/image/${id}/generate`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
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
            placeholder="Search image ID, satellite, AOI, state or date…"
            onChange={(e) => { setOffset(0); setQ(e.target.value); }}
          />
        </label>
        <button className="icBtn icBtnGhost" onClick={() => setShowFilters((v) => !v)}>
          <Filter size={14} /> Filters
        </button>
        <button className="icBtn icBtnGhost" onClick={load}><RefreshCw size={14} /> Refresh</button>
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
        </div>
      ) : null}

      {error ? <p className="icError">{error}</p> : null}

      <div className="icTableWrap">
        <table className="icTable">
          <thead>
            <tr>
              <th>Image ID</th><th>Satellite</th><th>Orbit</th><th>Date</th><th>Time (UTC)</th>
              <th>Latitude</th><th>Longitude</th><th>Altitude</th><th>AOI</th>
              <th>Status</th><th>Preview</th><th>Generate</th><th>Download</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={13} className="icMuted">Loading catalog…</td></tr>
            ) : rows.length === 0 ? (
              <tr><td colSpan={13} className="icMuted">No opportunities match these filters.</td></tr>
            ) : rows.map((r) => {
              const gen = r.generationStatus === "Generated";
              return (
                <tr key={r.imageId} className={selected === r.imageId ? "icSelected" : ""}>
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
                      <img className="icThumbSm" src={`${IC}/image/${r.imageId}/preview`} alt="" loading="lazy"
                           onClick={() => setSelected(r.imageId)} />
                    ) : <span className="icMuted">—</span>}
                  </td>
                  <td>
                    <button className="icBtn icBtnPrimary icBtnSm"
                            disabled={busyId === r.imageId}
                            onClick={() => generate(r.imageId)}>
                      {busyId === r.imageId ? <Loader2 size={13} className="icSpin" /> : gen ? <CheckCircle2 size={13} /> : <Camera size={13} />}
                      {busyId === r.imageId ? "Working" : gen ? "Done" : "Generate"}
                    </button>
                  </td>
                  <td><DownloadMenu imageId={r.imageId} disabled={!gen} onDownloaded={load} /></td>
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
            <ImageDetail imageId={selected} onClose={() => setSelected(null)} onChanged={load} />
          </div>
        </div>
      ) : null}
    </section>
  );
}

/* ----------------------------- gallery ----------------------------- */

export function ImageGalleryView() {
  const [images, setImages] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [selected, setSelected] = React.useState(null);
  const [error, setError] = React.useState("");

  const load = React.useCallback(() => {
    setLoading(true);
    getJSON(`${IC}/generated`)
      .then((d) => setImages(d.images || []))
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, []);

  React.useEffect(load, [load]);

  const remove = async (id) => {
    await fetch(`${IC}/image/${id}`, { method: "DELETE" }).catch(() => {});
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
                <img src={`${IC}/image/${im.imageId}/preview`} alt={im.imageId} loading="lazy" />
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
                    <DownloadMenu imageId={im.imageId} onDownloaded={load} />
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
            <ImageDetail imageId={selected} onClose={() => setSelected(null)} onChanged={load} />
          </div>
        </div>
      ) : null}
    </section>
  );
}

export default { ImageCatalogView, ImageGalleryView };
