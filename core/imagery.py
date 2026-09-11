"""Real-imagery retrieval for simulated camera footprints.

Source: Sentinel-2 L2A (surface reflectance) Cloud-Optimized GeoTIFFs on AWS
Open Data, discovered through the Element84 Earth Search STAC API. No account
or API key is required and reads are windowed, so retrieving one footprint
transfers only the bytes covering that footprint rather than a whole granule.

A note on time, because it is the one place this workflow cannot be literal:
the GMAT state report is a *simulation*, and its timestamps do not correspond to
dates on which Sentinel-2 actually observed Australia. There is no real imagery
for a simulated epoch. Rather than silently substituting an arbitrary scene and
labelling it with the simulation time, this module selects the archive scene
that best matches the footprint *seasonally* -- nearest day-of-year, lowest
cloud -- and every product carries both timestamps: the simulated acquisition
time and the true source-scene time. The synthetic image is honestly a
simulation dressed in real surface reflectance, and the metadata says so.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import lru_cache

import numpy as np

from core.time_utils import utc_iso

STAC_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"

# Sentinel-2 L2A asset keys for the bands the ASC074 camera models.
# The camera's four bands map onto S2 B02/B03/B04/B08 at 10 m native GSD.
# This is a spectral proxy, not a demonstrated match to ASC_074's own
# (unspecified) spectral response -- see core.spectral for the wavelength/
# bandwidth figures and the explicit disclosure carried in product metadata.
BAND_ASSETS = {"Blue": "blue", "Green": "green", "Red": "red", "Near Infrared": "nir"}
NATIVE_GSD_M = 10.0


class ImageryUnavailable(Exception):
    """No usable source scene for this footprint."""


@lru_cache(maxsize=1)
def _client():
    """Opening the STAC catalog fetches the root document over the network and
    measured ~22 s. It was previously re-opened for every single image; cache
    it so that cost is paid once per process instead of once per product."""
    from pystac_client import Client

    return Client.open(STAC_URL)


# GDAL settings for reading Cloud-Optimised GeoTIFFs over HTTPS. Without
# these, GDAL lists the remote "directory" on every open and re-fetches
# headers it already has, which dominates the read time.
GDAL_HTTP_OPTS = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF,.tiff",
    "GDAL_HTTP_MULTIPLEX": "YES",
    "GDAL_HTTP_VERSION": "2",
    "VSI_CACHE": True,
    "VSI_CACHE_SIZE": 50_000_000,
    "GDAL_CACHEMAX": 256,  # MB -- rasterio requires an int here, not a string
    # A windowed read of a tiled COG fetches every block the window touches as
    # a separate HTTP range request. The default 16 KB range-request chunk
    # under-covers a compressed 1024x1024 block (see the tile's own block
    # size), forcing GDAL to issue several small ranges per block instead of
    # one; merging adjacent block ranges into fewer, larger requests measured
    # faster for the same bytes on this same imagery (see scratchpad
    # time_read_only.py). Neither option changes which bytes are read.
    "CPL_VSIL_CURL_CHUNK_SIZE": "1048576",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
}


def _doy_distance(a, b):
    """Circular day-of-year distance, so 31 Dec and 1 Jan are 1 day apart."""
    d = abs(a - b) % 365
    return min(d, 365 - d)


@lru_cache(maxsize=256)
def _search_items(bbox, max_cloud, search_years, limit):
    """STAC query for one footprint, cached.

    The archive query took ~12 s per image and depends only on the footprint
    and cloud threshold -- not on the simulated timestamp, which is applied
    afterwards when ranking. Neighbouring opportunities along a ground track
    overlap heavily, so in a batch this is frequently a repeat query.

    Cached on the exact bbox: a coarser key could return granules that do not
    actually cover a shifted footprint.
    """
    end = datetime.utcnow()
    start = end - timedelta(days=365 * search_years)
    search = _client().search(
        collections=[COLLECTION],
        bbox=list(bbox),
        datetime=f"{start.date()}/{end.date()}",
        query={"eo:cloud_cover": {"lt": float(max_cloud)}},
        limit=limit,
    )
    return list(search.items())


def find_source_scenes(bbox, sim_timestamp, max_cloud=20.0, search_years=3,
                       limit=200, max_candidates=8, fallback_dates_per_tile=2):
    """Ranked archive scenes for a footprint: seasonally nearest, then least cloudy.

    Returns a *list*, not a single item, because a footprint frequently straddles
    a Sentinel-2 granule boundary. Granules are 110 km tiles and the modelled
    swath is ~69 km, so a footprint near a tile edge is covered by no single
    granule. Callers mosaic down this list until the footprint is filled.

    Two candidates for the same nominal tile on different dates are NOT
    interchangeable, even though the tile's fixed ~110 km grid square is the
    same: a granule's *actual* sensor-swath coverage within that square
    varies pass to pass -- a specific overpass can leave a real no-data wedge
    inside its own nominal tile boundary (confirmed by inspecting an actual
    generated product: two adjacent tiles each covered roughly a diagonal
    two-thirds of their square, not the full square, leaving a corner where
    neither reached). So this returns candidates in two tiers: first the
    single best-ranked (season + cloud) date for each distinct tile -- almost
    always enough, and keeps the common case to one read per tile rather than
    the 8-for-3-real-tiles cost this used to have -- followed by each tile's
    next `fallback_dates_per_tile` best-ranked dates, appended after every
    primary candidate. `read_footprint_mosaic` reads in order and stops once
    the footprint is filled, so the fallback tier is only ever touched for a
    tile whose primary date left a real gap, not paid for otherwise.

    `bbox` is (lon_min, lat_min, lon_max, lat_max).
    """
    items = _search_items(tuple(bbox), float(max_cloud), int(search_years), int(limit))
    if not items:
        raise ImageryUnavailable(
            f"No Sentinel-2 L2A scene under {max_cloud}% cloud covers bbox {bbox}"
        )

    target_doy = sim_timestamp.timetuple().tm_yday

    def rank(item):
        doy = item.datetime.timetuple().tm_yday
        cloud = float(item.properties.get("eo:cloud_cover", 100.0))
        # Season dominates; cloud breaks ties within a comparable season.
        return (_doy_distance(doy, target_doy), cloud)

    def tile_of(item):
        # grid:code (e.g. "MGRS-53LMG") is the STAC-standard field for this;
        # falling back to the item id covers a catalog that omits it.
        code = item.properties.get("grid:code")
        if code:
            return code
        parts = str(item.id).split("_")
        return parts[1] if len(parts) > 1 else item.id

    ranked = sorted(items, key=rank)

    by_tile = {}
    tile_order = []
    for item in ranked:
        tile = tile_of(item)
        if tile not in by_tile:
            by_tile[tile] = []
            tile_order.append(tile)
        by_tile[tile].append(item)

    tile_order = tile_order[:max_candidates]

    primary = [by_tile[tile][0] for tile in tile_order]
    fallback = [
        item
        for tile in tile_order
        for item in by_tile[tile][1:1 + max(int(fallback_dates_per_tile), 0)]
    ]
    return primary + fallback


def find_source_scene(bbox, sim_timestamp, **kwargs):
    """Single best scene. Retained for callers that do not need a mosaic."""
    return find_source_scenes(bbox, sim_timestamp, **kwargs)[0]


def read_footprint(item, bbox, out_shape, bands=("Red", "Green", "Blue", "Near Infrared")):
    """Windowed read of `bbox` from `item`, resampled to `out_shape` (rows, cols).

    Returns (array, provenance). The array is float32 reflectance shaped
    (len(bands), rows, cols) with NaN where the source has no data.
    """
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    rows, cols = int(out_shape[0]), int(out_shape[1])
    if rows < 1 or cols < 1:
        raise ImageryUnavailable(f"Degenerate output shape {out_shape}")

    hrefs = []
    for band in bands:
        asset_key = BAND_ASSETS.get(band)
        if not asset_key or asset_key not in item.assets:
            raise ImageryUnavailable(f"Source scene has no asset for band {band!r}")
        hrefs.append(item.assets[asset_key].href)

    def read_one(href):
        with rasterio.open(href) as src:
            # The COG is in UTM; the footprint bbox is lon/lat. Project the
            # bbox into the source CRS before windowing.
            left, bottom, right, top = transform_bounds("EPSG:4326", src.crs, *bbox, densify_pts=21)
            window = from_bounds(left, bottom, right, top, transform=src.transform)
            plane = src.read(
                1,
                window=window,
                out_shape=(rows, cols),
                resampling=Resampling.bilinear,
                boundless=True,
                fill_value=0,
            ).astype("float32")
            nodata = src.nodata if src.nodata is not None else 0
            plane[plane == nodata] = np.nan
            # L2A is scaled reflectance; 10000 -> 1.0.
            return plane / 10000.0

    # The bands are four independent windowed reads over HTTPS, so they were
    # spending almost all their time waiting on the network one after another.
    # Fetching them concurrently keeps the result byte-identical -- order is
    # preserved by the executor's map -- while cutting the wall time to
    # roughly that of the slowest single band.
    with rasterio.Env(**GDAL_HTTP_OPTS):
        with ThreadPoolExecutor(max_workers=len(hrefs) or 1) as pool:
            planes = list(pool.map(read_one, hrefs))

    used = list(bands)
    array = np.stack(planes)
    provenance = {
        "sourceCollection": COLLECTION,
        "sourceSceneId": item.id,
        "sourceDatetime": utc_iso(item.datetime),
        "sourceCloudCoverPercent": float(item.properties.get("eo:cloud_cover", float("nan"))),
        "sourcePlatform": item.properties.get("platform"),
        "sourceNativeGsdM": NATIVE_GSD_M,
        "sourceBands": used,
        "sourceCrs": item.properties.get("proj:code") or item.properties.get("proj:epsg"),
        "stacEndpoint": STAC_URL,
    }
    return array, provenance


def _match_radiometry(array, mosaic, min_overlap_px=500):
    """Scale `array` per band so it radiometrically matches `mosaic`.

    Sentinel-2 L2A runs its atmospheric correction independently per granule,
    so two tiles from the *same* overpass still differ in brightness by a few
    percent. Filling mosaic gaps with the raw neighbouring tile therefore
    leaves a hard rectangular step exactly on the tile boundary, which reads
    as "edited" rather than observed.

    Statistics are taken over the pixels where both rasters are valid (the
    granules overlap by design), using median and median-absolute-deviation
    so cloud and glint do not drag the fit. The gain is clamped: a correction
    beyond that is not a radiometric offset, it is genuinely different ground,
    and stretching it would fabricate agreement that is not there.

    Returns (adjusted array, per-band report). The report goes into the
    product's provenance so the applied gains stay auditable.
    """
    out = array.copy()
    report = []
    for b in range(array.shape[0]):
        a, m = array[b], mosaic[b]
        both = np.isfinite(a) & np.isfinite(m)
        overlap = int(both.sum())

        if overlap >= min_overlap_px:
            a_med = float(np.median(a[both]))
            m_med = float(np.median(m[both]))
            a_mad = float(np.median(np.abs(a[both] - a_med)))
            m_mad = float(np.median(np.abs(m[both] - m_med)))
            gain = (m_mad / a_mad) if a_mad > 1e-6 else 1.0
        else:
            # Granules that do not overlap at all: fall back to aligning the
            # median level only, with no contrast rescaling.
            a_valid, m_valid = np.isfinite(a), np.isfinite(m)
            if a_valid.sum() < min_overlap_px or m_valid.sum() < min_overlap_px:
                report.append({"band": b, "applied": False, "reason": "insufficient valid pixels"})
                continue
            a_med = float(np.median(a[a_valid]))
            m_med = float(np.median(m[m_valid]))
            gain = 1.0

        gain = float(np.clip(gain, 0.6, 1.6))
        offset = float(m_med - gain * a_med)
        out[b] = a * gain + offset
        report.append({
            "band": b, "applied": True, "overlapPx": overlap,
            "gain": round(gain, 4), "offset": round(offset, 5),
        })
    return out, report


FEATHER_PX = 12  # transition width, in delivered pixels, for _feather_seam


def _feather_seam(mosaic, array, feather_px=FEATHER_PX):
    """Fill mosaic's gaps from array with a soft-edged join instead of a
    hard cutover.

    `_match_radiometry` already corrects the *level* mismatch between two
    granules, but a single clamped gain cannot remove 100% of it (see its
    own docstring: past a point the difference is genuinely different
    ground, not a radiometric offset, and must not be stretched away). A
    hard boundary -- fully granule A on one pixel, fully granule B on the
    next -- turns whatever residual remains into one sharp, highly visible
    line, because human vision is far more sensitive to an edge than to a
    slow gradient of the same total magnitude.

    Sentinel-2 granules overlap by design, so wherever the two rasters are
    both real (`overlap`), the boundary is blended linearly over
    `feather_px` pixels -- standard mosaic feathering, the same technique
    QGIS/GDAL cutline blending and production ground segments use. This
    never invents a pixel: every blended value is a weighted average of two
    real observations in a region both scenes actually cover. Pixels where
    only one raster has data (deep in a genuine gap, or the primary's own
    exclusive footprint beyond the overlap) are left exactly as before.
    """
    gaps = ~np.isfinite(mosaic)
    fillable = gaps & np.isfinite(array)
    if not fillable.any():
        return mosaic

    out = mosaic.copy()
    use_feather = feather_px > 0

    for b in range(mosaic.shape[0]):
        band_overlap = np.isfinite(mosaic[b]) & np.isfinite(array[b])
        if use_feather and band_overlap.any():
            from scipy.ndimage import distance_transform_edt

            # Distance, in pixels, from each mosaic-covered pixel in this band
            # to the nearest gap pixel in this same band -- 0 right at the
            # join, growing deeper into the primary's own exclusive
            # territory. Computed per band since a band's own nodata mask
            # (not the union across bands) is what its blend must respect.
            dist_from_gap = distance_transform_edt(np.isfinite(mosaic[b]))
            alpha = np.clip(1.0 - dist_from_gap / float(feather_px), 0.0, 1.0)
            blended = alpha * array[b] + (1.0 - alpha) * mosaic[b]
            out[b] = np.where(band_overlap, blended, out[b])
        out[b] = np.where(fillable[b], array[b], out[b])
    return out


def _bbox_coverage_fraction(item, bbox):
    """Fraction of `bbox` actually covered by `item`'s own acquired footprint.

    STAC geometry is a real per-date polygon (always WGS84, same as `bbox`),
    already returned by the search that produced `item` -- this costs no
    extra network call, just the geometry already in hand. It is a much
    better predictor of how much of the requested footprint a granule will
    actually fill than its season/cloud rank: two dates for the very same
    110 km tile can differ hugely here, because a specific overpass can
    leave a real no-data wedge inside its own nominal tile boundary (see the
    module docstring and find_source_scenes). Ratio, not absolute area, so
    the latitude-dependent degree-to-km distortion cancels between numerator
    and denominator across the small (~1 degree) span of one footprint.
    """
    try:
        from shapely.geometry import box, shape

        bbox_poly = box(*bbox)
        area = bbox_poly.area
        if area <= 0:
            return 0.0
        return shape(item.geometry).intersection(bbox_poly).area / area
    except Exception:
        return 0.5  # unknown -- neither favour nor penalise vs a typical candidate


def read_footprint_mosaic(items, bbox, out_shape, bands=("Red", "Green", "Blue", "Near Infrared"),
                          min_coverage=0.995, harmonise=True, feather=True, on_progress=None):
    """Read `bbox` from `items`, filling gaps from later items until covered.

    A Sentinel-2 granule is a 110 km tile, so a ~69 km footprint sitting on a
    tile boundary is not fully covered by any single granule. Reading only the
    top-ranked scene leaves a void that would otherwise be filled with the band
    median and silently pass as real data.

    Items are tried in order of estimated bbox coverage (see
    _bbox_coverage_fraction), highest first -- not in the season/cloud order
    find_source_scenes ranked them for candidate *selection*. Measured before
    this change: a real footprint needed 3 full-resolution sequential reads
    (74 s) because the season-best candidate for its tile only actually
    covered 9.9% of the footprint on that specific date, and the next-ranked
    one covered 1.5%, before a lower-ranked candidate that covered 88.55%
    arrived third. Its own geometry showed that same tile covering 100% of
    the footprint on a different date -- trying highest-coverage first turns
    a wasted 96 MB read (four bands at full resolution) for a 1.5% gain into
    reading the highest-yield candidate up front, usually converging in
    fewer reads with no change to which real pixels end up in the mosaic
    (every candidate is still a genuine Sentinel-2 observation; this only
    changes the order they are tried in).

    `on_progress`, if given, is called as `on_progress(index, total, coverage)`
    before each candidate is read (index is 1-based, coverage is the fraction
    filled so far from prior reads) -- purely a status hook for a caller that
    wants to surface live progress; it does not affect what gets read.

    Returns (array, provenance). Pixels still missing after all items are
    exhausted stay NaN, and provenance reports the true coverage fraction so
    downstream quality assessment can exclude them rather than score them.
    """
    if not items:
        raise ImageryUnavailable("No candidate scenes supplied")

    items = sorted(items, key=lambda it: _bbox_coverage_fraction(it, bbox), reverse=True)

    mosaic = None
    contributors = []
    # Live-verified case (Tasmania footprint straddling a granule boundary):
    # 2 real candidates filled 99.46% of the bbox, just under min_coverage, and
    # every one of the next ~10 fallback candidates then cost a full 4-band
    # network read only to be discarded (filled_now <= 0.0005 each time) while
    # 2048px generation crawled past 3.5 minutes chasing the last <1%. Once
    # coverage stops moving for STALL_LIMIT reads in a row, further candidates
    # are overwhelmingly likely to be the same story -- stop paying for them.
    # This changes nothing about which real pixels end up in the mosaic, only
    # how many candidates get tried before accepting the gap as genuine.
    STALL_LIMIT = 2
    stalled_reads = 0

    def safe_read(item):
        """(array, prov, error) so one bad granule cannot sink the scene."""
        try:
            array, prov = read_footprint(item, bbox, out_shape, bands=bands)
            return array, prov, None
        except Exception as exc:
            return None, None, exc

    # Scenes are read one at a time, on purpose. Prefetching several
    # concurrently was measured and made things *worse* (245 s vs 119 s for a
    # four-scene mosaic): at full delivered resolution each band is already a
    # ~24 MB transfer, so a dozen parallel reads saturate the link and any
    # prefetched candidate that coverage then makes unnecessary is pure waste.
    # Concurrency pays off within a scene's four bands, not across scenes.
    def read_in_order():
        for item in items:
            yield item, safe_read(item)

    total_items = len(items)
    coverage_so_far = 0.0
    for i, (item, (array, prov, err)) in enumerate(read_in_order(), start=1):
        if on_progress is not None:
            try:
                on_progress(i, total_items, coverage_so_far)
            except Exception:
                pass  # a status hook must never break a real generation
        if err is not None:
            contributors.append({"sceneId": getattr(item, "id", "?"), "skipped": str(err)})
            continue

        match_report = None
        if mosaic is None:
            mosaic = array  # the primary defines the radiometric reference
            filled_now = float(np.isfinite(array).mean())
        else:
            gaps = ~np.isfinite(mosaic)
            if not gaps.any():
                break
            before = float(np.isfinite(mosaic).mean())
            # Bring this granule onto the primary's radiometric scale before
            # it fills anything, otherwise the join shows as a hard step.
            if harmonise:
                array, match_report = _match_radiometry(array, mosaic)
            mosaic = _feather_seam(mosaic, array, feather_px=FEATHER_PX if feather else 0)
            filled_now = float(np.isfinite(mosaic).mean()) - before
            if filled_now <= 0.0005:
                stalled_reads += 1
                if stalled_reads >= STALL_LIMIT:
                    break  # diminishing returns exhausted; remaining candidates won't help either
                continue  # contributed nothing useful; do not credit it
            stalled_reads = 0

        contributors.append({
            "radiometricMatch": match_report,
            "sceneId": prov["sourceSceneId"],
            "datetime": prov["sourceDatetime"],
            "cloudCoverPercent": prov["sourceCloudCoverPercent"],
            "platform": prov["sourcePlatform"],
            "coverageContributed": round(filled_now, 4),
        })

        coverage_so_far = float(np.isfinite(mosaic).mean())
        if coverage_so_far >= min_coverage:
            break

    if mosaic is None:
        raise ImageryUnavailable(f"No candidate scene could be read for bbox {bbox}")

    coverage = float(np.isfinite(mosaic).mean())
    primary = contributors[0] if contributors else {}
    provenance = {
        "sourceCollection": COLLECTION,
        "sourceSceneId": primary.get("sceneId"),
        "sourceDatetime": primary.get("datetime"),
        "sourceCloudCoverPercent": primary.get("cloudCoverPercent"),
        "sourcePlatform": primary.get("platform"),
        "sourceNativeGsdM": NATIVE_GSD_M,
        "sourceBands": list(bands),
        "stacEndpoint": STAC_URL,
        "mosaicContributors": contributors,
        "mosaicSceneCount": sum(1 for c in contributors if "skipped" not in c),
        "validDataFraction": round(coverage, 4),
        "seamFeathered": bool(feather),
        "seamFeatherPx": FEATHER_PX if feather else 0,
    }
    return mosaic, provenance
