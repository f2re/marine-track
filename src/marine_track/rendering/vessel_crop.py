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
        raise RuntimeError("rasterio is required for candidate crop rendering") from exc

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


def _format_optional(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def draw_crop_overlay(canvas: np.ndarray, x: int, y: int, detection: VesselDetection, index: int) -> None:
    cv2.circle(canvas, (x, y), 12, (0, 0, 255), 2)
    cv2.line(canvas, (x - 18, y), (x + 18, y), (0, 255, 255), 1)
    cv2.line(canvas, (x, y - 18), (x, y + 18), (0, 255, 255), 1)
    draw_wake_axis(canvas, x, y, detection)

    ais = detection.references.ais
    ais_line = "AIS reference: none"
    if ais is not None:
        ais_line = (
            f"AIS ref={ais.mmsi} SOG={_format_optional(ais.sog_knots)}kt "
            f"d={ais.distance_m:.0f}m {ais.status}"
        )
    kelvin = detection.research_proxies.kelvin_speed
    proxy_line = "Kelvin research proxy: none"
    if kelvin is not None:
        proxy_line = (
            f"Kelvin research proxy={kelvin.value_knots:.1f}kt "
            f"q={_format_optional(kelvin.quality_score, 2)}"
        )
    speed_line = (
        "Operational speed: not estimated"
        if detection.speed.value_knots is None
        else f"Operational speed={detection.speed.value_knots:.1f}kt"
    )
    heading = "n/a" if detection.heading_deg is None else f"{detection.heading_deg:.1f}"
    lines = [
        f"#{index} vessel candidate score={detection.ranking_score:.2f}",
        f"lon={detection.lon:.5f} lat={detection.lat:.5f}",
        f"candidate heading={heading} method={detection.heading_method.value}",
        speed_line,
        ais_line,
        proxy_line,
    ]
    panel_height = 10 + len(lines) * 18
    cv2.rectangle(canvas, (0, 0), (canvas.shape[1], panel_height), (0, 0, 0), -1)
    for idx, line in enumerate(lines):
        cv2.putText(
            canvas,
            line[:120],
            (8, 20 + idx * 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.44,
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
    ais = detection.references.ais
    if ais is None or len(ais.track) < 2:
        return
    points: list[tuple[int, int]] = []
    for point in ais.track:
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
