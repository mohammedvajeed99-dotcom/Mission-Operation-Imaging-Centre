"""Pushbroom sensor simulation.

Takes surface reflectance sampled at the camera's ground sample distance and
degrades it through the physical effects that separate a real detector's output
from a perfect sample of the ground:

  1. Resolution loss   -- source imagery is 10 m native; a camera with a coarser
                          GSD cannot resolve more than its own optics allow.
  2. Optical MTF       -- diffraction and aberration blur, as a Gaussian PSF.
  3. Along-track smear -- the ground moves during the line integration time,
                          smearing along-track only. This is the effect that
                          makes a pushbroom a pushbroom.
  4. Detector noise    -- shot noise (signal-dependent) and read noise (not).
  5. Quantisation      -- continuous radiance to discrete digital numbers.

Every parameter is derived from the configured camera model or passed in
explicitly. Where a value cannot be derived from configuration -- integration
time and read noise have no counterpart in the mission spreadsheet -- the
default is documented as a representative small-satellite figure and reported
in the metadata as such, so no fabricated number is silently presented as
mission data.
"""

import numpy as np

# Representative values for a smallsat pushbroom imager. These are NOT from the
# mission configuration; they are labelled "assumed" wherever they surface.
DEFAULT_LINE_INTEGRATION_MS = 1.5
DEFAULT_READ_NOISE_ELECTRONS = 35.0
DEFAULT_FULL_WELL_ELECTRONS = 22000.0
DEFAULT_MTF_SIGMA_PX = 0.6
DEFAULT_BIT_DEPTH = 12


def _gaussian_blur(plane, sigma_px):
    """Separable Gaussian blur. Written out rather than pulled from scipy to
    keep the dependency set to what the API already needs."""
    if sigma_px <= 0:
        return plane
    radius = max(int(np.ceil(3 * sigma_px)), 1)
    x = np.arange(-radius, radius + 1, dtype="float32")
    kernel = np.exp(-(x ** 2) / (2 * sigma_px ** 2))
    kernel /= kernel.sum()

    padded = np.pad(plane, radius, mode="edge")
    out = np.empty_like(plane)
    # Horizontal then vertical.
    tmp = np.zeros_like(padded)
    for i, w in enumerate(kernel):
        tmp += w * np.roll(padded, i - radius, axis=1)
    acc = np.zeros_like(padded)
    for i, w in enumerate(kernel):
        acc += w * np.roll(tmp, i - radius, axis=0)
    out[:] = acc[radius:-radius, radius:-radius]
    return out


def _motion_smear(plane, smear_px):
    """Uniform box smear along the along-track (row) axis."""
    if smear_px < 1.0:
        return plane
    n = int(round(smear_px))
    kernel = np.ones(n, dtype="float32") / n
    padded = np.pad(plane, ((n, n), (0, 0)), mode="edge")
    acc = np.zeros_like(padded)
    for i, w in enumerate(kernel):
        acc += w * np.roll(padded, i - n // 2, axis=0)
    return acc[n:-n, :]


def smear_pixels(ground_speed_km_s, gsd_m, integration_ms):
    """How many pixels the ground moves during one line integration."""
    if not (ground_speed_km_s and gsd_m):
        return 0.0
    metres = float(ground_speed_km_s) * 1000.0 * (float(integration_ms) / 1000.0)
    return metres / float(gsd_m)


def simulate(
    reflectance,
    ground_speed_km_s=None,
    gsd_m=None,
    integration_ms=DEFAULT_LINE_INTEGRATION_MS,
    mtf_sigma_px=DEFAULT_MTF_SIGMA_PX,
    read_noise_e=DEFAULT_READ_NOISE_ELECTRONS,
    full_well_e=DEFAULT_FULL_WELL_ELECTRONS,
    bit_depth=DEFAULT_BIT_DEPTH,
    add_noise=True,
    seed=None,
):
    """Run reflectance (bands, rows, cols) through the sensor chain.

    Returns (digital_numbers, report). DN is uint16 at the requested bit depth.
    """
    rng = np.random.default_rng(seed)
    arr = np.asarray(reflectance, dtype="float32")
    if arr.ndim != 3:
        raise ValueError(f"Expected (bands, rows, cols), got shape {arr.shape}")

    # Fill source gaps with the band median so blur and noise do not propagate NaN.
    filled = arr.copy()
    for b in range(filled.shape[0]):
        plane = filled[b]
        if np.isnan(plane).any():
            med = np.nanmedian(plane)
            plane[np.isnan(plane)] = 0.0 if np.isnan(med) else med

    smear_px = smear_pixels(ground_speed_km_s, gsd_m, integration_ms)

    out = np.empty_like(filled)
    for b in range(filled.shape[0]):
        plane = _gaussian_blur(filled[b], mtf_sigma_px)
        plane = _motion_smear(plane, smear_px)
        out[b] = plane

    # Reflectance -> electrons -> noise -> DN. Reflectance of 1.0 is taken as
    # full well, which is the standard well-filled-at-saturation convention.
    electrons = np.clip(out, 0.0, None) * full_well_e
    if add_noise:
        electrons = rng.poisson(np.clip(electrons, 0, None)).astype("float32")
        electrons += rng.normal(0.0, read_noise_e, size=electrons.shape).astype("float32")

    max_dn = (2 ** int(bit_depth)) - 1
    dn = np.clip(electrons / full_well_e, 0.0, 1.0) * max_dn
    dn = np.rint(dn).astype("uint16")

    signal = float(np.nanmean(electrons)) if electrons.size else 0.0
    noise = float(np.sqrt(max(signal, 0.0) + read_noise_e ** 2)) if add_noise else 0.0

    report = {
        "mtfSigmaPx": float(mtf_sigma_px),
        "alongTrackSmearPx": float(smear_px),
        "lineIntegrationMs": float(integration_ms),
        "readNoiseElectrons": float(read_noise_e),
        "fullWellElectrons": float(full_well_e),
        "bitDepth": int(bit_depth),
        "noiseApplied": bool(add_noise),
        "estimatedSnr": (signal / noise) if noise > 0 else None,
        "parameterProvenance": (
            "Integration time, read noise, full well, and MTF sigma are "
            "representative smallsat values, not mission-configured data. "
            "GSD, swath and ground speed are derived from mission configuration "
            "and GMAT telemetry."
        ),
    }
    return dn, report


def to_rgb(dn, band_order=("Red", "Green", "Blue", "Near Infrared"), stretch=(2, 98)):
    """8-bit RGB preview from simulated DN, percentile-stretched per band."""
    idx = [band_order.index(b) for b in ("Red", "Green", "Blue") if b in band_order]
    if len(idx) < 3:
        idx = [0, 1, 2]
    rgb = np.stack([dn[i].astype("float32") for i in idx], axis=-1)
    for c in range(3):
        chan = rgb[..., c]
        lo, hi = np.percentile(chan, stretch)
        rgb[..., c] = np.clip((chan - lo) / (hi - lo) if hi > lo else chan, 0, 1)
    return (rgb * 255).astype("uint8")
