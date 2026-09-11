"""Data Quality & Validation: per-mission diagnostics of what was actually
found and parsed from the raw GMAT files, so missing/partial data is shown
honestly instead of silently producing zeros or blank charts.
"""

from pathlib import Path

import pandas as pd

from core.missions import get_mission

STATE_OPTIONAL_COLUMNS = ["RMAG", "ECC"]


def _glob_txt(folder):
    return sorted(folder.glob("*.txt")) if folder.exists() else []


def _find_state_files(raw_dir):
    """Mirrors core.data_pipeline.run_pipeline's state-file resolution:
    data/raw/state/StateReport.txt, falling back to <repo root>/StateReport.txt
    for missions (like the reference 6x8 one) whose state file predates the
    per-mission raw/state/ convention."""
    primary = raw_dir / "state" / "StateReport.txt"
    if primary.exists():
        return [primary]
    fallback = raw_dir.parent.parent / "StateReport.txt"
    if fallback.exists():
        return [fallback]
    return []


def _check(name, raw_files, processed_path, optional_columns=None):
    optional_columns = optional_columns or []
    if not raw_files:
        return {"dataset": name, "status": "missing", "detail": "No raw report files found for this mission."}

    if not processed_path.exists():
        return {
            "dataset": name,
            "status": "missing",
            "detail": f"{len(raw_files)} raw file(s) found, but the processed dataset has not been built yet (run Refresh).",
        }

    try:
        df = pd.read_excel(processed_path)
    except Exception as exc:  # noqa: BLE001
        return {"dataset": name, "status": "missing", "detail": f"Processed file exists but could not be read: {exc}"}

    if df.empty:
        return {
            "dataset": name,
            "status": "warning",
            "detail": f"{len(raw_files)} raw file(s) found, but parsing produced 0 rows.",
        }

    satellites = int(df["Satellite Name"].nunique()) if "Satellite Name" in df.columns else None
    missing_cols = [c for c in optional_columns if c not in df.columns]
    detail = f"{len(raw_files)} raw file(s) parsed -> {len(df)} rows"
    if satellites is not None:
        detail += f", {satellites} satellite(s) detected"

    if missing_cols:
        detail += f". Not present in this mission's source report: {', '.join(missing_cols)} (shown as N/A where used)."
        return {"dataset": name, "status": "warning", "detail": detail}

    return {"dataset": name, "status": "ok", "detail": detail}


def assess_data_quality(mission_id):
    mission = get_mission(mission_id)
    raw = Path(mission["raw_dir"])
    processed = Path(mission["processed_dir"])

    checks = [
        _check(
            "RF Contact Locator",
            _glob_txt(raw / "contacts" / "rf"),
            processed / "RF_Contacts.xlsx",
        ),
        _check(
            "Optical Contact Locator",
            _glob_txt(raw / "contacts" / "optical"),
            processed / "Optical_Contacts.xlsx",
        ),
        _check(
            "Eclipse Locator",
            _glob_txt(raw / "eclipse"),
            processed / "All_Eclipse_Events.xlsx",
        ),
        _check(
            "Satellite State Report",
            _find_state_files(raw),
            processed / "Satellite_State_History.xlsx",
            optional_columns=STATE_OPTIONAL_COLUMNS,
        ),
    ]

    config_path = Path(mission["config_path"])
    checks.append(
        {
            "dataset": "Mission Configuration",
            "status": "ok" if config_path.exists() else "missing",
            "detail": f"{config_path.name} found" if config_path.exists() else "Mission_Configuration.xlsx not found",
        }
    )

    ok = sum(1 for c in checks if c["status"] == "ok")
    warning = sum(1 for c in checks if c["status"] == "warning")
    missing = sum(1 for c in checks if c["status"] == "missing")

    return {
        "missionId": mission_id,
        "checks": checks,
        "summary": {"ok": ok, "warning": warning, "missing": missing, "total": len(checks)},
    }
