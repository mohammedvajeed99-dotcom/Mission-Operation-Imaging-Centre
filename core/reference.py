"""Real Earth reference imagery for geospatial validation.

Every generated product is derived from real Sentinel-2 L2A surface
reflectance for the observation's true footprint -- the simulated preview is
not a random or invented image. What was missing was a way to *see* that: the
reflectance is fetched and immediately fed into the sensor simulation, so no
un-simulated render of it was ever saved or shown.

This module renders that reference view. It is deliberately a thin wrapper
around data `core.products.generate_product` already fetches -- rendering it
here costs no extra network request -- but is written behind a narrow
interface (`build_reference_preview`, `reference_provenance`) so a future,
genuinely different reference source (a different archive, or a manually
supplied file) could be substituted without callers changing. Nothing here
invents a second data source that does not exist in this project.
"""

import numpy as np

from core.pushbroom import to_rgb


def build_reference_preview(reflectance, valid_mask, band_order):
    """Render the pre-simulation reflectance through the same tone pipeline
    used for the simulated preview, so the two images are visually
    comparable (same stretch, same no-data treatment) rather than one being
    processed and the other raw.

    `reflectance` is the real Sentinel-2 array `generate_product` already
    read, before `simulate()` degrades it -- this is the actual Earth scene,
    not a placeholder.
    """
    # to_rgb expects DN-like values; reflectance is 0-1 surface reflectance,
    # so it is scaled the same way simulate() scales reflectance to
    # electrons before quantising, keeping the two renders on comparable
    # tonal footing without re-running any part of the sensor model.
    scaled = np.clip(np.asarray(reflectance, dtype="float32"), 0.0, None) * 4095.0
    return to_rgb(scaled, band_order, valid_mask=valid_mask)


def reference_provenance(provenance, delivered_width_px, delivered_height_px):
    """Metadata describing the reference image, honestly distinct from an
    ASC_074 acquisition.

    `provenance` is the dict `read_footprint_mosaic` already returns --
    reused, not recomputed, so the reference's stated source/date/resolution
    can never drift from what was actually read.
    """
    return {
        "source": provenance.get("sourceCollection", "sentinel-2-l2a"),
        "sourceSceneId": provenance.get("sourceSceneId"),
        "sourceDatetime": provenance.get("sourceDatetime"),
        "sourcePlatform": provenance.get("sourcePlatform"),
        "nativeGsdM": provenance.get("sourceNativeGsdM"),
        "deliveredWidthPx": delivered_width_px,
        "deliveredHeightPx": delivered_height_px,
        "provider": "pluggable: current implementation reuses the Sentinel-2 L2A "
                    "mosaic already fetched for this observation's footprint; a "
                    "different archive or a manually supplied reference image "
                    "could be substituted here without changing any caller",
        "note": (
            "This is real Earth imagery for the observation's true coordinates, "
            "rendered WITHOUT the ASC_074 sensor simulation -- it is a reference "
            "scene, not an ASC_074 acquisition and not a measurement of ASC_074's "
            "performance. Its acquisition date (sourceDatetime) differs from the "
            "product's simulated acquisition time by design; the two are not the "
            "same observation, only the same ground location."
        ),
    }
