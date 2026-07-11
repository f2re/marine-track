from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from marine_track.cache_policy import cleanup_runtime
from marine_track.calibration_phase2 import Phase2Targets
from marine_track.calibration_phase2_evaluation import (
    build_proposed_profile,
    evaluate_phase2,
    promote_proposed_profile,
    rollback_profile,
)
from marine_track.calibration_phase2_tiles import generate_independent_tasks
from marine_track.config import load_config
from marine_track.land_mask_update import DEFAULT_LAND_MASK_SOURCE_URL
from marine_track.land_mask_update import update_land_mask as build_land_mask
from marine_track.models import Sensor
from marine_track.output import write_csv, write_geojson, write_parquet
from marine_track.pipeline import parse_utc_datetime, run_search_stage, search_scenes_with_fallback
from marine_track.processing_config import load_effective_detector_config
from marine_track.provider_canary import run_sentinel1_canary
from marine_track.raster_detection import detect_candidates_from_raster
from marine_track.sensor_preprocessing import build_local_preprocessing_plan

app = typer.Typer(help="Marine Track MVP: vessel and ship-wake detection from satellite imagery")
console = Console()


@app.command()
def search(
    aoi: Path = typer.Option(..., exists=True, readable=True, help="AOI GeoJSON path"),
    start: str = typer.Option(..., "--from", help="UTC start time, e.g. 2026-07-01T00:00:00Z"),
    end: str = typer.Option(..., "--to", help="UTC end time, e.g. 2026-07-06T00:00:00Z"),
    sensor: Sensor = typer.Option(Sensor.AUTO, help="auto, sentinel1 or sentinel2"),
    max_results: int = typer.Option(20, min=1, max=500),
) -> None:
    """Search scenes using configured provider fallback order."""
    config = load_config()
    provider, concrete_sensor, scenes = search_scenes_with_fallback(
        config=config,
        aoi=aoi,
        start=parse_utc_datetime(start),
        end=parse_utc_datetime(end),
        sensor=sensor,
        max_results=max_results,
    )

    table = Table(title=f"Scenes from {provider} / {concrete_sensor.value}")
    table.add_column("time")
    table.add_column("product_id")
    table.add_column("beam")
    table.add_column("pol/cloud")
    table.add_column("assets")
    for scene in scenes:
        table.add_row(
            scene.acquisition_time.isoformat(),
            scene.product_id,
            scene.beam_mode or "-",
            scene.polarization_label(),
            str(len(scene.assets)),
        )
    console.print(table)


@app.command()
def run(
    aoi: Path = typer.Option(..., exists=True, readable=True, help="AOI GeoJSON path"),
    start: str = typer.Option(..., "--from", help="UTC start time"),
    end: str = typer.Option(..., "--to", help="UTC end time"),
    sensor: Sensor = typer.Option(Sensor.AUTO),
    output: Path = typer.Option(Path("runs/latest")),
    max_results: int = typer.Option(50, min=1, max=500),
    write_manifest: bool = typer.Option(True, help="Write asset manifest for selected scenes"),
) -> None:
    """Run scene search, provenance and asset manifest."""
    result = run_search_stage(
        aoi=aoi,
        start=parse_utc_datetime(start),
        end=parse_utc_datetime(end),
        sensor=sensor,
        output=output,
        max_results=max_results,
        write_manifest=write_manifest,
    )
    console.print(
        f"[green]Found {result.scene_count} scenes via "
        f"{result.provider}/{result.sensor.value}[/green]"
    )
    console.print(f"Saved provenance: {result.scenes_json}")
    if result.asset_manifest:
        console.print(f"Saved asset manifest: {result.asset_manifest}")


@app.command("detect-raster")
def detect_raster(
    raster: Path = typer.Option(..., exists=True, readable=True, help="Single-band GeoTIFF path"),
    output: Path = typer.Option(Path("runs/latest/candidates.geojson")),
    satellite: Sensor = typer.Option(Sensor.SENTINEL1),
    provider: str = typer.Option("local"),
    product_id: str = typer.Option("local-raster"),
    acquisition_time: str = typer.Option(..., help="UTC acquisition time"),
    asset_key: str = typer.Option("band1", help="Band/polarization asset key, e.g. vv"),
    input_units: str | None = typer.Option(None, help="Declared raster units, e.g. amplitude, sigma0 or dB"),
    input_scale: float = typer.Option(1.0, help="Scale applied before radiometric conversion"),
    input_offset: float = typer.Option(0.0, help="Offset applied before radiometric conversion"),
    threshold_sigma: float | None = typer.Option(None),
    min_area_px: int | None = typer.Option(None),
    max_area_px: int | None = typer.Option(None),
    local_window_px: int | None = typer.Option(None),
    guard_window_px: int | None = typer.Option(None),
    min_contrast_sigma: float | None = typer.Option(None),
) -> None:
    """Detect bright candidates using the same effective config as Telegram."""
    effective = load_effective_detector_config(
        satellite,
        threshold_sigma=threshold_sigma,
        min_area_px=min_area_px,
        max_area_px=max_area_px,
        local_window_px=local_window_px,
        guard_window_px=guard_window_px,
        min_contrast_sigma=min_contrast_sigma,
    )
    preprocessing_plan = build_local_preprocessing_plan(
        satellite,
        effective.preprocessing,
        asset_key=asset_key,
        input_units=input_units,
        scale=input_scale,
        offset=input_offset,
    )
    detections = detect_candidates_from_raster(
        path=raster,
        satellite=satellite.value,
        provider=provider,
        product_id=product_id,
        acquisition_time=parse_utc_datetime(acquisition_time),
        **effective.detector_kwargs(),
        preprocessing_plan=preprocessing_plan,
    )
    write_geojson(detections, output)
    write_csv(detections, output.with_suffix(".csv"))
    write_parquet(detections, output.with_suffix(".parquet"))
    console.print(
        f"[green]Saved {len(detections)} candidates to {output}[/green] "
        f"config={effective.config_hash[:12]}"
    )


@app.command("effective-config")
def effective_config_command(
    sensor: Sensor = typer.Option(Sensor.SENTINEL1),
) -> None:
    """Print validated detector parameters and reproducibility hash."""
    effective = load_effective_detector_config(sensor)
    console.print_json(data=effective.as_report_dict())


@app.command("provider-canary")
def provider_canary(
    mode: str = typer.Option("asset", help="asset or detection"),
    output_dir: Path = typer.Option(Path(os.getenv("MARINE_TRACK_OUTPUT_DIR", "runs/telegram"))),
    default_aoi: Path = typer.Option(
        Path(os.getenv("MARINE_TRACK_DEFAULT_AOI", "data/aoi/example_black_sea.geojson"))
    ),
    canary_aoi: Path | None = typer.Option(None, help="Optional explicit compact-source AOI"),
    lookback_hours: int | None = typer.Option(None, help="Defaults to MARINE_TRACK_CANARY_LOOKBACK_HOURS"),
    max_results: int | None = typer.Option(None, help="Defaults to MARINE_TRACK_CANARY_MAX_RESULTS"),
    span_deg: float | None = typer.Option(None, help="Compact AOI span in degrees"),
    owner_user_id: int = typer.Option(0, help="Required for detection mode"),
    owner_chat_id: int = typer.Option(0, help="Required for detection mode"),
    confirm_detection: bool = typer.Option(
        False,
        "--confirm-detection",
        help="Explicitly allow the quota-using end-to-end detection canary",
    ),
) -> None:
    """Run a redacted Sentinel-1 provider/asset or compact detection canary."""

    result = run_sentinel1_canary(
        output_dir=output_dir,
        default_aoi=default_aoi,
        mode=mode,
        canary_aoi=canary_aoi,
        lookback_hours=lookback_hours,
        max_results=max_results,
        span_deg=span_deg,
        owner_user_id=owner_user_id,
        owner_chat_id=owner_chat_id,
        confirm_detection=confirm_detection,
    )
    console.print_json(data=result.report)
    console.print(f"report_file: {result.report_path.name}")
    if result.report.get("status") != "success":
        raise typer.Exit(code=1)


@app.command("calibration-generate-tiles")
def calibration_generate_tiles(
    output_dir: Path = typer.Option(Path("runs/telegram"), help="Telegram/output directory"),
    context_geojson: Path | None = typer.Option(
        None,
        exists=True,
        readable=True,
        help="Optional GeoJSON with stratum=coastline|port|offshore_structure",
    ),
    tile_size_px: int = typer.Option(768, min=384, max=1536),
    max_tiles_per_scene: int = typer.Option(24, min=1, max=500),
    force: bool = typer.Option(False, help="Rebuild manifest and tasks"),
) -> None:
    """Generate detector-independent, scene-grouped calibration tiles."""
    targets = Phase2Targets(
        tile_size_px=tile_size_px,
        max_tiles_per_scene=max_tiles_per_scene,
    )
    manifest = generate_independent_tasks(
        output_dir,
        targets=targets,
        context_geojson=context_geojson,
        force=force,
    )
    console.print(
        f"[green]Generated {len(manifest.get('tasks', []))} phase-2 tiles[/green]\n"
        f"strata={manifest.get('counts', {})}\nsplits={manifest.get('splits', {})}"
    )


@app.command("calibration-evaluate")
def calibration_evaluate(
    output_dir: Path = typer.Option(Path("runs/telegram")),
    bootstrap_samples: int = typer.Option(300, min=10, max=5000),
    json_output: Path | None = typer.Option(None, help="Optional copy of evaluation JSON"),
) -> None:
    """Evaluate phase-2 labels on fixed scene/pass groups."""
    result = evaluate_phase2(output_dir, bootstrap_samples=bootstrap_samples)
    if json_output:
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    table = Table(title="Calibration phase 2")
    table.add_column("split")
    table.add_column("n")
    table.add_column("groups")
    table.add_column("F1")
    table.add_column("POD")
    table.add_column("FAR")
    table.add_column("CSI")
    for split in ("train", "calibration", "test"):
        metrics = result["splits"][split]
        table.add_row(
            split,
            str(metrics["count"]),
            str(metrics["groups"]),
            f"{metrics['f1']:.3f}",
            f"{metrics['pod']:.3f}",
            f"{metrics['far']:.3f}",
            f"{metrics['csi']:.3f}",
        )
    console.print(table)


@app.command("calibration-propose")
def calibration_propose(
    output_dir: Path = typer.Option(Path("runs/telegram")),
) -> None:
    """Build a versioned profile without activating it."""
    profile = build_proposed_profile(output_dir)
    console.print(
        f"profile={profile['profile_id']} status={profile['status']} "
        f"gate={profile['promotion_gate']['passed']}"
    )


@app.command("calibration-promote")
def calibration_promote(
    output_dir: Path = typer.Option(Path("runs/telegram")),
    min_test_groups: int = typer.Option(3, min=1),
    min_validation_groups: int = typer.Option(3, min=1),
    min_improvement: float = typer.Option(0.01, min=0.0, max=1.0),
) -> None:
    """Activate a post-filter profile only after held-out gate success."""
    targets = Phase2Targets(
        min_test_groups=min_test_groups,
        min_validation_groups=min_validation_groups,
        min_improvement=min_improvement,
    )
    profile = promote_proposed_profile(output_dir, targets)
    console.print(f"[green]Activated profile {profile['profile_id']}[/green]")


@app.command("calibration-rollback")
def calibration_rollback(
    output_dir: Path = typer.Option(Path("runs/telegram")),
    profile_id: str | None = typer.Option(None, help="History profile id; latest when omitted"),
) -> None:
    """Restore a previous active calibration profile."""
    profile = rollback_profile(output_dir, profile_id)
    console.print(f"[green]Rolled back to profile {profile['profile_id']}[/green]")


@app.command("update-land-mask")
def update_land_mask_command(
    output: Path = typer.Option(Path("data/masks/land.geojson"), help="Output GeoJSON mask path"),
    source: str = typer.Option(DEFAULT_LAND_MASK_SOURCE_URL, help="Source URL or local ZIP/SHP/GeoJSON path"),
    cache_dir: Path = typer.Option(Path("data/masks/cache"), help="Download/cache directory"),
    aoi: Path | None = typer.Option(None, exists=True, readable=True, help="Optional AOI GeoJSON to clip mask"),
    force: bool = typer.Option(False, help="Rebuild even if output already exists"),
) -> None:
    """Download/read land polygons and build MARINE_TRACK_LAND_MASK_GEOJSON."""
    result = build_land_mask(
        output_path=output,
        source=source,
        cache_dir=cache_dir,
        aoi_geojson=aoi,
        force=force,
    )
    console.print(
        "[green]Land mask ready[/green]: "
        f"{result.output_path} features={result.feature_count} clipped={result.clipped}"
    )


@app.command("cleanup-cache")
def cleanup_cache_command() -> None:
    """Remove expired scene-search cache, raster cache and old detection outputs."""
    reports = cleanup_runtime()
    table = Table(title="Marine Track cleanup")
    table.add_column("section")
    table.add_column("files")
    table.add_column("dirs")
    table.add_column("bytes")
    for name, report in reports.items():
        table.add_row(name, str(report.removed_files), str(report.removed_dirs), str(report.removed_bytes))
    console.print(table)


if __name__ == "__main__":
    app()
