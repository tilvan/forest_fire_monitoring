from __future__ import annotations

import numpy as np
import pandas as pd
from rasterio.features import shapes
from scipy.ndimage import binary_closing, binary_opening
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from app.services.worldcover import forest_mask

# USGS / Key & Benson dNBR classes
CLASS_LABELS = {
    1: "low",
    2: "moderate",
    3: "high",
    4: "very_high",
}
CLASS_TITLES = {
    1: "слабое",
    2: "умеренное",
    3: "сильное",
    4: "очень сильное",
}


def classify_dnbr(dnbr: np.ndarray) -> np.ndarray:
    classified = np.zeros(dnbr.shape, dtype=np.uint8)
    valid = np.isfinite(dnbr)
    classified[(dnbr >= 0.10) & (dnbr < 0.27) & valid] = 1
    classified[(dnbr >= 0.27) & (dnbr < 0.44) & valid] = 2
    classified[(dnbr >= 0.44) & (dnbr < 0.66) & valid] = 3
    classified[(dnbr >= 0.66) & valid] = 4
    return classified


def map_burns(
    dnbr: np.ndarray,
    grid: dict,
    bbox: tuple[float, float, float, float],
    hotspots: pd.DataFrame,
) -> tuple[dict, dict]:
    classified = classify_dnbr(dnbr)
    trees = forest_mask(grid, bbox)
    forest_available = trees is not None
    if trees is not None:
        classified = np.where(trees, classified, 0)
        forest_pixels = int(trees.sum())
    else:
        forest_pixels = int(np.isfinite(dnbr).sum())

    burned = classified >= 1
    if burned.any():
        burned = binary_opening(burned, iterations=1)
        burned = binary_closing(burned, iterations=2)
        classified = np.where(burned, classified, 0)

    pixel_ha = (grid["resolution_m"] ** 2) / 10_000.0
    forest_ha = forest_pixels * pixel_ha

    hotspot_union = _hotspot_buffer(hotspots, grid)
    features = []
    by_class_ha = {label: 0.0 for label in CLASS_LABELS.values()}
    uncertain_ha = 0.0

    mask = classified >= 1
    if mask.any():
        for geom, value in shapes(
            classified.astype(np.int16),
            mask=mask,
            transform=grid["transform"],
        ):
            value = int(value)
            if value < 1:
                continue
            poly = shape(geom)
            if poly.is_empty or poly.area <= 0:
                continue
            area_ha = poly.area / 10_000.0
            if area_ha < 0.5:
                continue
            near = True
            if hotspot_union is not None:
                near = poly.intersects(hotspot_union)
            label = CLASS_LABELS[value]
            by_class_ha[label] += area_ha
            if not near:
                uncertain_ha += area_ha
            features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(poly),
                    "properties": {
                        "severity": value,
                        "severity_label": label,
                        "severity_title": CLASS_TITLES[value],
                        "area_ha": round(area_ha, 2),
                        "near_hotspot": near,
                    },
                    "crs": None,
                }
            )

    geojson = {
        "type": "FeatureCollection",
        "crs": {
            "type": "name",
            "properties": {"name": grid["crs"].to_string()},
        },
        "features": [
            {
                "type": "Feature",
                "geometry": _to_wgs84(feat["geometry"], grid),
                "properties": feat["properties"],
            }
            for feat in features
        ],
    }

    burned_ha = sum(by_class_ha.values())
    summary = {
        "burned_ha": round(burned_ha, 2),
        "by_class_ha": {k: round(v, 2) for k, v in by_class_ha.items()},
        "uncertain_ha": round(uncertain_ha, 2),
        "forest_ha": round(forest_ha, 2),
        "forest_share": round(burned_ha / forest_ha, 4) if forest_ha else None,
        "forest_mask": forest_available,
        "polygon_count": len(features),
    }
    return geojson, summary


def _hotspot_buffer(hotspots: pd.DataFrame, grid: dict):
    if hotspots is None or hotspots.empty:
        return None
    from pyproj import Transformer
    from shapely.geometry import Point

    transformer = Transformer.from_crs("EPSG:4326", grid["crs"], always_xy=True)
    buffers = []
    for _, row in hotspots.iterrows():
        x, y = transformer.transform(row["longitude"], row["latitude"])
        buffers.append(Point(x, y).buffer(3000))
    if not buffers:
        return None
    return unary_union(buffers)


def _to_wgs84(geom: dict, grid: dict) -> dict:
    from pyproj import Transformer
    from shapely.ops import transform

    transformer = Transformer.from_crs(grid["crs"], "EPSG:4326", always_xy=True)
    shp = shape(geom)
    return mapping(transform(transformer.transform, shp))
