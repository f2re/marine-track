from __future__ import annotations

import cv2
import numpy as np
import rasterio
from affine import Affine

from marine_track.rendering.overview import overview_dimensions, render_overview


class FakeDataset:
    width = 4000
    height = 2000
    nodata = None
    transform = Affine.identity()
    crs = "EPSG:3857"

    def __init__(self):
        self.read_kwargs = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, band, **kwargs):
        assert band == 1
        self.read_kwargs = kwargs
        height, width = kwargs["out_shape"]
        return np.ma.masked_array(
            np.zeros((height, width), dtype="float32"),
            mask=False,
        )


def test_overview_dimensions_preserve_aspect_ratio():
    assert overview_dimensions(4000, 2000, 1600) == (1600, 800)
    assert overview_dimensions(800, 600, 1600) == (800, 600)


def test_render_overview_requests_only_bounded_out_shape(tmp_path, monkeypatch):
    dataset = FakeDataset()
    written = {}
    monkeypatch.setattr(rasterio, "open", lambda _path: dataset)

    def fake_imwrite(path, canvas):
        written["path"] = path
        written["shape"] = canvas.shape
        return True

    monkeypatch.setattr(cv2, "imwrite", fake_imwrite)
    output = render_overview(
        tmp_path / "large.tif",
        [],
        tmp_path / "overview.png",
        "bounded",
        max_size_px=1600,
    )

    assert dataset.read_kwargs is not None
    assert dataset.read_kwargs["out_shape"] == (800, 1600)
    assert dataset.read_kwargs["masked"] is True
    assert written["shape"] == (800, 1600, 3)
    assert output == tmp_path / "overview.png"
