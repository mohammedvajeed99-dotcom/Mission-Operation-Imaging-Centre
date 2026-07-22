from functools import lru_cache
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify
from flask_cors import CORS

from core.australia_coverage import (
    MAINLAND_AUSTRALIA,
    TASMANIA,
    footprint_intersects_australia,
)
from core.camera_model import build_camera_model, build_camera_modules
from core.config_loader import load_mission_configuration, validate_configuration
from core.cumulative_coverage import cumulative_australia_coverage
from core.data_pipeline import run_pipeline
from core.global_regions import build_global_coverage
from core.imaging_summary import build_imaging_summary
from core.observation_duration import observation_duration_analysis


BASE = Path(__file__).resolve().parent
PROCESSED = BASE / "data" / "processed"

# Mission Area of Interest rectangle (from the mission duty-cycle matrix):
# longitude 110E..160E, latitude 10S..40S.
AOI = {"lonMin": 110.0, "lonMax": 160.0, "latMin": -40.0, "latMax": -10.0}

app = Flask(__name__)
CORS(app)

# Mission Image Center (v1.1) -- additive blueprint under /api/imagecenter.
# Registered here only; it defines no route that existed before and modifies
# no existing endpoint, payload or calculation.
from api_image_center import bp as image_center_bp  # noqa: E402

app.register_blueprint(image_center_bp)


def read_processed(name):
    path = PROCESSED / name
    return pd.read_excel(path) if path.exists() else pd.DataFrame()


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


def satellite_event_matrix(rf, optical, eclipse):
    satellites = sorted(
        set(rf.get("Satellite Name", pd.Series(dtype=str)).dropna().astype(str))
        | set(optical.get("Satellite Name", pd.Series(dtype=str)).dropna().astype(str))
        | set(eclipse.get("Satellite Name", pd.Series(dtype=str)).dropna().astype(str))
    )
    rows = []
    for sat in satellites:
        rows.append(
            {
                "satellite": sat,
                "rf": int((rf.get("Satellite Name", pd.Series(dtype=str)).astype(str) == sat).sum()) if not rf.empty else 0,
                "optical": int((optical.get("Satellite Name", pd.Series(dtype=str)).astype(str) == sat).sum()) if not optical.empty else 0,
                "eclipse": int((eclipse.get("Satellite Name", pd.Series(dtype=str)).astype(str) == sat).sum()) if not eclipse.empty else 0,
            }
        )
    return rows


def build_duty(state, eclipse, swath_km):
    if state.empty:
        return {"summary": [], "timeline": [], "metrics": {}}

    duty = state.copy()
    duty["Timestamp"] = pd.to_datetime(duty["Timestamp"], errors="coerce")
    duty["Latitude"] = pd.to_numeric(duty["Latitude"], errors="coerce")
    duty["Longitude"] = pd.to_numeric(duty["Longitude"], errors="coerce")
    duty = duty.dropna(subset=["Timestamp", "Satellite Name", "Latitude", "Longitude"])
    duty["observingAustralia"] = footprint_intersects_australia(
        duty, float(swath_km), lon_col="Longitude", lat_col="Latitude"
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


@lru_cache(maxsize=1)
def dashboard_payload():
    config = load_mission_configuration(BASE)
    mission = config["mission"]
    constellation = config["constellation"]
    orbit = config["orbit"]
    payload_cfg = config.get("payload", {}) if isinstance(config.get("payload", {}), dict) else {}

    rf = read_processed("RF_Contacts.xlsx")
    optical = read_processed("Optical_Contacts.xlsx")
    eclipse = read_processed("All_Eclipse_Events.xlsx")
    state = read_processed("Satellite_State_History.xlsx")

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

    coverage_grid, coverage_contrib, coverage_pct = cumulative_australia_coverage(state, swath_km, resolution_deg=1.0)
    coverage_view = coverage_grid.copy()
    if not coverage_view.empty:
        coverage_view = coverage_view.rename(columns={"Latitude": "lat", "Longitude": "lon", "Covered": "covered"})

    per_sat_obs, observation_windows, overall_obs, observation_timeline = observation_duration_analysis(state, swath_km)
    duty = build_duty(state, eclipse, swath_km)
    imaging_summary, imaging_fleet = build_imaging_summary(state, camera, per_sat_obs)
    global_per_sat, global_fleet, global_regions = build_global_coverage(state)

    latest_payload = latest.rename(
        columns={
            "Satellite Name": "satellite",
            "Latitude": "lat",
            "Longitude": "lon",
            "Altitude": "altitude",
        }
    )

    return {
        "mission": {
            "name": str(mission.get("Mission Name", "Mission")),
            "type": str(mission.get("Mission Type", "Not configured")),
            "aoi": str(mission.get("Area of Interest", "Not configured")),
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
            "eventMatrix": satellite_event_matrix(rf, optical, eclipse),
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
            "outline": [{"lon": lon, "lat": lat} for lon, lat in MAINLAND_AUSTRALIA],
            "tasmania": [{"lon": lon, "lat": lat} for lon, lat in TASMANIA],
            "aoi": AOI,
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

PRODUCTS = BASE / "data" / "products"


def _camera():
    config = load_mission_configuration(BASE)
    payload_cfg = config.get("payload", {})
    payload_cfg = payload_cfg if isinstance(payload_cfg, dict) else {}
    return build_camera_model(config["orbit"].get("Altitude", None), payload_cfg)


@lru_cache(maxsize=1)
def _state_cached():
    return read_processed("Satellite_State_History.xlsx")


@lru_cache(maxsize=1)
def scene_catalog_payload():
    """Every candidate scene the constellation could capture over Australia."""
    from core.footprint import scene_grid

    camera = _camera()
    scenes = scene_grid(_state_cached(), camera)
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
    return jsonify(scene_catalog_payload())


@app.post("/api/scenes/<scene_index>/generate")
def generate_scene(scene_index):
    """Generate a real product for one catalogued scene."""
    from flask import request

    from core.footprint import scene_grid
    from core.imagery import ImageryUnavailable
    from core.imaging_summary import _ground_speed_km_s
    from core.products import generate_product

    opts = request.get_json(silent=True) or {}
    camera = _camera()
    state = _state_cached()
    scenes_df = scene_grid(state, camera)

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
            PRODUCTS,
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

    if not PRODUCTS.exists():
        return jsonify({"products": [], "count": 0})
    items = []
    for path in sorted(PRODUCTS.glob("*.json")):
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
    path = PRODUCTS / f"{scene_id}{suffix}"
    if not path.exists():
        return jsonify({"ok": False, "error": f"No {kind} for scene {scene_id}"}), 404
    return send_file(path, as_attachment=(kind != "preview"))


@app.get("/api/intelligence")
def intelligence():
    """Mission-level intelligence roll-up across all generated products."""
    import json

    from core.classify import mission_intelligence

    products = []
    if PRODUCTS.exists():
        for path in PRODUCTS.glob("*.json"):
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
    from flask import request

    from core.planning import imaging_opportunities

    try:
        lat = float(request.args["lat"])
        lon = float(request.args["lon"])
    except (KeyError, ValueError):
        return jsonify({"ok": False, "error": "lat and lon query parameters are required"}), 400

    opps = imaging_opportunities(
        _state_cached(), _camera(), lat, lon,
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
    from flask import request

    from core.planning import revisit_analysis

    try:
        lat = float(request.args["lat"])
        lon = float(request.args["lon"])
    except (KeyError, ValueError):
        return jsonify({"ok": False, "error": "lat and lon query parameters are required"}), 400

    return jsonify(revisit_analysis(_state_cached(), _camera(), lat, lon))


@app.post("/api/plan/schedule")
def plan_schedule():
    from flask import request

    from core.planning import schedule_requests

    body = request.get_json(silent=True) or {}
    requests_in = body.get("requests", [])
    if not isinstance(requests_in, list) or not requests_in:
        return jsonify({"ok": False, "error": "Body must contain a non-empty 'requests' list"}), 400

    return jsonify(schedule_requests(_state_cached(), _camera(), requests_in))


@lru_cache(maxsize=4)
def _replay(steps):
    from core.planning import coverage_replay

    return coverage_replay(_state_cached(), _camera(), steps=steps)


@app.get("/api/plan/replay")
def plan_replay():
    from flask import request

    steps = max(2, min(int(request.args.get("steps", 24)), 96))
    return jsonify({"steps": steps, "frames": _replay(steps)})


@lru_cache(maxsize=1)
def state_series_payload(max_points=180):
    """Per-satellite downsampled state time-series for the State Explorer."""
    state = read_processed("Satellite_State_History.xlsx")
    if state.empty:
        return {"satellites": [], "series": {}, "range": {}}

    work = state.copy()
    work["Timestamp"] = pd.to_datetime(work["Timestamp"], errors="coerce")
    for col in ["Latitude", "Longitude", "Altitude", "RMAG", "ECC"]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work.dropna(subset=["Timestamp", "Satellite Name"]).sort_values("Timestamp")

    in_aoi_all = (
        work["Longitude"].between(AOI["lonMin"], AOI["lonMax"])
        & work["Latitude"].between(AOI["latMin"], AOI["latMax"])
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
        "aoi": AOI,
        "range": {
            "start": clean_value(work["Timestamp"].min()),
            "end": clean_value(work["Timestamp"].max()),
        },
    }


@app.get("/api/dashboard")
def dashboard():
    return jsonify(dashboard_payload())


@app.get("/api/state")
def state_series():
    return jsonify(state_series_payload())


@app.post("/api/refresh")
def refresh():
    result = run_pipeline(BASE)
    dashboard_payload.cache_clear()
    state_series_payload.cache_clear()
    _state_cached.cache_clear()
    scene_catalog_payload.cache_clear()
    _replay.cache_clear()
    return jsonify({"ok": True, "result": result})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
