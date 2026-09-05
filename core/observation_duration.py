import pandas as pd
import numpy as np
from core.australia_coverage import footprint_intersects_region

def _fmt_duration(seconds):
    seconds = max(float(seconds or 0), 0.0)
    days = int(seconds // 86400)
    seconds %= 86400
    hours = int(seconds // 3600)
    seconds %= 3600
    minutes = int(seconds // 60)
    secs = int(round(seconds % 60))
    if days:
        return f"{days}d {hours:02d}h {minutes:02d}m {secs:02d}s"
    return f"{hours:02d}h {minutes:02d}m {secs:02d}s"

def observation_duration_analysis(state_df, swath_km, densify=True, region="australia"):
    """Per-satellite AOI observation time, windows and duty cycle.

    The GMAT report samples every ~94 s (~629 km of ground track, roughly nine
    swath widths). At that spacing an entire AOI pass can fall between two
    fixes, so testing only the reported fixes under-reports observation time and
    splits real windows. The track is densified onto a great-circle path at
    half-swath spacing first. Pass densify=False for the older behaviour.
    """
    df = state_df.copy()
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
    df = df.dropna(subset=["Timestamp","Satellite Name","Latitude","Longitude"])
    df = df.sort_values(["Satellite Name","Timestamp"]).reset_index(drop=True)

    if df.empty:
        return pd.DataFrame(), pd.DataFrame(), {}, pd.DataFrame()

    if densify:
        from core.footprint import densify_track

        df = densify_track(df, max_gap_km=max(float(swath_km) / 2.0, 1.0))
        df = df.sort_values(["Satellite Name", "Timestamp"]).reset_index(drop=True)

    df["Observing AOI"] = footprint_intersects_region(
        df, float(swath_km), region=region, lon_col="Longitude", lat_col="Latitude"
    )

    # Infer each satellite's nominal report step. Each sample represents the
    # interval until the next sample, capped at the satellite's nominal step.
    med_steps = {}
    for sat, g in df.groupby("Satellite Name"):
        diffs = g["Timestamp"].diff().dt.total_seconds()
        valid = diffs[(diffs > 0) & (diffs < 86400)]
        med_steps[sat] = float(valid.median()) if not valid.empty else 0.0

    next_t = df.groupby("Satellite Name")["Timestamp"].shift(-1)
    dt = (next_t - df["Timestamp"]).dt.total_seconds()
    nominal = df["Satellite Name"].map(med_steps).astype(float)
    df["Sample Duration (s)"] = np.where(
        dt.notna() & (dt > 0),
        np.minimum(dt, nominal.where(nominal > 0, dt)),
        0.0
    )
    df["Observed Duration (s)"] = df["Sample Duration (s)"] * df["Observing AOI"].astype(int)

    # Build continuous observation windows per satellite.
    windows = []
    for sat, g in df.groupby("Satellite Name", sort=True):
        g = g.sort_values("Timestamp").copy()
        nominal_step = med_steps.get(sat, 0.0)
        active = g[g["Observing AOI"]].copy()
        if active.empty:
            continue
        gaps = active["Timestamp"].diff().dt.total_seconds()
        active["Window ID"] = ((gaps.isna()) | (gaps > max(nominal_step * 1.5, 1.0))).cumsum()
        for _, w in active.groupby("Window ID"):
            duration = float(w["Observed Duration (s)"].sum())
            windows.append({
                "Satellite Name": sat,
                "Start Time": w["Timestamp"].min(),
                "End Time": w["Timestamp"].max() + pd.to_timedelta(float(w["Observed Duration (s)"].iloc[-1]), unit="s"),
                "Observation Duration (s)": duration
            })
    windows_df = pd.DataFrame(windows)

    rows = []
    for sat, g in df.groupby("Satellite Name", sort=True):
        wg = windows_df[windows_df["Satellite Name"].eq(sat)] if not windows_df.empty else pd.DataFrame()
        total = float(g["Observed Duration (s)"].sum())
        sim = float(g["Sample Duration (s)"].sum())
        durations = wg["Observation Duration (s)"] if not wg.empty else pd.Series(dtype=float)
        rows.append({
            "Satellite Name": sat,
            "Total Observation Time": _fmt_duration(total),
            "Total Observation Seconds": total,
            "Observation Windows": int(len(wg)),
            "Average Window": _fmt_duration(durations.mean() if len(durations) else 0),
            "Longest Window": _fmt_duration(durations.max() if len(durations) else 0),
            "First Observation": wg["Start Time"].min() if not wg.empty else pd.NaT,
            "Last Observation": wg["End Time"].max() if not wg.empty else pd.NaT,
            "Observation Duty Cycle (%)": (100.0 * total / sim) if sim > 0 else 0.0
        })
    per_sat = pd.DataFrame(rows)

    # Unique constellation observation time on the common timestamp grid.
    timeline = df.groupby("Timestamp", as_index=False).agg(
        Observing_Satellites=("Observing AOI", "sum")
    ).sort_values("Timestamp")
    timeline["Next Timestamp"] = timeline["Timestamp"].shift(-1)
    timeline["Interval (s)"] = (timeline["Next Timestamp"] - timeline["Timestamp"]).dt.total_seconds().fillna(0)
    valid_intervals = timeline.loc[timeline["Interval (s)"] > 0, "Interval (s)"]
    if not valid_intervals.empty:
        cap = float(valid_intervals.median()) * 1.5
        timeline["Interval (s)"] = timeline["Interval (s)"].clip(upper=cap)
    timeline["Any Observing"] = timeline["Observing_Satellites"] > 0
    timeline["Unique Observed Duration (s)"] = timeline["Interval (s)"] * timeline["Any Observing"].astype(int)

    summed = float(per_sat["Total Observation Seconds"].sum()) if not per_sat.empty else 0.0
    unique = float(timeline["Unique Observed Duration (s)"].sum())
    elapsed = float(timeline["Interval (s)"].sum())
    overall = {
        "Summed Satellite Observation Time": _fmt_duration(summed),
        "Unique Constellation Observation Time": _fmt_duration(unique),
        "Overall Observation Duty Cycle (%)": (100.0 * unique / elapsed) if elapsed > 0 else 0.0,
        "Maximum Simultaneous Observing Satellites": int(timeline["Observing_Satellites"].max()) if not timeline.empty else 0,
        "Simulation Analysis Duration": _fmt_duration(elapsed)
    }
    return per_sat, windows_df, overall, timeline
