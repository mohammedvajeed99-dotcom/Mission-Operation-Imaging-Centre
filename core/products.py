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

from core.imagery import ImageryUnavailable, find_source_scenes, read_footprint_mosaic
from core.pushbroom import simulate, to_rgb

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
):
    """Produce one scene product. Returns its metadata dict.

    `scene` is a row from core.footprint.scene_grid.
    """
    from core.classify import classify_scene
    from core.quality import assess_quality, estimate_cloud_cover

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sid = scene_id(scene)

    # Cap output size so a single request cannot pull an unbounded raster.
    rows = min(int(scene["heightPx"] or 0), max_pixels)
    cols = min(int(scene["widthPx"] or 0), max_pixels)
    if rows < 1 or cols < 1:
        raise ImageryUnavailable(f"Scene {sid} has degenerate pixel dimensions")

    items = find_source_scenes(scene["bbox"], scene["timestamp"], max_cloud=max_cloud)
    reflectance, provenance = read_footprint_mosaic(items, scene["bbox"], (rows, cols), bands=BANDS)

    # Pixels with no source imagery anywhere in the mosaic. simulate() fills
    # these so blur and noise stay finite, but they are not real observations
    # and must be excluded from every statistic computed downstream.
    valid_mask = np.isfinite(reflectance).all(axis=0)

    dn, sensor_report = simulate(
        reflectance,
        ground_speed_km_s=ground_speed_km_s,
        gsd_m=scene["gsdM"],
        add_noise=add_noise,
        seed=seed,
    )

    cloud = estimate_cloud_cover(reflectance, BANDS)
    quality = assess_quality(dn, sensor_report, cloud, valid_mask=valid_mask)
    classification = classify_scene(reflectance, BANDS)

    tif_path = out_dir / f"{sid}.tif"
    png_path = out_dir / f"{sid}.png"
    json_path = out_dir / f"{sid}.json"

    _write_geotiff(tif_path, dn, scene["bbox"], BANDS)

    from PIL import Image

    Image.fromarray(to_rgb(dn, BANDS)).save(png_path)

    ts = scene["timestamp"]
    metadata = {
        "sceneId": sid,
        "acquisition": {
            "satellite": scene["satellite"],
            "simulatedTimestampUtc": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
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
        },
        "sensor": sensor_report,
        "cloud": cloud,
        "quality": quality,
        "classification": classification,
        "provenance": {
            **provenance,
            "note": (
                "Synthetic product. Surface reflectance is real Sentinel-2 L2A "
                "imagery acquired at sourceDatetime; the acquisition geometry, "
                "timing and sensor response are simulated from GMAT telemetry "
                "and the mission camera configuration. simulatedTimestampUtc and "
                "sourceDatetime are different by design -- see core/imagery.py."
            ),
        },
        "files": {
            "geotiff": tif_path.name,
            "preview": png_path.name,
            "metadata": json_path.name,
        },
    }

    json_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    return metadata
