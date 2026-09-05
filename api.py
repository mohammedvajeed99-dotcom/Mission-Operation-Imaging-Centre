from functools import lru_cache
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from core.australia_coverage import (
    MAINLAND_AUSTRALIA,
    MAINLAND_INDIA,
    TASMANIA,
    footprint_intersects_region,
)
from core.regions import AOI_BOXES, region_for_mission, region_label_for_mission
from core.camera_model import build_camera_model, build_camera_modules
from core.config_loader import load_mission_configuration, validate_configuration
from core.cumulative_coverage import cumulative_region_coverage
from core.data_pipeline import read_processed_frame, run_pipeline
from core.data_quality import assess_data_quality
from core.access_control import (
    CODED_SECTIONS,
    SECTIONS,
    STATE_SECTIONS,
    clear_failures,
    download_listing,
    filter_dashboard_payload,
    issue_token,
    mission_listing,
    record_failure,
    section_listing,
    throttle_state,
    unlocked_downloads,
    unlocked_missions,
    unlocked_sections,
    verify_code,
    verify_download_code,
    verify_download_token,
    verify_master_code,
    verify_mission_code,
    verify_mission_token,
    verify_token,
)
from core.glossary import GLOSSARY
from core.global_regions import build_global_coverage
from core.imaging_summary import build_imaging_summary
from core.image_center import derive_planes
from core.missions import DEFAULT_MISSION, MISSIONS, get_mission, list_missions
from core.observation_duration import observation_duration_analysis
from core.constellation_analytics import (
    compute_constellation_summary,
    compute_revisit_analytics,
    compute_gap_analysis,
    compute_satellite_contributions,
    compute_density_heatmaps,
    compute_aoi_analytics,
    compute_simulation_details,
    compute_mission_analytics,
    compute_ground_station_analysis,
    compute_engineering_observations,
)


BASE = Path(__file__).resolve().parent

# Kept for any external caller still expecting the original Australia-only
# AOI box under this module-level name; per-mission code should use
# core.regions.aoi_box_for_mission(mission_id) instead.
AOI = AOI_BOXES["australia"]

_REGION_OUTLINES = {
    "australia": {"outline": MAINLAND_AUSTRALIA, "secondary": TASMANIA},
    "india": {"outline": MAINLAND_INDIA, "secondary": []},
}

app = Flask(__name__)
# The access token travels in a custom header, which triggers a CORS preflight
# -- it has to be allowed explicitly or every gated request fails at OPTIONS.
CORS(app, allow_headers=["Content-Type", "X-Access-Token"])

# Mission Image Center (v1.1) -- additive blueprint under /api/imagecenter.
# Registered here only; it defines no route that existed before and modifies
# no existing endpoint, payload or calculation.
from api_image_center import bp as image_center_bp  # noqa: E402

app.register_blueprint(image_center_bp)


def _mission_id_from_request():
    return request.args.get("mission") or DEFAULT_MISSION


def _unlocked():
    return unlocked_sections(request)


def _unlocked_missions():
    return unlocked_missions(request)


def _unlocked_downloads():
    return unlocked_downloads(request)


def _deny(*sections):
    """403 payload naming which section's code would open this endpoint."""
    labels = [SECTIONS[s]["label"] for s in sections if s in SECTIONS]
    return jsonify({
        "ok": False,
        "error": "Access code required",
        "requiredSections": list(sections),
        "requiredLabels": labels,
    }), 403


def _require(*sections):
    """None if any of `sections` is unlocked, else a 403 response tuple."""
    unlocked = _unlocked()
    if any(s in unlocked for s in sections):
        return None
    return _deny(*sections)


def _deny_download(*sections):
    """403 payload naming which section's download code would allow this."""
    labels = [SECTIONS[s]["label"] for s in sections if s in SECTIONS]
    return jsonify({
        "ok": False,
        "error": "Download access code required",
        "requiredDownloadSections": list(sections),
        "requiredLabels": labels,
    }), 403


def _require_download(*sections):
    """None if any of `sections` has its download code unlocked, else 403.

    Separate from _require: a caller can hold a section's view code (and so
    pass _require for it) while still lacking its download code -- viewing
    and downloading are gated independently.
    """
    granted = _unlocked_downloads()
    if any(s in granted for s in sections):
        return None
    return _deny_download(*sections)


# Legacy API surface kept from earlier versions and no longer called by the
# UI (/api/scenes, /api/products, /api/intelligence, /api/plan/*,
# /api/analytics/aoi/*). These read the same underlying mission data, so
# leaving them open would be a way around every gate below. One hook closes
# the whole set.
LEGACY_PREFIXES = (
    "/api/scenes",
    "/api/products",
    "/api/intelligence",
    "/api/plan/",
    "/api/analytics/aoi/",
)


# --------------------------------------------------------------------------
# Built frontend
# --------------------------------------------------------------------------
# In development Vite serves the UI on its own port and talks to this API
# cross-origin. In a deployment the UI is built once into dist/ and served
# from here, so the whole application is a single origin on a single port:
# no CORS exposure, one URL to share, and the access-code header travels
# without a preflight.

DIST = BASE / "dist"


@app.get("/")
def serve_index():
    if not (DIST / "index.html").exists():
        return jsonify({
            "ok": False,
            "error": "UI not built. Run `npm run build` to generate dist/.",
        }), 404
    return send_from_directory(DIST, "index.html")


@app.get("/<path:asset_path>")
def serve_asset(asset_path):
    # Never let the catch-all shadow the API surface.
    if asset_path.startswith("api/"):
        return jsonify({"ok": False, "error": "Unknown endpoint"}), 404
    candidate = (DIST / asset_path)
    if candidate.is_file():
        return send_from_directory(DIST, asset_path)
    # The UI routes on the hash, so anything else falls back to the shell.
    if (DIST / "index.html").exists():
        return send_from_directory(DIST, "index.html")
    return jsonify({"ok": False, "error": "Not found"}), 404


def _deny_mission(mission_id):
    """403 payload naming which mission's code would open this data."""
    return jsonify({
        "ok": False,
        "error": "Access code required",
        "requiredMission": mission_id,
        "requiredMissionLabel": get_mission(mission_id)["label"],
    }), 403


@app.before_request
def _gate_legacy_routes():
    if request.method == "OPTIONS":  # never block the CORS preflight
        return None
    path = request.path or ""
    if path.startswith(LEGACY_PREFIXES):
        denied = _require("legacy-tools")
        if denied:
            return denied

    # Switching mission is itself gated, the same way a section is: a
    # request naming a non-default mission the caller has not unlocked gets
    # no data for it, regardless of which sections that caller holds. This
    # runs for every request (including the Image Center blueprint, which
    # registers on this same app), so it is the one place this needs to be
    # enforced rather than in each endpoint.
    requested_mission = request.args.get("mission")
    if requested_mission and requested_mission in MISSIONS and requested_mission not in _unlocked_missions():
        return _deny_mission(requested_mission)
    return None


def read_processed(name, mission_id):
    return read_processed_frame(get_mission(mission_id)["processed_dir"] / name)


def numeric_sum(df, col):
    if df.empty or col not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())


def nunique(df, col):
    if df.empty or col not in df.columns:
        return 0
    return int(df[col].dropna().astype(str).nunique())


def clean_value(value):
    if isinstance(value, (list, tuple)):
        return [clean_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): clean_value(item) for key, item in value.items()}
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def records(df, limit=None):
    if df.empty:
        return []
    out = df.head(limit).copy() if limit else df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%dT%H:%M:%S")
    return [
        {str(key): clean_value(value) for key, value in row.items()}
        for row in out.to_dict(orient="records")
    ]


def count_by(df, col, value_name="value", count_name="count"):
    if df.empty or col not in df.columns:
        return []
    data = df[col].fillna("Unknown").astype(str).value_counts().reset_index()
    data.columns = [value_name, count_name]
    return records(data)


def top_duration(df, group_col):
    if df.empty or group_col not in df.columns:
        return []
    work = df.copy()
    work["Duration (s)"] = pd.to_numeric(work.get("Duration (s)", 0), errors="coerce").fillna(0)
    grouped = work.groupby(group_col, as_index=False).agg(
        events=("Duration (s)", "size"),
        durationSeconds=("Duration (s)", "sum"),
    )
    grouped["durationMinutes"] = grouped["durationSeconds"] / 60.0
    return records(grouped.sort_values("durationSeconds", ascending=False))


def latest_state(state):
    if state.empty or "Timestamp" not in state.columns:
        return pd.DataFrame(), None
    work = state.copy()
    work["Timestamp"] = pd.to_datetime(work["Timestamp"], errors="coerce")
    latest_time = work["Timestamp"].max()
    if pd.isna(latest_time):
        return pd.DataFrame(), None
    latest = work[work["Timestamp"].eq(latest_time)].copy()
    for col in ["Latitude", "Longitude", "Altitude", "RMAG", "ECC"]:
        if col in latest.columns:
            latest[col] = pd.to_numeric(latest[col], errors="coerce")
    return latest, latest_time


def satellite_event_matrix(rf, optical, eclipse, state_df=None, satellites_per_plane=None):
    satellites = sorted(
        set(rf.get("Satellite Name", pd.Series(dtype=str)).dropna().astype(str))
        | set(optical.get("Satellite Name", pd.Series(dtype=str)).dropna().astype(str))
        | set(eclipse.get("Satellite Name", pd.Series(dtype=str)).dropna().astype(str))
    )
    # Real, data-derived plane assignment (from ascending-node longitude, see
    # core.image_center.derive_planes) rather than assumed from the naming
    # convention -- so a satellite with zero eclipse events in this window can
    # be attributed to the actual orbital plane whose geometry keeps it lit,
    # not a guess.
    planes = {}
    if state_df is not None and not state_df.empty:
        try:
            planes = derive_planes(state_df, satellites_per_plane or 8)
        except Exception:
            planes = {}
    rows = []
    for sat in satellites:
        rows.append(
            {
                "satellite": sat,
                "rf": int((rf.get("Satellite Name", pd.Series(dtype=str)).astype(str) == sat).sum()) if not rf.empty else 0,
                "optical": int((optical.get("Satellite Name", pd.Series(dtype=str)).astype(str) == sat).sum()) if not optical.empty else 0,
                "eclipse": int((eclipse.get("Satellite Name", pd.Series(dtype=str)).astype(str) == sat).sum()) if not eclipse.empty else 0,
                "plane": planes.get(sat),
            }
        )
    return rows


def build_duty(state, eclipse, swath_km, region="australia"):
    if state.empty:
        return {"summary": [], "timeline": [], "metrics": {}}

    duty = state.copy()
    duty["Timestamp"] = pd.to_datetime(duty["Timestamp"], errors="coerce")
    duty["Latitude"] = pd.to_numeric(duty["Latitude"], errors="coerce")
    duty["Longitude"] = pd.to_numeric(duty["Longitude"], errors="coerce")
    duty = duty.dropna(subset=["Timestamp", "Satellite Name", "Latitude", "Longitude"])
    duty["observingAustralia"] = footprint_intersects_region(
        duty, float(swath_km), region=region, lon_col="Longitude", lat_col="Latitude"
    )
    duty = duty.sort_values(["Satellite Name", "Timestamp"])
    steps = duty.groupby("Satellite Name")["Timestamp"].diff().dt.total_seconds()
    nominal_step = steps[(steps > 0) & (steps < 3600)].median()
    nominal_step = float(nominal_step) if pd.notna(nominal_step) else 0.0
    duty["sampleDurationSeconds"] = nominal_step
    duty["activeDurationSeconds"] = duty["sampleDurationSeconds"].where(duty["observingAustralia"], 0.0)

    duty["inEclipse"] = False
    if not eclipse.empty and {"Satellite Name", "Start UTC", "Stop UTC"}.issubset(eclipse.columns):
        ec = eclipse[["Satellite Name", "Start UTC", "Stop UTC"]].copy()
        ec["Start UTC"] = pd.to_datetime(ec["Start UTC"], errors="coerce")
        ec["Stop UTC"] = pd.to_datetime(ec["Stop UTC"], errors="coerce")
        ec = ec.dropna()
        for sat_name, intervals in ec.groupby("Satellite Name"):
            sat_mask = duty["Satellite Name"].eq(sat_name)
            if not sat_mask.any():
                continue
            times = duty.loc[sat_mask, "Timestamp"]
            in_eclipse = pd.Series(False, index=times.index)
            for start, stop in intervals[["Start UTC", "Stop UTC"]].itertuples(index=False, name=None):
                in_eclipse |= times.between(start, stop)
            duty.loc[in_eclipse.index, "inEclipse"] = in_eclipse.values

    summary = duty.groupby("Satellite Name", as_index=False).agg(
        samples=("Timestamp", "size"),
        activeSamples=("observingAustralia", "sum"),
        activeDurationSeconds=("activeDurationSeconds", "sum"),
        eclipseSamples=("inEclipse", "sum"),
    )
    summary["activeMinutes"] = summary["activeDurationSeconds"] / 60.0
    summary["dutyPercent"] = 100.0 * summary["activeSamples"] / summary["samples"]
    summary = summary.rename(columns={"Satellite Name": "satellite"})

    timeline = duty.groupby("Timestamp", as_index=False).agg(
        observingSatellites=("observingAustralia", "sum"),
        eclipseSatellites=("inEclipse", "sum"),
    ).sort_values("Timestamp")
    if len(timeline) > 600:
        timeline = timeline.iloc[:: max(int(len(timeline) / 600), 1), :]
    timeline["Timestamp"] = timeline["Timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")

    total_samples = len(duty)
    active_samples = int(duty["observingAustralia"].sum())
    active_hours = float(duty["activeDurationSeconds"].sum() / 3600.0)
    overlap_hours = float(duty.loc[duty["observingAustralia"] & duty["inEclipse"], "sampleDurationSeconds"].sum() / 3600.0)

    return {
        "summary": records(summary.sort_values("activeDurationSeconds", ascending=False)),
        "timeline": records(timeline),
        "metrics": {
            "nominalStepSeconds": nominal_step,
            "activeSamples": active_samples,
            "totalSamples": total_samples,
            "fleetDutyPercent": (100.0 * active_samples / total_samples) if total_samples else 0.0,
            "fleetActiveHours": active_hours,
            "aoiEclipseOverlapHours": overlap_hours,
        },
    }


@lru_cache(maxsize=8)
def dashboard_payload(mission_id=DEFAULT_MISSION):
    mission_entry = get_mission(mission_id)
    region = region_for_mission(mission_id)
    config = load_mission_configuration(BASE, config_path=mission_entry["config_path"])
    mission = config["mission"]
    constellation = config["constellation"]
    orbit = config["orbit"]
    payload_cfg = config.get("payload", {}) if isinstance(config.get("payload", {}), dict) else {}

    rf = read_processed("RF_Contacts.xlsx", mission_id)
    optical = read_processed("Optical_Contacts.xlsx", mission_id)
    eclipse = read_processed("All_Eclipse_Events.xlsx", mission_id)
    state = read_processed("Satellite_State_History.xlsx", mission_id)

    configured_sats = int(float(constellation.get("Total Satellites", 0) or 0))
    planes = int(float(constellation.get("Number of Planes", 0) or 0))
    sats_per_plane = int(float(constellation.get("Satellites per Plane", 0) or 0))
    altitude = orbit.get("Altitude", None)
    camera = build_camera_model(altitude, payload_cfg)
    swath_km = float(camera["Ground Swath (km)"])

    detected = set()
    for frame in (rf, optical, eclipse, state):
        if not frame.empty and "Satellite Name" in frame.columns:
            detected.update(frame["Satellite Name"].dropna().astype(str).unique())

    latest, latest_time = latest_state(state)
    camera_sats = sorted(state["Satellite Name"].dropna().astype(str).unique()) if not state.empty else []
    camera_modules = build_camera_modules(camera_sats, camera)

    state_work = state.copy()
    if not state_work.empty:
        state_work["Timestamp"] = pd.to_datetime(state_work["Timestamp"], errors="coerce")
        for col in ["Latitude", "Longitude", "Altitude", "RMAG", "ECC"]:
            if col in state_work.columns:
                state_work[col] = pd.to_numeric(state_work[col], errors="coerce")

    tracks = []
    if not state_work.empty:
        for sat, group in state_work.sort_values("Timestamp").groupby("Satellite Name"):
            sample = group.iloc[:: max(int(len(group) / 90), 1), :]
            for row in sample.tail(90).itertuples(index=False):
                tracks.append(
                    {
                        "satellite": str(getattr(row, "Satellite_Name", sat)) if hasattr(row, "Satellite_Name") else str(sat),
                        "timestamp": clean_value(row.Timestamp),
                        "lat": clean_value(row.Latitude),
                        "lon": clean_value(row.Longitude),
                        "altitude": clean_value(row.Altitude),
                    }
                )

    altitude_history = []
    if not state_work.empty:
        alt = state_work.groupby("Satellite Name", as_index=False).agg(
            minAltitude=("Altitude", "min"),
            meanAltitude=("Altitude", "mean"),
            maxAltitude=("Altitude", "max"),
        )
        altitude_history = records(alt.rename(columns={"Satellite Name": "satellite"}))

    coverage_grid, coverage_contrib, coverage_pct = cumulative_region_coverage(state, swath_km, resolution_deg=1.0, region=region)
    coverage_view = coverage_grid.copy()
    if not coverage_view.empty:
        coverage_view = coverage_view.rename(columns={"Latitude": "lat", "Longitude": "lon", "Covered": "covered"})

    per_sat_obs, observation_windows, overall_obs, observation_timeline = observation_duration_analysis(state, swath_km, region=region)
    duty = build_duty(state, eclipse, swath_km, region=region)
    imaging_summary, imaging_fleet = build_imaging_summary(state, camera, per_sat_obs)
    global_per_sat, global_fleet, global_regions = build_global_coverage(state, region=region)

    latest_payload = latest.rename(
        columns={
            "Satellite Name": "satellite",
            "Latitude": "lat",
            "Longitude": "lon",
            "Altitude": "altitude",
        }
    )

    # Constellation Analytics Platform computations. Revisit is computed once
    # and shared -- it is the most expensive step and both the summary and the
    # gap analysis consume it.
    revisit_analytics = compute_revisit_analytics(state, swath_km, region=region)
    summary_analytics = compute_constellation_summary(
        config, state, rf, optical, camera, overall_obs,
        imaging_fleet=imaging_fleet, revisit_stats=revisit_analytics,
    )
    gap_analytics = compute_gap_analysis(revisit_analytics)
    sat_contributions = compute_satellite_contributions(state, rf, optical, duty.get("summary", []), records(imaging_summary), config)
    density_heatmaps = compute_density_heatmaps(state, rf, optical, camera, swath_km=swath_km, region=region)
    aoi_analytics = compute_aoi_analytics(state, camera, region, config)
    simulation_details = compute_simulation_details(config, state)
    mission_analytics = compute_mission_analytics(
        summary_analytics, gap_analytics, sat_contributions,
        coverage_percent=coverage_pct, observation_overall=overall_obs,
        state_df=state, rf_df=rf, optical_df=optical, eclipse_df=eclipse,
        constellation=constellation,
    )
    ground_station_analytics = compute_ground_station_analysis(rf, optical, config.get("ground_stations"))

    analytics_payload = {
        "summary": summary_analytics,
        "revisit": revisit_analytics,
        "gapAnalysis": gap_analytics,
        "satelliteContributions": sat_contributions,
        "heatmaps": density_heatmaps,
        "aoi": aoi_analytics,
        "simulationDetails": simulation_details,
        "missionHealth": mission_analytics,
        "groundStations": ground_station_analytics,
    }

    return {
        "analytics": analytics_payload,
        "mission": {
            "name": str(mission.get("Mission Name", "Mission")),
            "type": str(mission.get("Mission Type", "Not configured")),
            "aoi": str(mission.get("Area of Interest", "Not configured")),
            "aoiRegion": region,
            "aoiRegionLabel": region_label_for_mission(mission_id),
            "latestEpoch": latest_time.isoformat() if latest_time is not None else None,
        },
        "constellation": {
            "configuredSatellites": configured_sats,
            "detectedSatellites": len(detected),
            "planes": planes,
            "satellitesPerPlane": sats_per_plane,
            "altitudeKm": clean_value(altitude),
            "inclinationDeg": clean_value(orbit.get("Inclination", None)),
        },
        "metrics": {
            "rfEvents": len(rf),
            "opticalEvents": len(optical),
            "eclipseEvents": len(eclipse),
            "stateRows": len(state),
            "rfMinutes": numeric_sum(rf, "Duration (s)") / 60.0,
            "opticalMinutes": numeric_sum(optical, "Duration (s)") / 60.0,
            "eclipseHours": numeric_sum(eclipse, "Duration (s)") / 3600.0,
            "fleetCoveragePercent": (len(detected) / configured_sats * 100.0) if configured_sats else 0.0,
            "meanAltitude": clean_value(latest["Altitude"].mean()) if "Altitude" in latest.columns and not latest.empty else None,
            "meanEccentricity": clean_value(latest["ECC"].mean()) if "ECC" in latest.columns and not latest.empty else None,
        },
        "camera": {
            "model": {key: clean_value(value) if not isinstance(value, list) else value for key, value in camera.items()},
            "moduleCount": len(camera_modules),
            "modules": records(camera_modules),
        },
        "charts": {
            "eventMatrix": satellite_event_matrix(rf, optical, eclipse, state_df=state_work, satellites_per_plane=sats_per_plane),
            "eclipseTypes": count_by(eclipse, "Eclipse Type", "type", "events"),
            "groundStationsRf": top_duration(rf, "Ground Station"),
            "groundStationsOptical": top_duration(optical, "Ground Station"),
            "altitudeBands": altitude_history,
            "latestPositions": records(latest_payload),
            "tracks": tracks,
        },
        "coverage": {
            "percent": coverage_pct,
            "coveredCells": int(coverage_grid["Covered"].sum()) if not coverage_grid.empty else 0,
            "totalCells": int(len(coverage_grid)),
            "cells": records(coverage_view),
            "outline": [{"lon": lon, "lat": lat} for lon, lat in _REGION_OUTLINES.get(region, _REGION_OUTLINES["australia"])["outline"]],
            "tasmania": [{"lon": lon, "lat": lat} for lon, lat in _REGION_OUTLINES.get(region, _REGION_OUTLINES["australia"])["secondary"]],
            "aoi": AOI_BOXES.get(region, AOI_BOXES["australia"]),
            "contribution": records(coverage_contrib.rename(columns={"Satellite Name": "satellite", "Covered Cell Centers": "coveredCells"})),
            "observation": {
                "overall": overall_obs,
                "perSatellite": records(per_sat_obs.rename(columns={"Satellite Name": "satellite"})),
                "windows": records(observation_windows.rename(columns={"Satellite Name": "satellite"}), limit=250),
            },
        },
        "duty": duty,
        "imaging": {
            "fleet": {k: clean_value(v) for k, v in imaging_fleet.items()},
            "perSatellite": records(imaging_summary),
        },
        "globalCoverage": {
            "fleet": {k: clean_value(v) for k, v in global_fleet.items()},
            "regions": [{k: clean_value(v) for k, v in r.items()} for r in global_regions],
            "perSatellite": [
                {
                    **{k: clean_value(v) for k, v in r.items() if k != "regions"},
                    "regions": {k: clean_value(v) for k, v in r["regions"].items()},
                }
                for r in global_per_sat
            ],
        },
        "configuration": {
            "issues": validate_configuration(config),
            "mission": records(config["mission_table"]),
            "constellation": records(config["constellation_table"]),
            "orbit": records(config["orbit_table"]),
            "groundStations": records(config["ground_stations"]),
            "payload": records(config["payload_table"]),
            "power": records(config["power_table"]),
        },
        "tables": {
            "rf": records(rf.sort_values("Duration (s)", ascending=False) if not rf.empty else rf, limit=120),
            "optical": records(optical.sort_values("Duration (s)", ascending=False) if not optical.empty else optical, limit=120),
            "eclipse": records(eclipse.sort_values("Duration (s)", ascending=False) if not eclipse.empty else eclipse, limit=120),
        },
    }


@app.get("/api/health")
def health():
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# Imaging workflow (v1.0)
# --------------------------------------------------------------------------

def _products_dir(mission_id):
    return get_mission(mission_id)["products_dir"]


@lru_cache(maxsize=8)
def _camera(mission_id=DEFAULT_MISSION):
    mission_entry = get_mission(mission_id)
    config = load_mission_configuration(BASE, config_path=mission_entry["config_path"])
    payload_cfg = config.get("payload", {})
    payload_cfg = payload_cfg if isinstance(payload_cfg, dict) else {}
    return build_camera_model(config["orbit"].get("Altitude", None), payload_cfg)


@lru_cache(maxsize=8)
def _state_cached(mission_id=DEFAULT_MISSION):
    return read_processed("Satellite_State_History.xlsx", mission_id)


@lru_cache(maxsize=8)
def scene_catalog_payload(mission_id=DEFAULT_MISSION):
    """Every candidate scene the constellation could capture over the mission's AOI."""
    from core.footprint import scene_grid

    camera = _camera(mission_id)
    scenes = scene_grid(_state_cached(mission_id), camera, region=region_for_mission(mission_id))
    if scenes.empty:
        return {"scenes": [], "count": 0, "camera": {}}

    listing = scenes.copy()
    listing["timestamp"] = listing["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    listing["bbox"] = listing["bbox"].apply(list)
    return {
        "count": int(len(listing)),
        "camera": {
            "gsdM": camera["GSD (m/pixel)"],
            "swathKm": camera["Ground Swath (km)"],
            "bands": camera["Spectral Bands"],
        },
        "scenes": listing.to_dict(orient="records"),
    }


@app.get("/api/scenes")
def scenes():
    return jsonify(scene_catalog_payload(_mission_id_from_request()))


@app.post("/api/scenes/<scene_index>/generate")
def generate_scene(scene_index):
    """Generate a real product for one catalogued scene."""
    from core.footprint import scene_grid
    from core.imagery import ImageryUnavailable
    from core.imaging_summary import _ground_speed_km_s
    from core.products import generate_product

    mission_id = _mission_id_from_request()
    opts = request.get_json(silent=True) or {}
    camera = _camera(mission_id)
    state = _state_cached(mission_id)
    scenes_df = scene_grid(state, camera, region=region_for_mission(mission_id))

    try:
        idx = int(scene_index)
        scene = scenes_df.iloc[idx].to_dict()
    except (ValueError, IndexError):
        return jsonify({"ok": False, "error": f"No scene at index {scene_index}"}), 404

    sat_rows = state[state["Satellite Name"].astype(str) == scene["satellite"]].copy()
    sat_rows["Timestamp"] = pd.to_datetime(sat_rows["Timestamp"], errors="coerce")
    for col in ("Latitude", "Longitude"):
        sat_rows[col] = pd.to_numeric(sat_rows[col], errors="coerce")
    speed = _ground_speed_km_s(sat_rows.dropna(subset=["Timestamp", "Latitude", "Longitude"]))

    try:
        metadata = generate_product(
            scene,
            _products_dir(mission_id),
            ground_speed_km_s=speed,
            max_cloud=float(opts.get("maxCloud", 20.0)),
            add_noise=bool(opts.get("addNoise", True)),
            seed=opts.get("seed"),
        )
    except ImageryUnavailable as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502

    return jsonify({"ok": True, "product": metadata})


@app.get("/api/products")
def list_products():
    """Catalogue of already-generated products, newest first."""
    import json

    products_dir = _products_dir(_mission_id_from_request())
    if not products_dir.exists():
        return jsonify({"products": [], "count": 0})
    items = []
    for path in sorted(products_dir.glob("*.json")):
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    items.sort(key=lambda m: m.get("acquisition", {}).get("simulatedTimestampUtc", ""), reverse=True)
    return jsonify({"count": len(items), "products": items})


@app.get("/api/products/<scene_id>/<kind>")
def download_product(scene_id, kind):
    """Download a generated product file: geotiff, preview or metadata."""
    from flask import send_file

    suffix = {"geotiff": ".tif", "preview": ".png", "metadata": ".json"}.get(kind)
    if not suffix:
        return jsonify({"ok": False, "error": f"Unknown file kind {kind!r}"}), 400
    path = _products_dir(_mission_id_from_request()) / f"{scene_id}{suffix}"
    if not path.exists():
        return jsonify({"ok": False, "error": f"No {kind} for scene {scene_id}"}), 404
    return send_file(path, as_attachment=(kind != "preview"))


@app.get("/api/intelligence")
def intelligence():
    """Mission-level intelligence roll-up across all generated products."""
    import json

    from core.classify import mission_intelligence

    products_dir = _products_dir(_mission_id_from_request())
    products = []
    if products_dir.exists():
        for path in products_dir.glob("*.json"):
            try:
                products.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
    return jsonify(mission_intelligence(products))


# --------------------------------------------------------------------------
# Mission planning (v1.0)
# --------------------------------------------------------------------------


@app.get("/api/plan/opportunities")
def plan_opportunities():
    from core.planning import imaging_opportunities

    mission_id = _mission_id_from_request()
    try:
        lat = float(request.args["lat"])
        lon = float(request.args["lon"])
    except (KeyError, ValueError):
        return jsonify({"ok": False, "error": "lat and lon query parameters are required"}), 400

    opps = imaging_opportunities(
        _state_cached(mission_id), _camera(mission_id), lat, lon,
        after=request.args.get("after"),
        max_results=int(request.args.get("limit", 50)),
    )
    return jsonify({
        "target": {"lat": lat, "lon": lon},
        "count": int(len(opps)),
        "opportunities": records(opps),
    })


@app.get("/api/plan/revisit")
def plan_revisit():
    from core.planning import revisit_analysis

    mission_id = _mission_id_from_request()
    try:
        lat = float(request.args["lat"])
        lon = float(request.args["lon"])
    except (KeyError, ValueError):
        return jsonify({"ok": False, "error": "lat and lon query parameters are required"}), 400

    return jsonify(revisit_analysis(_state_cached(mission_id), _camera(mission_id), lat, lon))


@app.post("/api/plan/schedule")
def plan_schedule():
    from core.planning import schedule_requests

    mission_id = _mission_id_from_request()
    body = request.get_json(silent=True) or {}
    requests_in = body.get("requests", [])
    if not isinstance(requests_in, list) or not requests_in:
        return jsonify({"ok": False, "error": "Body must contain a non-empty 'requests' list"}), 400

    return jsonify(schedule_requests(_state_cached(mission_id), _camera(mission_id), requests_in))


@lru_cache(maxsize=32)
def _replay(mission_id, steps):
    from core.planning import coverage_replay

    return coverage_replay(_state_cached(mission_id), _camera(mission_id), steps=steps,
                            region=region_for_mission(mission_id))


@app.get("/api/plan/replay")
def plan_replay():
    mission_id = _mission_id_from_request()
    steps = max(2, min(int(request.args.get("steps", 24)), 96))
    return jsonify({"steps": steps, "frames": _replay(mission_id, steps)})


@lru_cache(maxsize=8)
def state_series_payload(mission_id=DEFAULT_MISSION, max_points=180):
    """Per-satellite downsampled state time-series for the State Explorer."""
    state = read_processed("Satellite_State_History.xlsx", mission_id)
    if state.empty:
        return {"satellites": [], "series": {}, "range": {}}

    work = state.copy()
    work["Timestamp"] = pd.to_datetime(work["Timestamp"], errors="coerce")
    for col in ["Latitude", "Longitude", "Altitude", "RMAG", "ECC"]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")
        else:
            # Not every mission's GMAT ReportFile includes RMAG/ECC (e.g. the
            # 3x1 mission's state report only has Lat/Lon/Altitude/epoch) --
            # keep the column present but empty rather than fail downstream.
            work[col] = pd.NA
    work = work.dropna(subset=["Timestamp", "Satellite Name"]).sort_values("Timestamp")

    aoi_box = AOI_BOXES.get(region_for_mission(mission_id), AOI_BOXES["australia"])
    in_aoi_all = (
        work["Longitude"].between(aoi_box["lonMin"], aoi_box["lonMax"])
        & work["Latitude"].between(aoi_box["latMin"], aoi_box["latMax"])
    )
    work["inAOI"] = in_aoi_all

    series = {}
    summary = []
    for sat, grp in work.groupby("Satellite Name"):
        grp = grp.sort_values("Timestamp")
        step = max(int(len(grp) / max_points), 1)
        sample = grp.iloc[::step, :]
        points = [
            {
                "t": clean_value(row.Timestamp),
                "lat": clean_value(row.Latitude),
                "lon": clean_value(row.Longitude),
                "alt": clean_value(row.Altitude),
                "rmag": clean_value(row.RMAG),
                "ecc": clean_value(row.ECC),
                "inAOI": bool(row.inAOI),
            }
            for row in sample.itertuples(index=False)
        ]
        series[str(sat)] = points
        aoi_share = float(100.0 * grp["inAOI"].mean()) if len(grp) else 0.0
        summary.append(
            {
                "satellite": str(sat),
                "samples": int(len(grp)),
                "minAltitude": clean_value(grp["Altitude"].min()),
                "meanAltitude": clean_value(grp["Altitude"].mean()),
                "maxAltitude": clean_value(grp["Altitude"].max()),
                "meanEccentricity": clean_value(grp["ECC"].mean()),
                "meanRmag": clean_value(grp["RMAG"].mean()),
                "aoiSharePercent": aoi_share,
                "aoiSamples": int(grp["inAOI"].sum()),
            }
        )

    return {
        "satellites": sorted(series.keys()),
        "series": series,
        "summary": sorted(summary, key=lambda r: r["satellite"]),
        "aoi": aoi_box,
        "range": {
            "start": clean_value(work["Timestamp"].min()),
            "end": clean_value(work["Timestamp"].max()),
        },
    }


@app.get("/api/satellite/<satellite_name>")
def satellite_profile(satellite_name):
    """One satellite's full profile, sliced from data already computed
    elsewhere: state summary, contacts, eclipse events, imaging opportunities
    and its constellation-contribution figures."""
    denied = _require("sat-contribution")
    if denied:
        return denied

    mission_id = _mission_id_from_request()
    payload = dashboard_payload(mission_id)

    rf = read_processed("RF_Contacts.xlsx", mission_id)
    optical = read_processed("Optical_Contacts.xlsx", mission_id)
    eclipse = read_processed("All_Eclipse_Events.xlsx", mission_id)
    state = read_processed("Satellite_State_History.xlsx", mission_id)

    def filt(df):
        if df.empty or "Satellite Name" not in df.columns:
            return df.iloc[0:0]
        return df[df["Satellite Name"].astype(str) == satellite_name]

    sat_rf = filt(rf)
    sat_optical = filt(optical)
    sat_eclipse = filt(eclipse)
    sat_state = filt(state)

    if sat_state.empty and sat_rf.empty and sat_optical.empty and sat_eclipse.empty:
        return jsonify({"ok": False, "error": f"Unknown satellite {satellite_name!r} for mission {mission_id}"}), 404

    state_summary = {}
    if not sat_state.empty:
        alt = pd.to_numeric(sat_state["Altitude"], errors="coerce")
        state_summary = {
            "samples": int(len(sat_state)),
            "minAltitudeKm": clean_value(alt.min()),
            "meanAltitudeKm": clean_value(alt.mean()),
            "maxAltitudeKm": clean_value(alt.max()),
        }

    contributions = payload.get("analytics", {}).get("satelliteContributions", [])
    contribution = next((c for c in contributions if c.get("satellite") == satellite_name), None)

    observations = []
    try:
        from api_image_center import _catalog as _ic_catalog

        cat = _ic_catalog(mission_id)
        if not cat.empty and "satellite" in cat.columns:
            sat_cat = cat[cat["satellite"].astype(str) == satellite_name]
            if "captureEpochUtc" in sat_cat.columns:
                sat_cat = sat_cat.sort_values("captureEpochUtc")
            observations = records(sat_cat, limit=200)
    except Exception:  # noqa: BLE001 -- image center catalog is a best-effort addition here
        observations = []

    return jsonify({
        "satellite": satellite_name,
        "mission": mission_id,
        "state": state_summary,
        "contribution": contribution,
        "rf": records(sat_rf.sort_values("Start UTC") if not sat_rf.empty else sat_rf),
        "optical": records(sat_optical.sort_values("Start UTC") if not sat_optical.empty else sat_optical),
        "eclipse": records(sat_eclipse.sort_values("Start UTC") if not sat_eclipse.empty else sat_eclipse),
        "observations": observations,
        "observationCount": len(observations),
    })


@app.get("/api/analytics/aoi/<aoi_key>")
def aoi_analytics_endpoint(aoi_key):
    mission_id = _mission_id_from_request()
    mission_entry = get_mission(mission_id)
    config = load_mission_configuration(BASE, config_path=mission_entry["config_path"])
    camera = _camera(mission_id)
    state = _state_cached(mission_id)
    return jsonify(compute_aoi_analytics(state, camera, aoi_key, config))


@app.get("/api/missions")
def missions():
    return jsonify({"missions": list_missions(), "default": DEFAULT_MISSION})


@app.get("/api/glossary")
def glossary():
    return jsonify({"terms": GLOSSARY})


@app.get("/api/dataquality")
def data_quality():
    denied = _require("data")
    if denied:
        return denied
    return jsonify(assess_data_quality(_mission_id_from_request()))


# --------------------------------------------------------------------------
# Access control
# --------------------------------------------------------------------------


@app.get("/api/access/sections")
def access_sections():
    """Every section, mission and download-lock, and whether this caller has
    unlocked each. Never returns codes."""
    return jsonify({
        "sections": section_listing(_unlocked()),
        "missions": mission_listing(_unlocked_missions()),
        "downloads": download_listing(_unlocked_downloads()),
    })


@app.post("/api/access/unlock")
def access_unlock():
    """Exchange a section's, mission's, download's, or the master, code for
    a token that includes it.

    The caller passes back its existing token so unlocks accumulate: entering
    a second section's code widens the same session rather than replacing it.
    """
    # Guessing is the only way in, so make guesses expensive.
    allowed, wait = throttle_state(request)
    if not allowed:
        return jsonify({
            "ok": False,
            "error": f"Too many incorrect attempts. Try again in {wait} seconds.",
            "retryAfterSeconds": wait,
        }), 429

    body = request.get_json(silent=True) or {}
    section = str(body.get("section", "")).strip()
    mission = str(body.get("mission", "")).strip()
    download_section = str(body.get("downloadSection", "")).strip()
    code = str(body.get("code", "")).strip()

    already_sections = verify_token(body.get("token")) | _unlocked()
    already_missions = verify_mission_token(body.get("token")) | _unlocked_missions()
    already_downloads = verify_download_token(body.get("token")) | _unlocked_downloads()

    # section="*" is the master code: one code that grants every section,
    # mission AND download at once, for someone (developer, reviewer,
    # leadership) who needs the whole dashboard rather than unlocking each
    # one in turn. Mirrors the "*" convention /api/access/lock uses to lock
    # everything back up.
    if section == "*":
        if not verify_master_code(code):
            record_failure(request)
            return jsonify({"ok": False, "error": "Incorrect access code"}), 401
        clear_failures(request)
        granted_sections = already_sections | CODED_SECTIONS
        granted_missions = already_missions | set(MISSIONS)
        granted_downloads = already_downloads | CODED_SECTIONS
        return jsonify({
            "ok": True,
            "token": issue_token(granted_sections, granted_missions, granted_downloads),
            "unlocked": sorted(granted_sections),
            "unlockedMissions": sorted(granted_missions),
            "unlockedDownloads": sorted(granted_downloads),
            "section": "*",
            "label": "Full Access",
        })

    # A mission switch, gated the same way a section is: its own code, its
    # own throttle, and the token carries it forward the same way.
    if mission:
        if mission not in MISSIONS:
            return jsonify({"ok": False, "error": f"Unknown mission {mission!r}"}), 404
        if not verify_mission_code(mission, code):
            record_failure(request)
            return jsonify({"ok": False, "error": "Incorrect access code"}), 401
        clear_failures(request)
        granted_missions = already_missions | {mission}
        return jsonify({
            "ok": True,
            "token": issue_token(already_sections, granted_missions, already_downloads),
            "unlocked": sorted(already_sections),
            "unlockedMissions": sorted(granted_missions),
            "unlockedDownloads": sorted(already_downloads),
            "mission": mission,
            "label": get_mission(mission)["label"],
        })

    # A download unlock: a second, separate code from the section's view
    # code, entered at the moment of download rather than reused from
    # whatever unlocked the section for viewing.
    if download_section:
        if download_section not in SECTIONS:
            return jsonify({"ok": False, "error": f"Unknown section {download_section!r}"}), 404
        if not verify_download_code(download_section, code):
            record_failure(request)
            return jsonify({"ok": False, "error": "Incorrect access code"}), 401
        clear_failures(request)
        granted_downloads = already_downloads | {download_section}
        return jsonify({
            "ok": True,
            "token": issue_token(already_sections, already_missions, granted_downloads),
            "unlocked": sorted(already_sections),
            "unlockedMissions": sorted(already_missions),
            "unlockedDownloads": sorted(granted_downloads),
            "downloadSection": download_section,
            "label": SECTIONS[download_section]["label"],
        })

    if section not in SECTIONS:
        return jsonify({"ok": False, "error": f"Unknown section {section!r}"}), 404

    if not verify_code(section, code):
        record_failure(request)
        return jsonify({"ok": False, "error": "Incorrect access code"}), 401

    clear_failures(request)

    granted_sections = already_sections | {section}
    return jsonify({
        "ok": True,
        "token": issue_token(granted_sections, already_missions, already_downloads),
        "unlocked": sorted(granted_sections),
        "unlockedMissions": sorted(already_missions),
        "unlockedDownloads": sorted(already_downloads),
        "section": section,
        "label": SECTIONS[section]["label"],
    })


@app.post("/api/access/lock")
def access_lock():
    """Give back access to a section, a mission, or a download: re-issue the
    token without it.

    Locking needs no code -- you can always surrender access you hold. Pass
    section="*" to lock every section (missions/downloads are untouched);
    mission="<id>" to lock one mission back to needing its code again;
    downloadSection="<id>" to lock one section's download access back to
    needing its download code again.
    """
    body = request.get_json(silent=True) or {}
    section = str(body.get("section", "")).strip()
    mission = str(body.get("mission", "")).strip()
    download_section = str(body.get("downloadSection", "")).strip()
    held_sections = verify_token(body.get("token")) | _unlocked()
    held_missions = verify_mission_token(body.get("token")) | _unlocked_missions()
    held_downloads = verify_download_token(body.get("token")) | _unlocked_downloads()

    if mission:
        if mission not in MISSIONS:
            return jsonify({"ok": False, "error": f"Unknown mission {mission!r}"}), 404
        remaining_missions = held_missions - {mission}
        return jsonify({
            "ok": True,
            "token": issue_token(held_sections, remaining_missions, held_downloads),
            "unlocked": sorted(held_sections),
            "unlockedMissions": sorted(remaining_missions),
            "unlockedDownloads": sorted(held_downloads),
            "mission": mission,
        })

    if download_section:
        if download_section not in SECTIONS:
            return jsonify({"ok": False, "error": f"Unknown section {download_section!r}"}), 404
        remaining_downloads = held_downloads - {download_section}
        return jsonify({
            "ok": True,
            "token": issue_token(held_sections, held_missions, remaining_downloads),
            "unlocked": sorted(held_sections),
            "unlockedMissions": sorted(held_missions),
            "unlockedDownloads": sorted(remaining_downloads),
            "downloadSection": download_section,
        })

    if section == "*":
        remaining = set()
    elif section in SECTIONS:
        remaining = held_sections - {section}
    else:
        return jsonify({"ok": False, "error": f"Unknown section {section!r}"}), 404

    return jsonify({
        "ok": True,
        "token": issue_token(remaining, held_missions, held_downloads),
        "unlocked": sorted(remaining),
        "unlockedMissions": sorted(held_missions),
        "unlockedDownloads": sorted(held_downloads),
        "section": section,
    })


@app.get("/api/dashboard")
def dashboard():
    """Mission payload, stripped to just what the caller's unlocked sections need."""
    payload = dashboard_payload(_mission_id_from_request())
    return jsonify(filter_dashboard_payload(payload, _unlocked()))


@app.get("/api/state")
def state_series():
    # The state report is one indivisible telemetry series shared by several
    # views, so any state-consuming section grants it.
    denied = _require(*sorted(STATE_SECTIONS))
    if denied:
        return denied
    return jsonify(state_series_payload(_mission_id_from_request()))


@app.post("/api/refresh")
def refresh():
    denied = _require("data")
    if denied:
        return denied
    mission_id = _mission_id_from_request() or (request.get_json(silent=True) or {}).get("mission") or DEFAULT_MISSION
    mission_entry = get_mission(mission_id)
    result = run_pipeline(
        base_dir=BASE,
        raw_dir=mission_entry["raw_dir"],
        out_dir=mission_entry["processed_dir"],
    )
    dashboard_payload.cache_clear()
    state_series_payload.cache_clear()
    _state_cached.cache_clear()
    scene_catalog_payload.cache_clear()
    _replay.cache_clear()
    return jsonify({"ok": True, "mission": mission_id, "result": result})


@app.get("/api/compare")
def compare_missions():
    """Side-by-side projection of key metrics across the requested missions."""
    # The consolidated report (Data & Config) embeds a comparison section, so
    # either code opens this.
    denied = _require("comparison", "data")
    if denied:
        return denied

    raw = request.args.get("missions", "")
    ids = [m.strip() for m in raw.split(",") if m.strip()] or [DEFAULT_MISSION]
    ids = [get_mission(m)["id"] for m in ids]
    # This endpoint takes a plural ?missions= list rather than the singular
    # ?mission= the before_request hook checks, so the mission gate is
    # applied here explicitly: a mission the caller has not unlocked is
    # dropped from the comparison rather than leaking its data through a
    # section code that was never meant to open it.
    granted_missions = _unlocked_missions()
    ids = [m for m in ids if m in granted_missions]
    if not ids:
        ids = [DEFAULT_MISSION]

    out = []
    for mission_id in ids:
        payload = dashboard_payload(mission_id)
        analytics = payload.get("analytics", {})
        summary = analytics.get("summary", {})
        gap = analytics.get("gapAnalysis", {})
        out.append({
            "missionId": mission_id,
            "label": get_mission(mission_id)["label"],
            "constellation": payload["constellation"],
            "coveragePercent": payload["coverage"]["percent"],
            "rfEvents": payload["metrics"]["rfEvents"],
            "opticalEvents": payload["metrics"]["opticalEvents"],
            "eclipseEvents": payload["metrics"]["eclipseEvents"],
            "rfMinutes": payload["metrics"]["rfMinutes"],
            "opticalMinutes": payload["metrics"]["opticalMinutes"],
            "eclipseHours": payload["metrics"]["eclipseHours"],
            "meanRevisitMin": summary.get("meanRevisitMin"),
            "worstRevisitMin": summary.get("worstRevisitMin"),
            "bestRevisitMin": summary.get("bestRevisitMin"),
            "largestGapMin": gap.get("largestGapMin"),
            "meanGapMin": gap.get("meanGapMin"),
            "imagesPerDay": summary.get("imagesPerDay"),
            "rfContactsPerDay": summary.get("rfContactsPerDay"),
            "satelliteContributions": analytics.get("satelliteContributions", []),
        })
    return jsonify({"missions": out, "observations": compute_engineering_observations(out)})


def _all_missions_compare_rows():
    # Excludes any mission the caller has not unlocked -- this report is
    # reachable with just the "data" section code, which was never meant to
    # be a way to see a mission whose own code was never entered.
    granted_missions = _unlocked_missions()
    out = []
    for m in list_missions():
        mission_id = m["id"]
        if mission_id not in granted_missions:
            continue
        payload = dashboard_payload(mission_id)
        analytics = payload.get("analytics", {})
        summary = analytics.get("summary", {})
        gap = analytics.get("gapAnalysis", {})
        out.append({
            "missionId": mission_id,
            "label": m["label"],
            "constellation": payload["constellation"],
            "coveragePercent": payload["coverage"]["percent"],
            "rfEvents": payload["metrics"]["rfEvents"],
            "opticalEvents": payload["metrics"]["opticalEvents"],
            "eclipseEvents": payload["metrics"]["eclipseEvents"],
            "rfMinutes": payload["metrics"]["rfMinutes"],
            "opticalMinutes": payload["metrics"]["opticalMinutes"],
            "eclipseHours": payload["metrics"]["eclipseHours"],
            "meanRevisitMin": summary.get("meanRevisitMin"),
            "largestGapMin": gap.get("largestGapMin"),
            "meanGapMin": gap.get("meanGapMin"),
            "imagesPerDay": summary.get("imagesPerDay"),
            "rfContactsPerDay": summary.get("rfContactsPerDay"),
        })
    return out


@app.get("/api/report/excel")
def report_excel():
    """Consolidated multi-sheet mission analysis report -- executive summary,
    configuration, coverage/gap/revisit, contacts, ground stations, eclipse,
    satellite contribution, simulation details, data quality, parameter
    glossary and a cross-mission comparison. Built with openpyxl (already a
    backend dependency) rather than adding a client-side Excel library."""
    denied = _require("data")
    if denied:
        return denied
    denied = _require_download("data")
    if denied:
        return denied

    import io
    from datetime import datetime, timezone

    import openpyxl
    from flask import send_file
    from openpyxl.styles import Font, PatternFill

    mission_id = _mission_id_from_request()
    mission_entry = get_mission(mission_id)
    payload = dashboard_payload(mission_id)
    quality = assess_data_quality(mission_id)
    compare_rows = _all_missions_compare_rows()
    observations = compute_engineering_observations(compare_rows)

    mission = payload["mission"]
    constellation = payload["constellation"]
    metrics = payload["metrics"]
    analytics = payload.get("analytics", {})
    summary = analytics.get("summary", {})
    gap = analytics.get("gapAnalysis", {})
    revisit = analytics.get("revisit", {})
    sim = analytics.get("simulationDetails", {})

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="2282EE")

    def write_kv_sheet(name, rows):
        ws = wb.create_sheet(name[:31])
        ws.append(["Parameter", "Value"])
        for c in ws[1]:
            c.font = header_font
            c.fill = header_fill
        for k, v in rows:
            ws.append([k, v if v is not None else "Not Available"])
        ws.column_dimensions["A"].width = 34
        ws.column_dimensions["B"].width = 54
        return ws

    def write_table_sheet(name, columns, rows):
        ws = wb.create_sheet(name[:31])
        ws.append(columns)
        for c in ws[1]:
            c.font = header_font
            c.fill = header_fill
        for row in rows:
            ws.append([str(row.get(col, "")) if row.get(col) is not None else "" for col in columns])
        for i in range(len(columns)):
            ws.column_dimensions[chr(65 + i)].width = 22
        return ws

    write_kv_sheet("Executive Summary", [
        ("Mission", mission.get("name")),
        ("Configuration", f'{constellation.get("planes")} x {constellation.get("satellitesPerPlane")}'),
        ("Total Satellites", constellation.get("configuredSatellites")),
        ("Nominal Orbit Altitude (km)", constellation.get("altitudeKm")),
        ("Inclination (deg)", constellation.get("inclinationDeg")),
        ("Area of Interest", mission.get("aoi")),
        ("Australia Coverage (%)", payload["coverage"]["percent"]),
        ("Mean Revisit (min)", summary.get("meanRevisitMin")),
        ("Largest Coverage Gap (min)", gap.get("largestGapMin")),
        ("RF Contact Events", metrics.get("rfEvents")),
        ("Optical Contact Events", metrics.get("opticalEvents")),
        ("Eclipse Events", metrics.get("eclipseEvents")),
        ("State Samples", metrics.get("stateRows")),
        ("Report Generated (UTC)", datetime.now(timezone.utc).isoformat()),
    ])

    config_rows = (
        [(r.get("Parameter"), r.get("Value")) for r in payload["configuration"]["mission"]]
        + [(r.get("Parameter"), r.get("Value")) for r in payload["configuration"]["constellation"]]
        + [(r.get("Parameter"), r.get("Value")) for r in payload["configuration"]["orbit"]]
    )
    write_kv_sheet("Mission Configuration", config_rows)
    write_table_sheet(
        "Ground Stations Config",
        ["Station Name", "Link Type", "Latitude (deg)", "Longitude (deg)", "Minimum Elevation (deg)"],
        payload["configuration"]["groundStations"],
    )

    write_kv_sheet("Coverage & Gap Analysis", [
        ("Australia Coverage (%)", payload["coverage"]["percent"]),
        ("Covered Cells", payload["coverage"]["coveredCells"]),
        ("Total Cells", payload["coverage"]["totalCells"]),
        ("Largest Gap (min)", gap.get("largestGapMin")),
        ("Mean Gap (min)", gap.get("meanGapMin")),
        ("Median Gap (min)", gap.get("medianGapMin")),
        ("Max Gap (min)", gap.get("maxGapMin")),
        ("95th Percentile Gap (min)", gap.get("p95GapMin")),
        ("% Grid Cells Satisfying Requirement", gap.get("pctSatisfyingRequirement")),
        ("Requirement Threshold (min)", gap.get("requirementMin")),
        ("Data-bearing Grid Cells", gap.get("dataBearingCells")),
        ("Total Grid Cells", gap.get("totalCells")),
    ])

    write_kv_sheet("Revisit Analysis", [
        ("Mean Revisit (min)", revisit.get("mean_revisit")),
        ("Minimum Revisit (min)", revisit.get("min_revisit")),
        ("Maximum Revisit (min)", revisit.get("max_revisit")),
        ("Median Revisit (min)", revisit.get("median_revisit")),
        ("95th Percentile Revisit (min)", revisit.get("p95_revisit")),
    ])

    contact_cols = ["Satellite Name", "Ground Station", "Start UTC", "Stop UTC", "Duration (s)"]
    write_table_sheet("RF Contacts", contact_cols, payload["tables"]["rf"])
    write_table_sheet("Optical Contacts", contact_cols, payload["tables"]["optical"])

    write_table_sheet(
        "Ground Station Analysis",
        ["stationName", "linkType", "minElevationDeg", "passCount", "totalDurationSec", "avgDurationSec", "minDurationSec", "maxDurationSec", "longestGapMin"],
        analytics.get("groundStations", []),
    )

    write_table_sheet(
        "Eclipse Events",
        ["Satellite Name", "Eclipse Type", "Start UTC", "Stop UTC", "Duration (s)"],
        payload["tables"]["eclipse"],
    )

    write_table_sheet(
        "Satellite Contribution",
        ["satellite", "coverageContributionPct", "rfContacts", "opticalContacts", "meanDutyCyclePct", "imagesCaptured", "avgObservationDurationMin", "isLowContributor"],
        analytics.get("satelliteContributions", []),
    )

    verified = set(sim.get("verifiedFields", []))
    ws = wb.create_sheet("Simulation Details")
    ws.append(["Parameter", "Value", "Verification"])
    for c in ws[1]:
        c.font = header_font
        c.fill = header_fill
    for key, value in sim.items():
        if key == "verifiedFields":
            continue
        ws.append([key, value, "Verified" if key in verified else "Assumed (not verified for this mission)"])
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 44
    ws.column_dimensions["C"].width = 32

    write_table_sheet("Data Quality", ["dataset", "status", "detail"], quality["checks"])

    write_table_sheet(
        "Parameter Definitions",
        ["name", "definition", "unit", "source", "calculation", "significance"],
        GLOSSARY,
    )

    write_table_sheet(
        "Mission Comparison",
        ["label", "coveragePercent", "meanRevisitMin", "largestGapMin", "rfEvents", "opticalEvents", "eclipseEvents", "rfMinutes", "opticalMinutes", "eclipseHours"],
        compare_rows,
    )

    ws = wb.create_sheet("Engineering Observations")
    ws.append(["Observation (factual comparison, not a recommendation)"])
    for c in ws[1]:
        c.font = header_font
        c.fill = header_fill
    for obs in observations:
        ws.append([obs])
    ws.column_dimensions["A"].width = 110

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    safe_label = mission_entry["label"].replace(" ", "_").replace("—", "-")
    filename = f"{safe_label}_Full_Mission_Report.xlsx"
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )


def _warm_caches():
    """Precompute each mission's payload in the background at startup.

    Building the 48-satellite payload takes several seconds the first time.
    Doing it here means the wait happens while the server is starting rather
    than while the operator watches the loading screen. Failures are ignored:
    this is only a head start, the request path recomputes if needed.
    """
    import threading

    def run():
        for entry in list_missions():
            try:
                dashboard_payload(entry["id"])
                state_series_payload(entry["id"])
            except Exception:
                pass

    threading.Thread(target=run, name="warm-caches", daemon=True).start()


if __name__ == "__main__":
    import os

    # Under the reloader only the child process serves requests; warming in
    # the parent too would duplicate the work for nothing.
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        _warm_caches()

    app.run(host="127.0.0.1", port=5001, debug=True)
