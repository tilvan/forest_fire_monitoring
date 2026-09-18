from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

from app.services.worldcover import VEGETATION_FOR_HOTSPOTS, class_name, sample_landcover

EARTH_KM = 6371.0088
CLUSTER_RADIUS_KM = 2.0
TYPE_REASONS = {
    1: "volcano",
    2: "static_land_source",
    3: "offshore",
}


def filter_and_cluster(
    df: pd.DataFrame,
    bbox: tuple[float, float, float, float],
    date_from: date,
    date_to: date,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        empty = df.copy()
        empty["reject_reason"] = pd.Series(dtype=str)
        empty["cluster_id"] = pd.Series(dtype=int)
        return empty, empty

    work = df.copy()
    work["reject_reason"] = ""

    type_num = pd.to_numeric(work["type"], errors="coerce").fillna(0).astype(int)
    for code, reason in TYPE_REASONS.items():
        work.loc[(work["reject_reason"] == "") & (type_num == code), "reject_reason"] = reason

    daynight = work["daynight"].astype(str).str.upper().str[:1]
    low_day = (work["reject_reason"] == "") & (daynight == "D") & (work["confidence_level"] == "low")
    work.loc[low_day, "reject_reason"] = "daytime_low_confidence"

    pending = work["reject_reason"] == ""
    if pending.any():
        lons = work.loc[pending, "longitude"].to_numpy()
        lats = work.loc[pending, "latitude"].to_numpy()
        cover = sample_landcover(lons, lats, bbox)
        work.loc[pending, "landcover"] = cover
        codes = pd.to_numeric(work["landcover"], errors="coerce")
        not_veg = (
            pending
            & codes.notna()
            & (codes.round() != 0)
            & ~codes.round().isin(VEGETATION_FOR_HOTSPOTS)
        )
        work.loc[not_veg, "reject_reason"] = codes.loc[not_veg].map(
            lambda v: f"landcover_{class_name(v)}"
        )

    work = _mark_persistent(work, date_from, date_to)

    accepted = work[work["reject_reason"] == ""].copy()
    rejected = work[work["reject_reason"] != ""].copy()
    accepted = _cluster(accepted)
    return accepted.reset_index(drop=True), rejected.reset_index(drop=True)


def _mark_persistent(work: pd.DataFrame, date_from: date, date_to: date) -> pd.DataFrame:
    window_days = max(1, (date_to - date_from).days + 1)
    threshold = min(12, max(6, int(window_days * 0.55)))
    pending = work["reject_reason"] == ""
    if pending.sum() < threshold:
        return work
    cells = pd.DataFrame(
        {
            "cell_x": (work.loc[pending, "longitude"] / 0.02).round().astype(int),
            "cell_y": (work.loc[pending, "latitude"] / 0.02).round().astype(int),
            "acq_date": work.loc[pending, "acq_date"],
        },
        index=work.loc[pending].index,
    )
    distinct = cells.groupby(["cell_x", "cell_y"])["acq_date"].nunique()
    hot_cells = set(distinct[distinct >= threshold].index)
    if not hot_cells:
        return work
    for idx, row in cells.iterrows():
        if (row["cell_x"], row["cell_y"]) in hot_cells:
            work.at[idx, "reject_reason"] = "persistent_heat"
    return work


def _cluster(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        df["cluster_id"] = pd.Series(dtype=int)
        return df
    df = df.copy().reset_index(drop=True)
    coords = np.radians(df[["latitude", "longitude"]].to_numpy())
    db = DBSCAN(
        eps=CLUSTER_RADIUS_KM / EARTH_KM,
        min_samples=1,
        metric="haversine",
    )
    df["spatial_id"] = db.fit_predict(coords)
    cluster_id = 0
    ids = np.full(len(df), -1, dtype=int)
    for _, group in df.groupby("spatial_id"):
        ordered = group.sort_values("acq_date")
        prev = None
        current = None
        for idx, row in ordered.iterrows():
            if prev is None or (row["acq_date"] - prev).days > 5:
                current = cluster_id
                cluster_id += 1
            ids[idx] = current
            prev = row["acq_date"]
    df["cluster_id"] = ids
    return df.drop(columns=["spatial_id"])


def frames_to_geojson(df: pd.DataFrame, accepted: bool) -> dict:
    features = []
    for _, row in df.iterrows():
        props = {
            "accepted": accepted,
            "acq_date": row["acq_date"].isoformat() if hasattr(row["acq_date"], "isoformat") else str(row["acq_date"]),
            "acq_time": str(row.get("acq_time", "")),
            "satellite": str(row.get("satellite", "")),
            "instrument": str(row.get("instrument", "")),
            "sensor": str(row.get("sensor_group", "")),
            "source": str(row.get("source", "")),
            "confidence": str(row.get("confidence", "")),
            "confidence_level": str(row.get("confidence_level", "")),
            "frp": None if pd.isna(row.get("frp")) else float(row.get("frp")),
            "daynight": str(row.get("daynight", "")),
            "brightness": None if pd.isna(row.get("brightness")) else float(row.get("brightness")),
            "cluster_id": None if pd.isna(row.get("cluster_id")) else int(row.get("cluster_id")),
            "reject_reason": str(row.get("reject_reason", "")) or None,
            "landsat_confirmed": bool(row.get("landsat_confirmed", False)),
        }
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row["longitude"]), float(row["latitude"])],
                },
                "properties": props,
            }
        )
    return {"type": "FeatureCollection", "features": features}
