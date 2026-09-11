"""Offline population of data/geocode_cache.json.

Run this manually before shipping a new mission, after an AOI change, or
whenever the catalog gains new opportunities -- never at runtime. It builds
every mission's imaging-opportunity catalog, dedupes down to the real set
of coordinate buckets that still need a lookup (see core.geocode's
GEOCODE_BUCKET_DECIMALS), and geocodes each one exactly once via
core.geocode.lookup_and_cache, respecting Nominatim's ~1 req/s usage
policy. Safe to interrupt (Ctrl-C) and re-run: already-cached buckets are
skipped on the next run, so adding a 5th mission only pays for its new
points, not the first four missions' again.

Usage:
    python scripts/populate_geocode_cache.py                # every mission
    python scripts/populate_geocode_cache.py asc074_6x8      # just this one
    python scripts/populate_geocode_cache.py asc074_6x8 asc080_1x3
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Cache entries are always written to disk as UTF-8 (core.geocode does this
# correctly regardless of console encoding) -- but a Windows console's
# default codepage (cp1252) cannot print many real Indian place names,
# which would otherwise crash this script's own progress output after the
# data was already safely written. Reconfigure stdout so the *display* of
# real non-ASCII names degrades gracefully instead of aborting the run.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from core.camera_model import build_camera_model
from core.config_loader import load_mission_configuration
from core.data_pipeline import read_processed_frame
from core.geocode import CACHE_PATH, MIN_REQUEST_INTERVAL_SECONDS, bucket_key, lookup_and_cache
from core.image_center import build_catalog
from core.missions import MISSIONS, get_mission
from core.regions import region_for_mission

BASE = Path(__file__).resolve().parent.parent


def _existing_buckets():
    import json

    try:
        return set(json.loads(CACHE_PATH.read_text(encoding="utf-8")).keys())
    except Exception:
        return set()


def _catalog_for(mission_id):
    m = get_mission(mission_id)
    cfg = load_mission_configuration(BASE, config_path=m["config_path"])
    camera = build_camera_model(cfg["orbit"].get("Altitude", None), cfg.get("payload", {}))
    state_df = read_processed_frame(m["processed_dir"] / "Satellite_State_History.xlsx")
    return build_catalog(state_df, camera, cfg["mission"], cfg["constellation"],
                          region=region_for_mission(mission_id))


def main():
    requested = sys.argv[1:] or list(MISSIONS.keys())
    unknown = [m for m in requested if m not in MISSIONS]
    if unknown:
        print(f"Unknown mission id(s): {', '.join(unknown)}. Known: {', '.join(MISSIONS)}")
        sys.exit(1)

    cached = _existing_buckets()
    print(f"{len(cached)} coordinate bucket(s) already cached in {CACHE_PATH}")

    # Dedupe across ALL requested missions before geocoding anything -- two
    # missions covering the same region (e.g. asc074_6x8 and asc074_3x1, both
    # Australia) share most of their buckets, so this avoids paying for the
    # same lookup twice even within one run.
    pending = {}
    for mission_id in requested:
        cat = _catalog_for(mission_id)
        if cat.empty:
            print(f"{mission_id}: catalog is empty, nothing to geocode")
            continue
        new_for_mission = 0
        for lat, lon in zip(cat["latitude"], cat["longitude"]):
            key = bucket_key(lat, lon)
            if key in cached or key in pending:
                continue
            pending[key] = (lat, lon)
            new_for_mission += 1
        print(f"{mission_id}: {len(cat)} opportunities, {new_for_mission} new bucket(s) to geocode")

    if not pending:
        print("Nothing new to geocode.")
        return

    print(f"Geocoding {len(pending)} bucket(s) via Nominatim at ~1 req/s "
          f"(estimated {len(pending) * MIN_REQUEST_INTERVAL_SECONDS / 60:.1f} min)...")
    import requests

    session = requests.Session()
    done = 0
    for key, (lat, lon) in pending.items():
        t0 = time.monotonic()
        entry = lookup_and_cache(lat, lon, session=session)
        done += 1
        status = "ok" if entry.get("district") or entry.get("city") else entry.get("status", "unavailable")
        print(f"[{done}/{len(pending)}] {key} -> {entry.get('locationDisplay')!r} ({status})")
        elapsed = time.monotonic() - t0
        if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)

    print(f"Done. Cache now at {CACHE_PATH}")


if __name__ == "__main__":
    main()
