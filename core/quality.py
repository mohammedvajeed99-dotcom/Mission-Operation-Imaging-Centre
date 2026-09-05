"""Cloud-cover estimation and image quality assessment.

Cloud detection here is a brightness/whiteness test on surface reflectance, not
a trained cloud mask. Sentinel-2 L2A ships a scene classification layer (SCL)
that is far more reliable, and `estimate_cloud_cover_scl` uses it when the
source scene's SCL asset is available; the spectral test is the fallback. Which
method produced a given number is always reported alongside it.
"""

import numpy as np

# SCL class codes that count as cloud or cloud-adjacent.
SCL_CLOUD_CLASSES = {3: "cloud shadow", 8: "cloud medium probability",
                     9: "cloud high probability", 10: "thin cirrus"}


def estimate_cloud_cover(reflectance, band_names):
    """Fraction of the footprint that reads as cloud, from a spectral test.

    Clouds are bright across the visible bands and spectrally flat (low
    saturation). Bright desert and salt pan defeat brightness-only tests, which
    matters over Australia specifically, so flatness is required as well.
    """
    idx = {b: i for i, b in enumerate(band_names)}
    needed = ("Red", "Green", "Blue")
    if not all(b in idx for b in needed):
        return {"cloudCoverPercent": None, "method": "unavailable",
                "reason": "scene lacks visible bands"}

    r = reflectance[idx["Red"]]
    g = reflectance[idx["Green"]]
    b = reflectance[idx["Blue"]]
    valid = np.isfinite(r) & np.isfinite(g) & np.isfinite(b)
    if not valid.any():
        return {"cloudCoverPercent": None, "method": "unavailable",
                "reason": "no valid pixels"}

    stack = np.stack([r, g, b])
    brightness = np.nanmean(stack, axis=0)
    spread = np.nanmax(stack, axis=0) - np.nanmin(stack, axis=0)

    # Bright AND spectrally flat. Thresholds are in surface reflectance units.
    cloudy = valid & (brightness > 0.28) & (spread < 0.08)
    pct = 100.0 * float(cloudy[valid].mean())

    return {
        "cloudCoverPercent": pct,
        "method": "spectral-brightness-flatness",
        "thresholds": {"brightness": 0.28, "spread": 0.08},
        "caveat": (
            "Heuristic test on surface reflectance, not a trained cloud mask. "
            "Bright arid surfaces can register as false positives."
        ),
    }


def estimate_cloud_cover_scl(item, bbox, out_shape):
    """Cloud fraction from the Sentinel-2 scene classification layer, when present."""
    if "scl" not in getattr(item, "assets", {}):
        return None

    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    with rasterio.open(item.assets["scl"].href) as src:
        left, bottom, right, top = transform_bounds("EPSG:4326", src.crs, *bbox, densify_pts=21)
        window = from_bounds(left, bottom, right, top, transform=src.transform)
        scl = src.read(
            1, window=window, out_shape=out_shape,
            resampling=Resampling.nearest, boundless=True, fill_value=0,
        )

    total = scl.size
    if not total:
        return None
    cloud = np.isin(scl, list(SCL_CLOUD_CLASSES)).sum()
    return {
        "cloudCoverPercent": 100.0 * float(cloud) / total,
        "method": "sentinel2-scl",
        "classesCounted": SCL_CLOUD_CLASSES,
    }


OK = "ok"
QUALITY_LIMITED = "quality_limited"
UNUSABLE = "unusable"


def validate_product(dn, rgb, valid_mask, cloud, quality, contributors=None):
    """Gate a generated product before it is presented as a successful observation.

    A frame that is mostly cloud, mostly gap, clipped at either end of the
    range, or visibly seamed is still a real output of the pipeline -- but it
    is not a usable observation, and showing it as a clean success would
    misrepresent the mission's imaging performance. Each check returns a
    reason so the operator can see exactly why a product was downgraded.
    """
    checks = []

    def fail(level, code, detail):
        checks.append({"level": level, "check": code, "detail": detail})

    arr = np.asarray(dn)
    if arr.ndim != 3 or min(arr.shape[1:]) < 16:
        fail(UNUSABLE, "dimensions", f"Raster shape {tuple(arr.shape)} is not a usable image")
    if not np.isfinite(np.asarray(rgb, dtype="float32")).all():
        fail(UNUSABLE, "corrupt", "Preview contains non-finite values")

    valid_pct = 100.0 * float(np.asarray(valid_mask).mean()) if valid_mask is not None else 100.0
    if valid_pct < 50.0:
        fail(UNUSABLE, "coverage", f"Only {valid_pct:.1f}% of the frame is backed by source imagery")
    elif valid_pct < 90.0:
        fail(QUALITY_LIMITED, "coverage", f"{100.0 - valid_pct:.1f}% of the frame has no source imagery")

    # Tone checks run on the delivered preview, over real pixels only.
    prev = np.asarray(rgb)
    sel = prev[np.asarray(valid_mask)] if valid_mask is not None and np.asarray(valid_mask).any() else prev.reshape(-1, prev.shape[-1])
    if sel.size:
        black_pct = 100.0 * float((sel.max(axis=-1) <= 2).mean())
        white_pct = 100.0 * float((sel.min(axis=-1) >= 253).mean())
        if black_pct > 5.0:
            fail(QUALITY_LIMITED, "crushedShadows", f"{black_pct:.1f}% of pixels are effectively pure black")
        if white_pct > 5.0:
            fail(QUALITY_LIMITED, "clippedHighlights", f"{white_pct:.1f}% of pixels are clipped white")
        # A frame with almost no tonal spread is not a usable observation.
        if float(sel.std()) < 4.0:
            fail(UNUSABLE, "noContrast", "Preview has almost no tonal variation")
    else:
        black_pct = white_pct = 0.0

    cloud_pct = (cloud or {}).get("cloudCoverPercent")
    if cloud_pct is not None:
        if cloud_pct >= 80.0:
            fail(UNUSABLE, "cloud", f"Cloud cover {cloud_pct:.0f}% leaves no usable ground")
        elif cloud_pct >= 40.0:
            fail(QUALITY_LIMITED, "cloud", f"Cloud cover {cloud_pct:.0f}% obscures much of the footprint")

    score = (quality or {}).get("score")
    if score is not None and score < 45.0:
        fail(QUALITY_LIMITED, "qualityScore", f"Composite quality score {score:.0f}/100")

    # Residual seam check: granules are radiometrically matched during
    # mosaicking, so a large remaining gain means the join could not be fully
    # reconciled. core.imagery.read_footprint_mosaic now feathers that join
    # over a ~12px band (core.imagery._feather_seam) rather than cutting over
    # in one pixel, which removes the hard visible line even when the gain
    # was clamped -- but the two granules still disagree radiometrically by
    # more than a straight gain/offset can correct, so this is flagged as a
    # real, disclosed limitation rather than treated as fixed.
    #
    # Only the visible bands (0-2) can produce a seam a viewer actually sees,
    # so only those downgrade the product. A large near-infrared gain is worth
    # recording for anyone working with the GeoTIFF's NIR band, but it does
    # not make the delivered image unusable and must not be reported as if it
    # did -- the preview is built from RGB alone.
    VISIBLE_BANDS = (0, 1, 2)
    for c in (contributors or []):
        for band in (c.get("radiometricMatch") or []):
            gain = band.get("gain")
            if gain is None or not (gain <= 0.62 or gain >= 1.55):
                continue
            if band.get("band") in VISIBLE_BANDS:
                fail(QUALITY_LIMITED, "seam",
                     f"Granule {c.get('sceneId')} needed an extreme radiometric gain ({gain}) "
                     f"in a visible band; the join is feathered so it should not read as a hard "
                     f"line, but the two granules still disagree radiometrically beyond what "
                     f"the gain correction could reconcile")
                break
            fail("note", "seamNonVisible",
                 f"Granule {c.get('sceneId')} needed an extreme gain ({gain}) in a non-visible "
                 f"band (index {band.get('band')}); affects the GeoTIFF's infrared band only, "
                 f"not the delivered preview")

    # "note" entries are informational and never downgrade the product.
    downgrades = [c for c in checks if c["level"] in (UNUSABLE, QUALITY_LIMITED)]
    if any(c["level"] == UNUSABLE for c in downgrades):
        status, label = UNUSABLE, "Unusable — Quality Constraints"
    elif downgrades:
        status, label = QUALITY_LIMITED, "Generated — Quality Limited"
    else:
        status, label = OK, "Generated"

    return {
        "status": status,
        "label": label,
        "issues": checks,
        "measurements": {
            "validDataPercent": round(valid_pct, 2),
            "pureBlackPercent": round(black_pct, 3),
            "clippedWhitePercent": round(white_pct, 3),
            "cloudCoverPercent": round(cloud_pct, 2) if cloud_pct is not None else None,
        },
    }


def assess_quality(dn, sensor_report, cloud, valid_mask=None):
    """Overall usability score for a generated scene.

    Combines radiometric health (saturation, dynamic range use), sharpness
    (smear), cloud obstruction and source-data completeness into a 0-100 score,
    with the contributing factors itemised so the number is never a black box.

    `valid_mask` marks pixels backed by real source imagery. Where a footprint
    straddles a granule boundary the mosaic may not fill completely; those
    pixels are synthetic fill and are excluded from all radiometric statistics
    rather than being scored as if they were observations.
    """
    arr = dn.astype("float32")
    bit_depth = int(sensor_report.get("bitDepth", 12))
    max_dn = (2 ** bit_depth) - 1

    if valid_mask is not None:
        coverage = float(np.asarray(valid_mask).mean())
        sel = arr[:, valid_mask] if arr.ndim == 3 else arr[valid_mask]
    else:
        coverage = 1.0
        sel = arr

    if sel.size == 0:
        return {"score": 0.0, "grade": "unusable",
                "reason": "no pixels backed by source imagery",
                "measurements": {"validDataPercent": 0.0}}

    saturated = float((sel >= max_dn).mean()) * 100.0
    dark = float((sel <= 0).mean()) * 100.0
    used_range = float(np.percentile(sel, 99) - np.percentile(sel, 1)) / max_dn * 100.0

    smear = float(sensor_report.get("alongTrackSmearPx", 0.0))
    snr = sensor_report.get("estimatedSnr")
    cloud_pct = cloud.get("cloudCoverPercent")

    # Each factor scores 0-100; the total is their weighted mean.
    factors = {
        "dynamicRange": max(0.0, min(used_range, 100.0)),
        "unsaturated": max(0.0, 100.0 - saturated * 5.0),
        "notUnderexposed": max(0.0, 100.0 - dark * 5.0),
        "sharpness": max(0.0, 100.0 - smear * 20.0),
        "cloudFree": (100.0 - cloud_pct) if cloud_pct is not None else 100.0,
        "dataComplete": coverage * 100.0,
    }
    weights = {"dynamicRange": 0.15, "unsaturated": 0.1, "notUnderexposed": 0.1,
               "sharpness": 0.2, "cloudFree": 0.2, "dataComplete": 0.25}
    score = sum(factors[k] * weights[k] for k in factors)

    if score >= 80:
        grade = "excellent"
    elif score >= 65:
        grade = "good"
    elif score >= 45:
        grade = "marginal"
    else:
        grade = "poor"

    return {
        "score": round(score, 1),
        "grade": grade,
        "factors": {k: round(v, 1) for k, v in factors.items()},
        "weights": weights,
        "measurements": {
            "saturatedPixelPercent": round(saturated, 3),
            "zeroPixelPercent": round(dark, 3),
            "usedDynamicRangePercent": round(used_range, 1),
            "alongTrackSmearPx": round(smear, 2),
            "estimatedSnr": round(snr, 1) if snr else None,
            "validDataPercent": round(coverage * 100.0, 2),
        },
    }
