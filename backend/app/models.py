from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


Bbox = tuple[float, float, float, float]


class JobRequest(BaseModel):
    bbox: tuple[float, float, float, float] = Field(
        description="west, south, east, north in WGS84"
    )
    date_from: date
    date_to: date

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: Bbox) -> Bbox:
        west, south, east, north = value
        if west >= east or south >= north:
            raise ValueError("bbox must be (west, south, east, north) with west < east and south < north")
        if west < -180 or east > 180 or south < -90 or north > 90:
            raise ValueError("bbox is outside WGS84 bounds")
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> JobRequest:
        if self.date_to < self.date_from:
            raise ValueError("date_to must be on or after date_from")
        return self


JobStatus = Literal["queued", "hotspots", "burns", "done", "error"]


class JobPublic(BaseModel):
    id: str
    status: JobStatus
    message: str
    bbox: Bbox
    date_from: date
    date_to: date
    error: str | None = None
    area_km2: float | None = None
    summary: dict | None = None
