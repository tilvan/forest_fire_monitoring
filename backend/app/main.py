from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.geo import bbox_area_km2
from app.models import JobPublic, JobRequest
from app.pipeline import run_pipeline
from app import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fire-job")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    yield
    executor.shutdown(wait=False)


app = FastAPI(title="Forest Fire Monitor", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "firms_key": bool(settings.firms_map_key),
        "max_aoi_km2": settings.max_aoi_km2,
        "max_date_span_days": settings.max_date_span_days,
    }


@app.post("/api/jobs", response_model=JobPublic)
def create_job(payload: JobRequest) -> JobPublic:
    west, south, east, north = payload.bbox
    area = bbox_area_km2(west, south, east, north)
    if area > settings.max_aoi_km2:
        raise HTTPException(
            status_code=400,
            detail=f"Область {area:.0f} км² больше лимита {settings.max_aoi_km2:.0f} км²",
        )
    span = (payload.date_to - payload.date_from).days + 1
    if span > settings.max_date_span_days:
        raise HTTPException(
            status_code=400,
            detail=f"Интервал дат {span} дн. больше лимита {settings.max_date_span_days} дн.",
        )
    if not settings.firms_map_key:
        raise HTTPException(
            status_code=400,
            detail="Не задан FIRMS_MAP_KEY. Добавьте ключ в backend/.env",
        )
    job = store.create_job(payload, area)
    executor.submit(run_pipeline, job.id, payload.model_copy())
    return job


@app.get("/api/jobs/{job_id}", response_model=JobPublic)
def get_job(job_id: str) -> JobPublic:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return job


@app.get("/api/jobs/{job_id}/hotspots")
def get_hotspots(job_id: str):
    return _geojson(job_id, "hotspots")


@app.get("/api/jobs/{job_id}/rejected")
def get_rejected(job_id: str):
    return _geojson(job_id, "rejected")


@app.get("/api/jobs/{job_id}/burns")
def get_burns(job_id: str):
    return _geojson(job_id, "burns")


@app.get("/api/jobs/{job_id}/summary")
def get_summary(job_id: str):
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if job.summary is None:
        raise HTTPException(status_code=404, detail="Сводка ещё не готова")
    return job.summary


def _geojson(job_id: str, name: str):
    if store.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    payload = store.read_geojson(job_id, name)
    if payload is None:
        raise HTTPException(status_code=404, detail="Слой ещё не готов")
    return payload
