from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from marine_track.ais import read_ais_csv

AIS_COLUMNS = ["mmsi", "time", "lon", "lat", "sog_knots", "cog_deg"]


@dataclass(frozen=True)
class AISQuery:
    west: float
    south: float
    east: float
    north: float
    start: datetime
    end: datetime


class AISProviderError(RuntimeError):
    pass


class LocalAISProvider:
    name = "local_ais"

    def __init__(self, csv_path: str | Path):
        self.csv_path = Path(csv_path)

    def fetch(self, query: AISQuery) -> pd.DataFrame:
        if not self.csv_path.is_file():
            raise AISProviderError(f"AIS CSV not found: {self.csv_path}")
        return filter_ais(read_ais_csv(self.csv_path), query)


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def filter_ais(df: pd.DataFrame, query: AISQuery) -> pd.DataFrame:
    if df.empty:
        return empty_ais_frame()
    frame = normalize_ais_frame(df)
    if frame.empty:
        return frame
    start = pd.Timestamp(normalize_utc(query.start))
    end = pd.Timestamp(normalize_utc(query.end))
    return frame[
        (frame["time"] >= start)
        & (frame["time"] <= end)
        & (frame["lon"] >= query.west)
        & (frame["lon"] <= query.east)
        & (frame["lat"] >= query.south)
        & (frame["lat"] <= query.north)
    ].reset_index(drop=True)


def normalize_ais_frame(df: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "MMSI": "mmsi",
        "BaseDateTime": "time",
        "LON": "lon",
        "LAT": "lat",
        "SOG": "sog_knots",
        "COG": "cog_deg",
    }
    frame = df.rename(columns={key: value for key, value in aliases.items() if key in df.columns})
    if {"mmsi", "time", "lon", "lat"}.difference(frame.columns):
        return empty_ais_frame()
    frame = frame.copy()
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    for column in ("lon", "lat", "sog_knots", "cog_deg"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "sog_knots" not in frame.columns:
        frame["sog_knots"] = pd.NA
    if "cog_deg" not in frame.columns:
        frame["cog_deg"] = pd.NA
    frame = frame.dropna(subset=["mmsi", "time", "lon", "lat"])
    return frame[AIS_COLUMNS].sort_values(["mmsi", "time"])


def empty_ais_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=AIS_COLUMNS)
