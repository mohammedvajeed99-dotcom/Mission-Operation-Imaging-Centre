import math
import pandas as pd

DEFAULT_CAMERA = {
    "Camera Name": "ASC074_BrisbaneCam",
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

def _number(value, default):
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)

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
    for src, dst in aliases.items():
        if src in payload_config and payload_config[src] not in (None, ""):
            cfg[dst] = payload_config[src]
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
    return cfg

def build_camera_modules(satellite_names, camera_model):
    rows = []
    for sat in sorted(set(str(x) for x in satellite_names if str(x).strip())):
        row = {"Satellite Name": sat}
        row.update(camera_model)
        rows.append(row)
    return pd.DataFrame(rows)
