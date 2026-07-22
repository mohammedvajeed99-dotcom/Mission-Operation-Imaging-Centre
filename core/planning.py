"""Mission planning: imaging opportunities, revisit statistics, request scheduling,
and coverage replay.

Scope note on "prediction": this module does not propagate orbits. It works
entirely within the span of the GMAT state report, which is already a
propagated ephemeris. "Future opportunities" therefore means opportunities
after a chosen reference time but still inside the report span. Predicting
beyond the report would require a propagator and TLEs/initial elements that the
report does not carry, and this module will not extrapolate past its data.
"""

import numpy as np
import pandas as pd

from core.footprint import (
    _bearing_deg,
    densify_track,
    footprint_corners,
    ground_track_heading,
    haversine_km,
    orbit_numbers,
)


def _prepare(state_df, densify_km=None):
    df = state_df.copy()
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    for col in ("Latitude", "Longitude", "Altitude"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Timestamp", "Satellite Name", "Latitude", "Longitude"])
    df = df.sort_values(["Satellite Name", "Timestamp"])
    if densify_km:
        # Without this, point-target access tests silently miss most passes:
        # the report's 629 km fix spacing is ~9x the camera swath, so a
        # satellite can overfly a target entirely between two samples.
        df = densify_track(df, max_gap_km=densify_km)
    return df


def _cross_track_distance_km(sat_lat, sat_lon, heading_deg, tgt_lat, tgt_lon):
    """Perpendicular distance from a target to the satellite's ground track.

    Cross-track offset determines whether a nadir footprint of a given swath
    actually contains the target, which along-track distance alone cannot tell you.
    """
    d = haversine_km(sat_lat, sat_lon, tgt_lat, tgt_lon)
    bearing_to_target = _bearing_deg(sat_lat, sat_lon, tgt_lat, tgt_lon)
    delta = np.radians(bearing_to_target - np.asarray(heading_deg))
    return np.abs(d * np.sin(delta))


def imaging_opportunities(state_df, camera_model, target_lat, target_lon,
                          after=None, max_results=50):
    """Every pass where the target falls inside the camera footprint.

    Returns a DataFrame ordered by time, with cross-track offset so an operator
    can prefer near-nadir passes over edge-of-swath ones.
    """
    swath_km = float(camera_model.get("Ground Swath (km)") or 0.0)
    if not swath_km:
        return pd.DataFrame()
    half_swath = swath_km / 2.0

    # Densify to a quarter-swath so no access window can slip between fixes.
    df = _prepare(state_df, densify_km=half_swath / 2.0)
    if df.empty:
        return pd.DataFrame()
    if after is not None:
        df = df[df["Timestamp"] > pd.to_datetime(after)]
        if df.empty:
            return pd.DataFrame()

    rows = []
    for sat, grp in df.groupby("Satellite Name", sort=True):
        grp = grp.sort_values("Timestamp").copy()
        grp["heading"] = ground_track_heading(grp)
        grp["orbit"] = orbit_numbers(grp)

        # Coarse gate first -- great-circle distance must at least be within the
        # half-swath -- then the exact cross-track test on survivors only.
        approx = haversine_km(
            grp["Latitude"].to_numpy(dtype=float),
            grp["Longitude"].to_numpy(dtype=float),
            target_lat, target_lon,
        )
        gate = approx <= half_swath * 1.5
        near = grp[gate].copy()
        if near.empty:
            continue
        near["slantKm"] = approx[gate]
        near["crossTrackKm"] = _cross_track_distance_km(
            near["Latitude"].to_numpy(), near["Longitude"].to_numpy(),
            near["heading"].to_numpy(), target_lat, target_lon,
        )
        hits = near[near["crossTrackKm"] <= half_swath]
        if hits.empty:
            continue

        # Collapse consecutive fixes into one opportunity per pass, keeping the
        # closest approach as the representative moment.
        hits = hits.sort_values("Timestamp")
        gaps = hits["Timestamp"].diff().dt.total_seconds()
        pass_id = ((gaps.isna()) | (gaps > 600)).cumsum()
        for _, window in hits.groupby(pass_id):
            best = window.loc[window["crossTrackKm"].idxmin()]
            rows.append({
                "satellite": str(sat),
                "timestamp": best["Timestamp"],
                "windowStart": window["Timestamp"].min(),
                "windowEnd": window["Timestamp"].max(),
                "windowSeconds": float(
                    (window["Timestamp"].max() - window["Timestamp"].min()).total_seconds()
                ),
                "orbit": int(best["orbit"]),
                "crossTrackKm": float(best["crossTrackKm"]),
                "offNadirFraction": float(best["crossTrackKm"] / half_swath),
                "subSatelliteLat": float(best["Latitude"]),
                "subSatelliteLon": float(best["Longitude"]),
                "headingDeg": float(best["heading"]),
                "altitudeKm": float(best["Altitude"]) if pd.notna(best["Altitude"]) else None,
                "footprint": footprint_corners(
                    best["Latitude"], best["Longitude"], best["heading"], swath_km, swath_km
                ),
            })

    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    return out.head(max_results) if max_results else out


def revisit_analysis(state_df, camera_model, target_lat, target_lon):
    """Revisit statistics for a point of interest.

    Revisit interval is measured between consecutive opportunities from *any*
    satellite, which is what a customer waiting for imagery actually experiences.
    """
    opps = imaging_opportunities(state_df, camera_model, target_lat, target_lon,
                                 max_results=None)
    if opps.empty:
        return {
            "target": {"lat": target_lat, "lon": target_lon},
            "opportunities": 0,
            "note": "No pass places this target inside the camera swath within the report span.",
        }

    times = opps["timestamp"].sort_values()
    gaps_h = times.diff().dt.total_seconds().dropna() / 3600.0
    span_h = (times.max() - times.min()).total_seconds() / 3600.0

    return {
        "target": {"lat": target_lat, "lon": target_lon},
        "opportunities": int(len(opps)),
        "satellitesInvolved": sorted(opps["satellite"].unique().tolist()),
        "firstOpportunity": times.min().isoformat(),
        "lastOpportunity": times.max().isoformat(),
        "spanHours": round(span_h, 2),
        "meanRevisitHours": round(float(gaps_h.mean()), 2) if len(gaps_h) else None,
        "medianRevisitHours": round(float(gaps_h.median()), 2) if len(gaps_h) else None,
        "minRevisitHours": round(float(gaps_h.min()), 2) if len(gaps_h) else None,
        "maxRevisitHours": round(float(gaps_h.max()), 2) if len(gaps_h) else None,
        "nearNadirOpportunities": int((opps["offNadirFraction"] <= 0.3).sum()),
        "meanOffNadirFraction": round(float(opps["offNadirFraction"].mean()), 3),
    }


def schedule_requests(state_df, camera_model, requests, min_gap_seconds=60):
    """Assign imaging requests to opportunities, resolving conflicts by priority.

    `requests` is a list of dicts: {id, lat, lon, priority (1 = highest),
    earliest (optional), latest (optional)}.

    A satellite cannot image two targets at once, so when two requests want the
    same satellite at overlapping times the higher priority wins and the loser
    falls to its next available opportunity. This is a greedy scheduler, not an
    optimal one -- it is deterministic and explainable, which for an ops demo
    matters more than squeezing out the last few percent of utilisation.
    """
    scheduled = []
    unscheduled = []
    # satellite -> list of (start, end) already committed
    committed = {}

    ordered = sorted(requests, key=lambda r: (int(r.get("priority", 5)), str(r.get("id"))))

    for req in ordered:
        opps = imaging_opportunities(
            state_df, camera_model, float(req["lat"]), float(req["lon"]),
            after=req.get("earliest"), max_results=None,
        )
        if opps.empty:
            unscheduled.append({**req, "reason": "no opportunity within report span"})
            continue
        if req.get("latest"):
            opps = opps[opps["timestamp"] <= pd.to_datetime(req["latest"])]
            if opps.empty:
                unscheduled.append({**req, "reason": "no opportunity before deadline"})
                continue

        # Prefer the most nadir-looking opportunity, then the earliest.
        opps = opps.sort_values(["offNadirFraction", "timestamp"])

        placed = False
        for opp in opps.itertuples(index=False):
            sat = opp.satellite
            start = opp.windowStart - pd.Timedelta(seconds=min_gap_seconds)
            end = opp.windowEnd + pd.Timedelta(seconds=min_gap_seconds)
            busy = committed.setdefault(sat, [])
            if any(not (end < s or start > e) for s, e in busy):
                continue
            busy.append((start, end))
            scheduled.append({
                "requestId": req.get("id"),
                "priority": int(req.get("priority", 5)),
                "target": {"lat": float(req["lat"]), "lon": float(req["lon"])},
                "satellite": sat,
                "acquisitionTime": opp.timestamp.isoformat(),
                "windowStart": opp.windowStart.isoformat(),
                "windowEnd": opp.windowEnd.isoformat(),
                "orbit": int(opp.orbit),
                "crossTrackKm": round(float(opp.crossTrackKm), 2),
                "offNadirFraction": round(float(opp.offNadirFraction), 3),
            })
            placed = True
            break

        if not placed:
            unscheduled.append({**req, "reason": "all opportunities conflict with higher-priority tasking"})

    return {
        "scheduled": sorted(scheduled, key=lambda r: r["acquisitionTime"]),
        "unscheduled": unscheduled,
        "satellitesTasked": sorted(committed.keys()),
        "method": "greedy, priority-ordered, nadir-preferring",
    }


def coverage_replay(state_df, camera_model, steps=24, resolution_deg=1.0):
    """Cumulative Australia coverage sampled at intervals across the report span.

    Returns one frame per step, each carrying the cumulative coverage percentage
    up to that moment, so the dashboard can animate coverage accumulating.
    """
    from core.cumulative_coverage import cumulative_australia_coverage

    swath_km = float(camera_model.get("Ground Swath (km)") or 0.0)
    df = _prepare(state_df)
    if df.empty or not swath_km:
        return []

    start, end = df["Timestamp"].min(), df["Timestamp"].max()
    edges = pd.date_range(start, end, periods=int(steps) + 1)

    frames = []
    for i, edge in enumerate(edges[1:], start=1):
        upto = df[df["Timestamp"] <= edge]
        if upto.empty:
            continue
        _, _, pct = cumulative_australia_coverage(upto, swath_km, resolution_deg=resolution_deg)
        frames.append({
            "step": i,
            "timestamp": edge.isoformat(),
            "elapsedHours": round((edge - start).total_seconds() / 3600.0, 2),
            "cumulativeCoveragePercent": round(float(pct), 3),
            "samplesUsed": int(len(upto)),
        })
    return frames
