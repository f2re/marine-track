from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from marine_track.geospatial import lonlat_to_pixel
from marine_track.models import VesselDetection


def render_overview(
    raster_path: str | Path,
    detections: list[VesselDetection],
    output_png: str | Path,
    title: str,
    max_size_px: int = 1600,
) -> Path:
    try:
        import rasterio
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("rasterio is required for overview rendering") from exc

    output = Path(output_png)
    output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(raster_path) as dataset:
        image = dataset.read(1).astype("float32")
        if dataset.nodata is not None:
            image[image == dataset.nodata] = np.nan
        transform = dataset.transform
        crs = dataset.crs

    canvas = grayscale_to_bgr(image)
    scale = resize_scale(canvas.shape[1], canvas.shape[0], max_size_px)
    if scale != 1.0:
        canvas = cv2.resize(canvas, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    for detection in detections:
        draw_ais_track(canvas, detection, transform, crs, scale)

    for index, detection in enumerate(detections, start=1):
        row, col = lonlat_to_pixel(detection.lon, detection.lat, transform, crs)
        x = int(round(col * scale))
        y = int(round(row * scale))
        draw_detection_marker(canvas, x, y, index, detection.ranking_score)

    draw_title(canvas, title, len(detections))
    cv2.imwrite(str(output), canvas)
    return output


def grayscale_to_bgr(image: np.ndarray) -> np.ndarray:
    finite = np.isfinite(image)
    if not finite.any():
        normalized = np.zeros(image.shape, dtype="uint8")
    else:
        lo, hi = np.nanpercentile(image[finite], [2, 98])
        if hi <= lo:
            normalized = np.zeros(image.shape, dtype="uint8")
        else:
            values = np.clip((image - lo) / (hi - lo), 0.0, 1.0)
            values[~finite] = 0.0
            normalized = (values * 255).astype("uint8")
    return cv2.cvtColor(normalized, cv2.COLOR_GRAY2BGR)


def resize_scale(width: int, height: int, max_size_px: int) -> float:
    longest = max(width, height)
    if longest <= max_size_px:
        return 1.0
    return max_size_px / float(longest)


def draw_detection_marker(canvas: np.ndarray, x: int, y: int, index: int, ranking_score: float) -> None:
    radius = 8 if ranking_score < 0.7 else 10
    cv2.circle(canvas, (x, y), radius, (0, 0, 255), 2)
    cv2.circle(canvas, (x, y), 2, (0, 255, 255), -1)
    cv2.putText(
        canvas,
        str(index),
        (x + 10, y - 10),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )


def draw_ais_track(canvas: np.ndarray, detection: VesselDetection, transform, crs, scale: float) -> None:
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
        x = int(round(col * scale))
        y = int(round(row * scale))
        if -50 <= x <= canvas.shape[1] + 50 and -50 <= y <= canvas.shape[0] + 50:
            points.append((x, y))
    if len(points) < 2:
        return
    cv2.polylines(canvas, [np.array(points, dtype=np.int32)], False, (0, 180, 255), 2, cv2.LINE_AA)
    cv2.putText(
        canvas,
        f"AIS ref {ais.mmsi}",
        points[-1],
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (0, 180, 255),
        1,
        cv2.LINE_AA,
    )


def draw_title(canvas: np.ndarray, title: str, count: int) -> None:
    text = f"{title} | vessel candidates: {count}"
    cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 36), (0, 0, 0), -1)
    cv2.putText(
        canvas,
        text[:140],
        (10, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
