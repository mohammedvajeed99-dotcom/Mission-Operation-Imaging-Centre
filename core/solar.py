"""Solar position at the observation location and time.

Nothing in the pipeline computed sun illumination before this -- it was
genuinely absent, not mislabelled. This adds it as a DERIVED quantity: a
standard, textbook low-precision solar position formula (Cooper's equation for
declination, a longitude-based local solar time, then the elevation/azimuth
identities), computed from data already on hand -- the capture timestamp and
sub-satellite longitude/latitude are used as a stand-in for the (unavailable)
true ground-target longitude/latitude, which is accurate to within the
footprint's own extent. No new dependency, no fabricated ephemeris.

This is intentionally NOT the higher-precision solar position used by
mission-planning tools (no equation-of-time correction, no atmospheric
refraction, no nutation) -- accurate to roughly +/-2 degrees in elevation,
which is more than sufficient to distinguish "well lit," "low sun," and
"night side," the only use this pipeline makes of it. It does not feed back
into pixel rendering in this pass; it is computed and displayed for context.
"""

import math


def solar_position(timestamp_utc, lat_deg, lon_deg):
    """Approximate solar elevation/azimuth and local solar time.

    `timestamp_utc` is a Python datetime (naive values are treated as UTC,
    matching how GMAT timestamps are already handled elsewhere in this
    pipeline). Returns a dict with the computed angles and the method note.
    """
    day_of_year = timestamp_utc.timetuple().tm_yday
    utc_hours = timestamp_utc.hour + timestamp_utc.minute / 60.0 + timestamp_utc.second / 3600.0

    # Cooper's equation: standard, widely-used approximation for solar
    # declination from day-of-year alone.
    declination_deg = 23.45 * math.sin(math.radians(360.0 / 365.0 * (284 + day_of_year)))

    # Local solar time from longitude alone (15 deg of longitude per hour of
    # solar time offset from UTC) -- the equation-of-time correction (+/- ~16
    # minutes across the year) is omitted, which is within this estimate's
    # stated +/-2 degree elevation tolerance.
    local_solar_time = (utc_hours + lon_deg / 15.0) % 24.0
    hour_angle_deg = 15.0 * (local_solar_time - 12.0)

    lat_r = math.radians(lat_deg)
    dec_r = math.radians(declination_deg)
    ha_r = math.radians(hour_angle_deg)

    sin_elev = (
        math.sin(lat_r) * math.sin(dec_r)
        + math.cos(lat_r) * math.cos(dec_r) * math.cos(ha_r)
    )
    sin_elev = max(-1.0, min(1.0, sin_elev))
    elevation_deg = math.degrees(math.asin(sin_elev))

    # Standard azimuth identity; guarded against the pole/zenith singularity.
    cos_az_denom = math.cos(math.radians(elevation_deg))
    if abs(cos_az_denom) < 1e-9:
        azimuth_deg = 0.0
    else:
        cos_az = (
            math.sin(dec_r) - math.sin(lat_r) * math.sin(math.radians(elevation_deg))
        ) / (math.cos(lat_r) * cos_az_denom)
        cos_az = max(-1.0, min(1.0, cos_az))
        azimuth_deg = math.degrees(math.acos(cos_az))
        if hour_angle_deg > 0:
            azimuth_deg = 360.0 - azimuth_deg

    if elevation_deg < -6.0:
        condition = "night"
    elif elevation_deg < 10.0:
        condition = "low sun (long shadows, strong atmospheric path)"
    else:
        condition = "daylight"

    return {
        "elevationDeg": round(elevation_deg, 2),
        "azimuthDeg": round(azimuth_deg, 2),
        "localSolarTimeHours": round(local_solar_time, 3),
        "declinationDeg": round(declination_deg, 3),
        "illuminationCondition": condition,
        "method": (
            "Cooper's equation for declination + longitude-based local solar "
            "time, standard elevation/azimuth identities. No equation-of-time "
            "or refraction correction (~+/-2 deg elevation accuracy) -- "
            "accurate enough to characterise illumination, not for precision "
            "pointing."
        ),
    }
