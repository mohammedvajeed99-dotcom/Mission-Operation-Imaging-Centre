import pandas as pd

def _positive(v):
    try:
        x = float(v)
        return x if x > 0 else None
    except Exception:
        return None

def default_k3_config():
    return {
        "Bits per Pixel": 12.0,
        "Along-track GSD (m)": None,
        "Compression Ratio": None,
        "Onboard Storage Capacity": None,
        "Processing Rate": None,
    }

def derive_pushbroom_data_model(camera_model, config, ground_speed_km_s=None):
    cross_track_pixels = _positive(camera_model.get("Image Width (px)"))
    spectral = camera_model.get("Spectral Bands", [])
    bands = float(len(spectral)) if isinstance(spectral, (list, tuple)) and spectral else None
    bpp = _positive(config.get("Bits per Pixel"))
    gsd_m = _positive(config.get("Along-track GSD (m)"))
    speed_km_s = _positive(ground_speed_km_s)

    line_rate_hz = speed_km_s * 1000.0 / gsd_m if speed_km_s and gsd_m else None
    bits_per_line = cross_track_pixels * bands * bpp if cross_track_pixels and bands and bpp else None
    raw_rate_mbps = bits_per_line * line_rate_hz / 1_000_000.0 if bits_per_line and line_rate_hz else None

    return {
        "Cross-track Pixels": cross_track_pixels,
        "Active Bands": bands,
        "Bits per Pixel": bpp,
        "Ground Speed (km/s)": speed_km_s,
        "Along-track GSD (m)": gsd_m,
        "Derived Line Rate (lines/s)": line_rate_hz,
        "Bits per Line": bits_per_line,
        "Continuous Raw Data Rate (Mbps)": raw_rate_mbps,
    }

def calculate_k3_from_observation(per_sat_obs, derived, config):
    df = per_sat_obs.copy()
    rate = _positive(derived.get("Continuous Raw Data Rate (Mbps)"))
    compression = _positive(config.get("Compression Ratio"))
    storage = _positive(config.get("Onboard Storage Capacity"))
    processing = _positive(config.get("Processing Rate"))
    obs_s = pd.to_numeric(df["Total Observation Seconds"], errors="coerce").fillna(0)

    if rate:
        df["Raw Data Generated (GB)"] = obs_s * rate / 8.0 / 1000.0
    else:
        df["Raw Data Generated (GB)"] = pd.NA

    raw = pd.to_numeric(df["Raw Data Generated (GB)"], errors="coerce")
    df["Compressed Data (GB)"] = raw / compression if compression else pd.NA
    stored = pd.to_numeric(df["Compressed Data (GB)"], errors="coerce") if compression else raw
    df["Storage Utilization (%)"] = 100.0 * stored / storage if storage else pd.NA
    df["Estimated Processing Time (s)"] = raw * 8000.0 / processing if processing else pd.NA
    return df
