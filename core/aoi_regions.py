"""Australian state / territory classification for image AOI naming and search.

Consistent with the engineering-approximation approach already used by
core.australia_coverage: these are simplified boundary polygons, not an
authoritative administrative dataset. Australia's inland state borders are
largely straight meridians and parallels, so a simplified model is accurate
over most of the continent and degrades only near coastal and river borders
(notably the Murray River along the NSW/Victoria line).

Every classification returned by this module is labelled with its method so no
caller mistakes it for a surveyed boundary.
"""

import numpy as np

# Ordered: the first matching rule wins. Tasmania and the offshore territories
# are tested before the mainland rectangles.
STATES = [
    ("Tasmania", "TAS", lambda lat, lon: (lat <= -39.5) & (lon >= 143.5) & (lon <= 149.0)),
    ("Victoria", "VIC", lambda lat, lon: (lat <= -34.0) & (lat > -39.5) & (lon >= 140.9) & (lon <= 150.1)),
    ("New South Wales", "NSW", lambda lat, lon: (lat <= -28.2) & (lat > -37.6) & (lon >= 141.0) & (lon <= 154.0)),
    ("Queensland", "QLD", lambda lat, lon: (lat <= -9.0) & (lat > -29.2) & (lon >= 138.0) & (lon <= 154.0)),
    ("South Australia", "SA", lambda lat, lon: (lat <= -25.9) & (lat > -38.5) & (lon >= 129.0) & (lon < 141.1)),
    ("Northern Territory", "NT", lambda lat, lon: (lat <= -10.5) & (lat > -26.1) & (lon >= 129.0) & (lon < 138.1)),
    ("Western Australia", "WA", lambda lat, lon: (lat <= -13.0) & (lat > -35.5) & (lon >= 112.0) & (lon < 129.1)),
]
OFFSHORE = ("Australian Waters / Offshore", "OFF")

STATE_NAMES = [name for name, _, _ in STATES] + [OFFSHORE[0]]
STATE_CODES = [code for _, code, _ in STATES] + [OFFSHORE[1]]


def classify_state(lat, lon):
    """Vectorised state classification. Returns an array of state names."""
    lat = np.atleast_1d(np.asarray(lat, dtype=float))
    lon = np.atleast_1d(np.asarray(lon, dtype=float))
    out = np.full(lat.shape, OFFSHORE[0], dtype=object)
    unresolved = np.ones(lat.shape, dtype=bool)
    for name, _code, rule in STATES:
        hit = unresolved & rule(lat, lon)
        out[hit] = name
        unresolved &= ~hit
    return out


def state_of(lat, lon):
    """State name for a single point."""
    return str(classify_state(lat, lon)[0])


def code_of(state_name):
    for name, code, _ in STATES:
        if name == state_name:
            return code
    return OFFSHORE[1]


def aoi_name(lat, lon, region="australia"):
    """Human-readable AOI label for an image footprint centre.

    Names the real state/territory beneath the footprint (falling back to an
    offshore label at sea) for both regions with a sourced subdivision
    classifier: the simplified state rectangles above for Australia, and
    core.india_states' simplified real state/UT polygons for India. A region
    with neither (if a third AOI is ever added before its own subdivision
    data exists) falls back to the plain region label rather than a
    fabricated subdivision.
    """
    if region == "india":
        from core.india_states import aoi_name as india_aoi_name
        return india_aoi_name(lat, lon)
    if region != "australia":
        from core.regions import REGION_LABELS
        return REGION_LABELS.get(region, region.title())

    state = state_of(lat, lon)
    if state == OFFSHORE[0]:
        return state
    return f"{state}, Australia"
