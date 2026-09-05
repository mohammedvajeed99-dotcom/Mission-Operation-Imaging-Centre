import numpy as np
import pandas as pd
from matplotlib.path import Path

# Operational land-boundary approximations, one per mission region. Each is
# substantially better than a rectangular bounding box, but is still an
# engineering polygon approximation rather than an official administrative
# dataset -- consistent with the disclosure already used throughout this
# project (core.aoi_regions carries the same caveat for Australia's states).
MAINLAND_AUSTRALIA = [
    (113.0,-22.0),(114.0,-16.0),(121.0,-13.5),(129.0,-14.5),(136.0,-12.0),
    (142.0,-10.5),(145.0,-14.5),(146.5,-19.0),(153.6,-28.5),(153.0,-32.5),
    (150.0,-37.5),(146.0,-39.0),(141.0,-38.0),(136.0,-35.0),(131.0,-32.0),
    (124.0,-34.5),(117.0,-35.0),(114.0,-29.0),(113.0,-22.0)
]
TASMANIA = [
    (144.5,-40.5),(148.5,-40.5),(148.5,-43.8),(145.0,-43.8),(144.5,-40.5)
]

# India's mainland outline, extracted from world-atlas's countries-50m.json
# (Natural Earth data, already bundled as a frontend dependency) via
# topojson-client, then decimated from ~1360 to ~150 points to match the
# coarseness already used for MAINLAND_AUSTRALIA above -- real coastline
# data, deliberately simplified for a coverage grid rather than survey use.
# Offshore island territories (Andaman & Nicobar, Lakshadweep) are excluded,
# the same way outlying Australian islands other than Tasmania are excluded.
MAINLAND_INDIA = [
    (68.16,23.86),(68.76,24.31),(69.23,24.27),(70.1,24.29),(70.77,24.25),
    (70.98,24.52),(70.7,25.33),(70.26,25.71),(70.06,26.58),(69.57,27.17),
    (70.32,27.98),(70.88,27.71),(72.18,28.42),(73.26,29.61),(73.88,30.35),
    (74.63,31.07),(74.55,31.82),(75.24,32.37),(74.59,32.75),(74.13,33.07),
    (74.13,33.55),(74.25,33.99),(73.97,34.24),(74.17,34.72),(75.45,34.54),
    (76.6,34.74),(77.17,35.17),(77.9,35.45),(78.24,34.77),(78.98,34.26),
    (78.8,33.5),(79.1,33.05),(79.22,32.51),(78.75,32.5),(78.44,32.4),
    (78.69,31.74),(78.85,31.3),(79.37,31.08),(79.93,30.89),(80.54,30.46),
    (80.85,30.14),(80.23,29.19),(80.42,28.61),(81.02,28.41),(81.9,27.87),
    (82.71,27.6),(83.55,27.46),(84.64,27.25),(85.18,26.78),(85.74,26.64),
    (86.7,26.43),(87.63,26.4),(88.11,26.93),(88.11,27.87),(88.62,28.09),
    (88.89,27.32),(89.04,26.87),(89.61,26.72),(90.56,26.8),(91.67,26.8),
    (92.03,27.04),(91.85,27.44),(91.82,27.75),(92.41,27.83),(92.7,28.15),
    (93.76,28.73),(94.62,29.31),(95.35,29.04),(96.04,29.45),(96.18,29.12),
    (96.55,28.83),(96.37,28.37),(97.15,28.34),(97.22,27.89),(97.1,27.12),
    (96.06,27.22),(95.09,26.53),(95.01,25.91),(94.55,25.22),(94.4,24.51),
    (93.76,23.98),(93.37,23.77),(93.16,23.03),(93.15,22.23),(92.72,22.13),
    (92.49,22.68),(92.25,23.68),(91.92,23.47),(91.51,23.03),(91.32,23.11),
    (91.39,24.1),(91.9,24.26),(92.23,24.77),(92.38,25.01),(90.61,25.17),
    (89.8,25.34),(89.57,26.13),(89.07,26.38),(88.9,26.26),(88.37,26.56),
    (88.24,26.18),(88.45,25.57),(88.93,25.22),(88.28,24.88),(88.29,24.48),
    (88.7,24.0),(88.72,23.25),(88.92,22.63),(89.05,21.65),(88.74,22.01),
    (88.31,21.72),(88.09,22.22),(87.95,21.83),(86.94,20.75),(86.38,20.01),
    (85.5,19.7),(85.23,19.6),(84.46,18.69),(82.36,17.1),(82.14,16.49),
    (80.98,15.76),(80.1,15.32),(80.23,13.86),(80.29,13.44),(79.79,11.45),
    (79.67,10.3),(78.92,9.45),(78.42,9.1),(77.3,8.15),(76.4,9.24),
    (76.46,9.54),(75.92,10.78),(74.94,12.56),(74.46,14.17),(73.95,15.07),
    (73.68,15.71),(72.99,18.1),(72.97,19.15),(72.77,19.41),(72.9,20.67),
    (72.73,21.47),(72.54,21.7),(72.81,22.23),(72.24,22.03),(72.25,21.53),
    (70.13,21.09),(69.05,22.44),(70.0,22.55),(70.4,23.03),(69.24,22.85),
    (68.5,23.75),(68.16,23.86),
]

# Region registry: each entry is a list of (name, ring) polygon parts that
# together make up that region's land test. Path objects and the combined
# bounding box are built once at import for every region -- rebuilding a
# Path per call was a measurable cost, this function runs over densified
# tracks of hundreds of thousands of points on every cold dashboard build.
_REGION_POLYGONS = {
    "australia": [MAINLAND_AUSTRALIA, TASMANIA],
    "india": [MAINLAND_INDIA],
}


class _Region:
    __slots__ = ("paths", "lon_min", "lon_max", "lat_min", "lat_max")

    def __init__(self, polygons):
        self.paths = [Path(p) for p in polygons]
        verts = [pt for poly in polygons for pt in poly]
        self.lon_min = min(p[0] for p in verts)
        self.lon_max = max(p[0] for p in verts)
        self.lat_min = min(p[1] for p in verts)
        self.lat_max = max(p[1] for p in verts)

    def contains_xy(self, lon, lat):
        pts = np.column_stack([lon, lat])
        hit = np.zeros(pts.shape[0], dtype=bool)
        for path in self.paths:
            hit |= path.contains_points(pts)
        return hit


_REGIONS = {key: _Region(polys) for key, polys in _REGION_POLYGONS.items()}

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


def region_land_mask(df, region="australia", lon_col="Longitude", lat_col="Latitude"):
    """Same as australia_land_mask, generalised to any region in _REGIONS."""
    r = _REGIONS.get(region) or _REGIONS["australia"]
    lon = pd.to_numeric(df[lon_col], errors="coerce").to_numpy(dtype=float)
    lat = pd.to_numeric(df[lat_col], errors="coerce").to_numpy(dtype=float)
    return r.contains_xy(lon, lat)


def footprint_intersects_region(df, swath_km, region="australia", lon_col="Longitude", lat_col="Latitude"):
    # Conservative operational trigger: sub-satellite point over the region's
    # land OR within half-swath angular distance of the approximated land
    # boundary. For dashboard efficiency, expand the polygon test by
    # checking nearby offsets rather than a full swath-footprint polygon.
    r = _REGIONS.get(region) or _REGIONS["australia"]
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
    # samples are nowhere near the region. A point can only pass any of the
    # nine tests if it falls inside the land bounding box widened by the
    # largest offset applied, so reject the rest with cheap array compares
    # before running any polygon test. This is a superset of the true
    # positives -- it can never discard a point the full test would keep.
    finite = np.isfinite(lon) & np.isfinite(lat)
    max_dlon = float(np.nanmax(deg_lon)) if finite.any() else 0.0
    candidate = (
        finite
        & (lon >= r.lon_min - max_dlon) & (lon <= r.lon_max + max_dlon)
        & (lat >= r.lat_min - deg_lat) & (lat <= r.lat_max + deg_lat)
    )
    if not candidate.any():
        return out

    clon = lon[candidate]
    clat = lat[candidate]
    cdlon = deg_lon[candidate]

    hit = np.zeros(clon.shape[0], dtype=bool)
    for sx, sy in _OFFSETS:
        hit |= r.contains_xy(clon + sx * cdlon, clat + sy * deg_lat)

    out[candidate] = hit
    return out


def footprint_intersects_australia(df, swath_km, lon_col="Longitude", lat_col="Latitude"):
    """Kept for every existing call site -- identical behaviour to before,
    now implemented as the "australia" case of footprint_intersects_region."""
    return footprint_intersects_region(df, swath_km, region="australia", lon_col=lon_col, lat_col=lat_col)
