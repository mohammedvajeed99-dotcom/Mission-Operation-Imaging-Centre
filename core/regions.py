"""Per-mission AOI region: which land-boundary polygon (core.australia_coverage)
and bounding box a mission's coverage/duty-cycle/imaging logic tests against.

Two regions exist today: Australia (asc074_6x8, asc074_3x1) and India
(asc080_1x3, asc080_6x4). Add a mission id to MISSION_REGIONS when a new
mission targets one of these two areas; add a new region here (plus its
land polygon in core.australia_coverage) only when a mission genuinely
targets a third area -- do not assume one is wanted.
"""

# Real bounding boxes, not each region's land polygon's incidental extent.
# Australia's is the long-standing AOI box already used throughout api.py.
# India's is read directly off the reference map supplied when this region
# was added: extreme points 68 deg 7' E / 97 deg 25' E / 8 deg 4' N /
# 37 deg 6' N (Indira Col), rounded outward slightly for margin.
AOI_BOXES = {
    "australia": {"lonMin": 110.0, "lonMax": 160.0, "latMin": -40.0, "latMax": -10.0},
    "india": {"lonMin": 68.0, "lonMax": 97.5, "latMin": 8.0, "latMax": 37.2},
}

REGION_LABELS = {
    "australia": "Australia",
    "india": "India",
}

MISSION_REGIONS = {
    "asc074_6x8": "australia",
    "asc074_3x1": "australia",
    "asc080_1x3": "india",
    "asc080_6x4": "india",
}


def region_for_mission(mission_id):
    return MISSION_REGIONS.get(mission_id, "australia")


def aoi_box_for_mission(mission_id):
    return AOI_BOXES[region_for_mission(mission_id)]


def region_label_for_mission(mission_id):
    return REGION_LABELS[region_for_mission(mission_id)]
