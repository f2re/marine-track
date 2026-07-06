from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from marine_track.estimation import LonLat, bearing_deg, haversine_distance_m, speed_from_displacement
from marine_track.models import VesselDetection


@dataclass(frozen=True)
class AISPoint:
    mmsi: str
    time: datetime
    lon: float
    lat: float
    sog_knots: float | None = None
    cog_deg: float | None = None


def read_ais_csv(path: str | Path) -> pd.DataFrame:
    """Read a normalized AIS CSV.

    Required columns: mmsi, time, lon, lat.
    Optional columns: sog_knots, cog_deg.
    """
    df = pd.read_csv(path)
    required = {"mmsi", "time", "lon", "lat"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"AIS CSV missing columns: {sorted(missing)}")
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.dropna(subset=["mmsi", "time", "lon", "lat"])
    df = df.sort_values(["mmsi", "time"])
    return df


def interpolate_track_position(group: pd.DataFrame, target_time: datetime) -> AISPoint | None:
    """Linearly interpolate one MMSI track to target_time."""
    if target_time.tzinfo is None:
        target_time = target_time.replace(tzinfo=pd.Timestamp.utcnow().tzinfo)
    target = pd.Timestamp(target_time)
    before = group[group["time"] <= target].tail(1)
    after = group[group["time"] >= target].head(1)
    if before.empty or after.empty:
        return None

    b = before.iloc[0]
    a = after.iloc[0]
    total_s = (a["time"] - b["time"]).total_seconds()
    if total_s == 0:
        ratio = 0.0
    else:
        ratio = (target - b["time"]).total_seconds() / total_s

    lon = float(b["lon"] + ratio * (a["lon"] - b["lon"]))
    lat = float(b["lat"] + ratio * (a["lat"] - b["lat"]))
    start = LonLat(lon=float(b["lon"]), lat=float(b["lat"]))
    end = LonLat(lon=float(a["lon"]), lat=float(a["lat"]))
    distance_m = haversine_distance_m(start, end)
    sog_knots = None
    cog_deg = None
    if total_s > 0 and distance_m > 0:
        _, sog_knots = speed_from_displacement(distance_m, total_s)
        cog_deg = bearing_deg(start, end)

    return AISPoint(
        mmsi=str(b["mmsi"]),
        time=target.to_pydatetime(),
        lon=lon,
        lat=lat,
        sog_knots=sog_knots,
        cog_deg=cog_deg,
    )


def match_detection_to_ais(
    detection: VesselDetection,
    ais_df: pd.DataFrame,
    time_window: timedelta = timedelta(minutes=30),
    max_distance_m: float = 3000.0,
) -> dict[str, object] | None:
    """Find the nearest AIS track point interpolated to the detection time."""
    t = pd.Timestamp(detection.acquisition_time)
    window = ais_df[(ais_df["time"] >= t - time_window) & (ais_df["time"] <= t + time_window)]
    if window.empty:
        return None

    det_point = LonLat(lon=detection.lon, lat=detection.lat)
    best: dict[str, object] | None = None
    for _, group in window.groupby("mmsi"):
        point = interpolate_track_position(group, detection.acquisition_time)
        if point is None:
            continue
        distance_m = haversine_distance_m(det_point, LonLat(lon=point.lon, lat=point.lat))
        if distance_m > max_distance_m:
            continue
        if best is None or distance_m < float(best["distance_m"]):
            best = {
                "mmsi": point.mmsi,
                "distance_m": distance_m,
                "ais_lon": point.lon,
                "ais_lat": point.lat,
                "ais_sog_knots": point.sog_knots,
                "ais_cog_deg": point.cog_deg,
            }
    return best
