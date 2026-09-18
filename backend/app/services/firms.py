from __future__ import annotations

from datetime import date, timedelta
from io import StringIO

import httpx
import pandas as pd

from app.config import settings

FIRMS_AREA = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

NRT_SOURCES = (
    "MODIS_NRT",
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
)
SP_SOURCES = (
    "MODIS_SP",
    "VIIRS_SNPP_SP",
    "VIIRS_NOAA20_SP",
)

# Standard processing typically lags NRT by 1–3 months.
SP_LAG_DAYS = 60


def fetch_hotspots(
    bbox: tuple[float, float, float, float],
    date_from: date,
    date_to: date,
    client: httpx.Client | None = None,
) -> pd.DataFrame:
    if not settings.firms_map_key:
        raise RuntimeError(
            "Не задан FIRMS_MAP_KEY. Получите ключ на https://firms.modaps.eosdis.nasa.gov/api/area/"
        )

    own_client = client is None
    client = client or httpx.Client(timeout=90.0)
    frames: list[pd.DataFrame] = []
    try:
        for start, day_range, sources in _windows_and_sources(date_from, date_to):
            for source in sources:
                frames.append(_fetch_window(client, bbox, source, day_range, start))
    finally:
        if own_client:
            client.close()

    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return _empty_frame()

    df = pd.concat(frames, ignore_index=True)
    df = _normalize(df)
    df = df.drop_duplicates(
        subset=["latitude", "longitude", "acq_date", "acq_time", "satellite", "instrument"]
    )
    return df.reset_index(drop=True)


def _windows_and_sources(date_from: date, date_to: date):
    sp_cutoff = date.today() - timedelta(days=SP_LAG_DAYS)
    current = date_from
    while current <= date_to:
        chunk_end = min(current + timedelta(days=4), date_to)
        day_range = (chunk_end - current).days + 1
        if chunk_end < sp_cutoff:
            sources = SP_SOURCES
        elif current >= sp_cutoff:
            sources = NRT_SOURCES
        else:
            sources = tuple(dict.fromkeys(SP_SOURCES + NRT_SOURCES))
        yield current, day_range, sources
        current = chunk_end + timedelta(days=1)


def _fetch_window(
    client: httpx.Client,
    bbox: tuple[float, float, float, float],
    source: str,
    day_range: int,
    start: date,
) -> pd.DataFrame:
    west, south, east, north = bbox
    area = f"{west},{south},{east},{north}"
    url = f"{FIRMS_AREA}/{settings.firms_map_key}/{source}/{area}/{day_range}/{start.isoformat()}"
    response = client.get(url)
    response.raise_for_status()
    text = response.text.strip()
    if "latitude" not in text.lower():
        lowered = text.lower()
        if "invalid" in lowered or "error" in lowered or "unauthorized" in lowered:
            raise RuntimeError(f"FIRMS {source}: {text[:200]}")
        return _empty_frame()
    df = pd.read_csv(StringIO(text))
    if df.empty or "latitude" not in df.columns:
        return _empty_frame()
    df["source"] = source
    return df


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [c.strip().lower() for c in out.columns]
    if "frp" not in out.columns:
        out["frp"] = pd.NA
    if "type" not in out.columns:
        out["type"] = 0
    if "daynight" not in out.columns:
        out["daynight"] = ""
    brightness = out.get("brightness", out.get("bright_ti4"))
    out["brightness"] = pd.to_numeric(brightness, errors="coerce")
    out["frp"] = pd.to_numeric(out["frp"], errors="coerce")
    out["latitude"] = pd.to_numeric(out["latitude"], errors="coerce")
    out["longitude"] = pd.to_numeric(out["longitude"], errors="coerce")
    out["acq_date"] = pd.to_datetime(out["acq_date"]).dt.date
    out["acq_time"] = out["acq_time"].astype(str).str.zfill(4)
    out["confidence_level"] = out["confidence"].map(_confidence_level)
    out["sensor_group"] = out["source"].map(_sensor_group)
    return out.dropna(subset=["latitude", "longitude", "acq_date"])


def _confidence_level(value) -> str:
    if pd.isna(value):
        return "nominal"
    if isinstance(value, str):
        letter = value.strip().lower()[:1]
        return {"l": "low", "n": "nominal", "h": "high"}.get(letter, "nominal")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "nominal"
    if number < 30:
        return "low"
    if number < 80:
        return "nominal"
    return "high"


def _sensor_group(source: str) -> str:
    source = source.upper()
    if source.startswith("MODIS"):
        return "MODIS"
    if "VIIRS" in source:
        return "VIIRS"
    return source


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "latitude",
            "longitude",
            "acq_date",
            "acq_time",
            "satellite",
            "instrument",
            "confidence",
            "confidence_level",
            "frp",
            "daynight",
            "type",
            "source",
            "sensor_group",
            "brightness",
        ]
    )
