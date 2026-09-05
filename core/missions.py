"""Mission registry: maps a mission id to the on-disk paths that hold its
GMAT-derived data. Every path for asc074_6x8 is the existing, unmoved
location -- adding a mission is purely additive and never relocates the
reference implementation's files.
"""

from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

MISSIONS = {
    "asc074_6x8": {
        "id": "asc074_6x8",
        # "6x8" names the Walker-Delta configuration: 6 orbital planes, 8
        # satellites per plane. Spelled out here rather than left as a bare
        # "6x8" so the label is self-explanatory wherever it is shown --
        # the dropdown, PDF/Excel report headers, comparison tables.
        "label": "ASC_074 — 6 planes x 8 sats/plane — 48 Satellites",
        "config_path": BASE / "config" / "Mission_Configuration.xlsx",
        "raw_dir": BASE / "data" / "raw",
        "processed_dir": BASE / "data" / "processed",
        "products_dir": BASE / "data" / "products",
        "image_center_dir": BASE / "data" / "image_center",
    },
    "asc074_3x1": {
        "id": "asc074_3x1",
        # Same convention: 3 orbital planes, 1 satellite per plane.
        "label": "ASC_074 — 3 planes x 1 sat/plane — 3 Satellites",
        "config_path": BASE / "data" / "missions" / "asc074_3x1" / "config" / "Mission_Configuration.xlsx",
        "raw_dir": BASE / "data" / "missions" / "asc074_3x1" / "raw",
        "processed_dir": BASE / "data" / "missions" / "asc074_3x1" / "processed",
        "products_dir": BASE / "data" / "missions" / "asc074_3x1" / "products",
        "image_center_dir": BASE / "data" / "missions" / "asc074_3x1" / "image_center",
    },
    "asc080_1x3": {
        "id": "asc080_1x3",
        # A different mission, ASC_080, not a third ASC_074 configuration:
        # 1 orbital plane, 3 satellites per plane, AOI India.
        "label": "ASC_080 — 1 plane x 3 sats/plane — 3 Satellites",
        "config_path": BASE / "data" / "missions" / "asc080_1x3" / "config" / "Mission_Configuration.xlsx",
        "raw_dir": BASE / "data" / "missions" / "asc080_1x3" / "raw",
        "processed_dir": BASE / "data" / "missions" / "asc080_1x3" / "processed",
        "products_dir": BASE / "data" / "missions" / "asc080_1x3" / "products",
        "image_center_dir": BASE / "data" / "missions" / "asc080_1x3" / "image_center",
    },
    "asc080_6x4": {
        "id": "asc080_6x4",
        # ASC_080, 6 orbital planes, 4 satellites per plane, AOI India.
        "label": "ASC_080 — 6 planes x 4 sats/plane — 24 Satellites",
        "config_path": BASE / "data" / "missions" / "asc080_6x4" / "config" / "Mission_Configuration.xlsx",
        "raw_dir": BASE / "data" / "missions" / "asc080_6x4" / "raw",
        "processed_dir": BASE / "data" / "missions" / "asc080_6x4" / "processed",
        "products_dir": BASE / "data" / "missions" / "asc080_6x4" / "products",
        "image_center_dir": BASE / "data" / "missions" / "asc080_6x4" / "image_center",
    },
}

DEFAULT_MISSION = "asc074_6x8"


def get_mission(mission_id):
    return MISSIONS.get(mission_id) or MISSIONS[DEFAULT_MISSION]


def normalize_mission_id(mission_id):
    return mission_id if mission_id in MISSIONS else DEFAULT_MISSION


_summary_cache = {}


def _mission_summary(m):
    """Static orbit/constellation figures for the welcome screen's mission
    picker, read directly from that mission's own config file -- never
    invented. Cached in memory since the config doesn't change at runtime
    and this is read on every unauthenticated page load."""
    cached = _summary_cache.get(m["id"])
    if cached is not None:
        return cached
    import pandas as pd

    xl = pd.ExcelFile(m["config_path"])

    def sheet(name):
        df = pd.read_excel(xl, sheet_name=name)
        return {str(r["Parameter"]).strip(): r["Value"] for _, r in df.iterrows() if pd.notna(r["Parameter"])}

    mission = sheet("Mission")
    constellation = sheet("Constellation")
    orbit = sheet("Orbit")
    summary = {
        "missionName": mission.get("Mission Name"),
        "missionType": mission.get("Mission Type"),
        "areaOfInterest": mission.get("Area of Interest"),
        "planes": constellation.get("Number of Planes"),
        "satellitesPerPlane": constellation.get("Satellites per Plane"),
        "totalSatellites": constellation.get("Total Satellites"),
        "altitudeKm": orbit.get("Altitude"),
        "inclinationDeg": orbit.get("Inclination"),
        "eccentricity": orbit.get("Eccentricity"),
    }
    _summary_cache[m["id"]] = summary
    return summary


def list_missions():
    return [{"id": m["id"], "label": m["label"], **_mission_summary(m)} for m in MISSIONS.values()]
