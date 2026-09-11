"""Real reverse geocoding for imaging-opportunity locations (district/city).

Every imaging opportunity already carries a real lat/lon from GMAT telemetry
and an already-real state classification (core.aoi_regions for Australia,
core.india_states for India). What was missing was finer granularity --
district and city/town -- and nothing in this codebase should invent that:
no district/city name is ever fabricated or guessed from a rule of thumb.

The only source used is Nominatim (OpenStreetMap's free reverse-geocoding
service) -- no API key, matching every other external data source this
project already uses (Sentinel-2 via STAC). Nominatim's usage policy caps
requests at ~1/second and requires a real User-Agent, and any result must
carry an "(c) OpenStreetMap contributors" attribution wherever it is shown.

With up to ~5,400 imaging opportunities per mission, calling Nominatim live
on a request thread is not viable (and would violate its rate policy many
times over). So this module is split in two, deliberately:

  * district_city_for() -- CACHE ONLY. Never touches the network. This is
    the only function core.image_center.build_catalog() may call.
  * lookup_and_cache()  -- the only function that ever calls Nominatim.
    Used exclusively by scripts/populate_geocode_cache.py, run offline
    before shipping, respecting the 1 req/s policy.

The cache is bucketed by rounded coordinates (see GEOCODE_BUCKET_DECIMALS)
so opportunities along the same ground-track pass share one lookup, and
persisted to data/geocode_cache.json -- checked into git, because the
hosted deployment's filesystem is ephemeral (see DEPLOY.md): the cache must
arrive pre-populated, not be built at runtime.
"""

import json
from functools import lru_cache
from pathlib import Path

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "AnsumiOrbitalHub/1.0 (contact: mohammedvajeed99@gmail.com)"

# Nominatim policy: max ~1 request/second. Enforced by the caller
# (scripts/populate_geocode_cache.py), not by this module, since
# lookup_and_cache() also needs to be usable for a single ad-hoc re-check.
MIN_REQUEST_INTERVAL_SECONDS = 1.05

# Coordinates are bucketed to this many decimal places before caching --
# 0.01 degrees is roughly 1.1 km, coarse enough that a single ground-track
# pass's closely-spaced opportunities share one lookup, fine enough that it
# rarely straddles a real district boundary (districts are typically tens
# of km across). A single tunable, not a magic number scattered around.
GEOCODE_BUCKET_DECIMALS = 2

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "geocode_cache.json"

UNAVAILABLE = {
    "district": None,
    "city": None,
    "country": None,
    "locationDisplay": "Location unavailable",
    "status": "unavailable",
}


def bucket_key(lat, lon):
    return f"{round(float(lat), GEOCODE_BUCKET_DECIMALS)},{round(float(lon), GEOCODE_BUCKET_DECIMALS)}"


@lru_cache(maxsize=1)
def _load_cache():
    """Cache-file loader, memoized for the life of the process.

    A missing or corrupt cache file must never break a catalog build --
    every imaging opportunity would fail to list otherwise -- so this
    degrades to an empty cache (every lookup then reports "unavailable")
    rather than raising.
    """
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def district_city_for(lat, lon):
    """Cache-only lookup for one coordinate. NEVER calls the network.

    Returns {"district", "city", "country", "locationDisplay", "status"}.
    A cache miss and a lookup Nominatim itself returned nothing useful for
    both report "unavailable" -- never a fabricated name.
    """
    if lat is None or lon is None:
        return dict(UNAVAILABLE)
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return dict(UNAVAILABLE)

    entry = _load_cache().get(bucket_key(lat_f, lon_f))
    if not entry:
        return dict(UNAVAILABLE)
    return {
        "district": entry.get("district"),
        "city": entry.get("city"),
        "country": entry.get("country"),
        "locationDisplay": entry.get("locationDisplay") or UNAVAILABLE["locationDisplay"],
        "status": "ok",
    }


def _parse_nominatim_address(address):
    """Extract district/city/country from a Nominatim `address` object.

    Nominatim's address breakdown varies by country -- India commonly uses
    state_district/county for district-level and city/town/village for
    settlement-level; Australia's address model rarely populates a
    district-equivalent field at all (Australian LGAs are not always
    returned by Nominatim), which is reported honestly as district=None
    rather than guessed.
    """
    district = address.get("state_district") or address.get("county")
    city = (address.get("city") or address.get("town")
            or address.get("village") or address.get("municipality"))
    country = address.get("country")
    return district, city, country


def lookup_and_cache(lat, lon, session=None, save=True):
    """Look up one coordinate via Nominatim and persist it to the cache.

    The ONLY function in this module that touches the network. Callers
    (scripts/populate_geocode_cache.py) are responsible for spacing calls
    at least MIN_REQUEST_INTERVAL_SECONDS apart -- this function does not
    rate-limit itself, so it can also be used to re-check a single bucket
    on its own.
    """
    import requests

    key = bucket_key(lat, lon)
    cache = dict(_load_cache())
    http = session or requests

    try:
        resp = http.get(
            NOMINATIM_URL,
            params={"lat": lat, "lon": lon, "format": "jsonv2", "addressdetails": 1, "zoom": 10},
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        address = data.get("address", {}) if isinstance(data, dict) else {}
        district, city, country = _parse_nominatim_address(address)
        parts = [p for p in (city, district) if p]
        display = ", ".join(parts) if parts else (data.get("display_name") or UNAVAILABLE["locationDisplay"])
        entry = {"district": district, "city": city, "country": country, "locationDisplay": display}
    except Exception as exc:
        entry = dict(UNAVAILABLE)
        entry["error"] = str(exc)

    cache[key] = entry
    if save:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(
            json.dumps(cache, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        _load_cache.cache_clear()  # next district_city_for() call re-reads the updated file
    return entry
