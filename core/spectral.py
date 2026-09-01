"""Spectral band definitions for the ASC_074 imaging pipeline.

ASC_074's own spectral response has never been specified anywhere in this
project -- only the band *names* Red/Green/Blue/Near Infrared exist
(core.products.BANDS), with no center wavelength or bandwidth attached to
them. The pipeline reads real Sentinel-2 L2A pixel data for each of those
names directly (core.imagery.BAND_ASSETS: Blue->B02, Green->B03, Red->B04,
Near Infrared->B08) and simulates ASC_074's sensor chain on top of it.

That is a real, specific assumption -- not a vague one -- and this module
states it precisely rather than leaving it implicit: the wavelength and
bandwidth figures below are Sentinel-2's own published MSI specification
(ESA, real hardware numbers, not invented), used here as a PROXY for
ASC_074's spectral response because no ASC_074 spectral specification exists
in any mission file. Using Sentinel-2's real numbers to describe what data is
actually feeding the pipeline is honest; it does not imply ASC_074's actual
sensor matches them.
"""

# Sentinel-2A MSI central wavelength and full-width-half-maximum bandwidth,
# in nanometres, for the four bands this pipeline uses. Source: ESA Sentinel-2
# User Handbook / MSI spectral response function summary (published hardware
# specification, not measured or fitted here). Sentinel-2B's equivalents
# differ by under 1 nm for every band in this set and are not tracked
# separately, since this pipeline does not distinguish which satellite
# (S2A/S2B/S2C) supplied a given granule for rendering purposes.
SPECTRAL_BANDS = {
    "Blue": {
        "centerWavelengthNm": 492.4,
        "bandwidthNm": 66,
        "sentinel2Band": "B02",
    },
    "Green": {
        "centerWavelengthNm": 559.8,
        "bandwidthNm": 36,
        "sentinel2Band": "B03",
    },
    "Red": {
        "centerWavelengthNm": 664.6,
        "bandwidthNm": 31,
        "sentinel2Band": "B04",
    },
    "Near Infrared": {
        "centerWavelengthNm": 832.8,
        "bandwidthNm": 106,
        "sentinel2Band": "B08",
    },
}

SPECTRAL_PROXY_DISCLOSURE = (
    "ASC_074's own spectral response (center wavelength, bandwidth, quantum "
    "efficiency) has not been specified anywhere in this project. The values "
    "here are Sentinel-2's own published MSI band specification, used as a "
    "PROXY because the pipeline reads real Sentinel-2 pixel data for each of "
    "these band names. This describes the real characteristics of the "
    "source data, not a measurement or specification of ASC_074's actual "
    "sensor -- it does not demonstrate that ASC_074 has an identical "
    "spectral response, only that its simulated bands are currently modelled "
    "as if it did."
)


def spectral_band_metadata(band_names=("Red", "Green", "Blue", "Near Infrared")):
    """Per-band spectral definitions plus the proxy disclosure, for embedding
    in generated-product metadata. `band_names` lets a caller report only the
    bands actually used, in their own order, rather than assuming all four.
    """
    return {
        "bands": {b: dict(SPECTRAL_BANDS[b]) for b in band_names if b in SPECTRAL_BANDS},
        "source": "Sentinel-2 MSI published specification (ESA), used as an assumed proxy for ASC_074",
        "disclosure": SPECTRAL_PROXY_DISCLOSURE,
    }
