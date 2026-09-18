from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd
from pyproj import Transformer
from rasterio.enums import Resampling
from scipy.ndimage import uniform_filter

from app.services.raster import read_cog_to_grid
from app.services.stac_client import search_items, signed_href

logger = logging.getLogger(__name__)

ST_SCALE = 0.00341802
ST_OFFSET = 149.0
ANOMALY_K = 8.0
ABS_K = 320.0
MATCH_M = 1500.0


def confirm_hotspots(
    hotspots: pd.DataFrame,
    bbox: tuple[float, float, float, float],
    grid: dict,
    date_from: date,
    date_to: date,
) -> tuple[pd.DataFrame, dict]:
    if hotspots.empty:
        hotspots = hotspots.copy()
        hotspots["landsat_confirmed"] = False
        return hotspots, {"scenes": [], "hot_pixels": 0, "confirmed": 0}

    items = search_items(
        collections=["landsat-c2-l2"],
        bbox=bbox,
        datetime=f"{date_from.isoformat()}/{date_to.isoformat()}",
        query={"eo:cloud_cover": {"lt": 40}},
        max_items=12,
    )
    if not items:
        result = hotspots.copy()
        result["landsat_confirmed"] = False
        return result, {"scenes": [], "hot_pixels": 0, "confirmed": 0, "note": "no_landsat_scene"}

    items = sorted(items, key=lambda it: it.properties.get("eo:cloud_cover", 100))[:3]
    hot_mask = np.zeros((grid["height"], grid["width"]), dtype=bool)
    used = []
    for item in items:
        try:
            st = _read_surface_temp(item, grid)
            qa = _read_qa(item, grid)
        except Exception:
            logger.exception("Landsat TIRS read failed for %s", item.id)
            continue
        if st is None:
            continue
        if qa is not None:
            cloud = _landsat_cloud(qa)
            st = np.where(cloud, np.nan, st)
        local = uniform_filter(np.nan_to_num(st, nan=np.nanmedian(st)), size=21)
        anomaly = st - local
        hot_mask |= (anomaly >= ANOMALY_K) & (st >= ABS_K) & np.isfinite(st)
        used.append({"id": item.id, "datetime": item.datetime.isoformat() if item.datetime else None})

    ys, xs = np.where(hot_mask)
    transformer = Transformer.from_crs(grid["crs"], "EPSG:4326", always_xy=True)
    confirmed = np.zeros(len(hotspots), dtype=bool)
    if len(xs):
        # convert pixel centers to lon/lat and match large hotspots
        from rasterio.transform import xy

        px_lons, px_lats = [], []
        for x, y in zip(xs[:: max(1, len(xs) // 4000)], ys[:: max(1, len(ys) // 4000)]):
            easting, northing = xy(grid["transform"], y, x)
            lon, lat = transformer.transform(easting, northing)
            px_lons.append(lon)
            px_lats.append(lat)
        px_lons = np.array(px_lons)
        px_lats = np.array(px_lats)
        cluster_sizes = hotspots.groupby("cluster_id")["cluster_id"].transform("size")
        large = (hotspots["frp"].fillna(0) >= 15) | (cluster_sizes.fillna(1) >= 3)
        to_utm = Transformer.from_crs("EPSG:4326", grid["crs"], always_xy=True)
        hx, hy = to_utm.transform(hotspots["longitude"].to_numpy(), hotspots["latitude"].to_numpy())
        px, py = to_utm.transform(px_lons, px_lats)
        for i, (x0, y0, is_large) in enumerate(zip(hx, hy, large.to_numpy())):
            if not is_large:
                continue
            dist2 = (px - x0) ** 2 + (py - y0) ** 2
            if dist2.min() <= MATCH_M**2:
                confirmed[i] = True

    result = hotspots.copy()
    result["landsat_confirmed"] = confirmed
    meta = {
        "scenes": used,
        "hot_pixels": int(hot_mask.sum()),
        "confirmed": int(confirmed.sum()),
    }
    return result, meta


def _read_surface_temp(item, grid) -> np.ndarray | None:
    key = next((k for k in ("lwir11", "ST_B10", "st_b10", "lwir") if k in item.assets), None)
    if key is None:
        return None
    href = signed_href(item, key)
    data = read_cog_to_grid(href, grid, resampling=Resampling.bilinear)
    scale, offset = _scale_offset(item, key, ST_SCALE, ST_OFFSET)
    kelvin = data * scale + offset
    kelvin = np.where((kelvin < 200) | (kelvin > 400), np.nan, kelvin)
    return kelvin.astype("float32")


def _read_qa(item, grid) -> np.ndarray | None:
    key = next((k for k in ("qa_pixel", "QA_PIXEL") if k in item.assets), None)
    if key is None:
        return None
    href = signed_href(item, key)
    return read_cog_to_grid(href, grid, resampling=Resampling.nearest)


def _landsat_cloud(qa: np.ndarray) -> np.ndarray:
    bits = np.nan_to_num(qa, nan=0).astype(np.uint16)
    dilated = (bits & (1 << 1)) > 0
    cirrus = (bits & (1 << 2)) > 0
    cloud = (bits & (1 << 3)) > 0
    shadow = (bits & (1 << 4)) > 0
    return dilated | cirrus | cloud | shadow


def _scale_offset(item, key: str, default_scale: float, default_offset: float) -> tuple[float, float]:
    extra = item.assets[key].extra_fields or {}
    raster = extra.get("raster:bands") or extra.get("raster_bands") or []
    if raster:
        band = raster[0]
        return float(band.get("scale", default_scale)), float(band.get("offset", default_offset))
    return default_scale, default_offset
