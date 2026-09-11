"""Mission Image Center API.

A self-contained Flask blueprint. It adds new routes under /api/imagecenter and
touches none of the existing dashboard endpoints, calculations or payloads.

Design notes:

  * The catalog is derived from GMAT telemetry and cached in memory. It is
    deterministic, so the same report always yields the same image IDs.
  * Generation is strictly on demand, one image per request. An already
    generated image is returned from cache and is never rebuilt unless the
    caller passes regenerate=true.
  * Generation status lives on disk in the product registry, so it survives a
    restart and a product is never silently regenerated.
"""

import csv
import io
import json
import zipfile
from functools import lru_cache
from pathlib import Path

import pandas as pd
from flask import Blueprint, jsonify, request, send_file
from werkzeug.datastructures import MultiDict

from core.access_control import SECTIONS, unlocked_downloads, unlocked_sections
from core.camera_model import build_camera_model
from core.data_pipeline import read_processed_frame
from core.config_loader import load_mission_configuration
from core.missions import DEFAULT_MISSION, MISSIONS, get_mission
from core.regions import region_for_mission, region_label_for_mission
from core.location_dataset import COUNTRY_REGION, city_coordinates, list_cities, list_districts
from core.nearest_opportunity import find_nearest_opportunity
from core.time_utils import utc_iso
from core.image_center import (
    FAILED,
    GENERATED,
    NOT_GENERATED,
    ProductRegistry,
    apply_registry,
    build_catalog,
    utc_now_iso,
)

BASE = Path(__file__).resolve().parent

bp = Blueprint("image_center", __name__, url_prefix="/api/imagecenter")

_registries = {}


def _registry(mission_id):
    if mission_id not in _registries:
        _registries[mission_id] = ProductRegistry(get_mission(mission_id)["image_center_dir"])
    return _registries[mission_id]


def _mission_id_from_request():
    return request.args.get("mission") or DEFAULT_MISSION


# Neither Image Center view touches /api/dashboard, so the whole blueprint is
# gated at one chokepoint. Any one of the three Image Center codes opens it:
# catalog, gallery and the global location explorer are three views onto the
# same product set, and the detail modal (shared by all three) hits the
# per-image routes.
IC_SECTIONS = ("ic-catalog", "ic-gallery", "ic-location")


@bp.before_request
def _gate_image_center():
    if request.method == "OPTIONS":  # never block the CORS preflight
        return None
    if request.path.endswith("/health"):
        return None
    if unlocked_sections(request) & set(IC_SECTIONS):
        return None
    return jsonify({
        "ok": False,
        "error": "Access code required",
        "requiredSections": list(IC_SECTIONS),
        "requiredLabels": [SECTIONS[s]["label"] for s in IC_SECTIONS],
    }), 403


# --------------------------------------------------------------------------
# Cached derivations
# --------------------------------------------------------------------------


@lru_cache(maxsize=8)
def _config(mission_id=DEFAULT_MISSION):
    return load_mission_configuration(BASE, config_path=get_mission(mission_id)["config_path"])


@lru_cache(maxsize=8)
def _camera(mission_id=DEFAULT_MISSION):
    cfg = _config(mission_id)
    payload = cfg.get("payload", {})
    return build_camera_model(cfg["orbit"].get("Altitude", None),
                              payload if isinstance(payload, dict) else {})


@lru_cache(maxsize=8)
def _state(mission_id=DEFAULT_MISSION):
    return read_processed_frame(get_mission(mission_id)["processed_dir"] / "Satellite_State_History.xlsx")


@lru_cache(maxsize=8)
def _catalog(mission_id=DEFAULT_MISSION):
    """Full imaging opportunity catalog. Expensive once, then cached."""
    cfg = _config(mission_id)
    return build_catalog(_state(mission_id), _camera(mission_id), cfg["mission"], cfg["constellation"],
                          region=region_for_mission(mission_id))


def _catalog_live(mission_id):
    """Catalog with current generation status overlaid from the registry."""
    return apply_registry(_catalog(mission_id), _registry(mission_id))


def reset_caches():
    _config.cache_clear()
    _camera.cache_clear()
    _state.cache_clear()
    _catalog.cache_clear()


# --------------------------------------------------------------------------
# Search / filter
# --------------------------------------------------------------------------


def _norm(s):
    """Whitespace/case-normalized comparison key for an exact-match filter
    -- "Vijayawada", "vijayawada" and " Vijayawada " must all select the
    same rows. casefold(), not lower(), so this stays correct for non-Latin
    district/city names too."""
    return str(s).strip().casefold()


def _apply_filters(df, args):
    """Apply every supported search and filter parameter."""
    out = df
    applied = {}

    def note(key, value):
        applied[key] = value

    # --- search ---
    if (q := args.get("q", "").strip()):
        note("q", q)
        mask = (
            out["imageId"].str.contains(q, case=False, na=False)
            | out["satellite"].str.contains(q, case=False, na=False)
            | out["aoiName"].str.contains(q, case=False, na=False)
            | out["australianState"].str.contains(q, case=False, na=False)
            | out["district"].str.contains(q, case=False, na=False)
            | out["city"].str.contains(q, case=False, na=False)
            | out["captureDate"].str.contains(q, case=False, na=False)
            # Coordinates as text, so typing e.g. "-24.3" or "116.7" finds
            # matching rows without needing the precise Min/Max range filters
            # below. astype(str) rather than a numeric comparison because this
            # is a substring match, the same as every other field here.
            | out["latitude"].astype(str).str.contains(q, case=False, na=False)
            | out["longitude"].astype(str).str.contains(q, case=False, na=False)
        )
        out = out[mask]

    for field, col in (("imageId", "imageId"), ("date", "captureDate")):
        if (v := args.get(field, "").strip()):
            note(field, v)
            out = out[out[col].str.contains(v, case=False, na=False)]

    # Dropdown-driven fields: EXACT match (normalized for stray whitespace
    # and case), not substring. These values always come from a facet-
    # populated <select>, never typed free text, so a partial match would
    # risk one district silently pulling in another whose name merely
    # contains it as a substring -- picking an exact option must never
    # include a neighbour. casefold() (not lower()) so this is safe for
    # non-Latin district/city names too.
    for field, col in (("satellite", "satellite"), ("state", "australianState"),
                       ("aoi", "aoiName"), ("district", "district"), ("city", "city")):
        if (v := args.get(field, "").strip()):
            note(field, v)
            target = _norm(v)
            out = out[out[col].notna() & (out[col].astype(str).str.strip().str.casefold() == target)]

    for field, col in (("orbit", "orbit"), ("plane", "plane"), ("orbitPass", "orbitPass")):
        if (v := args.get(field, "").strip()):
            try:
                note(field, int(v))
                out = out[out[col] == int(v)]
            except ValueError:
                pass

    # --- ranges ---
    for field, col, op in (
        ("timeFrom", "captureEpochUtc", "ge"), ("timeTo", "captureEpochUtc", "le"),
        ("latMin", "latitude", "ge"), ("latMax", "latitude", "le"),
        ("lonMin", "longitude", "ge"), ("lonMax", "longitude", "le"),
        ("qualityMin", "imageQualityScore", "ge"), ("qualityMax", "imageQualityScore", "le"),
        ("cloudMax", "cloudCoverPercent", "le"),
        ("gsdMax", "gsdM", "le"),
    ):
        raw = args.get(field, "").strip()
        if not raw:
            continue
        note(field, raw)
        series = out[col]
        if col in ("captureEpochUtc",):
            value = raw
        else:
            try:
                value = float(raw)
            except ValueError:
                continue
            series = pd.to_numeric(series, errors="coerce")
        # Rows with no value for a post-generation field cannot satisfy a
        # quality or cloud filter; drop them rather than silently keeping them.
        keep = series.ge(value) if op == "ge" else series.le(value)
        out = out[keep.fillna(False)]

    if (status := args.get("status", "").strip()):
        note("status", status)
        if status.lower() in ("generated", "true"):
            out = out[out["generationStatus"] == GENERATED]
        elif status.lower() in ("notgenerated", "not generated", "false"):
            out = out[out["generationStatus"] != GENERATED]
        else:
            out = out[out["generationStatus"].str.lower() == status.lower()]

    return out, applied


def _records(df, limit=None, offset=0):
    if df.empty:
        return []
    window = df.iloc[int(offset): int(offset) + int(limit)] if limit else df.iloc[int(offset):]
    return json.loads(window.to_json(orient="records"))


# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------


@bp.get("/health")
def health():
    mission_id = _mission_id_from_request()
    cat = _catalog(mission_id)
    return jsonify({
        "ok": True,
        "mission": mission_id,
        "catalogSize": int(len(cat)),
        "generated": len(_registry(mission_id).all()),
        "productsDir": str(get_mission(mission_id)["image_center_dir"]),
    })


@bp.get("/catalog")
def catalog():
    """Paged imaging opportunity catalog with search and filters applied."""
    df = _catalog_live(_mission_id_from_request())
    if df.empty:
        return jsonify({"total": 0, "count": 0, "offset": 0, "images": [], "filters": {}})

    filtered, applied = _apply_filters(df, request.args)

    sort_by = request.args.get("sortBy", "captureEpochUtc")
    if sort_by in filtered.columns:
        filtered = filtered.sort_values(
            sort_by, ascending=request.args.get("sortDir", "asc") != "desc"
        )

    limit = min(int(request.args.get("limit", 100)), 1000)
    offset = max(int(request.args.get("offset", 0)), 0)

    return jsonify({
        "total": int(len(filtered)),
        "count": int(min(limit, max(len(filtered) - offset, 0))),
        "offset": offset,
        "limit": limit,
        "filters": applied,
        "images": _records(filtered, limit, offset),
    })


def _facet_values(df, args, exclude_field, col, dropna=False):
    """Unique values for one filter dropdown's own options, computed against
    every OTHER filter already selected in the request -- never against its
    own current value, or picking e.g. a State would collapse that same
    State dropdown down to just its own selection instead of staying a full
    picker. This is what makes District/City actually narrow when a State
    is chosen (previously every facet list was the mission's full,
    unfiltered set regardless of what else was picked, which was fine while
    every field was dense but reads as broken once a sparse field like
    District sits next to a dense one like State).
    """
    sub_args = MultiDict(args)
    sub_args.pop(exclude_field, None)
    filtered, _ = _apply_filters(df, sub_args)
    series = filtered[col].dropna() if dropna else filtered[col]
    return series.unique().tolist()


def _facet_values_by(df, args, ancestor_fields, col, dropna=False):
    """Unique values for one level of a strict location hierarchy, computed
    using ONLY its ancestor fields -- never its own current value, and
    never a descendant's. This is what keeps State -> District -> City a
    true drill-down instead of a flat faceted search: if picking a
    District also narrowed the State dropdown (because some OTHER state
    doesn't share that district name), the user could never change State
    again without first clearing District back out. Only an ancestor
    (State, for District's purposes) may narrow a level; a sibling or
    descendant filter must not.
    """
    sub_args = MultiDict()
    for f in ancestor_fields:
        v = args.get(f, "")
        if v:
            sub_args[f] = v
    filtered, _ = _apply_filters(df, sub_args)
    series = filtered[col].dropna() if dropna else filtered[col]
    return series.unique().tolist()


@bp.get("/facets")
def facets():
    """Distinct values for populating filter controls. Satellite/plane/
    orbit/AOI are flat facets, each narrowed by every other filter
    currently applied (see _facet_values). State/District/City are a
    strict hierarchy instead: each level is narrowed only by its ANCESTOR
    (District by State; City by State+District), never by its own value or
    by a descendant -- see _facet_values_by for why that distinction
    matters (a descendant narrowing its ancestor would trap the picker)."""
    mission_id = _mission_id_from_request()
    df = _catalog_live(mission_id)
    if df.empty:
        return jsonify({})
    args = request.args
    return jsonify({
        "satellites": sorted(_facet_values(df, args, "satellite", "satellite")),
        "planes": sorted(int(p) for p in _facet_values(df, args, "plane", "plane")),
        "orbits": sorted(int(o) for o in _facet_values(df, args, "orbit", "orbit")),
        "states": sorted(_facet_values_by(df, args, [], "australianState")),
        "aois": sorted(_facet_values(df, args, "aoi", "aoiName")),
        # District/City come from the full authoritative dataset (every
        # real district/council for this mission's country), NOT from which
        # rows happen to already have a matching opportunity in this
        # mission's own catalog -- a reviewer must be able to pick any real
        # location and see an honest "no opportunity" for one this
        # constellation hasn't imaged, rather than that location being
        # invisible in the dropdown entirely. Still respects the same
        # State-only / State+District-only ancestor scoping as every other
        # level here.
        "districts": list_districts(region_for_mission(mission_id), state=args.get("state") or None),
        "cities": list_cities(region_for_mission(mission_id), state=args.get("state") or None,
                              district=args.get("district") or None),
        "country": region_label_for_mission(mission_id),
        "dates": sorted(_facet_values(df, args, "date", "captureDate")),
        "statuses": [NOT_GENERATED, GENERATED, FAILED],
        "timeRange": {
            "start": df["captureEpochUtc"].min(),
            "end": df["captureEpochUtc"].max(),
        },
        "gsdM": float(df["gsdM"].iloc[0]),
        "swathWidthKm": float(df["swathWidthKm"].iloc[0]),
        "counts": {
            "total": int(len(df)),
            "generated": int((df["generationStatus"] == GENERATED).sum()),
            "notGenerated": int((df["generationStatus"] != GENERATED).sum()),
        },
    })


@bp.get("/nearest")
def nearest_opportunity():
    """"See Near Opportunities": when the reviewer's selected State/
    District/City has zero matching rows, find the geographically nearest
    REAL opportunity instead.

    Every filter except state/district/city/aoi/q stays active (satellite,
    plane, orbit, status, date range, cloud, quality, lat/lon bounds) --
    relaxing exactly those location fields is the whole point of this
    search, nothing else the reviewer asked for is loosened. The selected
    city's own real coordinates come from core.location_dataset (the same
    authoritative dataset backing every other location feature -- never a
    second, hard-coded city list); the candidate pool is this mission's own
    real catalog (core.nearest_opportunity.find_nearest_opportunity, which
    also owns the haversine distance + prefer-same-state logic, unit
    tested in tests/test_nearest_opportunity.py). Never fabricates a
    result: an empty candidate pool is reported honestly.
    """
    mission_id = _mission_id_from_request()
    df = _catalog_live(mission_id)
    args = request.args

    state = args.get("state", "").strip()
    district = args.get("district", "").strip()
    city = args.get("city", "").strip()
    if not city:
        return jsonify({"ok": False, "error": "No city selected to search near."}), 400
    if df.empty:
        return jsonify({"ok": True, "available": False})

    coords = city_coordinates(region_for_mission(mission_id), state=state or None,
                              district=district or None, city=city)
    if not coords:
        return jsonify({"ok": False, "error": f"No coordinates on file for {city!r}."}), 404

    sub_args = MultiDict(args)
    for field in ("state", "district", "city", "aoi", "q"):
        sub_args.pop(field, None)
    filtered, _ = _apply_filters(df, sub_args)

    row, distance_km, within_state = find_nearest_opportunity(
        filtered, coords["lat"], coords["lon"], preferred_state=state or None
    )
    if row is None:
        return jsonify({"ok": True, "available": False, "fromCity": city})

    record = json.loads(pd.DataFrame([row]).to_json(orient="records"))[0]
    return jsonify({
        "ok": True,
        "available": True,
        "opportunity": record,
        "distanceKm": distance_km,
        "fromCity": city,
        "fromDistrict": district or None,
        "fromState": state or None,
        "withinSelectedState": within_state,
    })


# --------------------------------------------------------------------------
# Cross-mission location pipeline (Country -> State -> District -> City)
#
# Everything below loops core.missions.MISSIONS generically and reuses the
# exact same _catalog_live()/_apply_filters()/_records() every route above
# already uses -- there is no second, parallel location data structure and
# no per-mission special-casing. A 5th future mission needs zero changes
# here: it just appears in the loop.
# --------------------------------------------------------------------------


def _mission_country(mission_id):
    return region_label_for_mission(mission_id)


def _catalogs_for_country(country):
    """{missionId: catalog df} for every mission in `country`, or every
    mission if country is empty/unset ("All countries")."""
    out = {}
    for mission_id in MISSIONS:
        if country and _mission_country(mission_id) != country:
            continue
        df = _catalog_live(mission_id)
        if not df.empty:
            out[mission_id] = df
    return out


def _location_args(args):
    """A location query's country/mission scoping happens at the mission-
    loop level in this module (see above); _apply_filters only understands
    per-mission fields, so strip those two out before handing args to it."""
    sub = MultiDict(args)
    sub.pop("country", None)
    sub.pop("mission", None)
    return sub


@bp.get("/location/facets")
def location_facets():
    """Cross-mission facets for the global location picker -- same
    _apply_filters machinery as /facets above, looped across every mission
    in the selected country instead of scoped to one.

    Country -> State -> District -> City is a strict hierarchy: each level
    is narrowed only by its ANCESTOR selections (District by State only,
    City by State+District only), never by its own value or by a
    descendant. Narrowing a level by a descendant would trap the picker --
    e.g. if District also narrowed the State dropdown, a user could never
    switch to a different State without first clearing District back out,
    breaking the "change State -> District/City reset" flow the UI
    depends on. `missions`, by contrast, is a result, not a picker level,
    so it correctly reflects every filter currently selected.

    District/City themselves come from the full authoritative dataset
    (core.location_dataset), not from which rows happen to already have a
    matching opportunity -- every real district/council for the selected
    country is always selectable, even ones this fleet has never imaged;
    picking one just correctly returns zero opportunities rather than not
    existing as an option at all.
    """
    args = request.args
    country = args.get("country", "").strip()
    state = args.get("state", "").strip() or None
    district = args.get("district", "").strip() or None
    catalogs = _catalogs_for_country(country)
    countries = sorted({_mission_country(m) for m in MISSIONS})

    # Which dataset region(s) this applies to: the one the selected country
    # maps to, or every region if no country is picked yet ("All Countries").
    regions = [COUNTRY_REGION[country]] if country in COUNTRY_REGION else list(COUNTRY_REGION.values())
    districts = sorted({d for r in regions for d in list_districts(r, state=state)})
    cities = sorted({c for r in regions for c in list_cities(r, state=state, district=district)})

    if not catalogs:
        return jsonify({"countries": countries, "states": [], "districts": districts,
                         "cities": cities, "missions": []})

    def merged_by(ancestor_fields, col):
        values = set()
        sub_args = MultiDict()
        for f in ancestor_fields:
            v = args.get(f, "")
            if v:
                sub_args[f] = v
        for df in catalogs.values():
            filtered, _ = _apply_filters(df, sub_args)
            values.update(filtered[col].unique().tolist())
        return sorted(values)

    matching_missions = []
    for mission_id, df in catalogs.items():
        filtered, _ = _apply_filters(df, _location_args(args))
        if not filtered.empty:
            matching_missions.append({"id": mission_id, "label": get_mission(mission_id)["label"]})

    return jsonify({
        "countries": countries,
        "states": merged_by([], "australianState"),
        "districts": districts,
        "cities": cities,
        "missions": matching_missions,
    })


@bp.get("/location/opportunities")
def location_opportunities():
    """The actual cross-mission imaging-opportunity lookup behind the
    global location picker. Never fabricates a row: an empty match set is
    reported as available=false with an empty list, not padded."""
    args = request.args
    country = args.get("country", "").strip()
    only_mission = args.get("mission", "").strip()
    catalogs = _catalogs_for_country(country)
    if only_mission:
        catalogs = {m: df for m, df in catalogs.items() if m == only_mission}

    sub_args = _location_args(args)
    rows = []
    for mission_id, df in catalogs.items():
        filtered, _ = _apply_filters(df, sub_args)
        if filtered.empty:
            continue
        mission_label = get_mission(mission_id)["label"]
        country_label = _mission_country(mission_id)
        for rec in _records(filtered):
            rec["missionId"] = mission_id
            rec["missionLabel"] = mission_label
            # Prefer the real reverse-geocoded country when present; fall
            # back to the mission's own established region label (also
            # real, just coarser) rather than leaving it blank.
            rec["country"] = rec.get("country") or country_label
            rows.append(rec)

    rows.sort(key=lambda r: r.get("captureEpochUtc") or "")
    limit = min(int(args.get("limit", 200)), 1000)
    return jsonify({
        "available": len(rows) > 0,
        "count": len(rows),
        "opportunities": rows[:limit],
    })


@bp.get("/location/opportunities.csv")
def location_opportunities_csv():
    """Same query and columns as /location/opportunities, streamed as a
    downloadable report."""
    args = request.args
    country = args.get("country", "").strip()
    only_mission = args.get("mission", "").strip()
    catalogs = _catalogs_for_country(country)
    if only_mission:
        catalogs = {m: df for m, df in catalogs.items() if m == only_mission}

    sub_args = _location_args(args)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Mission", "Country", "State", "District", "City",
        "Latitude", "Longitude", "Observation Start (UTC)",
        "Duration (sec)", "Satellite", "Imaging Status",
    ])
    for mission_id, df in catalogs.items():
        filtered, _ = _apply_filters(df, sub_args)
        if filtered.empty:
            continue
        mission_label = get_mission(mission_id)["label"]
        country_label = _mission_country(mission_id)
        for rec in _records(filtered):
            writer.writerow([
                mission_label, rec.get("country") or country_label,
                rec.get("australianState"), rec.get("district"), rec.get("city"),
                rec.get("latitude"), rec.get("longitude"), rec.get("captureEpochUtc"),
                rec.get("captureDurationSec"), rec.get("satellite"), rec.get("generationStatus"),
            ])
    return send_file(
        io.BytesIO(buf.getvalue().encode("utf-8")),
        mimetype="text/csv", as_attachment=True, download_name="imaging_opportunities.csv",
    )


@bp.get("/image/<image_id>")
def image_detail(image_id):
    """Full detail for one catalog entry, merged with product metadata if generated."""
    mission_id = _mission_id_from_request()
    df = _catalog_live(mission_id)
    row = df[df["imageId"] == image_id]
    if row.empty:
        return jsonify({"ok": False, "error": f"Unknown image ID {image_id}"}), 404

    detail = json.loads(row.iloc[[0]].to_json(orient="records"))[0]
    product = _registry(mission_id).load(image_id)
    if product:
        detail["product"] = product
    # Which product files this deployment can actually serve, so the download
    # menu offers only what exists instead of failing on click.
    detail["assets"] = _registry(mission_id).assets(image_id)
    detail["telemetryRecord"] = {
        "source": "StateReport.txt -> data/processed/Satellite_State_History.xlsx",
        "satellite": detail["satellite"],
        "epochUtc": detail["captureEpochUtc"],
        "latitude": detail["latitude"],
        "longitude": detail["longitude"],
        "altitudeKm": detail["altitudeKm"],
        "fromInterpolatedFix": detail.get("fromInterpolatedFix", False),
        "note": (
            "Position is the sub-satellite fix at this epoch. Where "
            "fromInterpolatedFix is true the fix is great-circle interpolated "
            "between two reported records, because the report samples every "
            "~94 s (~629 km) which is far coarser than the camera swath."
        ),
    }
    return jsonify(detail)


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------


@bp.post("/image/<image_id>/generate")
def generate(image_id):
    """Generate one image on demand. Cached: never regenerates unless asked."""
    import core.generation_progress as gen_progress
    from core.imagery import ImageryUnavailable
    from core.imaging_summary import _ground_speed_km_s
    from core.products import generate_product

    mission_id = _mission_id_from_request()
    registry = _registry(mission_id)
    body = request.get_json(silent=True) or {}
    regenerate = bool(body.get("regenerate", False))

    existing = registry.load(image_id)
    if existing and not regenerate:
        return jsonify({"ok": True, "cached": True, "image": existing})

    df = _catalog(mission_id)
    row = df[df["imageId"] == image_id]
    if row.empty:
        return jsonify({"ok": False, "error": f"Unknown image ID {image_id}"}), 404
    entry = row.iloc[0].to_dict()

    state = _state(mission_id)
    sat_rows = state[state["Satellite Name"].astype(str) == entry["satellite"]].copy()
    sat_rows["Timestamp"] = pd.to_datetime(sat_rows["Timestamp"], errors="coerce")
    for col in ("Latitude", "Longitude"):
        sat_rows[col] = pd.to_numeric(sat_rows[col], errors="coerce")
    speed = _ground_speed_km_s(sat_rows.dropna(subset=["Timestamp", "Latitude", "Longitude"]))

    # core.products expects a scene dict shaped like core.footprint.scene_grid.
    scene = {
        "satellite": entry["satellite"],
        "timestamp": pd.to_datetime(entry["captureEpochUtc"]),
        "lat": entry["latitude"],
        "lon": entry["longitude"],
        "altitudeKm": entry["altitudeKm"],
        "headingDeg": entry["cameraHeadingDeg"],
        "orbit": entry["orbit"],
        "gsdM": entry["gsdM"],
        "swathKm": entry["swathWidthKm"],
        "alongTrackKm": entry["swathWidthKm"],
        "widthPx": entry["widthPx"],
        "heightPx": entry["heightPx"],
        "footprint": entry["groundFootprint"],
        "bbox": tuple(entry["bbox"]),
    }

    image_products = get_mission(mission_id)["image_center_dir"]
    # Delivered raster size is the dominant cost of a generation: the source
    # window is read at whatever overview level feeds this resolution, so the
    # bytes transferred scale with its square. 2048 stays the default so
    # quality is unchanged unless the caller asks for a faster product.
    try:
        max_pixels = int(body.get("maxPixels") or 2048)
    except (TypeError, ValueError):
        max_pixels = 2048
    max_pixels = max(256, min(max_pixels, 2048))

    gen_progress.start(mission_id, image_id, max_pixels)
    try:
        product = generate_product(
            scene,
            image_products,
            max_pixels=max_pixels,
            ground_speed_km_s=speed,
            max_cloud=float(body.get("maxCloud", 20.0)),
            add_noise=bool(body.get("addNoise", True)),
            seed=body.get("seed"),
            progress_cb=gen_progress.progress_callback(mission_id),
        )
    except ImageryUnavailable as exc:
        gen_progress.finish(mission_id, record=False)
        failure = {**entry, "generationStatus": FAILED, "error": str(exc),
                   "generatedTimestamp": utc_now_iso()}
        registry.save(image_id, failure)
        return jsonify({"ok": False, "error": str(exc), "image": failure}), 502
    except Exception as exc:  # noqa: BLE001 - surface the real reason to the operator
        gen_progress.finish(mission_id, record=False)
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
    else:
        gen_progress.finish(mission_id, record=True)

    # generate_product names files by its own scene id; rename onto the image ID
    # so the registry, the catalog and the download routes all agree.
    old_id = product["sceneId"]
    for suffix in (".tif", ".png", ".reference.jpg", ".json"):
        src = image_products / f"{old_id}{suffix}"
        dst = image_products / f"{image_id}{suffix}"
        if src.exists() and src != dst:
            src.replace(dst)

    merged = {
        **entry,
        **product,
        "imageId": image_id,
        "sceneId": image_id,
        "generationStatus": GENERATED,
        # Lifecycle state (above) and usability (below) are deliberately
        # separate: the product exists and is downloadable either way, but a
        # cloudy or gap-ridden frame must not be presented as a clean success.
        "qualityStatus": (product.get("validation") or {}).get("status", "ok"),
        "qualityLabel": (product.get("validation") or {}).get("label", "Generated"),
        "qualityIssues": (product.get("validation") or {}).get("issues", []),
        "generatedTimestamp": utc_now_iso(),
        "downloadStatus": "Not Downloaded",
        "files": {"geotiff": f"{image_id}.tif", "preview": f"{image_id}.png",
                  "reference": f"{image_id}.reference.jpg", "metadata": f"{image_id}.json"},
        "imageQualityScore": (product.get("quality") or {}).get("score"),
        "cloudCoverPercent": (product.get("cloud") or {}).get("cloudCoverPercent"),
    }
    registry.save(image_id, merged)
    return jsonify({"ok": True, "cached": False, "image": merged})


@bp.get("/progress")
def progress():
    """Live status of whatever generation is in flight for this mission right
    now, for a UI to poll while a Generate button or batch run is active.

    Not gated behind unlocked_sections like the rest of this blueprint's
    routes at first glance, but _gate_image_center runs as a before_request
    for the whole blueprint, so this is already covered the same as every
    other route here -- reachable only with an Image Center view code.
    """
    import core.generation_progress as gen_progress

    return jsonify(gen_progress.snapshot(_mission_id_from_request()))


@bp.get("/generated")
def generated():
    """Gallery listing: every generated image, newest capture first."""
    registry = _registry(_mission_id_from_request())
    items = registry.all()
    items = [i for i in items if i.get("generationStatus") == GENERATED]
    items.sort(key=lambda m: m.get("captureEpochUtc", ""), reverse=True)
    for item in items:
        iid = item.get("imageId") or item.get("sceneId")
        if iid:
            item["assets"] = registry.assets(iid)
    return jsonify({"count": len(items), "images": items})


@bp.delete("/image/<image_id>")
def delete_image(image_id):
    """Remove a generated product, returning the entry to Not Generated."""
    image_products = get_mission(_mission_id_from_request())["image_center_dir"]
    removed = []
    for suffix in (".tif", ".png", ".jpg", THUMB_SUFFIX, ".json"):
        p = image_products / f"{image_id}{suffix}"
        if p.exists():
            p.unlink()
            removed.append(p.name)
    if not removed:
        return jsonify({"ok": False, "error": f"No product for {image_id}"}), 404
    return jsonify({"ok": True, "removed": removed, "status": NOT_GENERATED})


# --------------------------------------------------------------------------
# Downloads
# --------------------------------------------------------------------------


def _require_product(mission_id, image_id):
    meta = _registry(mission_id).load(image_id)
    if not meta or meta.get("generationStatus") != GENERATED:
        return None, (jsonify({"ok": False,
                               "error": f"Image {image_id} has not been generated"}), 404)
    return meta, None


def _flatten(meta, prefix=""):
    """Flatten nested metadata into single-level rows for CSV export."""
    flat = {}
    for key, value in meta.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{name}."))
        elif isinstance(value, (list, tuple)):
            flat[name] = json.dumps(value)
        else:
            flat[name] = value
    return flat


def _metadata_csv(meta):
    flat = _flatten(meta)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["field", "value"])
    for key in sorted(flat):
        writer.writerow([key, flat[key]])
    return buf.getvalue().encode("utf-8")


@bp.get("/image/<image_id>/download/<kind>")
def download(image_id, kind):
    """Download a generated product as png, jpeg, geotiff, json, csv or zip.

    Gated separately from viewing: holding the ic-catalog/ic-gallery view
    code is what makes this route reachable at all (see _gate_image_center),
    but taking a file out of the dashboard needs that section's distinct
    download code too.
    """
    if not (unlocked_downloads(request) & set(IC_SECTIONS)):
        return jsonify({
            "ok": False,
            "error": "Download access code required",
            "requiredDownloadSections": list(IC_SECTIONS),
            "requiredLabels": [SECTIONS[s]["label"] for s in IC_SECTIONS],
        }), 403

    mission_id = _mission_id_from_request()
    meta, err = _require_product(mission_id, image_id)
    if err:
        return err

    image_products = get_mission(mission_id)["image_center_dir"]
    tif = image_products / f"{image_id}.tif"
    png = image_products / f"{image_id}.png"
    kind = kind.lower()

    if kind == "png":
        if not png.exists():
            return jsonify({
                "ok": False,
                "error": "Full-resolution preview is not available on this deployment.",
                "remedy": "Regenerate this observation, or run the dashboard locally.",
                "available": _registry(mission_id).assets(image_id),
            }), 409
        return send_file(png, as_attachment=True, download_name=f"{image_id}.png")

    if kind in ("jpg", "jpeg"):
        # Rendered on demand from the PNG rather than stored twice.
        from PIL import Image

        jpg = image_products / f"{image_id}.jpg"
        if not jpg.exists():
            if not png.exists():
                return jsonify({
                    "ok": False,
                    "error": "No source preview to render a JPEG from on this deployment.",
                    "remedy": "Regenerate this observation, or run the dashboard locally.",
                    "available": _registry(mission_id).assets(image_id),
                }), 409
            Image.open(png).convert("RGB").save(jpg, "JPEG", quality=92)
        return send_file(jpg, as_attachment=True, download_name=f"{image_id}.jpg")

    if kind in ("geotiff", "tif", "tiff"):
        if not tif.exists():
            # Distinct from 404: the product exists and its preview and
            # metadata are served -- only the full-resolution raster was not
            # shipped with this deployment. Say so, and say what recovers it.
            return jsonify({
                "ok": False,
                "error": "Full-resolution GeoTIFF is not available on this deployment.",
                "reason": "Previews and metadata are shipped; the ~16 MB GeoTIFFs are not.",
                "remedy": "Regenerate this observation to rebuild the GeoTIFF from the "
                          "Sentinel-2 archive, or run the dashboard locally where the "
                          "original product is stored.",
                "available": _registry(mission_id).assets(image_id),
            }), 409
        return send_file(tif, as_attachment=True, download_name=f"{image_id}.tif")

    if kind in ("json", "metadata"):
        return send_file(io.BytesIO(json.dumps(meta, indent=2, default=str).encode("utf-8")),
                         mimetype="application/json", as_attachment=True,
                         download_name=f"{image_id}.json")

    if kind == "csv":
        return send_file(io.BytesIO(_metadata_csv(meta)), mimetype="text/csv",
                         as_attachment=True, download_name=f"{image_id}.csv")

    if kind == "zip":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            if tif.exists():
                z.write(tif, f"{image_id}.tif")
            if png.exists():
                z.write(png, f"{image_id}.png")
            z.writestr(f"{image_id}.json", json.dumps(meta, indent=2, default=str))
            z.writestr(f"{image_id}.csv", _metadata_csv(meta))
        buf.seek(0)
        return send_file(buf, mimetype="application/zip", as_attachment=True,
                         download_name=f"{image_id}.zip")

    return jsonify({"ok": False, "error": f"Unsupported download kind {kind!r}"}), 400


# Preview tiers. The full preview is the 2048 px PNG -- about 6 MB. Serving
# that into a grid of sixteen tiles means ~96 MB per gallery view, which is
# tolerable over loopback and unusable over the internet. So the grid asks for
# a thumbnail instead: a small JPEG cached beside the product, built once from
# the PNG and reused thereafter.
THUMB_PX = 480
THUMB_QUALITY = 82
THUMB_SUFFIX = ".thumb.jpg"


def thumb_path(image_products, image_id):
    return Path(image_products) / f"{image_id}{THUMB_SUFFIX}"


def build_thumbnail(image_products, image_id):
    """Return the cached thumbnail path, rendering it from the PNG if needed.

    Returns None when neither a thumbnail nor a PNG is present -- which is the
    case on a deployment that ships previews but not this particular product.
    """
    thumb = thumb_path(image_products, image_id)
    if thumb.exists():
        return thumb

    png = Path(image_products) / f"{image_id}.png"
    if not png.exists():
        return None

    from PIL import Image

    with Image.open(png) as im:
        im = im.convert("RGB")
        im.thumbnail((THUMB_PX, THUMB_PX), Image.LANCZOS)
        try:
            im.save(thumb, "JPEG", quality=THUMB_QUALITY, optimize=True)
        except OSError:
            # Read-only filesystem: still serve the thumbnail, just do not
            # cache it. Correctness does not depend on the cache.
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=THUMB_QUALITY)
            buf.seek(0)
            return buf
    return thumb


@bp.get("/image/<image_id>/preview")
def preview(image_id):
    """Inline preview image. ?size=thumb for the grid, full-resolution otherwise.

    Products are immutable once generated -- regeneration writes a new file
    for the same id only on explicit request -- so both tiers are safe to
    cache in the browser for a long time.
    """
    image_products = get_mission(_mission_id_from_request())["image_center_dir"]
    want_thumb = (request.args.get("size") or "").lower() in ("thumb", "thumbnail", "small")

    if want_thumb:
        thumb = build_thumbnail(image_products, image_id)
        if thumb is None:
            return jsonify({"ok": False, "error": "No preview; image not generated"}), 404
        resp = (send_file(thumb, mimetype="image/jpeg") if isinstance(thumb, Path)
                else send_file(thumb, mimetype="image/jpeg"))
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    png = Path(image_products) / f"{image_id}.png"
    if not png.exists():
        return jsonify({"ok": False, "error": "No preview; image not generated"}), 404
    resp = send_file(png, mimetype="image/png")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@bp.get("/image/<image_id>/reference")
def reference_image(image_id):
    """The real Earth reference render for the Geospatial Validation panel --
    the same real Sentinel-2 reflectance the simulated product was derived
    from, rendered without the sensor simulation. See core/reference.py.

    Gated the same as /preview: reaching this route at all already required
    an Image Center view code (see _gate_image_center), and viewing this
    reference image is treated the same as viewing the simulated preview,
    not as a download -- it carries no more information than what the
    product's own metadata already discloses about the reference source.
    """
    image_products = get_mission(_mission_id_from_request())["image_center_dir"]
    ref = Path(image_products) / f"{image_id}.reference.jpg"
    if not ref.exists():
        return jsonify({
            "ok": False,
            "error": "No reference image for this product.",
            "reason": "Generated before the Geospatial Validation feature, or the reference render failed.",
            "remedy": "Regenerate this observation to produce its reference image.",
        }), 404
    resp = send_file(ref, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@bp.post("/image/<image_id>/downloaded")
def mark_downloaded(image_id):
    """Record that an operator has downloaded this product."""
    registry = _registry(_mission_id_from_request())
    meta = registry.load(image_id)
    if not meta:
        return jsonify({"ok": False, "error": f"No product for {image_id}"}), 404
    meta["downloadStatus"] = "Downloaded"
    meta["lastDownloadedTimestamp"] = utc_now_iso()
    registry.save(image_id, meta)
    return jsonify({"ok": True, "downloadStatus": meta["downloadStatus"]})


# --------------------------------------------------------------------------
# Map support
# --------------------------------------------------------------------------


@bp.get("/image/<image_id>/geometry")
def geometry(image_id):
    """Everything the map needs to highlight one image: footprint and track."""
    mission_id = _mission_id_from_request()
    df = _catalog(mission_id)
    row = df[df["imageId"] == image_id]
    if row.empty:
        return jsonify({"ok": False, "error": f"Unknown image ID {image_id}"}), 404
    entry = row.iloc[0].to_dict()

    # Ground track segment around the capture, for context on the map.
    state = _state(mission_id).copy()
    state["Timestamp"] = pd.to_datetime(state["Timestamp"], errors="coerce")
    sat = state[state["Satellite Name"].astype(str) == entry["satellite"]].sort_values("Timestamp")
    epoch = pd.to_datetime(entry["captureEpochUtc"])
    window = sat[(sat["Timestamp"] >= epoch - pd.Timedelta(minutes=25))
                 & (sat["Timestamp"] <= epoch + pd.Timedelta(minutes=25))]

    return jsonify({
        "imageId": image_id,
        "satellite": entry["satellite"],
        "satellitePosition": {"lat": entry["latitude"], "lon": entry["longitude"],
                              "altitudeKm": entry["altitudeKm"]},
        "cameraHeadingDeg": entry["cameraHeadingDeg"],
        "footprint": [{"lon": lo, "lat": la} for lo, la in entry["groundFootprint"]],
        "bbox": entry["bbox"],
        "groundTrack": [
            {"lon": float(r.Longitude), "lat": float(r.Latitude),
             "t": utc_iso(r.Timestamp)}
            for r in window.itertuples(index=False)
            if pd.notna(r.Latitude) and pd.notna(r.Longitude)
        ],
        "aoiName": entry["aoiName"],
    })
