import math
import numpy as np
import pandas as pd
from matplotlib.path import Path
from core.australia_coverage import MAINLAND_AUSTRALIA, TASMANIA

def _grid(resolution_deg=0.5):
    lats = np.arange(-44.0, -9.999, resolution_deg)
    lons = np.arange(112.0, 154.001, resolution_deg)
    lon2, lat2 = np.meshgrid(lons, lats)
    pts = np.column_stack([lon2.ravel(), lat2.ravel()])
    land = Path(MAINLAND_AUSTRALIA).contains_points(pts) | Path(TASMANIA).contains_points(pts)
    return pd.DataFrame({"Longitude": pts[:,0], "Latitude": pts[:,1], "Is Australia": land})

def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1 = np.radians(lat1)
    p2 = np.radians(lat2)
    dp = np.radians(lat2-lat1)
    dl = np.radians(lon2-lon1)
    a = np.sin(dp/2)**2 + np.cos(p1)*np.cos(p2)*np.sin(dl/2)**2
    return 2*r*np.arcsin(np.sqrt(np.clip(a, 0, 1)))

def cumulative_australia_coverage(state_df, swath_km, resolution_deg=0.5, densify=True):
    """
    Engineering cumulative-coverage estimate.
    Australia is discretized into geographic cell centers. A cell is covered when
    its center lies within half the modeled ground swath of any satellite subpoint
    at any point along the ground track.

    The GMAT report samples every ~94 s, which is ~629 km of ground track -- about
    nine times the modelled swath. Testing only the reported fixes therefore
    misses most of the ground actually overflown and materially under-reports
    coverage. The track is densified onto a great-circle path at half-swath
    spacing before testing. Pass densify=False to reproduce the older
    fixes-only behaviour.
    """
    grid = _grid(resolution_deg)
    aus = grid[grid["Is Australia"]].copy().reset_index(drop=True)
    if aus.empty:
        return aus, pd.DataFrame(), 0.0

    states = state_df.copy()
    states["Latitude"] = pd.to_numeric(states["Latitude"], errors="coerce")
    states["Longitude"] = pd.to_numeric(states["Longitude"], errors="coerce")
    states = states.dropna(subset=["Latitude","Longitude","Satellite Name"])
    half_swath = max(float(swath_km)/2.0, 0.0)

    if densify and not states.empty and "Timestamp" in states.columns:
        from core.footprint import densify_track

        states["Timestamp"] = pd.to_datetime(states["Timestamp"], errors="coerce")
        states = states.dropna(subset=["Timestamp"])
        states = densify_track(states, max_gap_km=max(half_swath, 1.0))

    # Only fixes near Australia can cover an Australian cell. Discarding the rest
    # first keeps the distance computation tractable after densification.
    if not states.empty:
        pad_lat = half_swath / 111.0
        pad_lon = pad_lat / max(math.cos(math.radians(27.0)), 0.2)
        states = states[
            states["Latitude"].between(-44.0 - pad_lat, -9.999 + pad_lat)
            & states["Longitude"].between(112.0 - pad_lon, 154.001 + pad_lon)
        ]

    covered = np.zeros(len(aus), dtype=bool)
    contributors = {}
    glat = aus["Latitude"].to_numpy()
    glon = aus["Longitude"].to_numpy()

    for sat, grp in states.groupby("Satellite Name"):
        slat = grp["Latitude"].to_numpy(dtype=float)
        slon = grp["Longitude"].to_numpy(dtype=float)
        sat_cov = np.zeros(len(aus), dtype=bool)
        # Chunk the satellite's fixes so the (cells x fixes) matrix stays bounded.
        chunk = max(int(4_000_000 / max(len(aus), 1)), 1)
        for start in range(0, len(slat), chunk):
            sub_lat = slat[start:start + chunk]
            sub_lon = slon[start:start + chunk]
            d = _haversine_km(
                glat[:, None], glon[:, None], sub_lat[None, :], sub_lon[None, :]
            )
            sat_cov |= (d <= half_swath).any(axis=1)
            if sat_cov.all():
                break
        covered |= sat_cov
        contributors[str(sat)] = int(sat_cov.sum())

    aus["Covered"] = covered
    # Latitude weighting approximates unequal geographic cell area.
    weights = np.cos(np.radians(aus["Latitude"].to_numpy()))
    total_w = weights.sum()
    covered_pct = float(100.0 * weights[covered].sum() / total_w) if total_w else 0.0

    contrib = pd.DataFrame({
        "Satellite Name": list(contributors.keys()),
        "Covered Cell Centers": list(contributors.values())
    }).sort_values("Covered Cell Centers", ascending=False)

    return aus, contrib, covered_pct
