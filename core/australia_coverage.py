import numpy as np
import pandas as pd
from matplotlib.path import Path

# Operational Australia land-boundary approximation (mainland + Tasmania).
# This is substantially better than a rectangular bounding box, but is still
# an engineering polygon approximation rather than an official administrative dataset.
MAINLAND_AUSTRALIA = [
    (113.0,-22.0),(114.0,-16.0),(121.0,-13.5),(129.0,-14.5),(136.0,-12.0),
    (142.0,-10.5),(145.0,-14.5),(146.5,-19.0),(153.6,-28.5),(153.0,-32.5),
    (150.0,-37.5),(146.0,-39.0),(141.0,-38.0),(136.0,-35.0),(131.0,-32.0),
    (124.0,-34.5),(117.0,-35.0),(114.0,-29.0),(113.0,-22.0)
]
TASMANIA = [
    (144.5,-40.5),(148.5,-40.5),(148.5,-43.8),(145.0,-43.8),(144.5,-40.5)
]

# Polygon objects and their combined bounding box are built once at import.
# Rebuilding a Path per call was a measurable cost: these functions run over
# densified tracks of ~840k points on every cold dashboard build.
_MAINLAND_PATH = Path(MAINLAND_AUSTRALIA)
_TASMANIA_PATH = Path(TASMANIA)
_ALL_VERTICES = MAINLAND_AUSTRALIA + TASMANIA
_LON_MIN = min(p[0] for p in _ALL_VERTICES)
_LON_MAX = max(p[0] for p in _ALL_VERTICES)
_LAT_MIN = min(p[1] for p in _ALL_VERTICES)
_LAT_MAX = max(p[1] for p in _ALL_VERTICES)

# Nine-point test: the sub-satellite point itself plus the eight half-swath
# offsets around it.
_OFFSETS = ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def _inside_polygon(lon, lat, polygon):
    path = Path(polygon)
    pts = np.column_stack([
        pd.to_numeric(lon, errors="coerce").to_numpy(dtype=float),
        pd.to_numeric(lat, errors="coerce").to_numpy(dtype=float),
    ])
    return path.contains_points(pts)

def australia_land_mask(df, lon_col="Longitude", lat_col="Latitude"):
    mainland = _inside_polygon(df[lon_col], df[lat_col], MAINLAND_AUSTRALIA)
    tas = _inside_polygon(df[lon_col], df[lat_col], TASMANIA)
    return mainland | tas

def _land_mask_xy(lon, lat):
    """Land test on raw coordinate arrays, no DataFrame round-trip."""
    pts = np.column_stack([lon, lat])
    return _MAINLAND_PATH.contains_points(pts) | _TASMANIA_PATH.contains_points(pts)

def footprint_intersects_australia(df, swath_km, lon_col="Longitude", lat_col="Latitude"):
    # Conservative operational trigger: sub-satellite point over Australia OR within
    # half-swath angular distance of the approximated land boundary.
    # For dashboard efficiency, expand the polygon test by checking nearby offsets.
    half = max(float(swath_km or 0)/2.0, 0.0)
    deg_lat = half / 111.0
    lat = pd.to_numeric(df[lat_col], errors="coerce").to_numpy(dtype=float)
    lon = pd.to_numeric(df[lon_col], errors="coerce").to_numpy(dtype=float)

    out = np.zeros(lat.shape[0], dtype=bool)
    if out.size == 0:
        return out

    coslat = np.maximum(np.cos(np.radians(np.minimum(np.abs(lat), 80.0))), 0.2)
    deg_lon = deg_lat / coslat

    # The constellation orbits the whole globe, so the large majority of
    # samples are nowhere near Australia. A point can only pass any of the
    # nine tests if it falls inside the land bounding box widened by the
    # largest offset applied, so reject the rest with cheap array compares
    # before running any polygon test. This is a superset of the true
    # positives -- it can never discard a point the full test would keep.
    finite = np.isfinite(lon) & np.isfinite(lat)
    max_dlon = float(np.nanmax(deg_lon)) if finite.any() else 0.0
    candidate = (
        finite
        & (lon >= _LON_MIN - max_dlon) & (lon <= _LON_MAX + max_dlon)
        & (lat >= _LAT_MIN - deg_lat) & (lat <= _LAT_MAX + deg_lat)
    )
    if not candidate.any():
        return out

    clon = lon[candidate]
    clat = lat[candidate]
    cdlon = deg_lon[candidate]

    hit = np.zeros(clon.shape[0], dtype=bool)
    for sx, sy in _OFFSETS:
        hit |= _land_mask_xy(clon + sx * cdlon, clat + sy * deg_lat)

    out[candidate] = hit
    return out
