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

def _inside_polygon(lon, lat, polygon):
    path = Path(polygon)
    pts = list(zip(pd.to_numeric(lon, errors="coerce"), pd.to_numeric(lat, errors="coerce")))
    return path.contains_points(pts)

def australia_land_mask(df, lon_col="Longitude", lat_col="Latitude"):
    mainland = _inside_polygon(df[lon_col], df[lat_col], MAINLAND_AUSTRALIA)
    tas = _inside_polygon(df[lon_col], df[lat_col], TASMANIA)
    return mainland | tas

def footprint_intersects_australia(df, swath_km, lon_col="Longitude", lat_col="Latitude"):
    # Conservative operational trigger: sub-satellite point over Australia OR within
    # half-swath angular distance of the approximated land boundary.
    # For dashboard efficiency, expand the polygon test by checking nearby offsets.
    half = max(float(swath_km or 0)/2.0, 0.0)
    deg_lat = half / 111.0
    lat = pd.to_numeric(df[lat_col], errors="coerce")
    lon = pd.to_numeric(df[lon_col], errors="coerce")
    coslat = lat.abs().clip(upper=80).map(lambda x: max(__import__("math").cos(__import__("math").radians(x)), 0.2))
    deg_lon = deg_lat / coslat
    masks = australia_land_mask(df, lon_col, lat_col)
    for sx, sy in [(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]:
        shifted = df[[lon_col,lat_col]].copy()
        shifted[lon_col] = lon + sx*deg_lon
        shifted[lat_col] = lat + sy*deg_lat
        masks |= australia_land_mask(shifted, lon_col, lat_col)
    return masks
