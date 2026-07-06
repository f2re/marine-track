import numpy as np

from marine_track.detection import adaptive_threshold_candidates


def test_adaptive_threshold_candidates_finds_bright_object():
    image = np.zeros((32, 32), dtype=float)
    image[10:13, 20:23] = 100.0
    candidates = adaptive_threshold_candidates(image, threshold_sigma=2.0, min_area_px=2)
    assert len(candidates) == 1
    assert candidates[0].area_px == 9
    assert candidates[0].centroid_yx == (11.0, 21.0)


def test_adaptive_threshold_candidates_handles_empty_image():
    image = np.full((8, 8), np.nan)
    assert adaptive_threshold_candidates(image) == []
