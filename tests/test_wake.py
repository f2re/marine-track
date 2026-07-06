import numpy as np

from marine_track.wake import detect_linear_wake_candidates


def test_detect_linear_wake_candidates_empty():
    image = np.zeros((32, 32), dtype=float)
    assert detect_linear_wake_candidates(image) == []


def test_detect_linear_wake_candidates_line():
    image = np.zeros((64, 64), dtype=float)
    image[30:34, 10:55] = 1.0
    lines = detect_linear_wake_candidates(image, sigma=1.0, num_peaks=3)
    assert len(lines) >= 1
    assert all(0.0 <= line.vessel_heading_deg < 360.0 for line in lines)
