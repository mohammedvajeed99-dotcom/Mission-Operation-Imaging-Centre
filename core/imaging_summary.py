import math
import numpy as np
import pandas as pd

R_EARTH_KM = 6371.0088


def _haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = np.radians(lat2 - lat1)
    dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R_EARTH_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _ground_speed_km_s(group):
    """Median ground-track speed for one satellite from consecutive state fixes."""
    g = group.sort_values("Timestamp")
    lat1, lon1 = g["Latitude"].to_numpy(), g["Longitude"].to_numpy()
    lat2, lon2 = np.roll(lat1, -1), np.roll(lon1, -1)
    dt = g["Timestamp"].diff().shift(-1).dt.total_seconds().to_numpy()
    dist = _haversine_km(lat1, lon1, lat2, lon2)
    with np.errstate(divide="ignore", invalid="ignore"):
        speed = dist / dt
    valid = speed[np.isfinite(speed) & (speed > 0) & (speed < 9.0)]
    return float(np.median(valid)) if valid.size else None


def build_imaging_summary(state_df, camera_model, per_sat_observation):
    """
    Engineering estimate of imagery captured during Australia observation windows.
    Pushbroom sensors capture a continuous strip, not discrete frames, so 'images'
    here means an estimated scene count: along-track distance imaged divided by a
    nominal along-track frame footprint derived from the camera's own geometry
    (GSD x Image Height). This is a derived estimate, not a raw payload counter.
    """
    swath_km = float(camera_model.get("Ground Swath (km)") or 0.0)
    gsd_m = float(camera_model.get("GSD (m/pixel)") or 0.0)
    image_height_px = float(camera_model.get("Image Height (px)") or 0.0)
    frame_footprint_km = (gsd_m * image_height_px / 1000.0) if (gsd_m and image_height_px) else 0.0

    df = state_df.copy()
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
    df = df.dropna(subset=["Timestamp", "Satellite Name", "Latitude", "Longitude"])

    obs = per_sat_observation.set_index("Satellite Name") if not per_sat_observation.empty else pd.DataFrame()

    rows = []
    for sat, grp in df.groupby("Satellite Name"):
        speed = _ground_speed_km_s(grp)
        observed_s = float(obs.loc[sat, "Total Observation Seconds"]) if sat in obs.index else 0.0
        distance_km = (speed * observed_s) if speed else None
        area_km2 = (distance_km * swath_km) if (distance_km is not None and swath_km) else None
        scenes = (distance_km / frame_footprint_km) if (distance_km is not None and frame_footprint_km) else None
        rows.append({
            "satellite": str(sat),
            "groundSpeedKmS": speed,
            "observedSeconds": observed_s,
            "imagedDistanceKm": distance_km,
            "imagedAreaKm2": area_km2,
            "estimatedScenes": scenes,
        })

    summary = pd.DataFrame(rows).sort_values("satellite").reset_index(drop=True)

    def _sum(col):
        s = pd.to_numeric(summary[col], errors="coerce")
        return float(s.sum()) if s.notna().any() else 0.0

    fleet = {
        "swathKm": swath_km,
        "gsdM": gsd_m,
        "frameFootprintKm": frame_footprint_km,
        "totalImagedDistanceKm": _sum("imagedDistanceKm"),
        "totalImagedAreaKm2": _sum("imagedAreaKm2"),
        "totalEstimatedScenes": _sum("estimatedScenes"),
        "satellitesWithImagery": int((pd.to_numeric(summary["estimatedScenes"], errors="coerce") > 0).sum()),
        "satelliteCount": int(len(summary)),
    }
    return summary, fleet
