import numpy as np
import pandas as pd

# Coarse, ordered bounding-box region classification for situational awareness.
# This is an engineering approximation (like the Australia land-boundary polygon
# elsewhere in core/), not an authoritative GIS/administrative boundary dataset.
# Order matters: the first matching rule wins.
AOI = {"lonMin": 110.0, "lonMax": 160.0, "latMin": -40.0, "latMax": -10.0}

REGIONS = [
    ("Australia AOI (mission focus)", lambda lat, lon: (lon >= AOI["lonMin"]) & (lon <= AOI["lonMax"]) & (lat >= AOI["latMin"]) & (lat <= AOI["latMax"])),
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
REGION_NAMES = [name for name, _ in REGIONS] + [FALLBACK]


def classify_region(lat, lon):
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    out = np.full(lat.shape, FALLBACK, dtype=object)
    unresolved = np.ones(lat.shape, dtype=bool)
    for name, rule in REGIONS:
        hit = unresolved & rule(lat, lon)
        out[hit] = name
        unresolved &= ~hit
    return out


def build_global_coverage(state_df):
    """
    Per-satellite breakdown of where the constellation's sub-satellite point
    passes over the globe, independent of whether the sensor is powered ON.
    Demonstrates full global reach while the mission intentionally gates
    payload power to the Australia AOI (see K2 / K6 / K7).
    """
    df = state_df.copy()
    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
    df = df.dropna(subset=["Satellite Name", "Latitude", "Longitude"])
    if df.empty:
        return [], {}, []

    df["Region"] = classify_region(df["Latitude"].to_numpy(), df["Longitude"].to_numpy())
    df["In AOI"] = df["Region"] == REGION_NAMES[0]

    per_sat = []
    for sat, grp in df.groupby("Satellite Name"):
        total = len(grp)
        counts = grp["Region"].value_counts()
        regions = {name: float(100.0 * counts.get(name, 0) / total) for name in REGION_NAMES}
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
            "aoiSharePercent": regions[REGION_NAMES[0]],
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
        for name in REGION_NAMES
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
