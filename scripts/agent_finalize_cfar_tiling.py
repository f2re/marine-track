from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"marker not found in {relative}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Python 3.10+ import location and consistent resource-limit exception.
replace_once(
    "src/marine_track/raster_detection.py",
    "from dataclasses import replace\nfrom datetime import datetime\nfrom pathlib import Path\nfrom typing import Any, Iterator\n",
    "from collections.abc import Iterator\nfrom dataclasses import replace\nfrom datetime import datetime\nfrom pathlib import Path\nfrom typing import Any\n",
)
replace_once(
    "src/marine_track/raster_detection.py",
    "from marine_track.resource_limits import ResourceLimits, validate_raster_workload\n",
    "from marine_track.resource_limits import (\n"
    "    ResourceLimitError,\n"
    "    ResourceLimits,\n"
    "    validate_raster_workload,\n"
    ")\n",
)
replace_once(
    "src/marine_track/raster_detection.py",
    "                    raise ValueError(\n"
    "                        f\"candidate count exceeds configured limit {limits.max_candidates}\"\n"
    "                    )\n",
    "                    raise ResourceLimitError(\n"
    "                        f\"candidate count exceeds configured limit {limits.max_candidates}\"\n"
    "                    )\n",
)

# Include AOI limits in the effective configuration/provenance and hash env overrides.
replace_once(
    "src/marine_track/processing_config.py",
    "    max_candidates: int\n    preprocessing: dict[str, Any]\n",
    "    max_candidates: int\n"
    "    max_aoi_area_km2: float\n"
    "    max_aoi_vertices: int\n"
    "    preprocessing: dict[str, Any]\n",
)
replace_once(
    "src/marine_track/processing_config.py",
    "    max_candidates: int | None = None,\n) -> EffectiveDetectorConfig:\n",
    "    max_candidates: int | None = None,\n"
    "    max_aoi_area_km2: float | None = None,\n"
    "    max_aoi_vertices: int | None = None,\n"
    ") -> EffectiveDetectorConfig:\n",
)
replace_once(
    "src/marine_track/processing_config.py",
    "        \"max_raster_pixels\": _number(\n",
    "        \"max_aoi_area_km2\": _number(\n"
    "            limits_root,\n"
    "            \"max_aoi_area_km2\",\n"
    "            25_000.0,\n"
    "            float,\n"
    "        ),\n"
    "        \"max_aoi_vertices\": _number(\n"
    "            limits_root,\n"
    "            \"max_aoi_vertices\",\n"
    "            5_000,\n"
    "            int,\n"
    "        ),\n"
    "        \"max_raster_pixels\": _number(\n",
)
replace_once(
    "src/marine_track/processing_config.py",
    "        \"max_raster_pixels\": (\"MARINE_TRACK_MAX_RASTER_PIXELS\", int),\n",
    "        \"max_aoi_area_km2\": (\"MARINE_TRACK_MAX_AOI_AREA_KM2\", float),\n"
    "        \"max_aoi_vertices\": (\"MARINE_TRACK_MAX_AOI_VERTICES\", int),\n"
    "        \"max_raster_pixels\": (\"MARINE_TRACK_MAX_RASTER_PIXELS\", int),\n",
)
replace_once(
    "src/marine_track/processing_config.py",
    "        \"max_raster_pixels\": max_raster_pixels,\n",
    "        \"max_aoi_area_km2\": max_aoi_area_km2,\n"
    "        \"max_aoi_vertices\": max_aoi_vertices,\n"
    "        \"max_raster_pixels\": max_raster_pixels,\n",
)
replace_once(
    "src/marine_track/processing_config.py",
    "        \"max_raster_pixels\": int(values[\"max_raster_pixels\"]),\n",
    "        \"max_aoi_area_km2\": float(values[\"max_aoi_area_km2\"]),\n"
    "        \"max_aoi_vertices\": int(values[\"max_aoi_vertices\"]),\n"
    "        \"max_raster_pixels\": int(values[\"max_raster_pixels\"]),\n",
)
replace_once(
    "src/marine_track/processing_config.py",
    "    max_raster_pixels = int(values[\"max_raster_pixels\"])\n",
    "    max_aoi_area_km2 = float(values[\"max_aoi_area_km2\"])\n"
    "    max_aoi_vertices = int(values[\"max_aoi_vertices\"])\n"
    "    max_raster_pixels = int(values[\"max_raster_pixels\"])\n",
)
replace_once(
    "src/marine_track/processing_config.py",
    "    minimum_overlap = (local_window // 2) + (max(guard_window, 1) // 2)\n",
    "    # The ownership boundary lies near the midpoint of the overlap. Each\n"
    "    # owning tile therefore needs two CFAR radii of overlap so that its\n"
    "    # complete outer training window is available at the boundary.\n"
    "    minimum_overlap = 2 * (local_window // 2)\n",
)
replace_once(
    "src/marine_track/processing_config.py",
    "    if max_raster_pixels < 1 or max_tiles < 1 or max_candidates < 1:\n"
    "        raise ValueError(\"resource limits must be positive\")\n",
    "    if max_aoi_area_km2 <= 0 or max_aoi_vertices < 4:\n"
    "        raise ValueError(\"AOI resource limits must be positive and allow a polygon\")\n"
    "    if max_raster_pixels < 1 or max_tiles < 1 or max_candidates < 1:\n"
    "        raise ValueError(\"processing resource limits must be positive\")\n",
)

# Fail closed on invalid coordinates/topology rather than silently repairing AOIs.
replace_once(
    "src/marine_track/resource_limits.py",
    "    vertex_count = sum(_count_vertices(geometry) for geometry in geometries)\n"
    "    if vertex_count > effective.max_aoi_vertices:\n",
    "    coordinate_pairs = [\n"
    "        pair for geometry in geometries for pair in _iter_coordinate_pairs(geometry)\n"
    "    ]\n"
    "    if not coordinate_pairs:\n"
    "        raise ResourceLimitError(\"AOI GeoJSON has no coordinate pairs\")\n"
    "    for longitude, latitude in coordinate_pairs:\n"
    "        if not math.isfinite(longitude) or not math.isfinite(latitude):\n"
    "            raise ResourceLimitError(\"AOI contains non-finite coordinates\")\n"
    "        if not -180.0 <= longitude <= 180.0 or not -90.0 <= latitude <= 90.0:\n"
    "            raise ResourceLimitError(\n"
    "                f\"AOI coordinate outside WGS84 bounds: {longitude}, {latitude}\"\n"
    "            )\n"
    "    vertex_count = len(coordinate_pairs)\n"
    "    if vertex_count > effective.max_aoi_vertices:\n",
)
replace_once(
    "src/marine_track/resource_limits.py",
    "        if not geometry.is_valid:\n"
    "            repaired = geometry.buffer(0)\n"
    "            if repaired.is_empty or not repaired.is_valid:\n"
    "                raise ResourceLimitError(\"AOI geometry is topologically invalid\")\n"
    "            geometry = repaired\n",
    "        if not geometry.is_valid:\n"
    "            raise ResourceLimitError(\"AOI geometry is topologically invalid\")\n",
)
replace_once(
    "src/marine_track/resource_limits.py",
    "def _count_vertices(value: Any) -> int:\n"
    "    if not isinstance(value, dict):\n"
    "        return 0\n"
    "    return _count_coordinate_nodes(value.get(\"coordinates\"))\n\n\n"
    "def _count_coordinate_nodes(value: Any) -> int:\n"
    "    if not isinstance(value, list):\n"
    "        return 0\n"
    "    if (\n"
    "        len(value) >= 2\n"
    "        and isinstance(value[0], (int, float))\n"
    "        and isinstance(value[1], (int, float))\n"
    "    ):\n"
    "        return 1\n"
    "    return sum(_count_coordinate_nodes(item) for item in value)\n",
    "def _iter_coordinate_pairs(value: Any):\n"
    "    if isinstance(value, dict):\n"
    "        coordinates = value.get(\"coordinates\")\n"
    "        if coordinates is not None:\n"
    "            yield from _iter_coordinate_pairs(coordinates)\n"
    "        geometries = value.get(\"geometries\")\n"
    "        if isinstance(geometries, list):\n"
    "            for geometry in geometries:\n"
    "                yield from _iter_coordinate_pairs(geometry)\n"
    "        return\n"
    "    if not isinstance(value, list):\n"
    "        return\n"
    "    if (\n"
    "        len(value) >= 2\n"
    "        and isinstance(value[0], (int, float))\n"
    "        and isinstance(value[1], (int, float))\n"
    "    ):\n"
    "        yield float(value[0]), float(value[1])\n"
    "        return\n"
    "    for item in value:\n"
    "        yield from _iter_coordinate_pairs(item)\n",
)

# Existing cache test now uses a valid AOI because validation is intentionally pre-provider.
replace_once(
    "tests/test_pipeline_cache.py",
    "        '{\"type\":\"FeatureCollection\",\"features\":[]}',\n",
    "        '{\"type\":\"Polygon\",\"coordinates\":[[[30,43],[30.1,43],[30.1,43.1],[30,43.1],[30,43]]]}',\n",
)

# Runtime import/numeric validation follows the new production contract.
replace_once(
    "runtime_check.py",
    '    "marine_track.processing_config",\n',
    '    "marine_track.processing_config",\n    "marine_track.resource_limits",\n',
)
replace_once(
    "runtime_check.py",
    '        "MARINE_TRACK_DETECTION_MIN_CONTRAST_SIGMA",\n',
    '        "MARINE_TRACK_DETECTION_MIN_CONTRAST_SIGMA",\n'
    '        "MARINE_TRACK_CFAR_MIN_TRAINING_FRACTION",\n'
    '        "MARINE_TRACK_MAX_AOI_AREA_KM2",\n',
)
replace_once(
    "runtime_check.py",
    '        "MARINE_TRACK_DETECTION_MIN_CONTRAST_SIGMA",\n'
    '        "MARINE_TRACK_CALIBRATION_MIN_LABELS",\n',
    '        "MARINE_TRACK_DETECTION_MIN_CONTRAST_SIGMA",\n'
    '        "MARINE_TRACK_CFAR_MIN_TRAINING_FRACTION",\n'
    '        "MARINE_TRACK_DETECTION_TILE_SIZE_PX",\n'
    '        "MARINE_TRACK_DETECTION_TILE_OVERLAP_PX",\n'
    '        "MARINE_TRACK_NORMALIZATION_SAMPLE_PIXELS",\n'
    '        "MARINE_TRACK_MAX_AOI_AREA_KM2",\n'
    '        "MARINE_TRACK_MAX_AOI_VERTICES",\n'
    '        "MARINE_TRACK_MAX_RASTER_PIXELS",\n'
    '        "MARINE_TRACK_MAX_TILES",\n'
    '        "MARINE_TRACK_MAX_CANDIDATES",\n'
    '        "MARINE_TRACK_CALIBRATION_MIN_LABELS",\n',
)

# Overview rendering must not undo tiled inference by loading the complete raster.
(ROOT / "src/marine_track/rendering/overview.py").write_text(
    dedent(
        '''\
        from __future__ import annotations

        from pathlib import Path

        import cv2
        import numpy as np

        from marine_track.geospatial import lonlat_to_pixel
        from marine_track.models import VesselDetection


        def render_overview(
            raster_path: str | Path,
            detections: list[VesselDetection],
            output_png: str | Path,
            title: str,
            max_size_px: int = 1600,
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
        '''
    ),
    encoding="utf-8",
)

(ROOT / "tests/test_cfar_tiling_limits.py").write_text(
    dedent(
        '''\
        from __future__ import annotations

        from datetime import datetime, timezone
        from pathlib import Path

        import numpy as np
        import pytest
        import rasterio
        from rasterio.transform import from_origin

        from marine_track.calibration_areas import CALIBRATION_AREAS
        from marine_track.detection import cfar_statistics
        from marine_track.models import Sensor
        from marine_track.pipeline import search_scenes_with_fallback
        from marine_track.processing_config import load_effective_detector_config
        from marine_track.raster_detection import _owned, _tile_windows, detect_candidates_from_raster
        from marine_track.resource_limits import (
            ResourceLimitError,
            ResourceLimits,
            estimated_tile_count,
            validate_geojson_payload,
            validate_raster_workload,
        )

        ROOT = Path(__file__).resolve().parents[1]


        def test_cfar_training_ring_excludes_guard_and_cut():
            image = np.ones((9, 9), dtype="float32")
            image[3:6, 3:6] = 50.0
            image[4, 4] = 100.0

            stats = cfar_statistics(
                image,
                threshold_sigma=3.0,
                local_window_px=7,
                guard_window_px=3,
                min_training_fraction=1.0,
            )

            assert stats.training_count[4, 4] == pytest.approx(40.0)
            assert stats.training_fraction[4, 4] == pytest.approx(1.0)
            assert stats.background_mean[4, 4] == pytest.approx(1.0)
            assert stats.background_std[4, 4] == pytest.approx(0.0)
            assert stats.threshold[4, 4] == pytest.approx(1.0)
            assert bool(stats.mask[4, 4]) is True
            assert bool(stats.edge[4, 4]) is False


        def test_cfar_reports_nodata_and_geometric_edge_support():
            image = np.ones((9, 9), dtype="float32")
            image[4, 4] = 100.0
            image[1, 1] = np.nan
            stats = cfar_statistics(
                image,
                threshold_sigma=3.0,
                local_window_px=7,
                guard_window_px=3,
                min_training_fraction=0.5,
            )
            assert stats.training_count[4, 4] == pytest.approx(39.0)
            assert stats.training_fraction[4, 4] == pytest.approx(39.0 / 40.0)
            assert bool(stats.edge[4, 4]) is True

            corner = np.ones((9, 9), dtype="float32")
            corner[0, 0] = 100.0
            strict = cfar_statistics(
                corner,
                threshold_sigma=3.0,
                local_window_px=7,
                guard_window_px=3,
                min_training_fraction=0.5,
            )
            assert strict.training_fraction[0, 0] < 0.5
            assert bool(strict.edge[0, 0]) is True
            assert bool(strict.mask[0, 0]) is False


        def test_tile_ownership_partitions_overlap_without_gaps_or_duplicates():
            windows = list(
                _tile_windows(
                    160,
                    128,
                    tile_size_px=96,
                    tile_overlap_px=32,
                )
            )
            assert len(windows) == 4
            for row in range(128):
                for col in range(160):
                    owners = sum(_owned(row, col, window[4]) for window in windows)
                    assert owners == 1


        def test_tiled_detection_emits_boundary_candidate_once(tmp_path):
            height, width = 128, 160
            yy, xx = np.mgrid[0:height, 0:width]
            image = (xx + 0.25 * yy).astype("float32")
            image[63:66, 79:82] += 1000.0
            raster = tmp_path / "scene.tif"
            with rasterio.open(
                raster,
                "w",
                driver="GTiff",
                width=width,
                height=height,
                count=1,
                dtype="float32",
                crs="EPSG:3857",
                transform=from_origin(0.0, 1280.0, 10.0, 10.0),
                nodata=-9999.0,
            ) as dataset:
                dataset.write(image, 1)

            detections = detect_candidates_from_raster(
                raster,
                satellite="sentinel1",
                provider="test",
                product_id="TEST_SCENE",
                acquisition_time=datetime(2026, 7, 10, tzinfo=timezone.utc),
                threshold_sigma=3.0,
                min_area_px=1,
                max_area_px=100,
                local_window_px=17,
                guard_window_px=5,
                min_training_fraction=1.0,
                tile_size_px=96,
                tile_overlap_px=32,
                normalization_sample_pixels=20_000,
                max_raster_pixels=100_000,
                max_tiles=10,
                max_candidates=100,
                calibration_profile={},
                phase2_output_dir=tmp_path / "state",
            )

            hits = [
                item
                for item in detections
                if abs(float(item.metadata["centroid_yx"][0]) - 64.0) <= 2.0
                and abs(float(item.metadata["centroid_yx"][1]) - 80.0) <= 2.0
            ]
            assert len(hits) == 1
            metadata = hits[0].metadata
            assert metadata["tile_count"] == 4
            assert metadata["training_fraction"] == pytest.approx(1.0)
            assert metadata["cfar_edge_flag"] is False
            assert metadata["bbox_yx"][0] <= 64 < metadata["bbox_yx"][2]
            assert metadata["bbox_yx"][1] <= 80 < metadata["bbox_yx"][3]


        def test_resource_limits_validate_coordinates_topology_area_and_workload():
            small = {
                "type": "Polygon",
                "coordinates": [[[30.0, 43.0], [30.1, 43.0], [30.1, 43.1], [30.0, 43.1], [30.0, 43.0]]],
            }
            metrics = validate_geojson_payload(small)
            assert 0.0 < metrics.area_km2 < 1_000.0
            assert metrics.vertex_count == 5

            with pytest.raises(ResourceLimitError, match="outside WGS84 bounds"):
                validate_geojson_payload(
                    {"type": "Polygon", "coordinates": [[[181, 0], [181, 1], [179, 1], [181, 0]]]}
                )
            with pytest.raises(ResourceLimitError, match="topologically invalid"):
                validate_geojson_payload(
                    {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]],
                    }
                )
            with pytest.raises(ResourceLimitError, match="exceeds configured limit"):
                validate_geojson_payload(
                    {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                    },
                    ResourceLimits(max_aoi_area_km2=1.0),
                )

            assert estimated_tile_count(160, 128, tile_size_px=96, tile_overlap_px=32) == 4
            with pytest.raises(ResourceLimitError, match="pixels"):
                validate_raster_workload(
                    50,
                    50,
                    32,
                    8,
                    ResourceLimits(max_raster_pixels=1_000),
                )


        def test_all_builtin_calibration_sectors_fit_default_aoi_limit():
            for area in CALIBRATION_AREAS:
                metrics = validate_geojson_payload(area.geojson())
                assert metrics.area_km2 <= ResourceLimits().max_aoi_area_km2, area.id


        def test_oversized_aoi_is_rejected_before_provider_creation(tmp_path, monkeypatch):
            aoi = tmp_path / "large.geojson"
            aoi.write_text(
                '{"type":"Polygon","coordinates":[[[0,0],[2,0],[2,2],[0,2],[0,0]]]}',
                encoding="utf-8",
            )
            monkeypatch.setenv("MARINE_TRACK_MAX_AOI_AREA_KM2", "1")
            provider_called = False

            def forbidden_manager():
                nonlocal provider_called
                provider_called = True
                raise AssertionError("provider manager must not be built")

            monkeypatch.setattr("marine_track.pipeline.build_source_manager", forbidden_manager)
            with pytest.raises(ResourceLimitError, match="area"):
                search_scenes_with_fallback(
                    config=object(),
                    aoi=aoi,
                    start=datetime(2026, 7, 1, tzinfo=timezone.utc),
                    end=datetime(2026, 7, 2, tzinfo=timezone.utc),
                    sensor=Sensor.SENTINEL1,
                )
            assert provider_called is False


        def test_effective_config_includes_aoi_limits_and_two_sided_halo(monkeypatch):
            path = ROOT / "config" / "processing.yaml"
            baseline = load_effective_detector_config(Sensor.SENTINEL1, path=path)
            assert baseline.max_aoi_area_km2 == pytest.approx(25_000.0)
            assert baseline.max_aoi_vertices == 5_000

            monkeypatch.setenv("MARINE_TRACK_MAX_AOI_AREA_KM2", "1234")
            changed = load_effective_detector_config(Sensor.SENTINEL1, path=path)
            assert changed.max_aoi_area_km2 == pytest.approx(1234.0)
            assert changed.config_hash != baseline.config_hash

            with pytest.raises(ValueError, match="minimum is 30"):
                load_effective_detector_config(
                    Sensor.SENTINEL1,
                    path=path,
                    local_window_px=31,
                    tile_overlap_px=20,
                )
        '''
    ),
    encoding="utf-8",
)

(ROOT / "tests/test_overview_bounded.py").write_text(
    dedent(
        '''\
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
        '''
    ),
    encoding="utf-8",
)

(ROOT / "docs/CFAR_TILING_LIMITS.md").write_text(
    dedent(
        '''\
        # CFAR, tiled inference and resource limits

        The operational detector reads a bounded scene-wide sample to establish one 2/98 percentile
        normalization domain, then processes the raster in overlapping windows. It does not load the
        full-resolution band into memory. The overview renderer also requests a bounded rasterio
        `out_shape`, so result rendering cannot undo the memory bound.

        Local CFAR uses an outer training window minus the complete inner guard region. The guard
        region includes the cell under test. Per-candidate provenance records the usable training
        count, training fraction, local mean/std, threshold and incomplete-support flag. Tile overlap
        must be at least twice the outer-window radius because ownership boundaries lie near the
        midpoint of an overlap.

        Candidate ownership partitions the full raster in global pixel coordinates. This removes
        duplicate emissions from overlapping tiles while retaining deterministic IDs and global
        bounding boxes.

        The fail-closed defaults are:

        ```dotenv
        MARINE_TRACK_MAX_AOI_AREA_KM2=25000
        MARINE_TRACK_MAX_AOI_VERTICES=5000
        MARINE_TRACK_MAX_RASTER_PIXELS=2000000000
        MARINE_TRACK_MAX_TILES=20000
        MARINE_TRACK_MAX_CANDIDATES=10000
        MARINE_TRACK_DETECTION_TILE_SIZE_PX=1024
        MARINE_TRACK_DETECTION_TILE_OVERLAP_PX=128
        MARINE_TRACK_CFAR_MIN_TRAINING_FRACTION=0.5
        MARINE_TRACK_NORMALIZATION_SAMPLE_PIXELS=1000000
        ```

        AOIs are interpreted as WGS84 polygonal GeoJSON. Out-of-range coordinates, invalid topology,
        excessive vertices and excessive geodesic area are rejected before provider search. Raster
        pixel/tile limits are checked immediately after opening the materialized crop and before tiled
        detection. These limits are operational safety controls, not scientific tuning parameters.
        '''
    ),
    encoding="utf-8",
)

print("CFAR tiling finalization applied")
