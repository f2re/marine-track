import numpy as np
import pytest

from marine_track.raster import finite_fraction, iter_tiles, percentile_normalize


def test_percentile_normalize_scales_finite_values():
    image = np.array([[0.0, 5.0], [10.0, np.nan]])
    out = percentile_normalize(image, lower=0.0, upper=100.0)
    assert out[0, 0] == pytest.approx(0.0)
    assert out[1, 0] == pytest.approx(1.0)
    assert np.isnan(out[1, 1])


def test_percentile_normalize_keeps_sparse_bright_targets():
    image = np.zeros((64, 64), dtype=float)
    image[20:23, 30:33] = 100.0
    out = percentile_normalize(image)
    assert out[20:23, 30:33].max() == pytest.approx(1.0)


def test_iter_tiles_with_overlap():
    image = np.zeros((5, 5), dtype=float)
    tiles = list(iter_tiles(image, tile_size=3, overlap=1))
    assert len(tiles) == 4
    assert tiles[0].data.shape == (3, 3)
    assert tiles[-1].row_start == 2
    assert tiles[-1].col_start == 2


def test_finite_fraction():
    image = np.array([[1.0, np.nan], [2.0, 3.0]])
    assert finite_fraction(image) == pytest.approx(0.75)
