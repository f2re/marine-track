from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from marine_track.config import load_config
from marine_track.models import Sensor
from marine_track.pipeline import parse_utc_datetime, search_scenes_with_fallback

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
    for scene in scenes:
        table.add_row(
            scene.acquisition_time.isoformat(),
            scene.product_id,
            scene.beam_mode or "-",
            scene.polarization or (str(scene.cloud_cover) if scene.cloud_cover is not None else "-"),
        )
    console.print(table)


@app.command()
def run(
    aoi: Path = typer.Option(..., exists=True, readable=True, help="AOI GeoJSON path"),
    start: str = typer.Option(..., "--from", help="UTC start time"),
    end: str = typer.Option(..., "--to", help="UTC end time"),
    sensor: Sensor = typer.Option(Sensor.AUTO),
    output: Path = typer.Option(Path("runs/latest")),
) -> None:
    """Run the current MVP stage: scene search and provenance capture.

    Full raster preprocessing/detection is intentionally separated into the next
    implementation stage. This command already validates provider fallback and
    creates a reproducible run directory.
    """
    output.mkdir(parents=True, exist_ok=True)
    config = load_config()
    provider, concrete_sensor, scenes = search_scenes_with_fallback(
        config=config,
        aoi=aoi,
        start=parse_utc_datetime(start),
        end=parse_utc_datetime(end),
        sensor=sensor,
        max_results=50,
    )
    provenance = output / "scenes.json"
    provenance.write_text(
        "[\n" + ",\n".join(scene.model_dump_json(indent=2) for scene in scenes) + "\n]",
        encoding="utf-8",
    )
    console.print(f"[green]Found {len(scenes)} scenes via {provider}/{concrete_sensor.value}[/green]")
    console.print(f"Saved provenance: {provenance}")


if __name__ == "__main__":
    app()
