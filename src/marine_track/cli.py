from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from marine_track.config import load_config
from marine_track.models import Sensor
from marine_track.pipeline import parse_utc_datetime, run_search_stage, search_scenes_with_fallback

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


if __name__ == "__main__":
    app()
