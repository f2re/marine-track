from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

from marine_track.geospatial import lonlat_to_pixel
from marine_track.models import VesselDetection
from marine_track.rendering.overview import grayscale_to_bgr


def render_vessel_crop(
    raster_path: str | Path,
    detection: VesselDetection,
    output_png: str | Path,
    index: int,
    crop_size_px: int = 512,
) -> Path:
    try:
        import rasterio
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("rasterio is required for vessel crop rendering") from exc

    output = Path(output_png)
    output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(raster_path) as dataset:
        row, col = lonlat_to_pixel(detection.lon, detection.lat, dataset.transform, dataset.crs)
        row_i = int(round(row))
        col_i = int(round(col))
        half = crop_size_px // 2
        row0 = max(0, row_i - half)
        col0 = max(0, col_i - half)
        row1 = min(dataset.height, row0 + crop_size_px)
        col1 = min(dataset.width, col0 + crop_size_px)
        row0 = max(0, row1 - crop_size_px)
        col0 = max(0, col1 - crop_size_px)
        window = rasterio.windows.Window(col0, row0, col1 - col0, row1 - row0)
        image = dataset.read(1, window=window).astype("float32")
        if dataset.nodata is not None:
            image[image == dataset.nodata] = np.nan
        transform = dataset.transform
        crs = dataset.crs

    canvas = grayscale_to_bgr(image)
    draw_ais_track(canvas, detection, transform, crs, row0=row0, col0=col0)
    local_x = int(round(col - col0))
    local_y = int(round(row - row0))
    draw_crop_overlay(canvas, local_x, local_y, detection, index)
    cv2.imwrite(str(output), canvas)
    return output


def draw_crop_overlay(canvas: np.ndarray, x: int, y: int, detection: VesselDetection, index: int) -> None:
    cv2.circle(canvas, (x, y), 12, (0, 0, 255), 2)
    cv2.line(canvas, (x - 18, y), (x + 18, y), (0, 255, 255), 1)
    cv2.line(canvas, (x, y - 18), (x, y + 18), (0, 255, 255), 1)
    draw_wake_axis(canvas, x, y, detection)
    ais = detection.validation.get("ais")
    ais_suffix = ""
    if isinstance(ais, dict):
        ais_suffix = f" AIS={ais.get('mmsi')} d={float(ais.get('distance_m', 0.0)):.0f}m"
    lines = [
        f"#{index} conf={detection.confidence:.2f}{ais_suffix}",
        f"lon={detection.lon:.5f} lat={detection.lat:.5f}",
        f"heading={detection.heading_deg if detection.heading_deg is not None else 'n/a'}",
        f"speed={detection.speed_knots if detection.speed_knots is not None else 'n/a'} kt",
    ]
    cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 82), (0, 0, 0), -1)
    for idx, line in enumerate(lines):
        cv2.putText(
            canvas,
            line[:120],
            (8, 20 + idx * 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )


def draw_wake_axis(canvas: np.ndarray, x: int, y: int, detection: VesselDetection) -> None:
    wake = detection.metadata.get("wake")
    if not isinstance(wake, dict):
        return
    angle = wake.get("axis_angle_image_deg")
    if not isinstance(angle, (int, float)):
        return
    length = min(canvas.shape[:2]) // 3
    angle_rad = math.radians(float(angle))
    dx = int(round(math.cos(angle_rad) * length))
    dy = int(round(math.sin(angle_rad) * length))
    cv2.line(canvas, (x - dx, y - dy), (x + dx, y + dy), (255, 180, 0), 2)


def draw_ais_track(canvas: np.ndarray, detection: VesselDetection, transform, crs, row0: int, col0: int) -> None:
    ais = detection.metadata.get("ais")
    if not isinstance(ais, dict):
        return
    track = ais.get("track")
    if not isinstance(track, list) or len(track) < 2:
        return
    points: list[tuple[int, int]] = []
    for point in track:
        if not isinstance(point, dict):
            continue
        try:
            row, col = lonlat_to_pixel(float(point["lon"]), float(point["lat"]), transform, crs)
        except Exception:
            continue
        x = int(round(col - col0))
        y = int(round(row - row0))
        if -50 <= x <= canvas.shape[1] + 50 and -50 <= y <= canvas.shape[0] + 50:
            points.append((x, y))
    if len(points) < 2:
        return
    cv2.polylines(canvas, [np.array(points, dtype=np.int32)], False, (0, 180, 255), 2, cv2.LINE_AA)
    cv2.circle(canvas, points[-1], 4, (0, 180, 255), -1)
