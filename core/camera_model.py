import math
import pandas as pd

# Representative small-satellite pushbroom camera. NONE of these are ASC_074's
# real, validated payload specifications -- they are placeholder values used
# so the imaging pipeline has something physically self-consistent to run on
# until a real payload is selected. Every one of them is reported as ASSUMED
# in the UI and in `build_camera_model()`'s returned `_meta.configSource`.
#
# The mission's actual config/Mission_Configuration.xlsx "Payload" sheet only
# defines Payload Name/Type/Field of View/GSD/Data Rate/Payload Power -- none
# of which are these seven optical parameters, and Field of View/GSD in that
# sheet are themselves blank ("Enter validated value"). So for this project's
# real mission files, every one of DEFAULT_CAMERA's values below is what
# actually reaches the simulation; the alias-override mechanism in
# build_camera_model() has never had a matching key to read in practice. It
# stays in place (real payload data would flow through it correctly the
# moment a spreadsheet provides these keys) but the source-tracking below
# makes today's all-defaults reality visible rather than assumed silently.
DEFAULT_CAMERA = {
    "Camera Name": "Generic Pushbroom Camera (assumed default)",
    "Sensor Type": "CMOS",
    "Camera Type": "Pushbroom",
    "Spectral Bands": ["Blue", "Green", "Red", "Near Infrared"],
    "Focal Length (mm)": 350.0,
    "Sensor Width (mm)": 45.0,
    "Sensor Height (mm)": 6.0,
    "Image Width (px)": 8192,
    "Image Height (px)": 1092,
    "Pixel Size (micron)": 5.5,
    "Pointing": "Nadir",
}

# The subset of DEFAULT_CAMERA that a real payload spec could override, and
# whose provenance (mission-configured vs. assumed-default) is tracked and
# reported. Excludes labels (Camera Name/Sensor Type/Camera Type/Pointing),
# which are descriptive rather than numeric/physical.
CONFIGURABLE_NUMERIC_KEYS = (
    "Focal Length (mm)", "Sensor Width (mm)", "Sensor Height (mm)",
    "Image Width (px)", "Image Height (px)", "Pixel Size (micron)",
)

# Sensor dimension vs. pixel-count-times-pitch is expected to agree closely
# (see validate_camera_geometry): DEFAULT_CAMERA's numbers were chosen to be
# consistent (8192 x 5.5 um = 45.056 mm ~ 45 mm sensor width; 1092 x 5.5 um =
# 6.006 mm ~ 6 mm height), but nothing previously checked that, so editing one
# without the others would silently desynchronise the model. 1% covers that
# rounding without masking a genuine mismatch.
GEOMETRY_TOLERANCE_FRACTION = 0.01


def _number(value, default):
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def validate_camera_geometry(cfg):
    """Check sensor width/height are consistent with pixel count x pitch.

    A real detector's physical width equals its pixel count times its pixel
    pitch, by definition -- there is no independent "sensor width" to
    disagree with that product. This never enforced that relationship
    before, even though pixel pitch was defined and displayed, so an edit to
    just one of the three numbers (e.g. a future real payload's Sensor Width
    without a matching Pixel Size) would have gone unnoticed. Mirrors the
    style of core.config_loader.validate_configuration: returns a list of
    human-readable issues, empty when consistent.
    """
    issues = []
    pixel_size_mm = _number(cfg.get("Pixel Size (micron)"), 5.5) / 1000.0

    for dim_label, sensor_key, pixel_key in (
        ("width", "Sensor Width (mm)", "Image Width (px)"),
        ("height", "Sensor Height (mm)", "Image Height (px)"),
    ):
        sensor_mm = _number(cfg.get(sensor_key), 0.0)
        pixels = _number(cfg.get(pixel_key), 0.0)
        if sensor_mm <= 0 or pixels <= 0 or pixel_size_mm <= 0:
            issues.append(f"Cannot check sensor {dim_label}: missing or non-positive value(s).")
            continue
        implied_mm = pixels * pixel_size_mm
        rel_error = abs(implied_mm - sensor_mm) / sensor_mm
        if rel_error > GEOMETRY_TOLERANCE_FRACTION:
            issues.append(
                f"Sensor {dim_label} ({sensor_mm:g} mm) does not match {pixel_key} "
                f"({pixels:g} px) x Pixel Size ({pixel_size_mm * 1000:g} um) = "
                f"{implied_mm:.3f} mm -- {rel_error * 100:.1f}% off, exceeds the "
                f"{GEOMETRY_TOLERANCE_FRACTION * 100:.0f}% tolerance."
            )

    return {"consistent": not issues, "issues": issues, "toleranceFraction": GEOMETRY_TOLERANCE_FRACTION}


def build_camera_model(altitude_km, payload_config=None):
    cfg = dict(DEFAULT_CAMERA)
    payload_config = payload_config or {}
    # Accept matching Excel keys when present; otherwise retain documented defaults.
    aliases = {
        "Camera Name":"Camera Name", "Sensor Type":"Sensor Type", "Camera Type":"Camera Type",
        "Focal Length (mm)":"Focal Length (mm)", "Sensor Width (mm)":"Sensor Width (mm)",
        "Sensor Height (mm)":"Sensor Height (mm)", "Image Width (px)":"Image Width (px)",
        "Image Height (px)":"Image Height (px)", "Pixel Size (micron)":"Pixel Size (micron)",
        "Pointing":"Pointing"
    }
    config_source = {}
    for src, dst in aliases.items():
        if src in payload_config and payload_config[src] not in (None, ""):
            cfg[dst] = payload_config[src]
            if dst in CONFIGURABLE_NUMERIC_KEYS:
                config_source[dst] = "mission_config"
        elif dst in CONFIGURABLE_NUMERIC_KEYS:
            config_source[dst] = "assumed_default"
    h = _number(altitude_km, 536)
    f = _number(cfg["Focal Length (mm)"], 350)
    sw = _number(cfg["Sensor Width (mm)"], 45)
    sh = _number(cfg["Sensor Height (mm)"], 6)
    iw = _number(cfg["Image Width (px)"], 8192)
    hfov = 2 * math.degrees(math.atan(sw / (2*f)))
    vfov = 2 * math.degrees(math.atan(sh / (2*f)))
    swath = 2 * h * math.tan(math.radians(hfov/2))
    gsd = swath * 1000 / iw
    cfg.update({
        "Altitude (km)": h, "HFOV (deg)": hfov, "VFOV (deg)": vfov,
        "Ground Swath (km)": swath, "GSD (m/pixel)": gsd
    })
    # Namespaced under one key, not spread across the top level, so the
    # generic "dump every camera field" table already in the UI can filter
    # this single key out rather than needing to know about each new one.
    assumed_count = sum(1 for v in config_source.values() if v == "assumed_default")
    cfg["_meta"] = {
        "configSource": config_source,
        "configSourceSummary": (
            f"{len(CONFIGURABLE_NUMERIC_KEYS) - assumed_count} of "
            f"{len(CONFIGURABLE_NUMERIC_KEYS)} optical parameters from mission "
            f"configuration, {assumed_count} assumed default"
            + ("s" if assumed_count != 1 else "")
        ),
        "geometryValidation": validate_camera_geometry(cfg),
    }
    return cfg

def build_camera_modules(satellite_names, camera_model):
    rows = []
    for sat in sorted(set(str(x) for x in satellite_names if str(x).strip())):
        row = {"Satellite Name": sat}
        row.update(camera_model)
        rows.append(row)
    return pd.DataFrame(rows)
