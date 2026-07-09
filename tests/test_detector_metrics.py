import numpy as np

from marine_track.detection import adaptive_threshold_candidates


def test_detector_reports_shape_and_contrast_metrics():
    image = np.zeros((64, 64), dtype="float32")
    image[30:33, 28:36] = 1.0

    candidates = adaptive_threshold_candidates(
        image,
        threshold_sigma=2.0,
        min_area_px=2,
        max_area_px=100,
        local_window_px=17,
        guard_window_px=0,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.area_px == 24
    assert candidate.peak_score == 1.0
    assert candidate.contrast_sigma > 0
    assert candidate.major_axis_px >= candidate.minor_axis_px
    assert candidate.elongation >= 1.0


def test_detector_min_contrast_filters_candidates():
    image = np.zeros((64, 64), dtype="float32")
    image[30:33, 28:36] = 1.0

    candidates = adaptive_threshold_candidates(
        image,
        threshold_sigma=2.0,
        min_area_px=2,
        max_area_px=100,
        local_window_px=17,
        guard_window_px=0,
        min_contrast_sigma=999.0,
    )

    assert candidates == []
