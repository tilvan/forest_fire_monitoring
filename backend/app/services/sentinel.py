from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import pystac
from rasterio.enums import Resampling

from app.services.raster import read_cog_to_grid
from app.services.stac_client import search_items, signed_href

logger = logging.getLogger(__name__)

SCL_INVALID = {0, 1, 3, 8, 9, 10}
CLOUD_QUERY = {"eo:cloud_cover": {"lt": 60}}


def pick_pre_post_windows(
    date_from: date,
    date_to: date,
    hotspot_dates: list[date],
) -> tuple[tuple[date, date], tuple[date, date]]:
    first = min(hotspot_dates) if hotspot_dates else date_from
    last = max(hotspot_dates) if hotspot_dates else date_to
    pre = (first - timedelta(days=60), first - timedelta(days=5))
    post = (last, last + timedelta(days=30))
    if pre[1] < pre[0]:
        pre = (pre[0], pre[0])
    return pre, post


def load_nbr_pair(
    bbox: tuple[float, float, float, float],
    grid: dict,
    pre_window: tuple[date, date],
    post_window: tuple[date, date],
) -> dict:
    pre = _load_nbr_scene(bbox, grid, pre_window, "pre-fire")
    post = _load_nbr_scene(bbox, grid, post_window, "post-fire")
    degraded = pre["degraded"] or post["degraded"]
    nbr_pre = pre["nbr"]
    nbr_post = post["nbr"]
    valid = np.isfinite(nbr_pre) & np.isfinite(nbr_post)
    dnbr = np.full(nbr_pre.shape, np.nan, dtype="float32")
    dnbr[valid] = nbr_pre[valid] - nbr_post[valid]
    return {
        "dnbr": dnbr,
        "valid": valid,
        "degraded": degraded,
        "pre_scenes": pre["scenes"],
        "post_scenes": post["scenes"],
        "pre_valid_fraction": pre["valid_fraction"],
        "post_valid_fraction": post["valid_fraction"],
    }


def _load_nbr_scene(
    bbox: tuple[float, float, float, float],
    grid: dict,
    window: tuple[date, date],
    label: str,
) -> dict:
    start, end = window
    items = search_items(
        collections=["sentinel-2-l2a"],
        bbox=bbox,
        datetime=f"{start.isoformat()}/{end.isoformat()}",
        query=CLOUD_QUERY,
        max_items=80,
    )
    if not items:
        items = search_items(
            collections=["sentinel-2-l2a"],
            bbox=bbox,
            datetime=f"{start.isoformat()}/{end.isoformat()}",
            max_items=80,
        )
    if not items:
        raise RuntimeError(f"Нет сцен Sentinel-2 для окна {label} {start}–{end}")

    groups = _group_by_date(items)
    ranked = sorted(groups.items(), key=lambda kv: kv[1]["cloud"])
    arrays = []
    used = []
    for date_key, group in ranked[:4]:
        nbr, valid_frac = _mosaic_nbr(group["items"], grid)
        if nbr is None:
            continue
        arrays.append(nbr)
        used.append(
            {
                "date": date_key.isoformat(),
                "cloud_cover": group["cloud"],
                "ids": [item.id for item in group["items"]],
            }
        )
        if valid_frac >= 0.45 and len(used) >= 1:
            break

    if not arrays:
        raise RuntimeError(f"Не удалось прочитать каналы Sentinel-2 для {label}")

    stack = np.stack(arrays, axis=0)
    with np.errstate(all="ignore"):
        composite = np.nanmedian(stack, axis=0)
    valid_fraction = float(np.isfinite(composite).mean())
    degraded = len(used) > 1 or valid_fraction < 0.5
    return {
        "nbr": composite.astype("float32"),
        "scenes": used,
        "degraded": degraded,
        "valid_fraction": valid_fraction,
    }


def _group_by_date(items: list[pystac.Item]) -> dict:
    groups: dict[date, dict] = defaultdict(lambda: {"items": [], "clouds": []})
    for item in items:
        dt = item.datetime.date() if item.datetime else date.fromisoformat(item.id[0:10])
        cloud = item.properties.get("eo:cloud_cover", 100)
        groups[dt]["items"].append(item)
        groups[dt]["clouds"].append(cloud)
    out = {}
    for dt, payload in groups.items():
        out[dt] = {
            "items": payload["items"],
            "cloud": float(np.mean(payload["clouds"])) if payload["clouds"] else 100.0,
        }
    return out


def _mosaic_nbr(items: list[pystac.Item], grid: dict) -> tuple[np.ndarray | None, float]:
    nbrs = []
    for item in items:
        try:
            nir = _read_band(item, ("B8A", "B08", "b8a", "b08"), grid, Resampling.bilinear)
            swir = _read_band(item, ("B12", "b12"), grid, Resampling.bilinear)
            scl = _read_band(item, ("SCL", "scl"), grid, Resampling.nearest)
        except Exception:
            logger.exception("Failed reading Sentinel-2 item %s", item.id)
            continue
        invalid = np.isin(np.nan_to_num(scl, nan=0), list(SCL_INVALID)) | ~np.isfinite(nir) | ~np.isfinite(swir)
        denom = nir + swir
        nbr = np.full(nir.shape, np.nan, dtype="float32")
        ok = ~invalid & (np.abs(denom) > 1e-6)
        nbr[ok] = (nir[ok] - swir[ok]) / denom[ok]
        nbrs.append(nbr)
    if not nbrs:
        return None, 0.0
    stack = np.stack(nbrs, axis=0)
    with np.errstate(all="ignore"):
        mosaic = np.nanmedian(stack, axis=0)
    return mosaic, float(np.isfinite(mosaic).mean())


def _read_band(item: pystac.Item, keys: tuple[str, ...], grid: dict, resampling: Resampling) -> np.ndarray:
    asset_key = next((k for k in keys if k in item.assets), None)
    if asset_key is None:
        raise KeyError(f"No asset {keys} in {item.id}: {list(item.assets)}")
    href = signed_href(item, asset_key)
    return read_cog_to_grid(href, grid, resampling=resampling)
