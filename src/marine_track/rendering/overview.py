from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from marine_track.geospatial import lonlat_to_pixel
from marine_track.models import VesselDetection
from marine_track.sensor_preprocessing import SensorPreprocessingPlan, read_preprocessed_band


def render_overview(
    raster_path: str | Path,
    detections: list[VesselDetection],
    output_png: str | Path,
    title: str,
    max_size_px: int = 1600,
    preprocessing_plan: SensorPreprocessingPlan | None = None,
) -> Path:
    try:
        import rasterio
        from rasterio.enums import Resampling
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("rasterio is required for overview rendering") from exc

    output = Path(output_png)
    output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(raster_path) as dataset:
        output_width, output_height = overview_dimensions(
            dataset.width,
            dataset.height,
            max_size_px,
        )
        if preprocessing_plan is None:
            sampled = dataset.read(
                1,
                out_shape=(output_height, output_width),
                out_dtype="float32",
                masked=True,
                resampling=Resampling.average,
            )
            if np.ma.isMaskedArray(sampled):
                image = np.asarray(sampled.filled(np.nan), dtype="float32")
            else:
                image = np.asarray(sampled, dtype="float32")
                if dataset.nodata is not None:
                    image[image == dataset.nodata] = np.nan
        else:
            image = read_preprocessed_band(
                dataset,
                preprocessing_plan,
                out_shape=(output_height, output_width),
                resampling=Resampling.average,
                apply_filter=True,
            )
        transform = dataset.transform
        crs = dataset.crs
        scale_x = output_width / float(dataset.width)
        scale_y = output_height / float(dataset.height)

    canvas = grayscale_to_bgr(image)
    for detection in detections:
        draw_ais_track(canvas, detection, transform, crs, scale_x, scale_y)

    for index, detection in enumerate(detections, start=1):
        row, col = lonlat_to_pixel(detection.lon, detection.lat, transform, crs)
        x = int(round(col * scale_x))
        y = int(round(row * scale_y))
        draw_detection_marker(canvas, x, y, index, detection.ranking_score)

    draw_title(canvas, title, len(detections))
    if not cv2.imwrite(str(output), canvas):
        raise RuntimeError(f"Failed to write overview image: {output}")
    return output


def overview_dimensions(width: int, height: int, max_size_px: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise ValueError("overview source dimensions must be positive")
    if max_size_px <= 0:
        raise ValueError("max_size_px must be positive")
    scale = min(1.0, max_size_px / float(max(width, height)))
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


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
    """Compatibility helper retained for callers/tests outside the renderer."""
    longest = max(width, height)
    if longest <= max_size_px:
        return 1.0
    return max_size_px / float(longest)


def draw_detection_marker(
    canvas: np.ndarray,
    x: int,
    y: int,
    index: int,
    ranking_score: float,
) -> None:
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


def draw_ais_track(
    canvas: np.ndarray,
    detection: VesselDetection,
    transform,
    crs,
    scale_x: float,
    scale_y: float,
) -> None:
    ais = detection.references.ais
    if ais is None or len(ais.track) < 2:
        return
    points: list[tuple[int, int]] = []
    for point in ais.track:
        if not isinstance(point, dict):
            continue
        try:
            row, col = lonlat_to_pixel(
                float(point["lon"]),
                float(point["lat"]),
                transform,
                crs,
            )
        except Exception:
            continue
        x = int(round(col * scale_x))
        y = int(round(row * scale_y))
        if -50 <= x <= canvas.shape[1] + 50 and -50 <= y <= canvas.shape[0] + 50:
            points.append((x, y))
    if len(points) < 2:
        return
    cv2.polylines(
        canvas,
        [np.array(points, dtype=np.int32)],
        False,
        (0, 180, 255),
        2,
        cv2.LINE_AA,
    )
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
