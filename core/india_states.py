"""India state / union-territory classification for image AOI naming and search.

Real administrative boundaries, not a fabricated approximation: state/UT
polygons derived from Survey-of-India-aligned boundaries carrying official
Local Government Directory (LGD) codes (source: datta07/INDIAN-SHAPEFILES,
INDIA_STATES.geojson), simplified from full survey resolution down to a
~0.1 degree (~11 km) tolerance via Shapely's Douglas-Peucker `simplify()` so
the whole country's 36 states/UTs embed as compactly as the coarse Australia
state rectangles in core.aoi_regions and the MAINLAND_INDIA outline in
core.australia_coverage. 11 km is well inside the ~69 km imaging swath width,
so this stays an "engineering approximation for situational grouping", not
survey-grade cartography -- same disclosure standard as the rest of this
project's geography.

For a mainland state, only its largest part was kept (offshore islets
dropped, the same simplification already applied to
MAINLAND_AUSTRALIA/MAINLAND_INDIA). Genuine multi-island administrative
units -- Andaman & Nicobar, Lakshadweep, and Puducherry's scattered
enclaves -- keep every part at least 15% of their largest part's area, so
Port Blair (South Andaman, not the largest island in the union territory)
and Puducherry's own real, non-contiguous geography both still classify
correctly rather than collapsing to one arbitrary island or being absorbed
by a larger neighbour. Dadra & Nagar Haveli and Daman & Diu are carried as
the two separate union territories the source dataset uses (their 2020
administrative merger into one UT is not reflected here) -- classification
into either one is still a real, correctly-located result, just under the
pre-2020 split.
"""

import numpy as np
from matplotlib.path import Path

from core.india_states_data import STATE_CODES_MAP, STATE_POLYGONS

OFFSHORE = ("Indian Waters / Offshore", "OFF")

STATE_NAMES = sorted(STATE_POLYGONS) + [OFFSHORE[0]]
STATE_CODES = [STATE_CODES_MAP[name] for name in sorted(STATE_POLYGONS)] + [OFFSHORE[1]]

# Each state/UT maps to a list of Paths, one per real, separately-kept part
# (see the multi-part note above) -- a point counts as inside the state if
# it falls in ANY of that state's parts.
_PATHS = [(name, [Path(ring) for ring in rings]) for name, rings in STATE_POLYGONS.items()]


def classify_state(lat, lon):
    """Vectorised state/UT classification. Returns an array of names.

    First-match-wins over the state list: simplification can leave a
    hair-line overlap between two adjacent states at a shared border, so a
    point already resolved by one state is not re-tested against another.
    """
    lat = np.atleast_1d(np.asarray(lat, dtype=float))
    lon = np.atleast_1d(np.asarray(lon, dtype=float))
    out = np.full(lat.shape, OFFSHORE[0], dtype=object)
    unresolved = np.ones(lat.shape, dtype=bool)
    pts = np.column_stack([lon, lat])
    for name, paths in _PATHS:
        in_state = np.zeros(lat.shape, dtype=bool)
        for path in paths:
            in_state |= path.contains_points(pts)
        hit = unresolved & in_state
        out[hit] = name
        unresolved &= ~hit
    return out


def state_of(lat, lon):
    """State/UT name for a single point."""
    return str(classify_state(lat, lon)[0])


def code_of(state_name):
    return STATE_CODES_MAP.get(state_name, OFFSHORE[1])


def aoi_name(lat, lon):
    """Human-readable AOI label for an image footprint centre over India."""
    state = state_of(lat, lon)
    if state == OFFSHORE[0]:
        return state
    return f"{state}, India"
