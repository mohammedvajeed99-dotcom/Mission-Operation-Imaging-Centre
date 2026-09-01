import numpy as np
import pandas as pd
from core.australia_coverage import MAINLAND_AUSTRALIA, TASMANIA, footprint_intersects_australia

DEFAULT_AOIS = {
    "australia": {
        "name": "Mainland Australia & TAS",
        "lonMin": 110.0,
        "lonMax": 160.0,
        "latMin": -40.0,
        "latMax": -10.0,
        "requirementMin": 60, # 60 minutes revisit requirement
    },
    "southeast_asia": {
        "name": "Southeast Asia Maritime",
        "lonMin": 95.0,
        "lonMax": 141.0,
        "latMin": -11.0,
        "latMax": 20.0,
        "requirementMin": 120,
    },
    "equatorial_belt": {
        "name": "Equatorial Belt",
        "lonMin": -180.0,
        "lonMax": 180.0,
        "latMin": -15.0,
        "latMax": 15.0,
        "requirementMin": 180,
    },
    "global": {
        "name": "Global Coverage Region",
        "lonMin": -180.0,
        "lonMax": 180.0,
        "latMin": -60.0,
        "latMax": 60.0,
        "requirementMin": 360,
    }
}


def _to_num(val, default=0.0):
    try:
        if pd.isna(val):
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def compute_orbital_period(altitude_km):
    if not altitude_km or altitude_km <= 0:
        return 95.4 # Default ~536km LEO period in minutes
    r = 6371.0 + altitude_km
    mu = 398600.4418
    period_sec = 2.0 * np.pi * np.sqrt((r ** 3) / mu)
    return float(period_sec / 60.0)


def compute_constellation_summary(config, state_df, rf_df, optical_df, camera_model, observation_overall,
                                  imaging_fleet=None, revisit_stats=None):
    constellation = config.get("constellation", {})
    orbit = config.get("orbit", {})
    mission = config.get("mission", {})

    configured_sats = int(_to_num(constellation.get("Total Satellites"), 48))
    planes = int(_to_num(constellation.get("Number of Planes"), 8))
    sats_per_plane = int(_to_num(constellation.get("Satellites per Plane"), 6))
    altitude = _to_num(orbit.get("Altitude"), 536.0)
    inclination = _to_num(orbit.get("Inclination"), 50.0)

    detected_sats = set()
    if not state_df.empty and "Satellite Name" in state_df.columns:
        detected_sats.update(state_df["Satellite Name"].dropna().unique())

    op_sats = len(detected_sats) if detected_sats else configured_sats
    period_min = compute_orbital_period(altitude)
    tracks_per_day = float((1440.0 / period_min) * op_sats)

    # Revisit is expensive to compute; reuse the caller's result when given.
    if revisit_stats is None:
        revisit_stats = compute_revisit_analytics(state_df, camera_model.get("Ground Swath (km)", 20.0))

    total_rf_contacts = len(rf_df) if not rf_df.empty else 0
    rf_duration_sec = rf_df["Duration (s)"].sum() if not rf_df.empty and "Duration (s)" in rf_df.columns else 0.0
    avg_rf_duration = float(rf_duration_sec / total_rf_contacts) if total_rf_contacts > 0 else 0.0

    # Days in state dataset
    if not state_df.empty and "Timestamp" in state_df.columns:
        ts = pd.to_datetime(state_df["Timestamp"], errors="coerce").dropna()
        duration_days = max(1.0, (ts.max() - ts.min()).total_seconds() / 86400.0)
    else:
        duration_days = 1.0

    # Scenes come from core.imaging_summary, which derives them from real
    # camera geometry and observed along-track distance. If imaging could not
    # be computed there is no honest number to show.
    total_scenes = (imaging_fleet or {}).get("totalEstimatedScenes")
    images_per_day = float(total_scenes) / duration_days if total_scenes else None
    rf_contacts_per_day = float(total_rf_contacts / duration_days)

    def _r(value, digits=1):
        return None if value is None else round(value, digits)

    return {
        "constellationName": str(mission.get("Mission Name", "ASC-074 Earth Observation")),
        "configuration": f"{planes} × {sats_per_plane}",
        "totalSatellites": configured_sats,
        "operationalSatellites": op_sats,
        "altitudeKm": altitude,
        "inclinationDeg": inclination,
        "orbitalPeriodMin": round(period_min, 2),
        "groundTracksPerDay": round(tracks_per_day, 1),
        "globalCoveragePct": _r(_to_num(observation_overall.get("Overall Observation Duty Cycle (%)"), None)),
        "meanRevisitMin": _r(revisit_stats.get("mean_revisit")),
        "worstRevisitMin": _r(revisit_stats.get("max_revisit")),
        "bestRevisitMin": _r(revisit_stats.get("min_revisit")),
        "imagesPerDay": _r(images_per_day, 0),
        "rfContactsPerDay": round(rf_contacts_per_day, 1),
        "avgContactDurationSec": round(avg_rf_duration, 1),
        "avgContactDurationMin": round(avg_rf_duration / 60.0, 2),
    }


def compute_revisit_analytics(state_df, swath_km=20.0):
    if state_df.empty or "Timestamp" not in state_df.columns:
        # No state telemetry: report nothing rather than placeholder numbers.
        return {
            "mean_revisit": None,
            "min_revisit": None,
            "max_revisit": None,
            "median_revisit": None,
            "p95_revisit": None,
            "histogram": [],
            "heatmap": [],
        }

    work = state_df.copy()
    work["Timestamp"] = pd.to_datetime(work["Timestamp"], errors="coerce")
    work["Latitude"] = pd.to_numeric(work["Latitude"], errors="coerce")
    work["Longitude"] = pd.to_numeric(work["Longitude"], errors="coerce")
    work = work.dropna(subset=["Timestamp", "Latitude", "Longitude"]).sort_values("Timestamp")

    if work.empty:
        # No state telemetry: report nothing rather than placeholder numbers.
        return {
            "mean_revisit": None,
            "min_revisit": None,
            "max_revisit": None,
            "median_revisit": None,
            "p95_revisit": None,
            "histogram": [],
            "heatmap": [],
        }

    # Grid sampling over AOI 110E..160E, -40S..-10S
    lons = np.linspace(112.0, 154.0, 15)
    lats = np.linspace(-38.0, -12.0, 12)
    
    half_swath_deg = (swath_km / 111.0) / 2.0
    
    # Calculate access gaps across sample grid
    all_revisits = []
    heatmap_grid = []

    for lat in lats:
        for lon in lons:
            # Distance from satellite subpoint to grid point
            dlat = np.abs(work["Latitude"].values - lat)
            dlon = np.abs(work["Longitude"].values - lon) * np.cos(np.radians(lat))
            dist_deg = np.sqrt(dlat**2 + dlon**2)
            
            in_view_mask = dist_deg <= (half_swath_deg * 3.0)
            times = work.loc[in_view_mask, "Timestamp"]

            insufficient = True
            avg_gap = max_gap = None
            if len(times) >= 2:
                gaps = times.diff().dt.total_seconds().dropna() / 60.0
                gaps = gaps[gaps > 2.0] # Ignore consecutive samples in same pass
                if not gaps.empty:
                    all_revisits.extend(gaps.values.tolist())
                    avg_gap = float(gaps.mean())
                    max_gap = float(gaps.max())
                    insufficient = False

            # Categorize color scale -- cells with too few real samples to
            # compute a gap are marked insufficientData rather than given a
            # fabricated value/color, since a single subpoint pass (or zero
            # passes) through a cell says nothing about its actual revisit.
            if insufficient:
                color_cat = "insufficient"
            elif avg_gap < 30.0:
                color_cat = "green"
            elif avg_gap <= 60.0:
                color_cat = "yellow"
            elif avg_gap <= 120.0:
                color_cat = "orange"
            else:
                color_cat = "red"

            heatmap_grid.append({
                "lat": float(lat),
                "lon": float(lon),
                "avgRevisitMin": round(avg_gap, 1) if avg_gap is not None else None,
                "maxRevisitMin": round(max_gap, 1) if max_gap is not None else None,
                "colorCategory": color_cat,
                "insufficientData": insufficient,
            })

    if not all_revisits:
        # Not one grid cell saw two passes -- there is no revisit to report.
        return {
            "mean_revisit": None,
            "min_revisit": None,
            "max_revisit": None,
            "median_revisit": None,
            "p95_revisit": None,
            "histogram": [],
            "heatmap": heatmap_grid,
        }

    all_revisits = np.array(all_revisits)
    mean_rev = float(np.mean(all_revisits))
    min_rev = float(np.min(all_revisits))
    max_rev = float(np.max(all_revisits))
    median_rev = float(np.median(all_revisits))
    p95_rev = float(np.percentile(all_revisits, 95))

    # Build histogram
    counts, bin_edges = np.histogram(all_revisits, bins=8)
    histogram = []
    for i in range(len(counts)):
        histogram.append({
            "bin": f"{int(bin_edges[i])}–{int(bin_edges[i+1])}m",
            "count": int(counts[i]),
        })

    # Scene-count estimation lives in core.imaging_summary, which derives it
    # from real camera geometry and observation time. It is not guessed from
    # a multiplier here.

    return {
        "mean_revisit": round(mean_rev, 1),
        "min_revisit": round(min_rev, 1),
        "max_revisit": round(max_rev, 1),
        "median_revisit": round(median_rev, 1),
        "p95_revisit": round(p95_rev, 1),
        "histogram": histogram,
        "heatmap": heatmap_grid,
    }


def compute_gap_analysis(revisit_stats, mission_req_min=60.0):
    heatmap = revisit_stats.get("heatmap", [])
    # Only cells with real computed gaps carry a signal; cells flagged
    # insufficientData contribute nothing rather than a fabricated value.
    valid_cells = [c for c in heatmap if not c.get("insufficientData")]

    all_revisits = []
    for cell in valid_cells:
        all_revisits.append(cell["avgRevisitMin"])
        all_revisits.append(cell["maxRevisitMin"])

    has_data = bool(all_revisits)
    arr = np.array(all_revisits) if has_data else np.array([0.0])
    mean_gap = float(np.mean(arr)) if has_data else None
    median_gap = float(np.median(arr)) if has_data else None
    max_gap = float(np.max(arr)) if has_data else None
    p95_gap = float(np.percentile(arr, 95)) if has_data else None
    largest_gap = max_gap

    # Percentage of (data-bearing) cells satisfying requirement (<= mission_req_min)
    satisfying_cells = sum(1 for c in valid_cells if c["avgRevisitMin"] <= mission_req_min)
    total_cells = max(1, len(valid_cells))
    pct_satisfying = float(satisfying_cells / total_cells * 100.0) if has_data else None

    # Gap breakdown chart
    gap_distribution = [
        {"range": "< 30 min", "count": sum(1 for c in valid_cells if c["avgRevisitMin"] < 30)},
        {"range": "30–60 min", "count": sum(1 for c in valid_cells if 30 <= c["avgRevisitMin"] <= 60)},
        {"range": "1–2 hours", "count": sum(1 for c in valid_cells if 60 < c["avgRevisitMin"] <= 120)},
        {"range": "> 2 hours", "count": sum(1 for c in valid_cells if c["avgRevisitMin"] > 120)},
    ]

    return {
        "largestGapMin": round(largest_gap, 1) if largest_gap is not None else None,
        "meanGapMin": round(mean_gap, 1) if mean_gap is not None else None,
        "medianGapMin": round(median_gap, 1) if median_gap is not None else None,
        "maxGapMin": round(max_gap, 1) if max_gap is not None else None,
        "p95GapMin": round(p95_gap, 1) if p95_gap is not None else None,
        "pctSatisfyingRequirement": round(pct_satisfying, 1) if pct_satisfying is not None else None,
        "requirementMin": mission_req_min,
        "gapDistribution": gap_distribution,
        "dataBearingCells": len(valid_cells),
        "totalCells": len(heatmap),
    }


def _fallback_satellite_names(config):
    constellation = (config or {}).get("constellation", {})
    total = int(_to_num(constellation.get("Total Satellites"), 0))
    prefix = str(constellation.get("Satellite Name Prefix", "") or "")
    if not total or not prefix:
        return []
    return [f"{prefix}{i:02d}" for i in range(1, total + 1)]


def compute_satellite_contributions(state_df, rf_df, optical_df, duty_summary, imaging_per_sat, config=None):
    satellites = set()
    for df in (state_df, rf_df, optical_df):
        if not df.empty and "Satellite Name" in df.columns:
            satellites.update(df["Satellite Name"].dropna().astype(str).unique())

    if not satellites:
        satellites = _fallback_satellite_names(config)

    rf_counts = rf_df["Satellite Name"].value_counts().to_dict() if not rf_df.empty and "Satellite Name" in rf_df.columns else {}
    opt_counts = optical_df["Satellite Name"].value_counts().to_dict() if not optical_df.empty and "Satellite Name" in optical_df.columns else {}
    
    duty_map = {}
    if isinstance(duty_summary, list):
        for item in duty_summary:
            duty_map[item.get("satellite")] = item.get("dutyPercent", 0.0)

    img_map = {}
    obs_map = {}
    if isinstance(imaging_per_sat, list):
        for item in imaging_per_sat:
            img_map[item.get("satellite")] = item.get("estimatedScenes", 0)
            obs_map[item.get("satellite")] = item.get("observedSeconds", 0)

    total_obs = sum(obs_map.values()) if sum(obs_map.values()) > 0 else 1

    rows = []
    duty_values = []
    
    for sat in sorted(satellites):
        rf_cnt = rf_counts.get(sat, 0)
        opt_cnt = opt_counts.get(sat, 0)
        # Absent values stay absent: a satellite with no duty/imaging entry
        # gets 0, not a stand-in figure.
        duty_pct = duty_map.get(sat, 0.0)
        duty_values.append(duty_pct)
        img_cnt = img_map.get(sat, 0)
        obs_sec = obs_map.get(sat, 0)

        contrib_pct = (obs_sec / total_obs) * 100.0 if total_obs > 0 else 0.0
        contacts = rf_cnt + opt_cnt
        # Mean observed seconds per contact opportunity for this satellite;
        # undefined when it had no contacts at all.
        avg_obs_duration_sec = (obs_sec / contacts) if contacts else None

        rows.append({
            "satellite": sat,
            "shortName": sat.replace("ASC_074_", "S"),
            "imagesCaptured": int(img_cnt),
            "coverageContributionPct": round(contrib_pct, 2),
            "rfContacts": int(rf_cnt),
            "opticalContacts": int(opt_cnt),
            "meanDutyCyclePct": round(duty_pct, 2),
            "observedSeconds": round(float(obs_sec), 1),
            "avgObservationDurationSec": round(avg_obs_duration_sec, 1) if avg_obs_duration_sec is not None else None,
            "avgObservationDurationMin": round(avg_obs_duration_sec / 60.0, 2) if avg_obs_duration_sec is not None else None,
            "isLowContributor": False,
        })

    mean_duty = float(np.mean(duty_values)) if duty_values else 0.0
    std_duty = float(np.std(duty_values)) if len(duty_values) > 1 else 0.0
    # 1.2 sigma below the fleet's own mean duty cycle -- a real statistical
    # outlier test. There used to be a hardcoded floor of max(2.0, ...) here,
    # intended as a sanity minimum, but for a symmetric Walker-Delta
    # constellation the whole fleet's duty cycle sits in a tight band (e.g.
    # mean ~1.9%, std ~0.2% over one day), so that floor sat ABOVE the mean
    # and flagged roughly half a perfectly healthy fleet as "low contribution"
    # -- 31 of 48 satellites, when a 1.2-sigma one-tailed cut should flag
    # close to 11-12%. No floor is needed: duty_pct can never be negative, so
    # a threshold that goes below 0 simply flags nobody on this test, which
    # is the correct behaviour when the fleet has no real outliers.
    threshold = mean_duty - 1.2 * std_duty

    for row in rows:
        if row["meanDutyCyclePct"] < threshold or row["coverageContributionPct"] < (100.0 / len(satellites) * 0.4):
            row["isLowContributor"] = True

    return sorted(rows, key=lambda r: r["coverageContributionPct"], reverse=True)


def _contact_subpoints(state_df, contact_df):
    """Sub-satellite positions sampled while a contact was in progress.

    Contact reports carry no coordinates, so the positions are recovered by
    intersecting each contact's [start, stop] window with that satellite's
    own state samples. Every point returned is a real reported fix taken
    during a real contact -- nothing is modelled from distance to the
    ground station.
    """
    if state_df.empty or contact_df is None or contact_df.empty:
        return np.array([]), np.array([])
    if not {"Satellite Name", "Start UTC", "Stop UTC"}.issubset(contact_df.columns):
        return np.array([]), np.array([])

    st = state_df[["Satellite Name", "Timestamp", "Latitude", "Longitude"]].copy()
    st["Timestamp"] = pd.to_datetime(st["Timestamp"], errors="coerce")
    st["Latitude"] = pd.to_numeric(st["Latitude"], errors="coerce")
    st["Longitude"] = pd.to_numeric(st["Longitude"], errors="coerce")
    st = st.dropna()

    ct = contact_df[["Satellite Name", "Start UTC", "Stop UTC"]].copy()
    ct["Start UTC"] = pd.to_datetime(ct["Start UTC"], errors="coerce")
    ct["Stop UTC"] = pd.to_datetime(ct["Stop UTC"], errors="coerce")
    ct = ct.dropna()

    lats, lons = [], []
    for sat, windows in ct.groupby("Satellite Name"):
        sat_rows = st[st["Satellite Name"].astype(str) == str(sat)]
        if sat_rows.empty:
            continue
        times = sat_rows["Timestamp"]
        in_contact = pd.Series(False, index=sat_rows.index)
        for start, stop in windows[["Start UTC", "Stop UTC"]].itertuples(index=False, name=None):
            in_contact |= times.between(start, stop)
        hit = sat_rows[in_contact]
        if not hit.empty:
            lats.append(hit["Latitude"].to_numpy())
            lons.append(hit["Longitude"].to_numpy())

    if not lats:
        return np.array([]), np.array([])
    return np.concatenate(lats), np.concatenate(lons)


def compute_density_heatmaps(state_df, rf_df, optical_df, camera_model, swath_km=None):
    """Four spatial densities, each counted from real reported positions.

    passDensity     -- where satellites flew
    imageDensity    -- where the sensor footprint actually intersected the AOI
    rf/opticalDensity -- where satellites were while a contact was in progress
    """
    lon_edges = np.linspace(-180.0, 180.0, 36)
    lat_edges = np.linspace(-60.0, 60.0, 24)
    centres = [
        (round((lat_edges[i] + lat_edges[i + 1]) / 2.0, 1),
         round((lon_edges[j] + lon_edges[j + 1]) / 2.0, 1))
        for i in range(len(lat_edges) - 1)
        for j in range(len(lon_edges) - 1)
    ]

    def grid_from(lats, lons):
        """Normalised 0-100 density, or an empty grid when there is no data."""
        if lats is None or len(lats) == 0:
            return []
        hist, _, _ = np.histogram2d(lats, lons, bins=[lat_edges, lon_edges])
        peak = hist.max()
        if peak <= 0:
            return []
        flat = hist.reshape(-1)
        return [
            {"lat": c[0], "lon": c[1], "density": round(float(v / peak * 100.0), 1)}
            for c, v in zip(centres, flat)
        ]

    if state_df.empty or "Latitude" not in state_df.columns:
        # No telemetry: return empty grids so the map reports "no data"
        # rather than drawing an invented pattern.
        return {"passDensity": [], "imageDensity": [], "rfContactDensity": [],
                "opticalContactDensity": [], "hasData": False}

    lat_all = pd.to_numeric(state_df["Latitude"], errors="coerce")
    lon_all = pd.to_numeric(state_df["Longitude"], errors="coerce")
    ok = lat_all.notna() & lon_all.notna()
    lat_all = lat_all[ok].to_numpy()
    lon_all = lon_all[ok].to_numpy()

    # Imaging density: the real sensor-over-AOI test, same one the coverage
    # and observation analytics use -- not a multiplier on pass density.
    swath = float(swath_km or (camera_model or {}).get("Ground Swath (km)") or 0.0)
    if swath > 0:
        observing = footprint_intersects_australia(
            state_df[ok.values], swath, lon_col="Longitude", lat_col="Latitude"
        )
        img_lat, img_lon = lat_all[observing], lon_all[observing]
    else:
        img_lat, img_lon = np.array([]), np.array([])

    rf_lat, rf_lon = _contact_subpoints(state_df, rf_df)
    opt_lat, opt_lon = _contact_subpoints(state_df, optical_df)

    return {
        "passDensity": grid_from(lat_all, lon_all),
        "imageDensity": grid_from(img_lat, img_lon),
        "rfContactDensity": grid_from(rf_lat, rf_lon),
        "opticalContactDensity": grid_from(opt_lat, opt_lon),
        "hasData": True,
    }


def compute_aoi_analytics(state_df, camera_model, aoi_key="australia", config=None):
    aoi_cfg = DEFAULT_AOIS.get(aoi_key, DEFAULT_AOIS["australia"])
    
    lon_min, lon_max = aoi_cfg["lonMin"], aoi_cfg["lonMax"]
    lat_min, lat_max = aoi_cfg["latMin"], aoi_cfg["latMax"]

    empty = {
        "aoiKey": aoi_key,
        "aoiName": aoi_cfg["name"],
        "bounds": {"lonMin": lon_min, "lonMax": lon_max, "latMin": lat_min, "latMax": lat_max},
        "firstAccess": None,
        "lastAccess": None,
        "passCount": None,
        "passesPerDay": None,
        "analysisDurationDays": None,
        "revisitHistogram": [],
        "satellitesCoveringAoi": 0,
        "avgObservationDurationSec": None,
        "avgObservationDurationMin": None,
        "hasData": False,
    }

    if state_df.empty or "Timestamp" not in state_df.columns:
        return empty

    work = state_df.copy()
    work["Timestamp"] = pd.to_datetime(work["Timestamp"], errors="coerce")
    work["Latitude"] = pd.to_numeric(work["Latitude"], errors="coerce")
    work["Longitude"] = pd.to_numeric(work["Longitude"], errors="coerce")
    work = work.dropna(subset=["Timestamp", "Satellite Name", "Latitude", "Longitude"])
    if work.empty:
        return empty

    in_aoi = work["Longitude"].between(lon_min, lon_max) & work["Latitude"].between(lat_min, lat_max)
    aoi_work = work[in_aoi].sort_values(["Satellite Name", "Timestamp"])
    covering_sats = sorted(aoi_work["Satellite Name"].dropna().astype(str).unique().tolist())
    if aoi_work.empty:
        return {**empty, "hasData": True}

    span_s = (work["Timestamp"].max() - work["Timestamp"].min()).total_seconds()
    duration_days = max(span_s / 86400.0, 1e-9)

    # A pass is one continuous stretch of a satellite inside the AOI. Split
    # where the gap between consecutive in-AOI samples exceeds four times
    # that satellite's own nominal sampling step -- the same rule used by
    # core.observation_duration for its observation windows.
    pass_durations = []
    pass_count = 0
    for sat, grp in aoi_work.groupby("Satellite Name"):
        grp = grp.sort_values("Timestamp")
        sat_all = work[work["Satellite Name"].eq(sat)].sort_values("Timestamp")
        steps = sat_all["Timestamp"].diff().dt.total_seconds()
        steps = steps[(steps > 0) & (steps < 86400)]
        nominal = float(steps.median()) if not steps.empty else 0.0

        gaps = grp["Timestamp"].diff().dt.total_seconds()
        breaks = gaps.isna() | (gaps > max(nominal * 4.0, 60.0))
        groups = breaks.cumsum()
        for _, window in grp.groupby(groups):
            pass_count += 1
            # One sample is a pass of one nominal step, not zero.
            dur = (window["Timestamp"].max() - window["Timestamp"].min()).total_seconds()
            pass_durations.append(dur if dur > 0 else nominal)

    avg_pass_s = float(np.mean(pass_durations)) if pass_durations else None

    # Distribution of real pass durations, replacing the previous fixed
    # 35/40/18/7 percentage split.
    def _bucket(lo, hi):
        return sum(1 for d in pass_durations if lo <= d / 60.0 < hi)

    revisit_hist = [
        {"bin": "< 5m", "passes": _bucket(0, 5)},
        {"bin": "5–10m", "passes": _bucket(5, 10)},
        {"bin": "10–20m", "passes": _bucket(10, 20)},
        {"bin": "> 20m", "passes": sum(1 for d in pass_durations if d / 60.0 >= 20)},
    ]

    return {
        "aoiKey": aoi_key,
        "aoiName": aoi_cfg["name"],
        "bounds": {"lonMin": lon_min, "lonMax": lon_max, "latMin": lat_min, "latMax": lat_max},
        "firstAccess": aoi_work["Timestamp"].min().strftime("%Y-%m-%dT%H:%M:%S"),
        "lastAccess": aoi_work["Timestamp"].max().strftime("%Y-%m-%dT%H:%M:%S"),
        "passCount": pass_count,
        "passesPerDay": round(pass_count / duration_days, 1),
        "analysisDurationDays": round(duration_days, 3),
        "revisitHistogram": revisit_hist,
        "satellitesCoveringAoi": len(covering_sats),
        "avgObservationDurationSec": round(avg_pass_s, 1) if avg_pass_s is not None else None,
        "avgObservationDurationMin": round(avg_pass_s / 60.0, 2) if avg_pass_s is not None else None,
        "hasData": True,
    }


def _classify_orbit_type(inclination_deg):
    """Rough LEO classification from inclination alone. SSO at these altitudes
    needs a retrograde inclination around 96-102 deg; anything else here is
    just a prograde or polar inclined orbit, not sun-synchronous."""
    if inclination_deg is None:
        return "Not Configured"
    if 95.0 <= inclination_deg <= 103.0:
        return "Sun-Synchronous Orbit (SSO)"
    if abs(inclination_deg - 90.0) < 1.0:
        return "Polar Orbit"
    if inclination_deg < 90.0:
        return "Prograde Inclined LEO"
    return "Retrograde Inclined LEO"


def compute_simulation_details(config, state_df):
    mission = config.get("mission", {})
    orbit = config.get("orbit", {})

    epoch_str = "2026-07-23T00:00:00.000"
    sim_duration = "1.0 days (86400 s)"
    if not state_df.empty and "Timestamp" in state_df.columns:
        ts = pd.to_datetime(state_df["Timestamp"], errors="coerce").dropna()
        if not ts.empty:
            epoch_str = ts.min().strftime("%Y-%m-%dT%H:%M:%S")
            dur_hrs = (ts.max() - ts.min()).total_seconds() / 3600.0
            sim_duration = f"{round(dur_hrs / 24.0, 2)} days ({round(dur_hrs * 3600, 0):.0f} s)"

    inclination = orbit.get("Inclination")
    inclination_num = _to_num(inclination, None) if inclination is not None else None

    # Fields actually derived from this mission's own config/state data --
    # everything else below is a generic simulation-configuration assumption
    # (not read from a GMAT script or per-mission source) and must not be
    # displayed as "Verified" in the UI.
    verified_fields = ["simulationDuration", "orbitType", "altitude", "inclination", "epoch"]

    return {
        "verifiedFields": verified_fields,
        "simulationEngine": "NASA General Mission Analysis Tool (GMAT)",
        "gmatVersion": "GMAT 2025 (Official Build)",
        "propagator": "PrinceDormand78 (Numerical)",
        "numericalIntegrator": "Runge-Kutta 8(9) Adaptive Step",
        "gravityModel": "EGM-96 (High-Fidelity)",
        "gravityDegreeOrder": "70 × 70",
        "earthHarmonics": "Spherical Harmonics (J2 – J70 included)",
        "atmosphericModel": "NRLMSISE-00 (Drag Enabled)",
        "solarRadiationPressure": "Spherical Model (Cr = 1.8, Area = 2.5 m²)",
        "thirdBodyPerturbations": "Sun, Moon (Point Mass)",
        "stepSize": "10.0 s (Adaptive 1.0s - 60.0s)",
        "propagationAccuracy": "1e-13",
        "simulationDuration": sim_duration,
        "orbitType": _classify_orbit_type(inclination_num),
        "altitude": f"{_to_num(orbit.get('Altitude'), 536.0)} km",
        "inclination": f"{_to_num(orbit.get('Inclination'), 50.0)}°",
        "epoch": epoch_str,
    }


def compute_ground_station_analysis(rf_df, optical_df, ground_stations_df):
    """Per-ground-station pass/duration/gap breakdown, using the actual
    ground segments defined in this mission's config (typically one RF
    station and one Optical station, each with its own elevation mask)."""
    if ground_stations_df is None or ground_stations_df.empty:
        return []

    by_link = {"rf": rf_df, "optical": optical_df}
    stations = []
    for _, row in ground_stations_df.iterrows():
        name = str(row.get("Station Name", "") or "")
        link_type = str(row.get("Link Type", "") or "")
        min_elev = row.get("Minimum Elevation (deg)")
        df = by_link.get(link_type.strip().lower(), pd.DataFrame())

        if df is None or df.empty:
            stations.append({
                "stationName": name,
                "linkType": link_type,
                "minElevationDeg": _to_num(min_elev, None) if min_elev is not None else None,
                "passCount": 0,
                "totalDurationSec": 0.0,
                "avgDurationSec": 0.0,
                "minDurationSec": 0.0,
                "maxDurationSec": 0.0,
                "longestGapMin": None,
            })
            continue

        durations = pd.to_numeric(df["Duration (s)"], errors="coerce").dropna()
        starts = pd.to_datetime(df["Start UTC"], errors="coerce").dropna().sort_values()
        gaps = starts.diff().dt.total_seconds().dropna() / 60.0

        stations.append({
            "stationName": name,
            "linkType": link_type,
            "minElevationDeg": _to_num(min_elev, None) if min_elev is not None else None,
            "passCount": int(len(df)),
            "totalDurationSec": float(durations.sum()) if not durations.empty else 0.0,
            "avgDurationSec": float(durations.mean()) if not durations.empty else 0.0,
            "minDurationSec": float(durations.min()) if not durations.empty else 0.0,
            "maxDurationSec": float(durations.max()) if not durations.empty else 0.0,
            "longestGapMin": float(gaps.max()) if not gaps.empty else None,
        })

    return stations


def compute_engineering_observations(mission_rows):
    """Factual, threshold-free comparisons across missions, derived purely
    from already-computed metrics. Reports which mission scores higher/lower
    on each metric and by how much -- never an overall "X is better"
    verdict, since that judgement depends on mission priorities this code
    has no basis to assume."""
    if not mission_rows or len(mission_rows) < 2:
        return []

    def fmt(v, digits=1):
        return None if v is None else round(float(v), digits)

    observations = []

    def compare(field, label, unit, lower_is_better):
        pairs = [(r.get("label", r.get("missionId", "?")), r.get(field)) for r in mission_rows]
        pairs = [(n, v) for n, v in pairs if v is not None]
        if len(pairs) < 2:
            return
        pairs.sort(key=lambda kv: kv[1])
        lo_name, lo_val = pairs[0]
        hi_name, hi_val = pairs[-1]
        if lo_val == hi_val:
            observations.append(f"{label}: all compared missions are equal at {fmt(lo_val)}{unit}.")
            return
        better_name, better_val = (lo_name, lo_val) if lower_is_better else (hi_name, hi_val)
        worse_name, worse_val = (hi_name, hi_val) if lower_is_better else (lo_name, lo_val)
        diff = abs(hi_val - lo_val)
        observations.append(
            f"{label}: {better_name} scores higher at {fmt(better_val)}{unit}, vs {worse_name} at {fmt(worse_val)}{unit} "
            f"(difference of {fmt(diff)}{unit})."
        )

    compare("coveragePercent", "Australia coverage", "%", lower_is_better=False)
    compare("meanRevisitMin", "Mean revisit time", " min", lower_is_better=True)
    compare("largestGapMin", "Largest coverage gap", " min", lower_is_better=True)
    compare("rfContactsPerDay", "RF contacts per day", "", lower_is_better=False)
    compare("imagesPerDay", "Estimated images per day", "", lower_is_better=False)

    counts = [(r.get("label", r.get("missionId", "?")), (r.get("constellation") or {}).get("configuredSatellites")) for r in mission_rows]
    counts = [(n, c) for n, c in counts if c is not None]
    if len(counts) >= 2:
        counts_str = "; ".join(f"{n}: {c} satellites" for n, c in counts)
        observations.append(f"Constellation size compared -- {counts_str}.")

    return observations


def _union_seconds(intervals):
    """Total wall-clock seconds covered by a set of possibly overlapping
    [start, stop] pairs, counting overlapping windows once."""
    spans = sorted((s, e) for s, e in intervals if pd.notna(s) and pd.notna(e) and e > s)
    if not spans:
        return 0.0
    total = 0.0
    cur_s, cur_e = spans[0]
    for s, e in spans[1:]:
        if s > cur_e:
            total += (cur_e - cur_s).total_seconds()
            cur_s, cur_e = s, e
        elif e > cur_e:
            cur_e = e
    total += (cur_e - cur_s).total_seconds()
    return float(total)


def compute_mission_analytics(summary, gap_analysis, contrib_rows, coverage_percent=None,
                              observation_overall=None, state_df=None, rf_df=None,
                              optical_df=None, eclipse_df=None, constellation=None):
    """Mission indicators, each derived from the GMAT datasets.

    This deliberately reports only what the data supports. Spacecraft
    availability and per-subsystem health (power, thermal, OBC, payload)
    would need housekeeping telemetry, which a GMAT mission-analysis run
    does not produce -- so they are reported as unavailable rather than
    given invented scores.
    """
    observation_overall = observation_overall or {}
    constellation = constellation or {}

    # Analysis window, shared denominator for the time-based shares.
    span_s = 0.0
    if state_df is not None and not state_df.empty and "Timestamp" in state_df.columns:
        ts = pd.to_datetime(state_df["Timestamp"], errors="coerce").dropna()
        if not ts.empty:
            span_s = float((ts.max() - ts.min()).total_seconds())

    def link_availability(df):
        """Share of the analysis window with at least one contact in progress."""
        if df is None or df.empty or span_s <= 0:
            return None
        if not {"Start UTC", "Stop UTC"}.issubset(df.columns):
            return None
        starts = pd.to_datetime(df["Start UTC"], errors="coerce")
        stops = pd.to_datetime(df["Stop UTC"], errors="coerce")
        covered = _union_seconds(zip(starts, stops))
        return round(min(100.0, 100.0 * covered / span_s), 2)

    # Eclipse share of fleet-time, counted per satellite then averaged.
    eclipse_share = None
    if eclipse_df is not None and not eclipse_df.empty and span_s > 0 \
            and {"Satellite Name", "Start UTC", "Stop UTC"}.issubset(eclipse_df.columns):
        per_sat = []
        ed = eclipse_df.copy()
        ed["Start UTC"] = pd.to_datetime(ed["Start UTC"], errors="coerce")
        ed["Stop UTC"] = pd.to_datetime(ed["Stop UTC"], errors="coerce")
        for _, grp in ed.groupby("Satellite Name"):
            per_sat.append(_union_seconds(zip(grp["Start UTC"], grp["Stop UTC"])) / span_s)
        if per_sat:
            eclipse_share = round(100.0 * float(np.mean(per_sat)), 2)

    configured = _to_num(constellation.get("Total Satellites"), 0)
    detected = 0
    if state_df is not None and not state_df.empty and "Satellite Name" in state_df.columns:
        detected = int(state_df["Satellite Name"].dropna().astype(str).nunique())
    data_completeness = round(100.0 * detected / configured, 1) if configured else None

    obs_duty = _to_num(observation_overall.get("Overall Observation Duty Cycle (%)"), None)

    return {
        "analysisWindowHours": round(span_s / 3600.0, 2) if span_s else None,
        "coveragePercent": coverage_percent,
        "observationDutyPct": round(obs_duty, 2) if obs_duty is not None else None,
        "rfLinkAvailabilityPct": link_availability(rf_df),
        "opticalLinkAvailabilityPct": link_availability(optical_df),
        "meanEclipseSharePct": eclipse_share,
        "dataCompletenessPct": data_completeness,
        "detectedSatellites": detected,
        "configuredSatellites": int(configured) if configured else None,
        # Explicitly unavailable rather than silently absent, so the UI can
        # say why instead of showing a number nobody can trace.
        "unavailable": [
            {
                "metric": "Spacecraft availability",
                "reason": "Requires housekeeping telemetry (bus health, mode history). Not produced by a GMAT mission-analysis run.",
            },
            {
                "metric": "Subsystem health (power, thermal, payload, OBC)",
                "reason": "Requires on-board subsystem telemetry. No such dataset exists in this project.",
            },
        ],
    }
