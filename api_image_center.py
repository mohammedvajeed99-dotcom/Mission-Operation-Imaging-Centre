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

from core.camera_model import build_camera_model
from core.config_loader import load_mission_configuration
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
PROCESSED = BASE / "data" / "processed"
IMAGE_PRODUCTS = BASE / "data" / "image_center"

bp = Blueprint("image_center", __name__, url_prefix="/api/imagecenter")
registry = ProductRegistry(IMAGE_PRODUCTS)


# --------------------------------------------------------------------------
# Cached derivations
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _config():
    return load_mission_configuration(BASE)


@lru_cache(maxsize=1)
def _camera():
    cfg = _config()
    payload = cfg.get("payload", {})
    return build_camera_model(cfg["orbit"].get("Altitude", None),
                              payload if isinstance(payload, dict) else {})


@lru_cache(maxsize=1)
def _state():
    path = PROCESSED / "Satellite_State_History.xlsx"
    return pd.read_excel(path) if path.exists() else pd.DataFrame()


@lru_cache(maxsize=1)
def _catalog():
    """Full imaging opportunity catalog. Expensive once, then cached."""
    cfg = _config()
    return build_catalog(_state(), _camera(), cfg["mission"], cfg["constellation"])


def _catalog_live():
    """Catalog with current generation status overlaid from the registry."""
    return apply_registry(_catalog(), registry)


def reset_caches():
    _config.cache_clear()
    _camera.cache_clear()
    _state.cache_clear()
    _catalog.cache_clear()


# --------------------------------------------------------------------------
# Search / filter
# --------------------------------------------------------------------------


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
            | out["captureDate"].str.contains(q, case=False, na=False)
        )
        out = out[mask]

    for field, col in (("imageId", "imageId"), ("satellite", "satellite"),
                       ("state", "australianState"), ("aoi", "aoiName"),
                       ("date", "captureDate")):
        if (v := args.get(field, "").strip()):
            note(field, v)
            out = out[out[col].str.contains(v, case=False, na=False)]

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
    cat = _catalog()
    return jsonify({
        "ok": True,
        "catalogSize": int(len(cat)),
        "generated": len(registry.all()),
        "productsDir": str(IMAGE_PRODUCTS),
    })


@bp.get("/catalog")
def catalog():
    """Paged imaging opportunity catalog with search and filters applied."""
    df = _catalog_live()
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


@bp.get("/facets")
def facets():
    """Distinct values for populating filter controls."""
    df = _catalog_live()
    if df.empty:
        return jsonify({})
    return jsonify({
        "satellites": sorted(df["satellite"].unique().tolist()),
        "planes": sorted(int(p) for p in df["plane"].unique()),
        "orbits": sorted(int(o) for o in df["orbit"].unique()),
        "states": sorted(df["australianState"].unique().tolist()),
        "aois": sorted(df["aoiName"].unique().tolist()),
        "dates": sorted(df["captureDate"].unique().tolist()),
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


@bp.get("/image/<image_id>")
def image_detail(image_id):
    """Full detail for one catalog entry, merged with product metadata if generated."""
    df = _catalog_live()
    row = df[df["imageId"] == image_id]
    if row.empty:
        return jsonify({"ok": False, "error": f"Unknown image ID {image_id}"}), 404

    detail = json.loads(row.iloc[[0]].to_json(orient="records"))[0]
    product = registry.load(image_id)
    if product:
        detail["product"] = product
    detail["gmatRecord"] = {
        "source": "GMAT StateReport.txt -> data/processed/Satellite_State_History.xlsx",
        "satellite": detail["satellite"],
        "epochUtc": detail["captureEpochUtc"],
        "latitude": detail["latitude"],
        "longitude": detail["longitude"],
        "altitudeKm": detail["altitudeKm"],
        "fromInterpolatedFix": detail.get("fromInterpolatedFix", False),
        "note": (
            "Position is the GMAT sub-satellite fix at this epoch. Where "
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
    from core.imagery import ImageryUnavailable
    from core.imaging_summary import _ground_speed_km_s
    from core.products import generate_product

    body = request.get_json(silent=True) or {}
    regenerate = bool(body.get("regenerate", False))

    existing = registry.load(image_id)
    if existing and not regenerate:
        return jsonify({"ok": True, "cached": True, "image": existing})

    df = _catalog()
    row = df[df["imageId"] == image_id]
    if row.empty:
        return jsonify({"ok": False, "error": f"Unknown image ID {image_id}"}), 404
    entry = row.iloc[0].to_dict()

    state = _state()
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

    try:
        product = generate_product(
            scene,
            IMAGE_PRODUCTS,
            ground_speed_km_s=speed,
            max_cloud=float(body.get("maxCloud", 20.0)),
            add_noise=bool(body.get("addNoise", True)),
            seed=body.get("seed"),
        )
    except ImageryUnavailable as exc:
        failure = {**entry, "generationStatus": FAILED, "error": str(exc),
                   "generatedTimestamp": utc_now_iso()}
        registry.save(image_id, failure)
        return jsonify({"ok": False, "error": str(exc), "image": failure}), 502
    except Exception as exc:  # noqa: BLE001 - surface the real reason to the operator
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500

    # generate_product names files by its own scene id; rename onto the image ID
    # so the registry, the catalog and the download routes all agree.
    old_id = product["sceneId"]
    for suffix in (".tif", ".png", ".json"):
        src = IMAGE_PRODUCTS / f"{old_id}{suffix}"
        dst = IMAGE_PRODUCTS / f"{image_id}{suffix}"
        if src.exists() and src != dst:
            src.replace(dst)

    merged = {
        **entry,
        **product,
        "imageId": image_id,
        "sceneId": image_id,
        "generationStatus": GENERATED,
        "generatedTimestamp": utc_now_iso(),
        "downloadStatus": "Not Downloaded",
        "files": {"geotiff": f"{image_id}.tif", "preview": f"{image_id}.png",
                  "metadata": f"{image_id}.json"},
        "imageQualityScore": (product.get("quality") or {}).get("score"),
        "cloudCoverPercent": (product.get("cloud") or {}).get("cloudCoverPercent"),
    }
    registry.save(image_id, merged)
    return jsonify({"ok": True, "cached": False, "image": merged})


@bp.get("/generated")
def generated():
    """Gallery listing: every generated image, newest capture first."""
    items = registry.all()
    items = [i for i in items if i.get("generationStatus") == GENERATED]
    items.sort(key=lambda m: m.get("captureEpochUtc", ""), reverse=True)
    return jsonify({"count": len(items), "images": items})


@bp.delete("/image/<image_id>")
def delete_image(image_id):
    """Remove a generated product, returning the entry to Not Generated."""
    removed = []
    for suffix in (".tif", ".png", ".jpg", ".json"):
        p = IMAGE_PRODUCTS / f"{image_id}{suffix}"
        if p.exists():
            p.unlink()
            removed.append(p.name)
    if not removed:
        return jsonify({"ok": False, "error": f"No product for {image_id}"}), 404
    return jsonify({"ok": True, "removed": removed, "status": NOT_GENERATED})


# --------------------------------------------------------------------------
# Downloads
# --------------------------------------------------------------------------


def _require_product(image_id):
    meta = registry.load(image_id)
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
    """Download a generated product as png, jpeg, geotiff, json, csv or zip."""
    meta, err = _require_product(image_id)
    if err:
        return err

    tif = IMAGE_PRODUCTS / f"{image_id}.tif"
    png = IMAGE_PRODUCTS / f"{image_id}.png"
    kind = kind.lower()

    if kind == "png":
        return send_file(png, as_attachment=True, download_name=f"{image_id}.png")

    if kind in ("jpg", "jpeg"):
        # Rendered on demand from the PNG rather than stored twice.
        from PIL import Image

        jpg = IMAGE_PRODUCTS / f"{image_id}.jpg"
        if not jpg.exists():
            Image.open(png).convert("RGB").save(jpg, "JPEG", quality=92)
        return send_file(jpg, as_attachment=True, download_name=f"{image_id}.jpg")

    if kind in ("geotiff", "tif", "tiff"):
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


@bp.get("/image/<image_id>/preview")
def preview(image_id):
    """Inline preview image for gallery thumbnails and the detail page."""
    png = IMAGE_PRODUCTS / f"{image_id}.png"
    if not png.exists():
        return jsonify({"ok": False, "error": "No preview; image not generated"}), 404
    return send_file(png, mimetype="image/png")


@bp.post("/image/<image_id>/downloaded")
def mark_downloaded(image_id):
    """Record that an operator has downloaded this product."""
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
    df = _catalog()
    row = df[df["imageId"] == image_id]
    if row.empty:
        return jsonify({"ok": False, "error": f"Unknown image ID {image_id}"}), 404
    entry = row.iloc[0].to_dict()

    # Ground track segment around the capture, for context on the map.
    state = _state().copy()
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
             "t": r.Timestamp.isoformat()}
            for r in window.itertuples(index=False)
            if pd.notna(r.Latitude) and pd.notna(r.Longitude)
        ],
        "aoiName": entry["aoiName"],
    })
