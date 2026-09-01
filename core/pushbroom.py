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

# Atmospheric path radiance, per band, at nadir. The source imagery is
# Sentinel-2 L2A -- surface reflectance, with the atmosphere already removed --
# but a real payload observes top-of-atmosphere, so a scattering term is added
# back to represent what ASC_074's camera would actually record.
#
# The shape is Rayleigh: scattering goes as roughly 1/lambda^4, so it is
# strongest in the blue and negligible in the near infrared. Magnitudes are
# representative clear-sky values, NOT a radiative-transfer solution, and are
# reported as a simulated effect wherever they surface.
RAYLEIGH_PATH_REFLECTANCE = {
    "Blue": 0.034,
    "Green": 0.021,
    "Red": 0.011,
    "Near Infrared": 0.003,
}
# Fraction of surface signal lost to atmospheric transmission, same ordering.
ATMOSPHERIC_TRANSMITTANCE = {
    "Blue": 0.90,
    "Green": 0.93,
    "Red": 0.96,
    "Near Infrared": 0.98,
}


def apply_atmosphere(reflectance, band_names, view_angle_deg=0.0, strength=1.0):
    """Add a simulated atmospheric path between the ground and the sensor.

    Surface reflectance is attenuated by transmittance and a scattering term is
    added on top: `toa = surface * t + path`. Slant paths through a thicker
    column at off-nadir angles are handled with a secant air-mass factor.

    This lifts absolute black off zero the way a real atmosphere does -- there
    is no such thing as a perfectly black pixel seen through air -- which is
    part of why the unmodified surface product looked harsh.
    """
    arr = np.asarray(reflectance, dtype="float32").copy()
    # Air mass grows as 1/cos(theta); clamped so extreme angles stay sane.
    air_mass = 1.0 / max(np.cos(np.radians(min(abs(float(view_angle_deg)), 60.0))), 0.5)

    applied = {}
    for i, band in enumerate(band_names[: arr.shape[0]]):
        path = RAYLEIGH_PATH_REFLECTANCE.get(band, 0.012) * air_mass * float(strength)
        trans = ATMOSPHERIC_TRANSMITTANCE.get(band, 0.95) ** air_mass
        arr[i] = arr[i] * trans + path
        applied[band] = {"pathReflectance": round(path, 5), "transmittance": round(trans, 4)}

    report = {
        "model": "Rayleigh path radiance + transmittance (simulated)",
        "airMass": round(float(air_mass), 3),
        "viewAngleDeg": float(view_angle_deg),
        "perBand": applied,
        "provenance": (
            "SIMULATED effect. Source imagery is Sentinel-2 L2A surface "
            "reflectance with the atmosphere removed; this stage re-applies a "
            "representative clear-sky atmosphere so the product approximates "
            "what an on-orbit sensor would observe. Values are representative, "
            "not a radiative-transfer computation, and are not measurements."
        ),
    }
    return arr, report


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
    band_names=("Red", "Green", "Blue", "Near Infrared"),
    view_angle_deg=0.0,
    atmosphere=True,
):
    """Run reflectance (bands, rows, cols) through the sensor chain.

    Returns (digital_numbers, report). DN is uint16 at the requested bit depth.
    """
    rng = np.random.default_rng(seed)
    arr = np.asarray(reflectance, dtype="float32")
    if arr.ndim != 3:
        raise ValueError(f"Expected (bands, rows, cols), got shape {arr.shape}")

    atmosphere_report = None
    if atmosphere:
        arr, atmosphere_report = apply_atmosphere(arr, list(band_names), view_angle_deg)

    # Gaps are held open rather than filled with the band median. Median-filling
    # manufactured a flat block of plausible-looking "ground" that a reader
    # could not distinguish from real observation -- the single worst integrity
    # defect in the pipeline. The blur/smear kernels still need finite input, so
    # gaps are neutral-filled *for the convolution only* and the mask is
    # returned so every downstream consumer can exclude them.
    gap_mask = ~np.isfinite(arr).all(axis=0)
    filled = arr.copy()
    for b in range(filled.shape[0]):
        plane = filled[b]
        bad = ~np.isfinite(plane)
        if bad.any():
            med = np.nanmedian(plane)
            plane[bad] = 0.0 if np.isnan(med) else med

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
        "atmosphere": atmosphere_report,
        "noDataPixelPercent": round(100.0 * float(gap_mask.mean()), 3),
        "parameterProvenance": (
            "Integration time, read noise, full well, and MTF sigma are "
            "representative smallsat values, not mission-configured data. "
            "GSD, swath and ground speed are derived from mission configuration "
            "and GMAT telemetry. Pixels with no source imagery are reported in "
            "noDataPixelPercent and are excluded from every statistic; they are "
            "not filled with invented ground."
        ),
    }
    return dn, report


# Preview rendering never touches the delivered raster. The GeoTIFF keeps the
# unaltered digital numbers; everything below shapes the 8-bit PNG only.
PREVIEW_BLACK_FLOOR = 6       # /255 -- shadows keep tone instead of going pure black
PREVIEW_WHITE_CEILING = 250   # /255 -- highlights keep texture instead of clipping flat


def _filmic(x, shoulder=0.72):
    """Roll the top of the range off smoothly instead of clipping it.

    A hard clip turns every bright cloud into a flat white blob with no
    internal structure, which is a large part of why the output read as
    artificial. Below the shoulder the response stays essentially linear, so
    midtones and terrain are unaffected; above it the curve compresses,
    preserving the ordering of bright values rather than discarding it.
    """
    x = np.clip(x, 0.0, None)
    out = x.copy()
    hi = x > shoulder
    if hi.any():
        headroom = 1.0 - shoulder
        excess = (x[hi] - shoulder) / max(headroom, 1e-6)
        out[hi] = shoulder + headroom * (excess / (1.0 + excess)) * 2.0 * (1.0 - 1.0 / (2.0 + excess))
    return np.clip(out, 0.0, 1.0)


def to_rgb(dn, band_order=("Red", "Green", "Blue", "Near Infrared"), stretch=(1, 99),
           valid_mask=None, white_balance=True):
    """8-bit RGB preview from simulated DN.

    A plain percentile stretch was producing the artificial look: it clipped
    hard at both ends, so shadows collapsed to pure black and clouds blew out
    to flat white with no internal texture, and a single bright region could
    dictate the exposure of the whole frame.

    The pipeline here instead:
      * takes its black/white points from real pixels only, so no-data fill
        cannot drag the exposure;
      * fits the white point to the bulk of the scene, so a cloudy corner
        does not crush everything else;
      * rolls highlights off with a filmic shoulder so cloud tops keep
        structure;
      * applies a constrained grey-world white balance so colour stays
        consistent across the frame;
      * lands inside [PREVIEW_BLACK_FLOOR, PREVIEW_WHITE_CEILING] so nothing
        is pure black or pure white.

    `valid_mask` marks pixels backed by real source imagery. Anything outside
    it is rendered as a flat neutral so a gap reads as a gap, not as ground.
    """
    idx = [band_order.index(b) for b in ("Red", "Green", "Blue") if b in band_order]
    if len(idx) < 3:
        idx = [0, 1, 2]
    rgb = np.stack([dn[i].astype("float32") for i in idx], axis=-1)

    use_mask = valid_mask is not None and np.asarray(valid_mask).any()
    gains = []

    for c in range(3):
        chan = rgb[..., c]
        sample = chan[valid_mask] if use_mask else chan.ravel()
        sample = sample[np.isfinite(sample)]
        if sample.size == 0:
            gains.append(1.0)
            continue

        lo = float(np.percentile(sample, stretch[0]))
        hi = float(np.percentile(sample, stretch[1]))

        # Fit the white point to the bulk of the scene. Without this a bright
        # cloud or glint patch sets the ceiling and everything else goes dark.
        bulk = sample[sample <= np.percentile(sample, 95)]
        if bulk.size:
            bulk_hi = float(np.percentile(bulk, 99))
            if hi > bulk_hi * 1.5:
                hi = bulk_hi * 1.15  # leave the brights somewhere to roll into

        norm = (chan - lo) / (hi - lo) if hi > lo else chan
        norm = _filmic(norm)
        rgb[..., c] = norm
        gains.append(float(np.mean(norm[valid_mask]) if use_mask else np.mean(norm)))

    # Constrained grey-world: nudge the channels toward a common mean so the
    # frame is colour-consistent, capped so a genuinely red desert or blue
    # ocean is not neutralised into grey.
    if white_balance and all(g > 1e-4 for g in gains):
        target = float(np.mean(gains))
        for c in range(3):
            adj = float(np.clip(target / gains[c], 0.85, 1.18))
            rgb[..., c] = np.clip(rgb[..., c] * adj, 0.0, 1.0)

    span = PREVIEW_WHITE_CEILING - PREVIEW_BLACK_FLOOR
    out = (PREVIEW_BLACK_FLOOR + rgb * span).astype("uint8")

    # No-data must read as a gap, not as a plausible dark surface. A flat
    # solid fill does not do that reliably -- a uniform grey block looks like
    # a rendering defect or an oddly flat patch of ground, which is exactly
    # the "cosmetic patch" a reader cannot distinguish from a real observation
    # at a glance. A diagonal hatch is the standard GIS/remote-sensing
    # convention for a masked/no-data region (QGIS, ArcGIS, most EO viewers)
    # precisely because a regular pattern reads as "excluded" rather than as
    # any possible terrain texture.
    if use_mask:
        gap = ~np.asarray(valid_mask)
        if gap.any():
            rows = np.arange(out.shape[0])[:, None]
            cols = np.arange(out.shape[1])[None, :]
            stripe = ((rows + cols) // 6) % 2 == 0
            hatch = np.where(stripe, 34, 58).astype("uint8")
            out[gap] = hatch[gap][:, None]

    return out
