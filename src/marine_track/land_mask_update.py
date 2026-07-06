from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

DEFAULT_LAND_MASK_SOURCE_URL = "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip"


class LandMaskUpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class LandMaskUpdateResult:
    output_path: Path
    source: str
    feature_count: int
    clipped: bool


def update_land_mask(
    output_path: str | Path,
    source: str | Path | None = None,
    cache_dir: str | Path | None = None,
    aoi_geojson: str | Path | None = None,
    force: bool = False,
) -> LandMaskUpdateResult:
    """Download/read a land polygon dataset and write an EPSG:4326 GeoJSON mask.

    The source may be an HTTP(S) URL or a local ZIP/Shapefile/GeoJSON path.
    By default it uses the Natural Earth 10m land ZIP URL. The output file is a
    GeoJSON that can be used as MARINE_TRACK_LAND_MASK_GEOJSON.
    """
    output = Path(output_path)
    if output.is_file() and not force:
        feature_count = count_features(output)
        return LandMaskUpdateResult(output_path=output, source="existing", feature_count=feature_count, clipped=False)

    source_value = str(source or os.getenv("MARINE_TRACK_LAND_MASK_SOURCE_URL") or DEFAULT_LAND_MASK_SOURCE_URL)
    cache = Path(cache_dir or os.getenv("MARINE_TRACK_LAND_MASK_CACHE_DIR") or "data/masks/cache")
    cache.mkdir(parents=True, exist_ok=True)

    local_source = materialize_source(source_value, cache)
    with tempfile.TemporaryDirectory(prefix="marine-track-land-mask-") as tmp_dir:
        work_dir = Path(tmp_dir)
        dataset_path = prepare_dataset(local_source, work_dir)
        frame = read_land_dataset(dataset_path)
        frame = frame.to_crs("EPSG:4326")
        clipped = False
        if aoi_geojson:
            frame = clip_to_aoi(frame, Path(aoi_geojson))
            clipped = True
        if frame.empty:
            raise LandMaskUpdateError("land mask dataset is empty after optional AOI clipping")
        output.parent.mkdir(parents=True, exist_ok=True)
        frame.to_file(output, driver="GeoJSON")
        return LandMaskUpdateResult(
            output_path=output,
            source=source_value,
            feature_count=len(frame),
            clipped=clipped,
        )


def materialize_source(source: str, cache_dir: Path) -> Path:
    if source.startswith(("http://", "https://")):
        suffix = Path(source.split("?", 1)[0]).suffix or ".dat"
        target = cache_dir / f"{hashlib.sha256(source.encode('utf-8')).hexdigest()[:16]}{suffix}"
        if target.is_file() and target.stat().st_size > 0:
            return target
        request = Request(source, headers={"User-Agent": "marine-track/0.1"})
        with urlopen(request, timeout=300) as response, target.open("wb") as file_obj:  # noqa: S310
            shutil.copyfileobj(response, file_obj)
        if not target.is_file() or target.stat().st_size == 0:
            raise LandMaskUpdateError(f"empty land mask download: {source}")
        return target
    path = Path(source)
    if not path.is_file():
        raise LandMaskUpdateError(f"land mask source not found: {path}")
    return path


def prepare_dataset(source_path: Path, work_dir: Path) -> Path:
    suffix = source_path.suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(source_path) as zip_obj:
            zip_obj.extractall(work_dir)
        shapefiles = sorted(work_dir.rglob("*.shp"))
        if not shapefiles:
            geojsons = sorted(work_dir.rglob("*.geojson")) + sorted(work_dir.rglob("*.json"))
            if geojsons:
                return geojsons[0]
            raise LandMaskUpdateError(f"no shapefile or GeoJSON found inside {source_path}")
        return shapefiles[0]
    if suffix in {".shp", ".geojson", ".json"}:
        return source_path
    raise LandMaskUpdateError(f"unsupported land mask source format: {source_path}")


def read_land_dataset(path: Path):
    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise LandMaskUpdateError("geopandas is required to build land mask GeoJSON") from exc
    frame = gpd.read_file(path)
    if frame.crs is None:
        frame = frame.set_crs("EPSG:4326")
    frame = frame[frame.geometry.notnull()].copy()
    if frame.empty:
        raise LandMaskUpdateError(f"land mask source has no geometries: {path}")
    return frame


def clip_to_aoi(frame, aoi_path: Path):
    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise LandMaskUpdateError("geopandas is required to clip land mask") from exc
    if not aoi_path.is_file():
        raise LandMaskUpdateError(f"AOI GeoJSON not found: {aoi_path}")
    aoi = gpd.read_file(aoi_path).to_crs(frame.crs)
    if aoi.empty:
        raise LandMaskUpdateError(f"AOI GeoJSON has no geometries: {aoi_path}")
    return gpd.clip(frame, aoi)


def count_features(path: Path) -> int:
    try:
        import geopandas as gpd
    except ImportError:
        return 0
    try:
        return len(gpd.read_file(path))
    except Exception:
        return 0
