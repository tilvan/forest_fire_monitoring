from __future__ import annotations

import logging

import numpy as np
from rasterio.enums import Resampling

from app.services.raster import read_cog_to_grid, sample_cog
from app.services.stac_client import search_items, signed_href

logger = logging.getLogger(__name__)

# ESA WorldCover 2021
TREE = 10
SHRUB = 20
GRASS = 30
CROP = 40
BUILT = 50
BARE = 60
SNOW = 70
WATER = 80
WETLAND = 90
MANGROVE = 95
MOSS = 100

VEGETATION_FOR_HOTSPOTS = {TREE, SHRUB, GRASS, WETLAND, MANGROVE}
FOREST_FOR_BURNS = {TREE, MANGROVE}

CLASS_NAMES = {
    TREE: "tree_cover",
    SHRUB: "shrubland",
    GRASS: "grassland",
    CROP: "cropland",
    BUILT: "built_up",
    BARE: "bare",
    SNOW: "snow",
    WATER: "water",
    WETLAND: "wetland",
    MANGROVE: "mangrove",
    MOSS: "moss",
}


def worldcover_href(bbox: tuple[float, float, float, float]) -> str | None:
    items = search_items(
        collections=["esa-worldcover"],
        bbox=bbox,
        datetime="2021-01-01/2021-12-31",
        max_items=4,
    )
    if not items:
        items = search_items(collections=["esa-worldcover"], bbox=bbox, max_items=4)
    if not items:
        logger.warning("ESA WorldCover 2021 not found for bbox %s", bbox)
        return None
    item = items[0]
    for key in ("map", "esa_worldcover_2021"):
        if key in item.assets:
            return signed_href(item, key)
    asset_key = next(iter(item.assets))
    return signed_href(item, asset_key)


def sample_landcover(lons: np.ndarray, lats: np.ndarray, bbox: tuple[float, float, float, float]) -> np.ndarray:
    values = np.full(len(lons), np.nan)
    if len(lons) == 0:
        return values
    items = search_items(
        collections=["esa-worldcover"],
        bbox=bbox,
        datetime="2021-01-01/2021-12-31",
        max_items=6,
    )
    if not items:
        items = search_items(collections=["esa-worldcover"], bbox=bbox, max_items=6)
    if not items:
        logger.warning("ESA WorldCover 2021 not found for bbox %s", bbox)
        return values
    for item in items:
        missing = ~np.isfinite(values)
        if not missing.any():
            break
        href = None
        for key in ("map", "esa_worldcover_2021"):
            if key in item.assets:
                href = signed_href(item, key)
                break
        if href is None:
            href = signed_href(item, next(iter(item.assets)))
        try:
            sampled = sample_cog(href, lons[missing], lats[missing])
            values[missing] = sampled
        except Exception:
            logger.exception("WorldCover point sampling failed for %s", item.id)
    return values


def forest_mask(grid: dict, bbox: tuple[float, float, float, float]) -> np.ndarray | None:
    href = worldcover_href(bbox)
    if href is None:
        return None
    try:
        data = read_cog_to_grid(href, grid, resampling=Resampling.nearest)
        return np.isin(data, list(FOREST_FOR_BURNS))
    except Exception:
        logger.exception("WorldCover forest mask failed")
        return None


def class_name(code: float) -> str:
    if np.isnan(code):
        return "unknown"
    return CLASS_NAMES.get(int(code), f"class_{int(code)}")
