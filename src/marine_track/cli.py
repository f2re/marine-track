from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from marine_track.cache_policy import cleanup_runtime
from marine_track.config import load_config
from marine_track.land_mask_update import DEFAULT_LAND_MASK_SOURCE_URL, update_land_mask as build_land_mask
from marine_track.models import Sensor
from marine_track.output import write_csv, write_geojson, write_parquet
from marine_track.pipeline import parse_utc_datetime, run_search_stage, search_scenes_with_fallback
from marine_track.raster_detection import detect_candidates_from_raster

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
    write_manifest: bool = typer.Option(True, help="Write asset manifest for the selected scenes"),
) -> None:
    """Run the current MVP stage: scene search, provenance and asset manifest."""
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
    output: Path = typer.Option(Path("runs/latest/detections.geojson")),
    satellite: str = typer.Option("unknown"),
    provider: str = typer.Option("local"),
    product_id: str = typer.Option("local-raster"),
    acquisition_time: str = typer.Option(..., help="UTC acquisition time"),
    threshold_sigma: float = typer.Option(3.5),
    min_area_px: int = typer.Option(2),
    max_area_px: int = typer.Option(5000),
) -> None:
    """Detect bright vessel candidates in one local georeferenced raster band."""
    detections = detect_candidates_from_raster(
        path=raster,
        satellite=satellite,
        provider=provider,
        product_id=product_id,
        acquisition_time=parse_utc_datetime(acquisition_time),
        threshold_sigma=threshold_sigma,
        min_area_px=min_area_px,
        max_area_px=max_area_px,
    )
    write_geojson(detections, output)
    write_csv(detections, output.with_suffix(".csv"))
    write_parquet(detections, output.with_suffix(".parquet"))
    console.print(f"[green]Saved {len(detections)} detections to {output}[/green]")


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
