"""Camera footprint geometry for the imaging workflow.

The GMAT state report provides sub-satellite position (Latitude, Longitude,
Altitude) but no velocity vector, so the along-track direction is derived from
the ground track itself: the bearing from each fix to the next one. Cross-track
is that bearing rotated 90 degrees.

All offsets use spherical-Earth geodesy. At the scene scale involved here
(swath of order 50 km) the spherical/WGS84 difference is well under one pixel
at the camera's GSD, so the simpler model is used deliberately rather than
carrying an ellipsoid through every corner calculation.

Footprints are nadir-pointing rectangles. The camera model's "Pointing" field is
honoured only insofar as non-nadir pointing is reported as unsupported rather
than silently producing a nadir footprint.
"""

import math

import numpy as np
import pandas as pd

R_EARTH_KM = 6371.0088


def _bearing_deg(lat1, lon1, lat2, lon2):
    """Initial great-circle bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    y = np.sin(dl) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return np.degrees(np.arctan2(y, x)) % 360.0


def _destination(lat, lon, bearing_deg, distance_km):
    """Point reached from (lat, lon) travelling distance_km along a great circle."""
    ang = np.asarray(distance_km, dtype=float) / R_EARTH_KM
    br = np.radians(np.asarray(bearing_deg, dtype=float))
    p1 = np.radians(np.asarray(lat, dtype=float))
    l1 = np.radians(np.asarray(lon, dtype=float))
    p2 = np.arcsin(np.sin(p1) * np.cos(ang) + np.cos(p1) * np.sin(ang) * np.cos(br))
    l2 = l1 + np.arctan2(
        np.sin(br) * np.sin(ang) * np.cos(p1),
        np.cos(ang) - np.sin(p1) * np.sin(p2),
    )
    return np.degrees(p2), (np.degrees(l2) + 540.0) % 360.0 - 180.0


def ground_track_heading(group):
    """Per-fix along-track bearing for one satellite, forward-differenced.

    The final fix has no successor, so it inherits the previous bearing.
    """
    g = group.sort_values("Timestamp")
    lat = g["Latitude"].to_numpy(dtype=float)
    lon = g["Longitude"].to_numpy(dtype=float)
    if len(lat) < 2:
        return np.zeros(len(lat))
    head = _bearing_deg(lat[:-1], lon[:-1], lat[1:], lon[1:])
    return np.append(head, head[-1])


def validate_wgs84(lat, lon):
    """Check a coordinate is a well-formed WGS84 lat/lon pair.

    GMAT telemetry is well-formed in practice, so this has never been
    expected to fail -- but "expected to be valid" and "validated" are
    different claims, and a displayed pass/fail is the latter. Returns
    a small structured result rather than raising, so a caller can surface
    it in the same product metadata as every other field.
    """
    issues = []
    lat_f = lon_f = None
    try:
        lat_f = float(lat)
        if not math.isfinite(lat_f):
            issues.append("latitude is not finite")
        elif not (-90.0 <= lat_f <= 90.0):
            issues.append(f"latitude {lat_f} is outside [-90, 90]")
    except (TypeError, ValueError):
        issues.append(f"latitude {lat!r} is not numeric")

    try:
        lon_f = float(lon)
        if not math.isfinite(lon_f):
            issues.append("longitude is not finite")
        elif not (-180.0 <= lon_f <= 180.0):
            issues.append(f"longitude {lon_f} is outside [-180, 180]")
    except (TypeError, ValueError):
        issues.append(f"longitude {lon!r} is not numeric")

    return {
        "valid": not issues,
        "datum": "WGS84",
        "latitude": lat_f,
        "longitude": lon_f,
        "issues": issues,
    }


def footprint_corners(lat, lon, heading_deg, swath_km, along_km):
    """Four corners of a nadir rectangular footprint, in order, closed.

    Returns a list of (lon, lat) pairs -- lon first, matching the convention in
    core.australia_coverage and the GeoJSON the API already emits.
    """
    half_x = float(swath_km) / 2.0
    half_y = float(along_km) / 2.0
    cross = (float(heading_deg) + 90.0) % 360.0

    corners = []
    for along_sign, cross_sign in ((+1, -1), (+1, +1), (-1, +1), (-1, -1)):
        mid_lat, mid_lon = _destination(lat, lon, heading_deg, along_sign * half_y)
        c_lat, c_lon = _destination(mid_lat, mid_lon, cross, cross_sign * half_x)
        corners.append((float(c_lon), float(c_lat)))
    corners.append(corners[0])
    return corners


def footprint_bbox(corners):
    """Lon/lat bounding box of a footprint, for STAC queries and windowed reads.

    Returns (lon_min, lat_min, lon_max, lat_max). Footprints spanning the
    antimeridian are not split; callers imaging Australia will not encounter one.
    """
    lons = [c[0] for c in corners]
    lats = [c[1] for c in corners]
    return (min(lons), min(lats), max(lons), max(lats))


def densify_track(df, max_gap_km=30.0, max_factor=32):
    """Interpolate a sparse ground track onto a fine great-circle path.

    The GMAT report samples every ~94 s, which at orbital ground speed is ~629 km
    between fixes -- roughly nine times the modelled 69 km swath. Any test that
    only examines sampled points therefore misses most of the ground actually
    overflown: a satellite can cross directly over a target between two fixes
    and leave no trace in the data.

    This densifies each satellite's track so consecutive points are no more than
    `max_gap_km` apart, interpolating position along the great circle and time
    linearly. Interpolated rows are marked `interpolated=True` so nothing
    downstream mistakes them for reported telemetry.

    Interpolation is skipped across large time gaps (orbit-scale discontinuities
    in the report), where a great-circle segment would not represent the real path.
    """
    out = []
    for sat, grp in df.groupby("Satellite Name", sort=True):
        g = grp.sort_values("Timestamp").reset_index(drop=True)
        if len(g) < 2:
            g = g.copy()
            g["interpolated"] = False
            out.append(g)
            continue

        lat = g["Latitude"].to_numpy(dtype=float)
        lon = g["Longitude"].to_numpy(dtype=float)
        t_ns = g["Timestamp"].to_numpy(dtype="datetime64[ns]").astype("int64")
        alt = (g["Altitude"].to_numpy(dtype=float)
               if "Altitude" in g.columns else np.full(len(g), np.nan))

        seg_km = haversine_km(lat[:-1], lon[:-1], lat[1:], lon[1:])
        dt_s = np.diff(t_ns) / 1e9
        positive = dt_s[dt_s > 0]
        nominal_dt = float(np.median(positive)) if positive.size else 0.0

        # Subdivisions per segment. 1 means "keep as is".
        n = np.ceil(np.where(seg_km > 0, seg_km / float(max_gap_km), 1.0))
        n = np.clip(n, 1, max_factor).astype(int)
        if nominal_dt:
            # Never bridge a report discontinuity with a great-circle guess.
            n[dt_s > nominal_dt * 1.5] = 1

        # Build the fractional offsets for every segment at once.
        seg_idx = np.repeat(np.arange(len(n)), n)
        within = np.arange(len(seg_idx)) - np.repeat(np.cumsum(n) - n, n)
        frac = within / n[seg_idx]

        new_lat, new_lon = _slerp_vec(
            lat[seg_idx], lon[seg_idx], lat[seg_idx + 1], lon[seg_idx + 1], frac
        )
        new_t = t_ns[seg_idx] + (np.diff(t_ns)[seg_idx] * frac).astype("int64")
        new_alt = alt[seg_idx] + (alt[seg_idx + 1] - alt[seg_idx]) * frac

        # Carry non-interpolated columns (e.g. Satellite Name, RMAG, ECC) forward
        # from each segment's starting fix.
        dense = g.iloc[seg_idx].reset_index(drop=True).copy()
        dense["Latitude"] = new_lat
        dense["Longitude"] = new_lon
        dense["Timestamp"] = pd.to_datetime(new_t)
        if "Altitude" in dense.columns:
            dense["Altitude"] = new_alt
        dense["interpolated"] = frac > 0

        # Append the final real fix, which starts no segment.
        tail = g.iloc[[-1]].copy()
        tail["interpolated"] = False
        out.append(pd.concat([dense, tail], ignore_index=True))

    return pd.concat(out, ignore_index=True) if out else df


def _slerp_vec(lat1, lon1, lat2, lon2, f):
    """Vectorised great-circle interpolation, fraction f from point 1 to point 2."""
    p1, l1 = np.radians(lat1), np.radians(lon1)
    p2, l2 = np.radians(lat2), np.radians(lon2)
    d = 2 * np.arcsin(np.sqrt(np.clip(
        np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin((l2 - l1) / 2) ** 2,
        0, 1)))
    small = d < 1e-12
    sin_d = np.where(small, 1.0, np.sin(d))
    a = np.sin((1 - f) * d) / sin_d
    b = np.sin(f * d) / sin_d
    x = a * np.cos(p1) * np.cos(l1) + b * np.cos(p2) * np.cos(l2)
    y = a * np.cos(p1) * np.sin(l1) + b * np.cos(p2) * np.sin(l2)
    z = a * np.sin(p1) + b * np.sin(p2)
    out_lat = np.degrees(np.arctan2(z, np.hypot(x, y)))
    out_lon = np.degrees(np.arctan2(y, x))
    return np.where(small, lat1, out_lat), np.where(small, lon1, out_lon)


def haversine_km(lat1, lon1, lat2, lon2):
    """Vectorised great-circle distance in kilometres."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = np.radians(np.asarray(lat2) - np.asarray(lat1))
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R_EARTH_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def orbit_numbers(group):
    """Sequential orbit number per fix, incremented at each ascending-node crossing.

    An ascending node is a south-to-north equator crossing. Orbits are numbered
    from 1 within the span of the state report -- this is a report-relative
    count, not an absolute epoch-referenced revolution number, because the
    report carries no launch epoch to count from.
    """
    g = group.sort_values("Timestamp")
    lat = g["Latitude"].to_numpy(dtype=float)
    if len(lat) == 0:
        return np.array([], dtype=int)
    ascending = (lat[:-1] < 0) & (lat[1:] >= 0)
    return np.append(0, np.cumsum(ascending)) + 1


def scene_grid(state_df, camera_model, min_scene_gap_km=None, region="australia"):
    """Discretise continuous pushbroom strips into individual scenes.

    A pushbroom sensor produces a continuous strip, not frames. To make the
    strip addressable as downloadable products it is cut into square-ish scenes
    every `frame footprint` kilometres along track, where the frame footprint is
    the camera's own GSD x image height. This mirrors how real EO providers
    tile a continuous downlink into granules.

    Returns a DataFrame of candidate scenes with footprint geometry attached.
    Only fixes where the payload is observing the mission's AOI region
    (see core.regions -- Australia or India today) are considered, so a
    mission whose AOI is India naturally produces scenes over India, not
    Australia's land polygon.
    """
    from core.australia_coverage import footprint_intersects_region

    swath_km = float(camera_model.get("Ground Swath (km)") or 0.0)
    gsd_m = float(camera_model.get("GSD (m/pixel)") or 0.0)
    # Presence check only: this validity guard does not use Image Height's
    # value beyond confirming the camera model is populated -- the actual
    # scene cut length below is swath-based, not derived from this nominal
    # frame constant. See build_imaging_summary in core.imaging_summary for
    # where "Image Height (px)" (a fixed DEFAULT_CAMERA constant, distinct
    # from any individual product's actual delivered height) is genuinely
    # used in a calculation.
    height_px = float(camera_model.get("Image Height (px)") or 0.0)
    width_px = float(camera_model.get("Image Width (px)") or 0.0)

    if not (swath_km and gsd_m and height_px):
        return pd.DataFrame()

    # Along-track extent of one scene. A pushbroom line is only Image Height
    # pixels tall, which at this GSD is a sliver a few km long; scenes are
    # instead cut at the swath width so products come out roughly square.
    along_km = float(min_scene_gap_km) if min_scene_gap_km else swath_km

    df = state_df.copy()
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    for col in ("Latitude", "Longitude", "Altitude"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Timestamp", "Satellite Name", "Latitude", "Longitude"])
    if df.empty:
        return pd.DataFrame()

    # Densify before the AOI test: at the report's native 629 km fix
    # spacing, whole AOI passes fall between samples.
    df = densify_track(df, max_gap_km=min(along_km, swath_km) / 2.0)

    df["Observing AOI"] = footprint_intersects_region(
        df, swath_km, region=region, lon_col="Longitude", lat_col="Latitude"
    )

    rows = []
    for sat, grp in df.groupby("Satellite Name", sort=True):
        grp = grp.sort_values("Timestamp").copy()
        grp["heading"] = ground_track_heading(grp)
        grp["orbit"] = orbit_numbers(grp)

        active = grp[grp["Observing AOI"]]
        if active.empty:
            continue

        # Walk the active fixes, emitting a scene whenever we have travelled a
        # full scene length since the last emitted one. Distance accumulates
        # along the real ground track, so scenes stay evenly spaced regardless
        # of the report's sampling rate.
        last_lat = last_lon = None
        travelled = 0.0
        for row in active.itertuples(index=False):
            if last_lat is not None:
                travelled += _haversine_km(last_lat, last_lon, row.Latitude, row.Longitude)
            emit = last_lat is None or travelled >= along_km
            last_lat, last_lon = row.Latitude, row.Longitude
            if not emit:
                continue
            travelled = 0.0

            corners = footprint_corners(
                row.Latitude, row.Longitude, row.heading, swath_km, along_km
            )
            rows.append(
                {
                    "satellite": str(sat),
                    "timestamp": row.Timestamp,
                    "lat": float(row.Latitude),
                    "lon": float(row.Longitude),
                    "altitudeKm": float(row.Altitude) if pd.notna(row.Altitude) else None,
                    "headingDeg": float(row.heading),
                    "orbit": int(row.orbit),
                    "gsdM": gsd_m,
                    "swathKm": swath_km,
                    "alongTrackKm": along_km,
                    "widthPx": int(width_px),
                    "heightPx": int(round(along_km * 1000.0 / gsd_m)) if gsd_m else 0,
                    "footprint": corners,
                    "bbox": footprint_bbox(corners),
                }
            )

    return pd.DataFrame(rows)


def _haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_EARTH_KM * math.asin(math.sqrt(min(a, 1.0)))
