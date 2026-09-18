from __future__ import annotations

import logging
import traceback

from app.geo import make_grid
from app.models import JobRequest
from app.services.burns import map_burns
from app.services.firms import fetch_hotspots
from app.services.hotspots import filter_and_cluster, frames_to_geojson
from app.services.landsat import confirm_hotspots
from app.services.sentinel import load_nbr_pair, pick_pre_post_windows
from app import store

logger = logging.getLogger(__name__)


def run_pipeline(job_id: str, request: JobRequest) -> None:
    try:
        _run(job_id, request)
    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        store.update_job(
            job_id,
            status="error",
            message="Ошибка обработки",
            error=str(exc) or traceback.format_exc().splitlines()[-1],
        )


def _run(job_id: str, request: JobRequest) -> None:
    bbox = request.bbox
    store.update_job(job_id, status="hotspots", message="Загрузка очагов FIRMS (MODIS, VIIRS)")
    raw = fetch_hotspots(bbox, request.date_from, request.date_to)
    accepted, rejected = filter_and_cluster(raw, bbox, request.date_from, request.date_to)

    grid = make_grid(bbox)
    landsat_meta = {"scenes": [], "hot_pixels": 0, "confirmed": 0}
    try:
        store.update_job(job_id, message="Проверка крупных очагов по Landsat TIRS")
        accepted, landsat_meta = confirm_hotspots(
            accepted, bbox, grid, request.date_from, request.date_to
        )
    except Exception:
        logger.exception("Landsat confirmation skipped")
        accepted = accepted.copy()
        accepted["landsat_confirmed"] = False

    store.write_geojson(job_id, "hotspots", frames_to_geojson(accepted, accepted=True))
    store.write_geojson(job_id, "rejected", frames_to_geojson(rejected, accepted=False))

    store.update_job(job_id, status="burns", message="Картирование гари по Sentinel-2")
    hotspot_dates = accepted["acq_date"].tolist() if not accepted.empty else []
    pre_window, post_window = pick_pre_post_windows(
        request.date_from, request.date_to, hotspot_dates
    )

    burn_error = None
    burns = {"type": "FeatureCollection", "features": []}
    burn_summary = {
        "burned_ha": 0,
        "by_class_ha": {"low": 0, "moderate": 0, "high": 0, "very_high": 0},
        "uncertain_ha": 0,
        "forest_ha": None,
        "forest_share": None,
        "forest_mask": False,
        "polygon_count": 0,
        "degraded": False,
        "pre_scenes": [],
        "post_scenes": [],
    }
    try:
        pair = load_nbr_pair(bbox, grid, pre_window, post_window)
        burns, burn_summary = map_burns(pair["dnbr"], grid, bbox, accepted)
        burn_summary["degraded"] = pair["degraded"]
        burn_summary["pre_scenes"] = pair["pre_scenes"]
        burn_summary["post_scenes"] = pair["post_scenes"]
        burn_summary["pre_valid_fraction"] = round(pair["pre_valid_fraction"], 3)
        burn_summary["post_valid_fraction"] = round(pair["post_valid_fraction"], 3)
    except Exception as exc:
        logger.exception("Burn mapping failed")
        burn_error = str(exc)

    store.write_geojson(job_id, "burns", burns)

    summary = {
        "hotspot_count": int(len(accepted)),
        "rejected_count": int(len(rejected)),
        "cluster_count": int(accepted["cluster_id"].nunique()) if not accepted.empty else 0,
        "landsat": landsat_meta,
        "resolution_m": round(grid["resolution_m"], 1),
        "pre_window": [pre_window[0].isoformat(), pre_window[1].isoformat()],
        "post_window": [post_window[0].isoformat(), post_window[1].isoformat()],
        "burn_error": burn_error,
        **burn_summary,
    }
    message = "Готово"
    if burn_error:
        message = f"Очаги построены, гарь не рассчитана: {burn_error}"
    elif burn_summary.get("degraded"):
        message = "Готово (гарь по облачному композиту, оценка неполная)"
    store.update_job(job_id, status="done", message=message, summary=summary)
