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
        "sourceDatetime": item.datetime.isoformat(),
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


def read_footprint_mosaic(items, bbox, out_shape, bands=("Red", "Green", "Blue", "Near Infrared"),
                          min_coverage=0.995, harmonise=True):
    """Read `bbox` from `items`, filling gaps from later items until covered.

    A Sentinel-2 granule is a 110 km tile, so a ~69 km footprint sitting on a
    tile boundary is not fully covered by any single granule. Reading only the
    top-ranked scene leaves a void that would otherwise be filled with the band
    median and silently pass as real data.

    Returns (array, provenance). Pixels still missing after all items are
    exhausted stay NaN, and provenance reports the true coverage fraction so
    downstream quality assessment can exclude them rather than score them.
    """
    if not items:
        raise ImageryUnavailable("No candidate scenes supplied")

    mosaic = None
    contributors = []

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

    for item, (array, prov, err) in read_in_order():
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
            mosaic = np.where(gaps & np.isfinite(array), array, mosaic)
            filled_now = float(np.isfinite(mosaic).mean()) - before
            if filled_now <= 0.0005:
                continue  # contributed nothing useful; do not credit it

        contributors.append({
            "radiometricMatch": match_report,
            "sceneId": prov["sourceSceneId"],
            "datetime": prov["sourceDatetime"],
            "cloudCoverPercent": prov["sourceCloudCoverPercent"],
            "platform": prov["sourcePlatform"],
            "coverageContributed": round(filled_now, 4),
        })

        if float(np.isfinite(mosaic).mean()) >= min_coverage:
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
    }
    return mosaic, provenance
