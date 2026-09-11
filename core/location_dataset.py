"""Authoritative Country -> State -> District -> City lookup, built from a
real administrative dataset (data/location_dataset.json, produced once by
scripts/import_location_dataset.py from a supplied Excel workbook covering
every Indian district and every Australian local-government council).

This replaces core.geocode's live Nominatim reverse-geocoding as the
primary source for district/city on every imaging opportunity. Nominatim
required a slow (~1 req/s), rate-limited offline population step per
mission and never returned a district for Australia at all -- confirmed
directly against the live API. This module is instant, deterministic, and
fully offline: no network call, no cache-population step, no stale-server
problem.

`nearest_district_city()` returns the exact same dict shape
`core.geocode.district_city_for()` already returned, so every existing
caller, API field, and frontend column keeps working unchanged -- this is
a drop-in swap of the data source, not a new pipeline.

Like every other classifier in this codebase, "nearest district/council
headquarters" is a disclosed approximation, not a claim of true polygon
containment: a point near a district's edge can nearest-match a
neighbouring district's HQ. It is not, however, a fabrication -- every
matched name and coordinate comes from the real supplied dataset.
"""

import json
import math
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "location_dataset.json"

# How far a point may be from the nearest district/council headquarters and
# still be considered "in" it. Real administrative areas vary hugely in
# size (some Australian shires span several hundred km), so this is
# deliberately generous -- a false "Location unavailable" from too tight a
# threshold is worse than a slightly-approximate match to the genuinely
# nearest real place. Not a hard science; adjust if real edge cases show it
# needs to be wider or tighter.
MAX_DISTANCE_KM = 250.0

R_EARTH_KM = 6371.0088

UNAVAILABLE = {
    "district": None,
    "city": None,
    "country": None,
    "locationDisplay": "Location unavailable",
    "status": "unavailable",
}

REGION_COUNTRY = {"india": "India", "australia": "Australia"}
COUNTRY_REGION = {v: k for k, v in REGION_COUNTRY.items()}

# The per-opportunity state/AOI label (core.india_states, core.aoi_regions --
# real, sourced classifiers, unrelated to this dataset and left unchanged)
# uses slightly different official-name conventions for a handful of Indian
# union territories than this workbook does. Every actual STATE, and every
# Australian state/territory, already match exactly (verified directly) --
# this covers only the confirmed UT mismatches, so a District list requested
# for the state a user picked (from the classifier's own facet) resolves
# against the right rows in this dataset instead of silently returning
# nothing.
STATE_ALIASES = {
    "Andaman & Nicobar": "Andaman and Nicobar Islands",
    "Dadra & Nagar Haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "Daman & Diu": "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi": "Delhi (National Capital Territory)",
    "Jammu & Kashmir": "Jammu and Kashmir",
}


def _canonical_state(state):
    return STATE_ALIASES.get(state, state)


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km. The one distance function every
    location-related feature in this module (nearest-district-lookup here,
    and the Image Catalog's "See Near Opportunities" fallback in
    api_image_center.py) shares -- never reimplemented per caller."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_EARTH_KM * math.asin(math.sqrt(min(1.0, max(0.0, a))))


# Old private name kept as an alias -- nearest_district_city() below and any
# other in-module caller keep working unchanged.
_haversine_km = haversine_km


def _load():
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        # A missing/corrupt bundled dataset must never break a catalog
        # build -- degrade to "nothing known" rather than raising, the same
        # rule core.geocode's cache loader already follows.
        return {"india": {"districts": []}, "australia": {"districts": []}}


_DATASET = _load()


def nearest_district_city(lat, lon, region="australia"):
    """Cache-free, network-free nearest-neighbour lookup against the
    bundled authoritative dataset. Returns
    {"district", "city", "country", "locationDisplay", "status"} -- the
    same shape core.geocode.district_city_for() returns, so callers don't
    need to know which source produced it.
    """
    if lat is None or lon is None:
        return dict(UNAVAILABLE)
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return dict(UNAVAILABLE)

    entries = _DATASET.get(region, {}).get("districts", [])
    if not entries:
        return dict(UNAVAILABLE)

    best = None
    best_dist = None
    for entry in entries:
        d = _haversine_km(lat_f, lon_f, entry["lat"], entry["lon"])
        if best_dist is None or d < best_dist:
            best, best_dist = entry, d

    if best is None or best_dist > MAX_DISTANCE_KM:
        return dict(UNAVAILABLE)

    district = best.get("district")
    city = best.get("city")
    # City and district are frequently the same real place (a council's
    # principal locality sharing its name, or a district named after its
    # own headquarters town) -- de-duplicated so the display reads
    # "Brisbane" rather than the redundant "Brisbane, Brisbane".
    parts = [p for p in (city, district) if p]
    if len(parts) == 2 and parts[0] == parts[1]:
        parts = parts[:1]
    display = ", ".join(parts) if parts else UNAVAILABLE["locationDisplay"]
    return {
        "district": district,
        "city": city,
        "country": REGION_COUNTRY.get(region),
        "locationDisplay": display,
        "status": "ok",
    }


# --------------------------------------------------------------------------
# Full-list lookups for filter dropdowns.
#
# These deliberately do NOT look at any mission's catalog -- they return
# every real district/city in the authoritative dataset for the given
# scope, whether or not any current imaging opportunity happens to fall
# inside it. A reviewer picking a real, valid location that this
# constellation simply hasn't imaged yet must see that location as
# selectable and get an honest "no opportunity" result, not have it
# silently missing from the dropdown because nothing matched it today.
# --------------------------------------------------------------------------


def list_states(region):
    entries = _DATASET.get(region, {}).get("districts", [])
    return sorted({e["state"] for e in entries if e.get("state")})


def list_districts(region, state=None):
    entries = _DATASET.get(region, {}).get("districts", [])
    if state:
        state = _canonical_state(state)
        entries = [e for e in entries if e.get("state") == state]
    return sorted({e["district"] for e in entries if e.get("district")})


def list_cities(region, state=None, district=None):
    entries = _DATASET.get(region, {}).get("districts", [])
    if state:
        state = _canonical_state(state)
        entries = [e for e in entries if e.get("state") == state]
    if district:
        entries = [e for e in entries if e.get("district") == district]
    return sorted({e["city"] for e in entries if e.get("city")})


def city_coordinates(region, state=None, district=None, city=None):
    """Real lat/lon for a selected City/District/State from the same
    authoritative dataset every other location feature uses -- never a
    second, separately-maintained city database. Scoped as tightly as the
    caller can provide (state+district+city narrows fastest; city alone
    still works, taking the first real match) since city names are not
    guaranteed globally unique. Returns None, never an invented pair of
    coordinates, if nothing matches.
    """
    if not city:
        return None
    entries = _DATASET.get(region, {}).get("districts", [])
    if state:
        state = _canonical_state(state)
        entries = [e for e in entries if e.get("state") == state]
    if district:
        entries = [e for e in entries if e.get("district") == district]
    entries = [e for e in entries if e.get("city") == city]
    if not entries:
        return None
    e = entries[0]
    return {"lat": e["lat"], "lon": e["lon"]}
