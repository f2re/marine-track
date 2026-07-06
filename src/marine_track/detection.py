from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage as ndi


@dataclass(frozen=True)
class PixelObject:
    label: int
    centroid_yx: tuple[float, float]
    area_px: int
    bbox_yx: tuple[int, int, int, int]
    score: float


def adaptive_threshold_candidates(
    image: np.ndarray,
    threshold_sigma: float = 3.5,
    min_area_px: int = 2,
    max_area_px: int = 5000,
) -> list[PixelObject]:
    """Minimal image-domain candidate detector.

    This is a deliberately simple MVP primitive. For SAR it can be used after
    calibration/geocoding/speckle reduction; for optical images after masking and
    contrast normalization. Production detection must add local CFAR and coastline
    suppression.
    """
    if image.ndim != 2:
        raise ValueError("image must be 2D")
    finite = np.isfinite(image)
    if not finite.any():
        return []

    values = image[finite]
    threshold = float(values.mean() + threshold_sigma * values.std())
    mask = np.zeros_like(image, dtype=bool)
    mask[finite] = image[finite] > threshold

    labels, n = ndi.label(mask)
    objects = ndi.find_objects(labels)
    candidates: list[PixelObject] = []
    for label_id in range(1, n + 1):
        slc = objects[label_id - 1]
        if slc is None:
            continue
        component = labels[slc] == label_id
        area = int(component.sum())
        if not (min_area_px <= area <= max_area_px):
            continue
        cy, cx = ndi.center_of_mass(component)
        y0, x0 = slc[0].start, slc[1].start
        y1, x1 = slc[0].stop, slc[1].stop
        score = float(image[slc][component].mean())
        candidates.append(
            PixelObject(
                label=label_id,
                centroid_yx=(float(y0 + cy), float(x0 + cx)),
                area_px=area,
                bbox_yx=(y0, x0, y1, x1),
                score=score,
            )
        )
    return candidates
