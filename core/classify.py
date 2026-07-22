"""Land-cover classification of generated scenes.

This uses spectral indices with published thresholds rather than a learned
model. That is a deliberate choice: a CNN would need training data, weights,
and a GPU dependency, and its output over a synthetic scene would be
unverifiable. Index thresholds (NDVI, NDWI, NDBI-substitutes) are standard
remote-sensing practice, run in milliseconds, and every classification decision
can be traced to a number in the metadata.

Classes: water, vegetation, bare/arid, urban/built, cloud.
"""

import numpy as np

CLASSES = ("water", "vegetation", "bare", "urban", "cloud")


def _index(a, b):
    """Normalised difference (a - b) / (a + b), NaN-safe."""
    num = a - b
    den = a + b
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(np.abs(den) > 1e-6, num / den, np.nan)
    return out


def classify_scene(reflectance, band_names):
    """Per-pixel classification collapsed to class fractions for the scene.

    Returns fractions, the dominant class, and the index statistics behind them.
    """
    idx = {b: i for i, b in enumerate(band_names)}
    required = ("Red", "Green", "Blue", "Near Infrared")
    missing = [b for b in required if b not in idx]
    if missing:
        return {"available": False, "reason": f"missing bands: {missing}"}

    red = reflectance[idx["Red"]]
    green = reflectance[idx["Green"]]
    blue = reflectance[idx["Blue"]]
    nir = reflectance[idx["Near Infrared"]]

    valid = np.isfinite(red) & np.isfinite(green) & np.isfinite(blue) & np.isfinite(nir)
    if not valid.any():
        return {"available": False, "reason": "no valid pixels"}

    ndvi = _index(nir, red)      # vegetation
    ndwi = _index(green, nir)    # open water
    visible = np.stack([red, green, blue])
    brightness = np.nanmean(visible, axis=0)
    spread = np.nanmax(visible, axis=0) - np.nanmin(visible, axis=0)

    # Order matters: each test claims pixels the later tests no longer see.
    labels = np.full(red.shape, -1, dtype="int8")
    unclaimed = valid.copy()

    def claim(mask, class_index):
        take = unclaimed & mask
        labels[take] = class_index
        unclaimed[take] = False

    claim((brightness > 0.28) & (spread < 0.08), CLASSES.index("cloud"))
    claim(ndwi > 0.2, CLASSES.index("water"))
    claim(ndvi > 0.35, CLASSES.index("vegetation"))
    # Built surfaces: moderate brightness, low vegetation, grey-ish.
    claim((ndvi < 0.2) & (brightness > 0.15) & (spread < 0.12), CLASSES.index("urban"))
    claim(np.ones_like(labels, dtype=bool), CLASSES.index("bare"))

    total = int(valid.sum())
    fractions = {
        name: round(100.0 * float((labels == i).sum()) / total, 2)
        for i, name in enumerate(CLASSES)
    }
    dominant = max(fractions, key=fractions.get)

    return {
        "available": True,
        "method": "spectral-index-thresholds",
        "classFractionsPercent": fractions,
        "dominantClass": dominant,
        "indices": {
            "meanNdvi": round(float(np.nanmean(ndvi[valid])), 4),
            "meanNdwi": round(float(np.nanmean(ndwi[valid])), 4),
            "meanBrightness": round(float(np.nanmean(brightness[valid])), 4),
        },
        "thresholds": {
            "cloud": "brightness > 0.28 and spread < 0.08",
            "water": "NDWI > 0.2",
            "vegetation": "NDVI > 0.35",
            "urban": "NDVI < 0.2 and brightness > 0.15 and spread < 0.12",
            "bare": "remaining valid pixels",
        },
        "caveat": (
            "Index-threshold classification, not a trained classifier. "
            "Thresholds are standard published values and are not tuned to "
            "Australian land cover specifically."
        ),
    }


def mission_intelligence(products):
    """Roll per-scene classifications up into a mission-level summary.

    `products` is a list of product metadata dicts from core.products.
    """
    usable = [p for p in products if p.get("classification", {}).get("available")]
    if not usable:
        return {"scenes": 0, "note": "no classified scenes"}

    totals = {c: 0.0 for c in CLASSES}
    for p in usable:
        for c, v in p["classification"]["classFractionsPercent"].items():
            totals[c] += v
    mean_fractions = {c: round(v / len(usable), 2) for c, v in totals.items()}

    qualities = [p["quality"]["score"] for p in usable if p.get("quality")]
    clouds = [
        p["cloud"]["cloudCoverPercent"]
        for p in usable
        if p.get("cloud", {}).get("cloudCoverPercent") is not None
    ]
    sats = sorted({p["acquisition"]["satellite"] for p in usable})

    return {
        "scenes": len(usable),
        "satellites": sats,
        "meanClassFractionsPercent": mean_fractions,
        "dominantClass": max(mean_fractions, key=mean_fractions.get),
        "meanQualityScore": round(float(np.mean(qualities)), 1) if qualities else None,
        "meanCloudCoverPercent": round(float(np.mean(clouds)), 1) if clouds else None,
        "usableScenes": sum(1 for p in usable if p.get("quality", {}).get("score", 0) >= 65),
    }
