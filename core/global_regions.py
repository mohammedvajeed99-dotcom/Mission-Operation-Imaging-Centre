import numpy as np
import pandas as pd
from core.regions import AOI_BOXES, REGION_LABELS

# Coarse, ordered bounding-box region classification for situational awareness.
# This is an engineering approximation (like the land-boundary polygons
# elsewhere in core/), not an authoritative GIS/administrative boundary dataset.
# Order matters: the first matching rule wins.

# Kept for backward compatibility with any external caller expecting the
# original Australia-only AOI box under this name.
AOI = AOI_BOXES["australia"]

_BASE_REGIONS = [
    ("Oceania", lambda lat, lon: (lon >= 110) & (lon <= 180) & (lat >= -50) & (lat < 0)),
    ("Southeast Asia", lambda lat, lon: (lon >= 92) & (lon <= 141) & (lat >= -11) & (lat <= 25)),
    ("East Asia", lambda lat, lon: (lon >= 100) & (lon <= 150) & (lat > 25) & (lat <= 50)),
    ("South Asia", lambda lat, lon: (lon >= 60) & (lon < 100) & (lat >= 5) & (lat <= 38)),
    ("Middle East", lambda lat, lon: (lon >= 25) & (lon < 63) & (lat >= 10) & (lat <= 42)),
    ("Africa", lambda lat, lon: (lon >= -20) & (lon < 52) & (lat >= -37) & (lat <= 38)),
    ("Europe", lambda lat, lon: (lon >= -12) & (lon < 40) & (lat > 36) & (lat <= 50)),
    ("North America", lambda lat, lon: (lon >= -170) & (lon < -50) & (lat >= 14) & (lat <= 50)),
    ("South America", lambda lat, lon: (lon >= -85) & (lon < -33) & (lat >= -50) & (lat < 14)),
    ("Pacific Ocean", lambda lat, lon: (lon >= 140) | (lon < -80)),
    ("Atlantic Ocean", lambda lat, lon: (lon >= -60) & (lon < -10)),
    ("Indian Ocean", lambda lat, lon: (lon >= 40) & (lon < 100)),
]
FALLBACK = "Open Ocean / Transit"


def _aoi_rule_name(region):
    label = REGION_LABELS.get(region, REGION_LABELS["australia"])
    return f"{label} AOI (mission focus)"


def _regions_for(region):
    box = AOI_BOXES.get(region) or AOI_BOXES["australia"]
    aoi_rule = (
        _aoi_rule_name(region),
        lambda lat, lon: (lon >= box["lonMin"]) & (lon <= box["lonMax"]) & (lat >= box["latMin"]) & (lat <= box["latMax"]),
    )
    return [aoi_rule] + _BASE_REGIONS


def region_names_for(region):
    return [name for name, _ in _regions_for(region)] + [FALLBACK]


def classify_region(lat, lon, region="australia"):
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    out = np.full(lat.shape, FALLBACK, dtype=object)
    unresolved = np.ones(lat.shape, dtype=bool)
    for name, rule in _regions_for(region):
        hit = unresolved & rule(lat, lon)
        out[hit] = name
        unresolved &= ~hit
    return out


def build_global_coverage(state_df, region="australia"):
    """
    Per-satellite breakdown of where the constellation's sub-satellite point
    passes over the globe, independent of whether the sensor is powered ON.
    Demonstrates full global reach while the mission intentionally gates
    payload power to its AOI (see K2 / K6 / K7).
    """
    df = state_df.copy()
    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
    df = df.dropna(subset=["Satellite Name", "Latitude", "Longitude"])
    if df.empty:
        return [], {}, []

    region_names = region_names_for(region)
    df["Region"] = classify_region(df["Latitude"].to_numpy(), df["Longitude"].to_numpy(), region=region)
    df["In AOI"] = df["Region"] == region_names[0]

    per_sat = []
    for sat, grp in df.groupby("Satellite Name"):
        total = len(grp)
        counts = grp["Region"].value_counts()
        regions = {name: float(100.0 * counts.get(name, 0) / total) for name in region_names}
        top_regions = sorted(
            ((name, pct) for name, pct in regions.items() if pct > 0),
            key=lambda kv: kv[1],
            reverse=True,
        )
        per_sat.append({
            "satellite": str(sat),
            "samples": int(total),
            "minLatitude": float(grp["Latitude"].min()),
            "maxLatitude": float(grp["Latitude"].max()),
            "aoiSharePercent": regions[region_names[0]],
            "regionsVisited": int(sum(1 for pct in regions.values() if pct > 0)),
            "topRegion": top_regions[0][0] if top_regions else FALLBACK,
            "topRegionPercent": top_regions[0][1] if top_regions else 0.0,
            "regions": regions,
        })
    per_sat.sort(key=lambda r: r["satellite"])

    total_samples = len(df)
    fleet_counts = df["Region"].value_counts()
    fleet_regions = [
        {"region": name, "percent": float(100.0 * fleet_counts.get(name, 0) / total_samples), "samples": int(fleet_counts.get(name, 0))}
        for name in region_names
    ]
    fleet_regions = [r for r in fleet_regions if r["samples"] > 0]
    fleet_regions.sort(key=lambda r: r["percent"], reverse=True)

    fleet = {
        "satelliteCount": int(df["Satellite Name"].nunique()),
        "minLatitude": float(df["Latitude"].min()),
        "maxLatitude": float(df["Latitude"].max()),
        "regionsTraversed": int(len(fleet_regions)),
        "aoiSharePercent": float(100.0 * df["In AOI"].sum() / total_samples),
        "globalSharePercent": float(100.0 * (total_samples - int(df["In AOI"].sum())) / total_samples),
    }
    return per_sat, fleet, fleet_regions
