from __future__ import annotations

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform as warp_transform
from rasterio.warp import transform_bounds

GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff,.TIF,.TIFF",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MULTIPLEX": "YES",
    "GDAL_HTTP_VERSION": "2",
    "CPL_VSIL_CURL_USE_HEAD": "NO",
    "GDAL_HTTP_TIMEOUT": "60",
    "GDAL_HTTP_CONNECTTIMEOUT": "30",
}


def rasterio_env():
    return rasterio.Env(**GDAL_ENV)


def read_cog_to_grid(
    href: str,
    grid: dict,
    resampling: Resampling = Resampling.bilinear,
    band: int = 1,
) -> np.ndarray:
    with rasterio_env():
        with rasterio.open(href) as src:
            with WarpedVRT(
                src,
                crs=grid["crs"],
                transform=grid["transform"],
                width=grid["width"],
                height=grid["height"],
                resampling=resampling,
            ) as vrt:
                data = vrt.read(band).astype("float32")
                nodata = vrt.nodata
    if nodata is not None:
        data = np.where(data == nodata, np.nan, data)
    return data


def sample_cog(href: str, lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
    with rasterio_env():
        with rasterio.open(href) as src:
            xs, ys = warp_transform("EPSG:4326", src.crs, lons.tolist(), lats.tolist())
            values = np.array(list(src.sample(zip(xs, ys))), dtype="float32").ravel()
            nodata = src.nodata
    if nodata is not None:
        values = np.where(values == nodata, np.nan, values)
    return values


def grid_bounds_wgs84(grid: dict) -> tuple[float, float, float, float]:
    return transform_bounds(grid["crs"], "EPSG:4326", *grid["bounds"], densify_pts=21)
