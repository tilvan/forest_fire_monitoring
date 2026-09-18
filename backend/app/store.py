from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from app.config import settings
from app.models import JobPublic, JobRequest, JobStatus


_lock = Lock()


def _job_dir(job_id: str) -> Path:
    path = settings.data_dir / "jobs" / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _meta_path(job_id: str) -> Path:
    return _job_dir(job_id) / "job.json"


def create_job(request: JobRequest, area_km2: float) -> JobPublic:
    job_id = uuid4().hex[:12]
    job = {
        "id": job_id,
        "status": "queued",
        "message": "Задача в очереди",
        "bbox": list(request.bbox),
        "date_from": request.date_from.isoformat(),
        "date_to": request.date_to.isoformat(),
        "error": None,
        "area_km2": area_km2,
        "summary": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_meta(job)
    return _to_public(job)


def get_job(job_id: str) -> JobPublic | None:
    path = _meta_path(job_id)
    if not path.exists():
        return None
    return _to_public(json.loads(path.read_text()))


def update_job(
    job_id: str,
    *,
    status: JobStatus | None = None,
    message: str | None = None,
    error: str | None = None,
    summary: dict | None = None,
) -> JobPublic:
    with _lock:
        path = _meta_path(job_id)
        job = json.loads(path.read_text())
        if status is not None:
            job["status"] = status
        if message is not None:
            job["message"] = message
        if error is not None:
            job["error"] = error
        if summary is not None:
            job["summary"] = summary
        _write_meta(job)
    return _to_public(job)


def write_geojson(job_id: str, name: str, payload: dict[str, Any]) -> Path:
    path = _job_dir(job_id) / f"{name}.geojson"
    path.write_text(json.dumps(payload, ensure_ascii=False))
    return path


def read_geojson(job_id: str, name: str) -> dict[str, Any] | None:
    path = _job_dir(job_id) / f"{name}.geojson"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _write_meta(job: dict[str, Any]) -> None:
    _meta_path(job["id"]).write_text(json.dumps(job, ensure_ascii=False, indent=2))


def _to_public(job: dict[str, Any]) -> JobPublic:
    return JobPublic(
        id=job["id"],
        status=job["status"],
        message=job["message"],
        bbox=tuple(job["bbox"]),
        date_from=job["date_from"],
        date_to=job["date_to"],
        error=job.get("error"),
        area_km2=job.get("area_km2"),
        summary=job.get("summary"),
    )
