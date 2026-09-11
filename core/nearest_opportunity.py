"""Nearest-opportunity fallback search for the Image Catalog's
"See Near Opportunities" feature.

When a reviewer's selected State/District/City combination has zero
matching imaging opportunities, this finds the geographically nearest REAL
opportunity instead -- using the same haversine great-circle distance
function used everywhere else location-related in this codebase
(core.location_dataset.haversine_km), searched against the mission's own
real catalog data. Never fabricates a result: an empty candidate set
returns (None, None, False), which the caller reports honestly rather than
inventing a placeholder.

Search levels (both handled by the one function below, driven by whether a
match exists in `preferred_state`):
  Level 2 -- prefer a candidate within the reviewer's selected State.
  Level 3 -- if none qualify there, widen to every candidate the caller
             passed in (already filtered by every OTHER active filter --
             satellite, status, cloud, quality, date range, lat/lon bounds
             -- by the caller, before this function ever sees it; only
             State/District/City are deliberately relaxed, since finding a
             genuinely nearby opportunity outside the exact selected
             location is this feature's entire purpose).
"""

from core.location_dataset import haversine_km


def find_nearest_opportunity(df, city_lat, city_lon, preferred_state=None, state_col="australianState"):
    """`df` should already have every filter applied EXCEPT state/district/
    city (relaxing exactly those three is the point of this search).

    Returns (row, distance_km, within_preferred_state):
      row              -- a pandas Series (one catalog row), or None if no
                           candidate with real coordinates exists at all.
      distance_km      -- great-circle distance from (city_lat, city_lon)
                           to the chosen row, rounded to 1 decimal place.
      within_preferred_state -- True if the chosen row's own state matches
                           `preferred_state` (Level 2 succeeded); False if
                           the search had to widen past it (Level 3), or if
                           no preferred_state was given at all.
    """
    if df is None or df.empty:
        return None, None, False

    candidates = df.dropna(subset=["latitude", "longitude"])
    if candidates.empty:
        return None, None, False

    distances = candidates.apply(
        lambda r: haversine_km(city_lat, city_lon, r["latitude"], r["longitude"]), axis=1
    )
    candidates = candidates.assign(_distanceKm=distances)

    pool, within_state = candidates, False
    if preferred_state:
        scoped = candidates[candidates[state_col] == preferred_state]
        if not scoped.empty:
            pool, within_state = scoped, True

    best = pool.loc[pool["_distanceKm"].idxmin()]
    distance_km = round(float(best["_distanceKm"]), 1)
    return best.drop(labels=["_distanceKm"]), distance_km, within_state
