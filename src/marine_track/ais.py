from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from marine_track.estimation import (
    LonLat,
    bearing_deg,
    haversine_distance_m,
    speed_from_displacement,
)
from marine_track.models import VesselDetection


@dataclass(frozen=True)
class AISPoint:
    mmsi: str
    time: datetime
    lon: float
    lat: float
    sog_knots: float | None = None
    cog_deg: float | None = None
    interpolation_gap_s: float = 0.0
    nearest_time_offset_s: float = 0.0
    before_time: datetime | None = None
    after_time: datetime | None = None


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


def _optional_float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _interpolate_optional(before: object, after: object, ratio: float) -> float | None:
    left = _optional_float(before)
    right = _optional_float(after)
    if left is not None and right is not None:
        return left + ratio * (right - left)
    return left if left is not None else right


def _interpolate_heading(before: object, after: object, ratio: float) -> float | None:
    left = _optional_float(before)
    right = _optional_float(after)
    if left is None:
        return right % 360.0 if right is not None else None
    if right is None:
        return left % 360.0
    delta = ((right - left + 180.0) % 360.0) - 180.0
    return (left + ratio * delta) % 360.0


def interpolate_track_position(
    group: pd.DataFrame,
    target_time: datetime,
    max_gap: timedelta | None = None,
) -> AISPoint | None:
    """Interpolate one MMSI track with an explicit interpolation-gap gate."""

    if target_time.tzinfo is None:
        target_time = target_time.replace(tzinfo=timezone.utc)
    target = pd.Timestamp(target_time)
    before = group[group["time"] <= target].tail(1)
    after = group[group["time"] >= target].head(1)
    if before.empty or after.empty:
        return None

    b = before.iloc[0]
    a = after.iloc[0]
    total_s = float((a["time"] - b["time"]).total_seconds())
    if total_s < 0:
        return None
    if max_gap is not None and total_s > max_gap.total_seconds():
        return None
    ratio = 0.0 if total_s == 0 else float((target - b["time"]).total_seconds()) / total_s
    ratio = max(0.0, min(1.0, ratio))

    lon = float(b["lon"] + ratio * (a["lon"] - b["lon"]))
    lat = float(b["lat"] + ratio * (a["lat"] - b["lat"]))
    start = LonLat(lon=float(b["lon"]), lat=float(b["lat"]))
    end = LonLat(lon=float(a["lon"]), lat=float(a["lat"]))
    distance_m = haversine_distance_m(start, end)

    computed_sog: float | None = None
    computed_cog: float | None = None
    if total_s > 0 and distance_m > 0:
        _, computed_sog = speed_from_displacement(distance_m, total_s)
        computed_cog = bearing_deg(start, end)

    reported_sog = _interpolate_optional(b.get("sog_knots"), a.get("sog_knots"), ratio)
    reported_cog = _interpolate_heading(b.get("cog_deg"), a.get("cog_deg"), ratio)
    before_offset = abs(float((target - b["time"]).total_seconds()))
    after_offset = abs(float((a["time"] - target).total_seconds()))

    return AISPoint(
        mmsi=str(b["mmsi"]),
        time=target.to_pydatetime(),
        lon=lon,
        lat=lat,
        sog_knots=reported_sog if reported_sog is not None else computed_sog,
        cog_deg=reported_cog if reported_cog is not None else computed_cog,
        interpolation_gap_s=total_s,
        nearest_time_offset_s=min(before_offset, after_offset),
        before_time=b["time"].to_pydatetime(),
        after_time=a["time"].to_pydatetime(),
    )


def _candidate_matches(
    detection: VesselDetection,
    ais_df: pd.DataFrame,
    *,
    time_window: timedelta,
    max_distance_m: float,
    max_interpolation_gap: timedelta,
) -> list[dict[str, object]]:
    timestamp = pd.Timestamp(detection.acquisition_time)
    window = ais_df[
        (ais_df["time"] >= timestamp - time_window)
        & (ais_df["time"] <= timestamp + time_window)
    ]
    if window.empty:
        return []

    det_point = LonLat(lon=detection.lon, lat=detection.lat)
    matches: list[dict[str, object]] = []
    for _, group in window.groupby("mmsi"):
        point = interpolate_track_position(
            group,
            detection.acquisition_time,
            max_gap=max_interpolation_gap,
        )
        if point is None:
            continue
        distance_m = haversine_distance_m(det_point, LonLat(lon=point.lon, lat=point.lat))
        if distance_m > max_distance_m:
            continue
        matches.append(
            {
                "mmsi": point.mmsi,
                "distance_m": float(distance_m),
                "ais_lon": point.lon,
                "ais_lat": point.lat,
                "ais_sog_knots": point.sog_knots,
                "ais_cog_deg": point.cog_deg,
                "interpolation_gap_s": point.interpolation_gap_s,
                "nearest_time_offset_s": point.nearest_time_offset_s,
                "before_time": point.before_time.isoformat() if point.before_time else None,
                "after_time": point.after_time.isoformat() if point.after_time else None,
            }
        )
    return sorted(matches, key=lambda item: (float(item["distance_m"]), str(item["mmsi"])))


def match_detection_to_ais(
    detection: VesselDetection,
    ais_df: pd.DataFrame,
    time_window: timedelta = timedelta(minutes=30),
    max_distance_m: float = 3000.0,
    max_interpolation_gap: timedelta = timedelta(minutes=20),
    ambiguity_margin_m: float = 500.0,
) -> dict[str, object] | None:
    """Return the nearest gated AIS reference for one candidate.

    This compatibility helper does not claim ground truth. Multi-candidate pipeline
    enrichment uses :func:`assign_detections_to_ais` for one-to-one assignment.
    """

    matches = _candidate_matches(
        detection,
        ais_df,
        time_window=time_window,
        max_distance_m=max_distance_m,
        max_interpolation_gap=max_interpolation_gap,
    )
    if not matches:
        return None
    selected = dict(matches[0])
    second_distance = float(matches[1]["distance_m"]) if len(matches) > 1 else None
    margin = second_distance - float(selected["distance_m"]) if second_distance is not None else None
    ambiguous = margin is not None and margin < ambiguity_margin_m
    selected.update(
        status="ambiguous" if ambiguous else "matched",
        reference_quality="ambiguous" if ambiguous else "usable",
        second_best_distance_m=second_distance,
        distance_margin_m=margin,
        assignment_method="nearest_single_candidate",
        not_ground_truth=True,
    )
    return selected


def assign_detections_to_ais(
    detections: list[VesselDetection],
    ais_df: pd.DataFrame,
    *,
    time_window: timedelta = timedelta(minutes=30),
    max_distance_m: float = 3000.0,
    max_interpolation_gap: timedelta = timedelta(minutes=20),
    ambiguity_margin_m: float = 500.0,
) -> dict[str, dict[str, object]]:
    """Assign each MMSI to at most one candidate using deterministic distance order."""

    candidates_by_detection: dict[str, list[dict[str, object]]] = {}
    pairs: list[tuple[float, str, str, dict[str, object]]] = []
    for detection in detections:
        candidates = _candidate_matches(
            detection,
            ais_df,
            time_window=time_window,
            max_distance_m=max_distance_m,
            max_interpolation_gap=max_interpolation_gap,
        )
        candidates_by_detection[detection.detection_id] = candidates
        for item in candidates:
            pairs.append(
                (
                    float(item["distance_m"]),
                    detection.detection_id,
                    str(item["mmsi"]),
                    item,
                )
            )

    assignments: dict[str, dict[str, object]] = {}
    used_detections: set[str] = set()
    used_mmsi: set[str] = set()
    for _, detection_id, mmsi, item in sorted(pairs, key=lambda row: (row[0], row[1], row[2])):
        if detection_id in used_detections or mmsi in used_mmsi:
            continue
        selected = dict(item)
        alternatives = [
            candidate
            for candidate in candidates_by_detection[detection_id]
            if str(candidate["mmsi"]) != mmsi
        ]
        second_distance = float(alternatives[0]["distance_m"]) if alternatives else None
        margin = second_distance - float(selected["distance_m"]) if second_distance is not None else None
        ambiguous = margin is not None and margin < ambiguity_margin_m
        selected.update(
            status="ambiguous" if ambiguous else "matched",
            reference_quality="ambiguous" if ambiguous else "usable",
            second_best_distance_m=second_distance,
            distance_margin_m=margin,
            assignment_method="greedy_one_to_one_distance",
            not_ground_truth=True,
        )
        assignments[detection_id] = selected
        used_detections.add(detection_id)
        used_mmsi.add(mmsi)
    return assignments
