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

from datetime import datetime, timedelta

import numpy as np

STAC_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"

# Sentinel-2 L2A asset keys for the bands the ASC074 camera models.
# The camera's four bands map onto S2 B02/B03/B04/B08 at 10 m native GSD.
BAND_ASSETS = {"Blue": "blue", "Green": "green", "Red": "red", "Near Infrared": "nir"}
NATIVE_GSD_M = 10.0


class ImageryUnavailable(Exception):
    """No usable source scene for this footprint."""


def _client():
    from pystac_client import Client

    return Client.open(STAC_URL)


def _doy_distance(a, b):
    """Circular day-of-year distance, so 31 Dec and 1 Jan are 1 day apart."""
    d = abs(a - b) % 365
    return min(d, 365 - d)


def find_source_scenes(bbox, sim_timestamp, max_cloud=20.0, search_years=3,
                       limit=200, max_candidates=8):
    """Ranked archive scenes for a footprint: seasonally nearest, then least cloudy.

    Returns a *list*, not a single item, because a footprint frequently straddles
    a Sentinel-2 granule boundary. Granules are 110 km tiles and the modelled
    swath is ~69 km, so a footprint near a tile edge is covered by no single
    granule. Callers mosaic down this list until the footprint is filled.

    `bbox` is (lon_min, lat_min, lon_max, lat_max).
    """
    client = _client()
    end = datetime.utcnow()
    start = end - timedelta(days=365 * search_years)

    search = client.search(
        collections=[COLLECTION],
        bbox=list(bbox),
        datetime=f"{start.date()}/{end.date()}",
        query={"eo:cloud_cover": {"lt": float(max_cloud)}},
        limit=limit,
    )
    items = list(search.items())
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

    return sorted(items, key=rank)[:max_candidates]


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

    planes = []
    used = []
    for band in bands:
        asset_key = BAND_ASSETS.get(band)
        if not asset_key or asset_key not in item.assets:
            raise ImageryUnavailable(f"Source scene has no asset for band {band!r}")
        href = item.assets[asset_key].href

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
            planes.append(plane / 10000.0)
            used.append(band)

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


def read_footprint_mosaic(items, bbox, out_shape, bands=("Red", "Green", "Blue", "Near Infrared"),
                          min_coverage=0.995):
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

    for item in items:
        try:
            array, prov = read_footprint(item, bbox, out_shape, bands=bands)
        except Exception as exc:  # a single bad granule must not sink the scene
            contributors.append({"sceneId": getattr(item, "id", "?"), "skipped": str(exc)})
            continue

        if mosaic is None:
            mosaic = array
            filled_now = float(np.isfinite(array).mean())
        else:
            gaps = ~np.isfinite(mosaic)
            if not gaps.any():
                break
            before = float(np.isfinite(mosaic).mean())
            mosaic = np.where(gaps & np.isfinite(array), array, mosaic)
            filled_now = float(np.isfinite(mosaic).mean()) - before
            if filled_now <= 0.0005:
                continue  # contributed nothing useful; do not credit it

        contributors.append({
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
