from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from skimage.feature import canny
from skimage.transform import hough_line, hough_line_peaks

from marine_track.estimation import normalize_heading_deg, reciprocal_heading_deg


@dataclass(frozen=True)
class WakeLine:
    angle_deg: float
    distance_px: float
    accumulator: float
    vessel_heading_deg: float


@dataclass(frozen=True)
class WakeAssociation:
    line: WakeLine
    line_distance_px: float
    score: float


def detect_linear_wake_candidates(
    image: np.ndarray,
    sigma: float = 2.0,
    num_peaks: int = 5,
) -> list[WakeLine]:
    """Detect candidate wake axes by Canny + Hough transform.

    This function is intentionally conservative. It does not classify Kelvin arms;
    it only returns high-level linear candidates that must be validated against the
    vessel location, coastline mask and sensor geometry.
    """
    if image.ndim != 2:
        raise ValueError("image must be 2D")
    finite = np.isfinite(image)
    if not finite.any():
        return []

    work = np.zeros_like(image, dtype=float)
    values = image[finite]
    span = values.max() - values.min()
    if span == 0:
        return []
    work[finite] = (image[finite] - values.min()) / span

    edges = canny(work, sigma=sigma)
    if not edges.any():
        return []

    hspace, angles, distances = hough_line(edges)
    accums, peak_angles, peak_distances = hough_line_peaks(
        hspace,
        angles,
        distances,
        num_peaks=num_peaks,
    )

    candidates: list[WakeLine] = []
    for accum, angle_rad, distance in zip(accums, peak_angles, peak_distances, strict=True):
        # skimage Hough angle is line normal angle. Convert to line axis heading.
        line_axis_deg = normalize_heading_deg(float(np.degrees(angle_rad) + 90.0))
        candidates.append(
            WakeLine(
                angle_deg=line_axis_deg,
                distance_px=float(distance),
                accumulator=float(accum),
                vessel_heading_deg=reciprocal_heading_deg(line_axis_deg),
            )
        )
    return candidates


def associate_wake_axis_with_vessel(
    image: np.ndarray,
    vessel_yx: tuple[float, float],
    sigma: float = 2.0,
    num_peaks: int = 8,
    max_line_distance_px: float = 24.0,
) -> WakeAssociation | None:
    """Return the strongest Hough line that passes near the vessel center."""
    candidates = detect_linear_wake_candidates(image, sigma=sigma, num_peaks=num_peaks)
    if not candidates:
        return None

    vessel_y, vessel_x = vessel_yx
    associations: list[WakeAssociation] = []
    for line in candidates:
        distance = hough_line_distance_px(line, vessel_x=vessel_x, vessel_y=vessel_y)
        if distance > max_line_distance_px:
            continue
        score = line.accumulator / (1.0 + distance)
        associations.append(WakeAssociation(line=line, line_distance_px=distance, score=score))
    if not associations:
        return None
    return max(associations, key=lambda item: item.score)


def hough_line_distance_px(line: WakeLine, vessel_x: float, vessel_y: float) -> float:
    normal_angle_rad = np.radians(line.angle_deg - 90.0)
    projected_distance = vessel_x * np.cos(normal_angle_rad) + vessel_y * np.sin(normal_angle_rad)
    return float(abs(projected_distance - line.distance_px))
