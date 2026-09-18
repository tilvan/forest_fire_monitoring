from __future__ import annotations

from pyproj import CRS, Geod, Transformer
from rasterio.crs import CRS as RioCRS
from rasterio.transform import from_origin

GEOD = Geod(ellps="WGS84")
MAX_PIXELS = 12_000_000
TARGET_RES_M = 20.0


def bbox_area_km2(west: float, south: float, east: float, north: float) -> float:
    lons = [west, east, east, west, west]
    lats = [south, south, north, north, south]
    area_m2, _ = GEOD.polygon_area_perimeter(lons, lats)
    return abs(area_m2) / 1_000_000.0


def utm_crs(west: float, south: float, east: float, north: float) -> CRS:
    lon = (west + east) / 2.0
    lat = (south + north) / 2.0
    zone = int((lon + 180) // 6) + 1
    epsg = (32600 if lat >= 0 else 32700) + zone
    return CRS.from_epsg(epsg)


def make_grid(bbox: tuple[float, float, float, float], resolution_m: float = TARGET_RES_M):
    west, south, east, north = bbox
    crs = utm_crs(west, south, east, north)
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    x0, y0 = transformer.transform(west, south)
    x1, y1 = transformer.transform(east, north)
    x2, y2 = transformer.transform(west, north)
    x3, y3 = transformer.transform(east, south)
    xmin = min(x0, x1, x2, x3)
    xmax = max(x0, x1, x2, x3)
    ymin = min(y0, y1, y2, y3)
    ymax = max(y0, y1, y2, y3)

    width = max(1, int(round((xmax - xmin) / resolution_m)))
    height = max(1, int(round((ymax - ymin) / resolution_m)))
    if width * height > MAX_PIXELS:
        scale = (width * height / MAX_PIXELS) ** 0.5
        resolution_m *= scale
        width = max(1, int(round((xmax - xmin) / resolution_m)))
        height = max(1, int(round((ymax - ymin) / resolution_m)))

    transform = from_origin(xmin, ymax, resolution_m, resolution_m)
    return {
        "crs": RioCRS.from_wkt(crs.to_wkt()),
        "transform": transform,
        "width": width,
        "height": height,
        "resolution_m": resolution_m,
        "bounds": (xmin, ymin, xmax, ymax),
    }
