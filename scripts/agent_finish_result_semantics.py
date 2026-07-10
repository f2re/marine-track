from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, got {count}: {old[:100]!r}")
    write(path, content.replace(old, new, 1))


replace_once(
    "src/marine_track/calibration.py",
    '''        raster_path = Path(str(report.get("raster_path") or ""))
        detections = report.get("detections") or []
''',
    '''        raster_path = _runtime_raster_path(report_path, report)
        detections = report.get("candidates") or report.get("detections") or []
''',
)
replace_once(
    "src/marine_track/calibration.py",
    '                    "ranking_score": detection.get("confidence"),\n',
    '                    "ranking_score": detection.get("ranking_score", detection.get("confidence")),\n',
)
replace_once(
    "src/marine_track/calibration.py",
    '                    "ais_matched": detection.get("validation_status") == "ais_matched",\n',
    '''                    "ais_matched": str(detection.get("validation_status") or "").startswith(
                        "ais_reference_"
                    ),
''',
)
replace_once(
    "src/marine_track/calibration.py",
    "\n\ndef _render_grid_task(\n",
    '''

def _runtime_raster_path(report_path: Path, report: dict[str, Any]) -> Path:
    runtime_reference = report.get("runtime_state_reference")
    if isinstance(runtime_reference, str) and runtime_reference:
        state_path = Path(runtime_reference)
        if not state_path.is_absolute():
            state_path = report_path.parents[2] / state_path
        try:
            state = _read_json(state_path)
            raster_path = Path(str(state.get("raster_path") or ""))
            if raster_path.is_file():
                return raster_path
        except (OSError, ValueError):
            pass
    legacy = Path(str(report.get("raster_path") or ""))
    return legacy


def _render_grid_task(
''',
)

replace_once(
    "src/marine_track/calibration_phase2_tiles.py",
    '    raster_path = Path(str(report.get("raster_path") or ""))\n',
    '    raster_path = _runtime_raster_path(report_path, report)\n',
)
replace_once(
    "src/marine_track/calibration_phase2_tiles.py",
    '    for detection in report.get("detections") or []:\n',
    '    for detection in report.get("candidates") or report.get("detections") or []:\n',
)
replace_once(
    "src/marine_track/calibration_phase2_tiles.py",
    '''            metadata = detection.get("metadata") if isinstance(detection.get("metadata"), dict) else {}
            inside.append(
''',
    '''            metadata = detection.get("metadata") if isinstance(detection.get("metadata"), dict) else {}
            references = detection.get("references") if isinstance(detection.get("references"), dict) else {}
            inside.append(
''',
)
replace_once(
    "src/marine_track/calibration_phase2_tiles.py",
    '''                    "ranking_score": detection.get("confidence"),
                    "validation_status": detection.get("validation_status"),
                    "ais": metadata.get("ais"),
''',
    '''                    "ranking_score": detection.get("ranking_score", detection.get("confidence")),
                    "validation_status": detection.get("validation_status"),
                    "ais": references.get("ais") or metadata.get("ais"),
''',
)
replace_once(
    "src/marine_track/calibration_phase2_tiles.py",
    '        if item.get("validation_status") == "ais_matched"\n',
    '''        if str(item.get("validation_status") or "").startswith("ais_reference_")
''',
)
replace_once(
    "src/marine_track/calibration_phase2_tiles.py",
    "\n\ndef _tasks_from_report(\n",
    '''

def _runtime_raster_path(report_path: Path, report: dict[str, Any]) -> Path:
    runtime_reference = report.get("runtime_state_reference")
    if isinstance(runtime_reference, str) and runtime_reference:
        state_path = Path(runtime_reference)
        if not state_path.is_absolute():
            state_path = report_path.parents[2] / state_path
        try:
            state = read_json(state_path)
            raster_path = Path(str(state.get("raster_path") or ""))
            if raster_path.is_file():
                return raster_path
        except (OSError, ValueError):
            pass
    return Path(str(report.get("raster_path") or ""))


def _tasks_from_report(
''',
)

replace_once(
    "tests/test_processing_config_provenance.py",
    '    assert report["schema_version"] == 2\n',
    '''    assert report["schema_version"] == 3
    assert report["result_type"] == "vessel_candidates"
    assert report["candidates"]
    assert result.runtime_state_json.is_file()
''',
)
replace_once(
    "tests/test_telegram_ui.py",
    '    assert "🔎 Найти суда" in labels(markup)\n',
    '    assert "🔎 Найти кандидаты" in labels(markup)\n',
)
replace_once(
    "tests/test_detection_pipeline_token.py",
    '''    assert result.report_json.is_file()
    assert len(result.detections) >= 1
''',
    '''    assert result.report_json.is_file()
    assert result.runtime_state_json.is_file()
    assert result.runtime_state_json.stat().st_mode & 0o777 == 0o600
    assert len(result.detections) >= 1
''',
)
replace_once(
    "src/marine_track/cli.py",
    '    output: Path = typer.Option(Path("runs/latest/detections.geojson")),\n',
    '    output: Path = typer.Option(Path("runs/latest/candidates.geojson")),\n',
)

replace_once(
    "runtime_check.py",
    '''        "MARINE_TRACK_AIS_MAX_DISTANCE_M",
        "MARINE_TRACK_CALIBRATION_PHASE2_MIN_VALID_FRACTION",
''',
    '''        "MARINE_TRACK_AIS_MAX_DISTANCE_M",
        "MARINE_TRACK_AIS_AMBIGUITY_MARGIN_M",
        "MARINE_TRACK_CALIBRATION_PHASE2_MIN_VALID_FRACTION",
''',
)
replace_once(
    "runtime_check.py",
    '''        "MARINE_TRACK_AIS_TRACK_WINDOW_MIN",
        "MARINE_TRACK_AIS_MAX_DISTANCE_M",
''',
    '''        "MARINE_TRACK_AIS_TRACK_WINDOW_MIN",
        "MARINE_TRACK_AIS_MAX_DISTANCE_M",
        "MARINE_TRACK_AIS_MAX_INTERPOLATION_GAP_MIN",
        "MARINE_TRACK_AIS_AMBIGUITY_MARGIN_M",
''',
)

(ROOT / "docs/RESULT_SEMANTICS_AIS_QC.md").write_text(
    '''# Result semantics and AIS QC

Marine Track exports georeferenced **vessel candidates**, not confirmed vessels. `ranking_score`
is an ordering/filtering score and is not a probability. Own-system operational speed remains
`speed.value_knots = null` until a separately validated estimator is available.

Deep-water Kelvin wavelength output is stored only in `research_proxies.kelvin_speed`; its
assumptions and quality score are explicit. AIS SOG/COG is stored only in `references.ais`, never
copied into own speed or heading, and is explicitly marked `not_ground_truth`.

AIS references use a maximum interpolation-gap gate, nearest/second-nearest ambiguity margin and
deterministic one-to-one MMSI assignment. Configure these with
`MARINE_TRACK_AIS_MAX_INTERPOLATION_GAP_MIN` and `MARINE_TRACK_AIS_AMBIGUITY_MARGIN_M`.

A local `runtime_state.json` (mode 0600) keeps the private raster path required by calibration.
It is not sent by Telegram. Public `report.json` stays redacted and points to this state only by a
relative reference.
''',
    encoding="utf-8",
)
