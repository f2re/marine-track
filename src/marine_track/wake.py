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
