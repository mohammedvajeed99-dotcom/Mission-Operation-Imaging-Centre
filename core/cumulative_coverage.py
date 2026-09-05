import math
import numpy as np
import pandas as pd
from matplotlib.path import Path
from core.australia_coverage import MAINLAND_AUSTRALIA, TASMANIA, MAINLAND_INDIA
from core.regions import AOI_BOXES

# Grid extent per region -- deliberately a little wider than each region's
# AOI_BOXES entry so cells right at the edge of the box are not clipped by
# the sampling grid itself.
_GRID_EXTENT = {
    "australia": {"lonMin": 112.0, "lonMax": 154.001, "latMin": -44.0, "latMax": -9.999},
    "india": {"lonMin": 67.0, "lonMax": 98.001, "latMin": 7.0, "latMax": 37.999},
}
_REGION_POLYGONS = {
    "australia": [MAINLAND_AUSTRALIA, TASMANIA],
    "india": [MAINLAND_INDIA],
}


def _grid(resolution_deg=0.5, region="australia"):
    extent = _GRID_EXTENT.get(region) or _GRID_EXTENT["australia"]
    polygons = _REGION_POLYGONS.get(region) or _REGION_POLYGONS["australia"]
    lats = np.arange(extent["latMin"], extent["latMax"], resolution_deg)
    lons = np.arange(extent["lonMin"], extent["lonMax"], resolution_deg)
    lon2, lat2 = np.meshgrid(lons, lats)
    pts = np.column_stack([lon2.ravel(), lat2.ravel()])
    land = np.zeros(pts.shape[0], dtype=bool)
    for poly in polygons:
        land |= Path(poly).contains_points(pts)
    return pd.DataFrame({"Longitude": pts[:,0], "Latitude": pts[:,1], "Is Land": land})

def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1 = np.radians(lat1)
    p2 = np.radians(lat2)
    dp = np.radians(lat2-lat1)
    dl = np.radians(lon2-lon1)
    a = np.sin(dp/2)**2 + np.cos(p1)*np.cos(p2)*np.sin(dl/2)**2
    return 2*r*np.arcsin(np.sqrt(np.clip(a, 0, 1)))

def cumulative_region_coverage(state_df, swath_km, resolution_deg=0.5, densify=True, region="australia"):
    """
    Engineering cumulative-coverage estimate, generalised over the mission's
    AOI region (core.regions -- Australia or India today).

    The region's land area is discretized into geographic cell centers. A
    cell is covered when its center lies within half the modeled ground
    swath of any satellite subpoint at any point along the ground track.

    The GMAT report samples every ~94 s, which is ~629 km of ground track --
    about nine times the modelled swath. Testing only the reported fixes
    therefore misses most of the ground actually overflown and materially
    under-reports coverage. The track is densified onto a great-circle path
    at half-swath spacing before testing. Pass densify=False to reproduce
    the older fixes-only behaviour.
    """
    extent = _GRID_EXTENT.get(region) or _GRID_EXTENT["australia"]
    grid = _grid(resolution_deg, region=region)
    land = grid[grid["Is Land"]].copy().reset_index(drop=True)
    if land.empty:
        return land, pd.DataFrame(), 0.0

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

    # Only fixes near the region can cover one of its cells. Discarding the
    # rest first keeps the distance computation tractable after densification.
    if not states.empty:
        pad_lat = half_swath / 111.0
        mid_lat = (extent["latMin"] + extent["latMax"]) / 2.0
        pad_lon = pad_lat / max(math.cos(math.radians(abs(mid_lat))), 0.2)
        states = states[
            states["Latitude"].between(extent["latMin"] - pad_lat, extent["latMax"] + pad_lat)
            & states["Longitude"].between(extent["lonMin"] - pad_lon, extent["lonMax"] + pad_lon)
        ]

    covered = np.zeros(len(land), dtype=bool)
    contributors = {}
    glat = land["Latitude"].to_numpy()
    glon = land["Longitude"].to_numpy()

    for sat, grp in states.groupby("Satellite Name"):
        slat = grp["Latitude"].to_numpy(dtype=float)
        slon = grp["Longitude"].to_numpy(dtype=float)
        sat_cov = np.zeros(len(land), dtype=bool)
        # Chunk the satellite's fixes so the (cells x fixes) matrix stays bounded.
        chunk = max(int(4_000_000 / max(len(land), 1)), 1)
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

    land["Covered"] = covered
    # Latitude weighting approximates unequal geographic cell area.
    weights = np.cos(np.radians(land["Latitude"].to_numpy()))
    total_w = weights.sum()
    covered_pct = float(100.0 * weights[covered].sum() / total_w) if total_w else 0.0

    contrib = pd.DataFrame({
        "Satellite Name": list(contributors.keys()),
        "Covered Cell Centers": list(contributors.values())
    }).sort_values("Covered Cell Centers", ascending=False)

    return land, contrib, covered_pct


def cumulative_australia_coverage(state_df, swath_km, resolution_deg=0.5, densify=True):
    """Kept for every existing call site -- identical behaviour to before,
    now implemented as the "australia" case of cumulative_region_coverage."""
    grid, contrib, pct = cumulative_region_coverage(
        state_df, swath_km, resolution_deg=resolution_deg, densify=densify, region="australia"
    )
    if not grid.empty:
        grid = grid.rename(columns={"Is Land": "Is Australia"})
    return grid, contrib, pct
