from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter1d, map_coordinates
from scipy.signal import find_peaks
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


@dataclass(frozen=True)
class WakeWavelengthEstimate:
    wavelength_px: float
    peak_count: int
    profile_length_px: int
    prominence: float
    confidence: float


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

    work = normalize_image(image)
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


def estimate_wake_wavelength_px(
    image: np.ndarray,
    vessel_yx: tuple[float, float],
    axis_angle_deg: float,
    half_length_px: int = 96,
    center_guard_px: int = 8,
    min_peak_distance_px: int = 4,
    min_peaks: int = 3,
) -> WakeWavelengthEstimate | None:
    """Estimate a tentative wake wavelength from a cross-axis intensity profile.

    The estimate is experimental. It samples a profile perpendicular to the detected
    wake axis, smooths it, finds repeated bright ridges and returns the median peak
    spacing in pixels. This is suitable as a weak scientific feature, not as a final
    speed-over-ground product.
    """
    if image.ndim != 2:
        raise ValueError("image must be 2D")
    finite = np.isfinite(image)
    if not finite.any():
        return None
    work = normalize_image(image)
    vessel_y, vessel_x = vessel_yx
    normal_rad = np.radians(axis_angle_deg + 90.0)
    offsets = np.arange(-half_length_px, half_length_px + 1, dtype="float64")
    rows = vessel_y + np.sin(normal_rad) * offsets
    cols = vessel_x + np.cos(normal_rad) * offsets
    profile = map_coordinates(work, [rows, cols], order=1, mode="nearest")
    valid = np.isfinite(profile)
    if not valid.any():
        return None
    profile = np.where(valid, profile, float(np.nanmedian(profile[valid])))
    profile = gaussian_filter1d(profile.astype("float64"), sigma=1.5)
    profile = profile - float(np.nanmedian(profile))
    profile[np.abs(offsets) <= center_guard_px] = 0.0
    positive = profile[profile > 0]
    if positive.size == 0:
        return None
    prominence = max(0.03, float(np.nanpercentile(positive, 75)) * 0.25)
    peaks, properties = find_peaks(profile, distance=min_peak_distance_px, prominence=prominence)
    if len(peaks) < min_peaks:
        return None
    peak_offsets = offsets[peaks]
    spacings = np.diff(np.sort(peak_offsets))
    spacings = spacings[spacings >= min_peak_distance_px]
    if len(spacings) < max(1, min_peaks - 1):
        return None
    wavelength = float(np.median(spacings))
    if not np.isfinite(wavelength) or wavelength <= 0:
        return None
    prominences = properties.get("prominences", np.array([], dtype="float64"))
    median_prominence = float(np.median(prominences)) if prominences.size else prominence
    regularity = 1.0 / (1.0 + float(np.std(spacings) / max(wavelength, 1e-6)))
    strength = min(1.0, median_prominence / max(prominence, 1e-6))
    confidence = max(0.0, min(1.0, 0.6 * regularity + 0.4 * min(1.0, strength / 3.0)))
    return WakeWavelengthEstimate(
        wavelength_px=wavelength,
        peak_count=int(len(peaks)),
        profile_length_px=int(len(profile)),
        prominence=median_prominence,
        confidence=confidence,
    )


def normalize_image(image: np.ndarray) -> np.ndarray:
    finite = np.isfinite(image)
    work = np.zeros_like(image, dtype="float64")
    if not finite.any():
        return work
    values = image[finite]
    span = values.max() - values.min()
    if span == 0:
        return work
    work[finite] = (image[finite] - values.min()) / span
    return work
