"""Mission Image Center: the imaging opportunity catalog and product registry.

This module is purely additive. It reads the existing GMAT outputs and the
existing camera model and does not modify either.

Two ideas are kept strictly separate:

  * A **catalog entry** is an imaging *opportunity* -- a moment on the ground
    track where the payload could capture a scene. Every field on it is derived
    from GMAT telemetry and mission configuration alone. Catalog entries are
    cheap, deterministic, and exist for all ~5,400 opportunities from the moment
    the report is parsed.

  * A **product** is a generated image. Products are created only on explicit
    request, are cached on disk, and are never regenerated unless asked.

Every image ID encodes the telemetry that produced it, so an image can always be
traced back to the exact GMAT record:

    ASC074-P3-S17-O0006-20260703T085335

    ASC074    mission
    P3        orbital plane (derived from ascending-node longitude)
    S17       satellite number within the constellation
    O0006     orbit number within the report span
    2026...   UTC capture epoch of the state record

Nothing here writes into the existing dashboard's data structures.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from core.aoi_regions import aoi_name, state_of as australia_state_of
from core.india_states import state_of as india_state_of
# core.location_dataset (the authoritative bundled district/council
# dataset) has replaced core.geocode (live Nominatim reverse-geocoding) as
# the source here -- same return shape, so every downstream field name
# (district/city/country/locationDisplay) is unchanged. core.geocode is
# left in place, not deleted, in case it's ever needed again.
from core.location_dataset import nearest_district_city as district_city_for
from core.imaging_summary import _ground_speed_km_s
from core.time_utils import utc_iso
from core.footprint import (
    _bearing_deg,
    densify_track,
    footprint_bbox,
    footprint_corners,
    ground_track_heading,
    haversine_km,
    orbit_numbers,
)

# Generation lifecycle. A catalog entry starts at NOT_GENERATED and only ever
# advances through explicit user action.
NOT_GENERATED = "Not Generated"
GENERATING = "Generating"
GENERATED = "Generated"
FAILED = "Failed"

BANDS = ("Red", "Green", "Blue", "Near Infrared")
BYTES_PER_SAMPLE = 2  # uint16 DN

# Delivered rasters are capped so a single generation request cannot pull a
# half-gigabyte scene. The native instrument size is reported separately.
MAX_DELIVERED_PX = 2048


def _sat_number(satellite_name):
    """Trailing index from a satellite name, e.g. ASC_074_17 -> 17.

    Some missions use a trailing letter instead of a numeric suffix (e.g.
    ASC_074A/B/C for a 3-satellite constellation) -- fall back to the
    letter's 1-indexed alphabet position (A=1, B=2, ...) so those satellites
    still get distinct numbers instead of all collapsing to 0.
    """
    name = str(satellite_name)
    m = re.search(r"(\d+)\s*$", name)
    if m:
        return int(m.group(1))
    m = re.search(r"([A-Za-z])\s*$", name)
    if m:
        return ord(m.group(1).upper()) - ord("A") + 1
    return 0


def derive_planes(state_df, satellites_per_plane=8):
    """Assign each satellite to an orbital plane using its ascending node.

    Satellites sharing a plane share a right ascension of the ascending node,
    which shows up in the telemetry as a common equator-crossing longitude.
    Deriving the plane this way keeps the field traceable to the data rather
    than assuming the naming convention encodes it -- although for this
    constellation the two agree exactly, which is used as a cross-check.

    Returns {satellite name: plane number}, planes numbered from 1 in ascending
    node order.
    """
    signatures = {}
    for sat, g in state_df.groupby("Satellite Name"):
        g = g.sort_values("Timestamp")
        lat = pd.to_numeric(g["Latitude"], errors="coerce").to_numpy(dtype=float)
        lon = pd.to_numeric(g["Longitude"], errors="coerce").to_numpy(dtype=float)
        asc = np.where((lat[:-1] < 0) & (lat[1:] >= 0))[0]
        if not len(asc):
            continue
        i = asc[0]
        span = lat[i + 1] - lat[i]
        f = (0.0 - lat[i]) / span if span else 0.0
        d = (lon[i + 1] - lon[i] + 540.0) % 360.0 - 180.0
        signatures[str(sat)] = (lon[i] + f * d) % 360.0

    if not signatures:
        return {}

    # Group by gaps in sorted ascending-node longitude. Within a plane
    # satellites sit a few degrees apart; between planes the step is far larger.
    ordered = sorted(signatures.items(), key=lambda kv: kv[1])
    lons = np.array([v for _, v in ordered])
    steps = np.diff(lons)
    threshold = max(float(np.median(steps)) * 4.0, 10.0) if len(steps) else 10.0
    group = np.concatenate([[0], np.cumsum(steps > threshold)])

    planes = {}
    for (sat, _), grp in zip(ordered, group):
        planes[sat] = int(grp) + 1

    # The wrap point at 0/360 can split one plane in two. If more groups were
    # found than the configuration allows, merge the first and last.
    if satellites_per_plane:
        expected = int(round(len(signatures) / satellites_per_plane))
        found = len(set(planes.values()))
        if expected and found == expected + 1:
            last = max(planes.values())
            for sat, p in planes.items():
                if p == last:
                    planes[sat] = 1
            remap = {p: i + 1 for i, p in enumerate(sorted(set(planes.values())))}
            planes = {s: remap[p] for s, p in planes.items()}

    # The grouping above comes from the telemetry; the *numbering* is then set
    # so plane 1 holds the lowest-numbered satellites. Operators expect
    # ASC_074_01..08 to be plane 1, and numbering by ascending-node longitude
    # would offset that arbitrarily depending on where the wrap falls.
    lowest = {}
    for sat, p in planes.items():
        n = _sat_number(sat)
        lowest[p] = min(lowest.get(p, n), n)
    order = {p: i + 1 for i, p in enumerate(sorted(lowest, key=lambda p: lowest[p]))}
    return {sat: order[p] for sat, p in planes.items()}


def make_image_id(mission, plane, sat_num, orbit, timestamp):
    stamp = timestamp.strftime("%Y%m%dT%H%M%S")
    prefix = re.sub(r"[^A-Za-z0-9]", "", str(mission)) or "MISSION"
    return f"{prefix}-P{int(plane)}-S{int(sat_num):02d}-O{int(orbit):04d}-{stamp}"


def _fmt_met(seconds):
    """Mission elapsed time as DDD:HH:MM:SS, the convention used in ops."""
    seconds = max(float(seconds), 0.0)
    d = int(seconds // 86400)
    seconds -= d * 86400
    h = int(seconds // 3600)
    seconds -= h * 3600
    m = int(seconds // 60)
    s = int(round(seconds - m * 60))
    return f"{d:03d}:{h:02d}:{m:02d}:{s:02d}"


def build_catalog(state_df, camera_model, mission_config=None, constellation_config=None, region="australia"):
    """Build the full imaging opportunity catalog from GMAT telemetry.

    Returns a DataFrame with one row per opportunity, carrying every metadata
    field that can be derived without generating an image. Fields that only
    exist after generation (quality score, cloud cover, generated timestamp)
    are present but null.
    """
    from core.regions import REGION_LABELS

    mission_config = mission_config or {}
    constellation_config = constellation_config or {}
    mission = str(mission_config.get("Mission Name", "MISSION"))
    default_aoi = str(mission_config.get("Area of Interest") or REGION_LABELS.get(region, "Australia"))
    per_plane = int(float(constellation_config.get("Satellites per Plane", 8) or 8))

    swath_km = float(camera_model.get("Ground Swath (km)") or 0.0)
    gsd_m = float(camera_model.get("GSD (m/pixel)") or 0.0)
    width_px = int(float(camera_model.get("Image Width (px)") or 0))
    pointing = str(camera_model.get("Pointing", "Nadir"))
    if not (swath_km and gsd_m):
        return pd.DataFrame()

    df = state_df.copy()
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    for col in ("Latitude", "Longitude", "Altitude"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Timestamp", "Satellite Name", "Latitude", "Longitude"])
    if df.empty:
        return pd.DataFrame()

    planes = derive_planes(df, per_plane)
    mission_start = df["Timestamp"].min()

    # Scene tiles are cut at the swath so products are roughly square, matching
    # core.footprint.scene_grid. Densify first: the report's native fix spacing
    # is ~9x the swath, so most of the overflown ground falls between samples.
    from core.australia_coverage import footprint_intersects_region

    along_km = swath_km
    dense = densify_track(df, max_gap_km=along_km / 2.0)
    dense["Observing AOI"] = footprint_intersects_region(
        dense, swath_km, region=region, lon_col="Longitude", lat_col="Latitude"
    )

    rows = []
    for sat, grp in dense.groupby("Satellite Name", sort=True):
        grp = grp.sort_values("Timestamp").copy()
        grp["heading"] = ground_track_heading(grp)
        grp["orbit"] = orbit_numbers(grp)
        active = grp[grp["Observing AOI"]]
        if active.empty:
            continue

        sat_num = _sat_number(sat)
        plane = planes.get(str(sat), ((sat_num - 1) // max(per_plane, 1)) + 1)
        # Median ground-track speed for this satellite, from its own real
        # consecutive state fixes (core.imaging_summary, already used for the
        # fleet-wide imaging-summary estimate) -- reused here to derive a real
        # per-opportunity capture duration (along-track distance / speed)
        # rather than inventing one.
        ground_speed_km_s = _ground_speed_km_s(grp)

        # Orbit pass number: each continuous stretch over the AOI is one pass,
        # numbered sequentially per satellite. This is the operational "pass"
        # an operator schedules against, distinct from the orbit number.
        times = active["Timestamp"]
        gaps = times.diff().dt.total_seconds()
        nominal = float(gaps[gaps > 0].median()) if (gaps > 0).any() else 0.0
        pass_id = ((gaps.isna()) | (gaps > max(nominal * 4.0, 60.0))).cumsum()
        # Not a leading underscore: itertuples renames such columns positionally.
        active = active.assign(passNumber=pass_id)

        # Emit one scene each time a full scene-length of track has been flown.
        last_lat = last_lon = None
        travelled = 0.0
        for row in active.itertuples(index=False):
            if last_lat is not None:
                travelled += float(haversine_km(last_lat, last_lon, row.Latitude, row.Longitude))
            emit = last_lat is None or travelled >= along_km
            last_lat, last_lon = row.Latitude, row.Longitude
            if not emit:
                continue
            travelled = 0.0

            corners = footprint_corners(row.Latitude, row.Longitude, row.heading, swath_km, along_km)
            bbox = footprint_bbox(corners)
            height_px = int(round(along_km * 1000.0 / gsd_m)) if gsd_m else 0
            met_s = (row.Timestamp - mission_start).total_seconds()
            if region == "india":
                state = india_state_of(row.Latitude, row.Longitude)
            elif region == "australia":
                state = australia_state_of(row.Latitude, row.Longitude)
            else:
                state = default_aoi
            loc = district_city_for(row.Latitude, row.Longitude, region=region)

            rows.append({
                "imageId": make_image_id(mission, plane, sat_num, row.orbit, row.Timestamp),
                "satellite": str(sat),
                "satelliteNumber": sat_num,
                "plane": int(plane),
                "orbit": int(row.orbit),
                "orbitPass": int(row.passNumber),
                "captureDate": row.Timestamp.strftime("%Y-%m-%d"),
                "captureTimeUtc": row.Timestamp.strftime("%H:%M:%S"),
                "captureEpochUtc": utc_iso(row.Timestamp),
                "missionElapsedTime": _fmt_met(met_s),
                "missionElapsedSeconds": float(met_s),
                "latitude": float(row.Latitude),
                "longitude": float(row.Longitude),
                "altitudeKm": float(row.Altitude) if pd.notna(row.Altitude) else None,
                "cameraHeadingDeg": float(row.heading),
                "cameraOrientation": pointing,
                "groundFootprint": corners,
                "bbox": list(bbox),
                "footprintAreaKm2": float(swath_km * along_km),
                "swathWidthKm": swath_km,
                "gsdM": gsd_m,
                # Time to traverse this scene's along-track footprint at this
                # satellite's own real ground speed -- None (not a fabricated
                # number) when speed couldn't be derived (e.g. too few fixes).
                "captureDurationSec": (
                    round(along_km / ground_speed_km_s, 2) if ground_speed_km_s else None
                ),
                # Native instrument product: what the camera would actually
                # produce at full sensor resolution.
                "estimatedResolution": f"{width_px} x {height_px} px",
                "widthPx": width_px,
                "heightPx": height_px,
                "estimatedSizeBytes": int(width_px * height_px * len(BANDS) * BYTES_PER_SAMPLE),
                # Delivered product: generation caps the raster so one request
                # cannot pull a half-gigabyte scene. Both are reported so the
                # native figure is never mistaken for the download size.
                "deliveredResolution": f"{min(width_px, MAX_DELIVERED_PX)} x {min(height_px, MAX_DELIVERED_PX)} px",
                "deliveredWidthPx": min(width_px, MAX_DELIVERED_PX),
                "deliveredHeightPx": min(height_px, MAX_DELIVERED_PX),
                "deliveredSizeBytes": int(
                    min(width_px, MAX_DELIVERED_PX) * min(height_px, MAX_DELIVERED_PX)
                    * len(BANDS) * BYTES_PER_SAMPLE
                ),
                "deliveredGsdM": gsd_m * (width_px / min(width_px, MAX_DELIVERED_PX)) if width_px else gsd_m,
                "aoiName": aoi_name(row.Latitude, row.Longitude, region=region),
                "australianState": state,
                "missionAoi": default_aoi,
                # Reverse-geocoded labels on this same real coordinate --
                # additive alongside aoiName/australianState above, never a
                # replacement. None where the geocode cache has no entry
                # (never a fabricated district/city name); see core.geocode.
                "district": loc["district"],
                "city": loc["city"],
                "country": loc["country"],
                "locationDisplay": loc["locationDisplay"],
                "fromInterpolatedFix": bool(getattr(row, "interpolated", False)),
                # Post-generation fields, null until an image exists.
                "imageQualityScore": None,
                "cloudCoverPercent": None,
                "generatedTimestamp": None,
                "generationStatus": NOT_GENERATED,
                "downloadStatus": "Not Downloaded",
            })

    if not rows:
        return pd.DataFrame()
    catalog = pd.DataFrame(rows).sort_values(["captureEpochUtc", "satellite"]).reset_index(drop=True)
    catalog.insert(0, "index", range(len(catalog)))
    return catalog


class ProductRegistry:
    """On-disk registry of generated products.

    The registry is the source of truth for generation status. It is rebuilt by
    scanning the products directory, so a product surviving a restart is still
    recognised as generated and is never regenerated by accident.
    """

    def __init__(self, products_dir):
        self.dir = Path(products_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, image_id, suffix):
        return self.dir / f"{image_id}{suffix}"

    def exists(self, image_id):
        return self.path(image_id, ".json").exists()

    def load(self, image_id):
        p = self.path(image_id, ".json")
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save(self, image_id, metadata):
        self.path(image_id, ".json").write_text(
            json.dumps(metadata, indent=2, default=str), encoding="utf-8"
        )
        return metadata

    # Which product files are actually present for an id. A deployment can
    # legitimately ship previews and metadata without the full-resolution
    # GeoTIFFs (they are ~16 MB each; see DEPLOY.md), so the UI has to be told
    # what it can offer rather than discovering the gap as a failed download.
    ASSET_SUFFIXES = {
        "geotiff": ".tif",
        "png": ".png",
        "thumbnail": ".thumb.jpg",
        "reference": ".reference.jpg",
        "metadata": ".json",
    }

    def assets(self, image_id):
        return {name: self.path(image_id, suffix).exists()
                for name, suffix in self.ASSET_SUFFIXES.items()}

    def all(self):
        out = []
        for p in sorted(self.dir.glob("*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                continue
        return out

    def status_map(self):
        """{imageId: status fields} for merging onto the catalog."""
        out = {}
        for meta in self.all():
            iid = meta.get("imageId") or meta.get("sceneId")
            if not iid:
                continue
            out[iid] = {
                "imageQualityScore": (meta.get("quality") or {}).get("score"),
                "cloudCoverPercent": (meta.get("cloud") or {}).get("cloudCoverPercent"),
                "generatedTimestamp": meta.get("generatedTimestamp"),
                "generationStatus": meta.get("generationStatus", GENERATED),
                "downloadStatus": meta.get("downloadStatus", "Not Downloaded"),
                # Usability of the frame, separate from whether it exists.
                "qualityStatus": meta.get("qualityStatus")
                    or (meta.get("validation") or {}).get("status"),
                "qualityLabel": meta.get("qualityLabel")
                    or (meta.get("validation") or {}).get("label"),
            }
        return out


def apply_registry(catalog, registry):
    """Overlay generated-product status onto a fresh catalog."""
    if catalog.empty:
        return catalog
    status = registry.status_map()
    if not status:
        return catalog
    out = catalog.copy()
    for field in ("imageQualityScore", "cloudCoverPercent", "generatedTimestamp",
                  "generationStatus", "downloadStatus"):
        out[field] = [
            status.get(iid, {}).get(field, default)
            for iid, default in zip(out["imageId"], out[field])
        ]
    # Quality fields have no catalog-side default -- an ungenerated
    # opportunity has no usability verdict yet.
    for field in ("qualityStatus", "qualityLabel"):
        out[field] = [status.get(iid, {}).get(field) for iid in out["imageId"]]
    return out


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()
