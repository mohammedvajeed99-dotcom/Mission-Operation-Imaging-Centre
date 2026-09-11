"""Scene product generation: telemetry -> footprint -> imagery -> sensor -> product.

Each generated product is a directory of files under data/products/<scene id>:

    <scene_id>.tif        GeoTIFF, 4-band uint16 DN, georeferenced EPSG:4326
    <scene_id>.png        8-bit RGB preview
    <scene_id>.json       full metadata, including provenance

The GeoTIFF is the deliverable that matters for GIS use; the PNG exists so the
dashboard has something to show without a raster client.
"""

import json
from pathlib import Path

import numpy as np

from core.footprint import validate_wgs84
from core.imagery import ImageryUnavailable, find_source_scenes, read_footprint_mosaic
from core.pushbroom import simulate, to_rgb
from core.reference import build_reference_preview, reference_provenance
from core.time_utils import utc_iso
from core.solar import solar_position
from core.spectral import spectral_band_metadata
from core.validation import compare_scenes

BANDS = ("Red", "Green", "Blue", "Near Infrared")


def scene_id(scene):
    ts = scene["timestamp"]
    stamp = ts.strftime("%Y%m%dT%H%M%S") if hasattr(ts, "strftime") else str(ts)
    return f"{scene['satellite']}_{stamp}_orb{int(scene['orbit']):04d}"


def _write_geotiff(path, dn, bbox, band_names):
    import rasterio
    from rasterio.transform import from_bounds

    bands, rows, cols = dn.shape
    lon_min, lat_min, lon_max, lat_max = bbox
    transform = from_bounds(lon_min, lat_min, lon_max, lat_max, cols, rows)

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=rows,
        width=cols,
        count=bands,
        dtype="uint16",
        crs="EPSG:4326",
        transform=transform,
        compress="deflate",
        tiled=True,
    ) as dst:
        for i in range(bands):
            dst.write(dn[i], i + 1)
            dst.set_band_description(i + 1, band_names[i])


def generate_product(
    scene,
    out_dir,
    ground_speed_km_s=None,
    max_cloud=20.0,
    add_noise=True,
    max_pixels=2048,
    seed=None,
    progress_cb=None,
):
    """Produce one scene product. Returns its metadata dict.

    `scene` is a row from core.footprint.scene_grid.

    `progress_cb`, if given, is called as `progress_cb(stage, detail=None)`
    at each major step -- purely a status hook (see
    core.generation_progress) for a caller that wants to surface live
    progress to a UI; it never changes what is generated.
    """
    from core.classify import classify_scene
    from core.quality import assess_quality, estimate_cloud_cover, validate_product

    def report(stage, detail=None):
        if progress_cb is not None:
            try:
                progress_cb(stage, detail)
            except Exception:
                pass  # a status hook must never break a real generation

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sid = scene_id(scene)

    # Cap output size so a single request cannot pull an unbounded raster.
    rows = min(int(scene["heightPx"] or 0), max_pixels)
    cols = min(int(scene["widthPx"] or 0), max_pixels)
    if rows < 1 or cols < 1:
        raise ImageryUnavailable(f"Scene {sid} has degenerate pixel dimensions")

    coordinate_validation = validate_wgs84(scene["lat"], scene["lon"])

    report("searching", "Searching the Sentinel-2 archive for this footprint")
    items = find_source_scenes(scene["bbox"], scene["timestamp"], max_cloud=max_cloud)

    def on_mosaic_progress(index, total, coverage):
        report(
            "reading",
            f"Reading source imagery -- tile {index} of {total} candidates "
            f"({coverage * 100:.0f}% of the footprint covered so far)",
        )

    report("reading", f"Reading source imagery -- tile 1 of {len(items)} candidates")
    reflectance, provenance = read_footprint_mosaic(
        items, scene["bbox"], (rows, cols), bands=BANDS, on_progress=on_mosaic_progress
    )

    # Pixels with no source imagery anywhere in the mosaic. simulate() fills
    # these so blur and noise stay finite, but they are not real observations
    # and must be excluded from every statistic computed downstream.
    valid_mask = np.isfinite(reflectance).all(axis=0)

    solar = solar_position(scene["timestamp"], scene["lat"], scene["lon"])

    report("simulating", "Running the pushbroom sensor simulation")
    dn, sensor_report = simulate(
        reflectance,
        ground_speed_km_s=ground_speed_km_s,
        gsd_m=scene["gsdM"],
        add_noise=add_noise,
        seed=seed,
        band_names=BANDS,
        view_angle_deg=float(scene.get("viewAngleDeg", 0.0) or 0.0),
    )

    report("validating", "Assessing cloud cover, quality and land cover")
    cloud = estimate_cloud_cover(reflectance, BANDS)
    quality = assess_quality(dn, sensor_report, cloud, valid_mask=valid_mask)
    classification = classify_scene(reflectance, BANDS)

    tif_path = out_dir / f"{sid}.tif"
    png_path = out_dir / f"{sid}.png"
    reference_path = out_dir / f"{sid}.reference.jpg"
    json_path = out_dir / f"{sid}.json"

    report("writing", "Writing the GeoTIFF and preview images")
    _write_geotiff(tif_path, dn, scene["bbox"], BANDS)

    from PIL import Image

    rgb = to_rgb(dn, BANDS, valid_mask=valid_mask)
    Image.fromarray(rgb).save(png_path)

    # Real Earth reference: the same reflectance already fetched above,
    # rendered WITHOUT the sensor simulation. See core/reference.py for why
    # this -- not a second, different imagery source -- is the honest choice.
    reference_rgb = build_reference_preview(reflectance, valid_mask, BANDS)
    Image.fromarray(reference_rgb).save(reference_path, quality=92)
    reference_meta = reference_provenance(provenance, cols, rows)

    validation = validate_product(
        dn, rgb, valid_mask, cloud, quality,
        contributors=provenance.get("mosaicContributors"),
    )

    geospatial_validation = compare_scenes(
        reflectance, classification, dn, sensor_report,
        coordinate_validation, quality, validation, BANDS,
    )

    ts = scene["timestamp"]
    metadata = {
        "sceneId": sid,
        "acquisition": {
            "satellite": scene["satellite"],
            "simulatedTimestampUtc": utc_iso(ts) if hasattr(ts, "isoformat") else str(ts),
            "orbitNumber": int(scene["orbit"]),
            "subSatelliteLat": scene["lat"],
            "subSatelliteLon": scene["lon"],
            "altitudeKm": scene["altitudeKm"],
            "headingDeg": scene["headingDeg"],
            "groundSpeedKmS": ground_speed_km_s,
        },
        "geometry": {
            "gsdM": scene["gsdM"],
            "swathKm": scene["swathKm"],
            "alongTrackKm": scene["alongTrackKm"],
            "footprintLonLat": scene["footprint"],
            "bbox": list(scene["bbox"]),
            "crs": "EPSG:4326",
            "widthPx": cols,
            "heightPx": rows,
            "heightBasis": (
                "This product's heightPx is computed from this specific observation's "
                "real along-track pass distance divided by GSD (core.image_center.build_catalog), "
                "then capped for delivery -- it is not the camera model's fixed nominal "
                "frame-length constant (DEFAULT_CAMERA['Image Height (px)']), which is used "
                "only for fleet-wide scene-count estimates, not for sizing any individual product."
            ),
        },
        "sensor": sensor_report,
        "solar": solar,
        "cloud": cloud,
        "quality": quality,
        "validation": validation,
        "classification": classification,
        "coordinateValidation": coordinate_validation,
        "reference": reference_meta,
        "geospatialValidation": geospatial_validation,
        "spectral": spectral_band_metadata(BANDS),
        "provenance": {
            **provenance,
            "note": (
                "Synthetic product. Surface reflectance is real Sentinel-2 L2A "
                "imagery acquired at sourceDatetime; the acquisition geometry, "
                "timing and sensor response are simulated from real orbital "
                "telemetry and the mission camera configuration. "
                "simulatedTimestampUtc and sourceDatetime are different by "
                "design -- see core/imagery.py."
            ),
        },
        "files": {
            "geotiff": tif_path.name,
            "preview": png_path.name,
            "reference": reference_path.name,
            "metadata": json_path.name,
        },
    }

    json_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    return metadata
