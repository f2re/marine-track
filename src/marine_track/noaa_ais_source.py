from __future__ import annotations

import os
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

from marine_track.ais_sources import AISProviderError, AISQuery, filter_ais, normalize_ais_frame


class NOAAMarineCadastreProvider:
    name = "noaa_marinecadastre"

    def __init__(self, cache_dir: str | Path | None = None, base_url: str | None = None):
        self.cache_dir = Path(cache_dir or os.getenv("NOAA_MARINECADASTRE_CACHE_DIR", "runs/noaa_ais"))
        self.base_url = (base_url or os.getenv("NOAA_MARINECADASTRE_BASE_URL") or "").rstrip("/")

    def fetch(self, query: AISQuery) -> pd.DataFrame:
        if not self.base_url:
            raise AISProviderError("NOAA_MARINECADASTRE_BASE_URL is not set")
        frames: list[pd.DataFrame] = []
        for day in iter_days(query.start, query.end):
            frames.extend(self._read_archive(self._download_day(day)))
        if not frames:
            return normalize_ais_frame(pd.DataFrame())
        return filter_ais(pd.concat(frames, ignore_index=True), query)

    def _download_day(self, day: datetime) -> Path:
        year = day.year
        name = f"AIS_{year}_{day.month:02d}_{day.day:02d}.zip"
        target = self.cache_dir / str(year) / name
        if target.is_file() and target.stat().st_size > 0:
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"{self.base_url}/{year}/{name}"
        request = Request(url, headers={"User-Agent": "marine-track/0.1"})
        with urlopen(request, timeout=300) as response, target.open("wb") as file_obj:  # noqa: S310
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                file_obj.write(chunk)
        if not target.is_file() or target.stat().st_size == 0:
            raise AISProviderError(f"empty NOAA archive: {url}")
        return target

    def _read_archive(self, archive: Path) -> list[pd.DataFrame]:
        frames: list[pd.DataFrame] = []
        with zipfile.ZipFile(archive) as zip_obj:
            for member in zip_obj.namelist():
                if member.lower().endswith(".csv"):
                    with zip_obj.open(member) as csv_file:
                        frames.append(normalize_ais_frame(pd.read_csv(csv_file)))
        return frames


def iter_days(start: datetime, end: datetime) -> list[datetime]:
    current = normalize_utc(start).replace(hour=0, minute=0, second=0, microsecond=0)
    limit = normalize_utc(end)
    output: list[datetime] = []
    while current <= limit:
        output.append(current)
        current += timedelta(days=1)
    return output


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
