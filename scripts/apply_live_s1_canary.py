from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"integration marker not found: {label} in {path}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "src/marine_track/detection_pipeline.py",
    '''    shoreline_buffer_m: float = 0.0,
    progress_callback: ProgressCallback | None = None,
) -> DetectionRunResult:
''',
    '''    shoreline_buffer_m: float = 0.0,
    wake_enabled_override: bool | None = None,
    progress_callback: ProgressCallback | None = None,
) -> DetectionRunResult:
''',
    "detection wake override signature",
)
replace_once(
    "src/marine_track/detection_pipeline.py",
    "    wake_enabled = wake_research_enabled()\n",
    '''    wake_enabled = (
        wake_research_enabled()
        if wake_enabled_override is None
        else bool(wake_enabled_override)
    )
''',
    "detection wake override resolution",
)

replace_once(
    "src/marine_track/cli.py",
    '''from marine_track.processing_config import load_effective_detector_config
from marine_track.raster_detection import detect_candidates_from_raster
''',
    '''from marine_track.processing_config import load_effective_detector_config
from marine_track.provider_canary import run_sentinel1_canary
from marine_track.raster_detection import detect_candidates_from_raster
''',
    "CLI canary import",
)
replace_once(
    "src/marine_track/cli.py",
    '''@app.command("calibration-generate-tiles")
def calibration_generate_tiles(
''',
    '''@app.command("provider-canary")
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
''',
    "CLI canary command",
)

replace_once(
    "src/marine_track/telegram_ui.py",
    '''ACTION_OUTPUT_MODE = "output_mode"
ACTION_CALIBRATION = "calibration"
ACTION_MENU = "menu"
''',
    '''ACTION_OUTPUT_MODE = "output_mode"
ACTION_CALIBRATION = "calibration"
ACTION_SELFTEST = "selftest"
ACTION_MENU = "menu"
''',
    "Telegram selftest menu action",
)
replace_once(
    "src/marine_track/telegram_ui.py",
    '''                InlineKeyboardButton(
                    f"{marker}🧪 Калибровка",
                    callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_CALIBRATION}",
                )
            ]
''',
    '''                InlineKeyboardButton(
                    f"{marker}🧪 Калибровка",
                    callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_CALIBRATION}",
                ),
                InlineKeyboardButton(
                    "🩺 Самопроверка",
                    callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_SELFTEST}",
                ),
            ]
''',
    "Telegram selftest admin button",
)

replace_once(
    "src/marine_track/telegram_bot.py",
    '''from marine_track.telegram_scene_browser import (
    CALLBACK_PREFIX,
    PAGE_CALLBACK_PREFIX,
)
''',
    '''from marine_track.telegram_scene_browser import (
    CALLBACK_PREFIX,
    PAGE_CALLBACK_PREFIX,
)
from marine_track.telegram_selftest import SELFTEST_CALLBACK_PREFIX
from marine_track.telegram_selftest import selftest_callback as admin_selftest_callback
from marine_track.telegram_selftest import selftest_command as admin_selftest_command
''',
    "Telegram selftest imports",
)
replace_once(
    "src/marine_track/telegram_bot.py",
    '''    ACTION_OUTPUT_MODE,
    ACTION_STATUS,
    ACTION_WHOAMI,
''',
    '''    ACTION_OUTPUT_MODE,
    ACTION_SELFTEST,
    ACTION_STATUS,
    ACTION_WHOAMI,
''',
    "Telegram selftest action import",
)
replace_once(
    "src/marine_track/telegram_bot.py",
    '''async def calibrate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_calibration_command(update, context, get_config())


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
''',
    '''async def calibrate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_calibration_command(update, context, get_config())


async def selftest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_selftest_command(update, context, get_config())


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
''',
    "Telegram selftest command wrapper",
)
replace_once(
    "src/marine_track/telegram_bot.py",
    '''    if action == ACTION_CALIBRATION:
        await admin_calibration_command(update, context, get_config())
        return
    if action == ACTION_OUTPUT_MODE:
''',
    '''    if action == ACTION_CALIBRATION:
        await admin_calibration_command(update, context, get_config())
        return
    if action == ACTION_SELFTEST:
        await admin_selftest_command(update, context, get_config())
        return
    if action == ACTION_OUTPUT_MODE:
''',
    "Telegram selftest menu dispatch",
)
replace_once(
    "src/marine_track/telegram_bot.py",
    '''async def calibration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_calibration_callback(update, context, get_config())


async def notify_admins_on_startup(application: Application) -> None:
''',
    '''async def calibration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_calibration_callback(update, context, get_config())


async def selftest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_selftest_callback(update, context, get_config())


async def notify_admins_on_startup(application: Application) -> None:
''',
    "Telegram selftest callback wrapper",
)
replace_once(
    "src/marine_track/telegram_bot.py",
    '''    app.add_handler(CommandHandler("calibrate", calibrate_command))
    app.add_handler(CommandHandler("dates", dates_command))
''',
    '''    app.add_handler(CommandHandler("calibrate", calibrate_command))
    app.add_handler(CommandHandler("selftest", selftest_command))
    app.add_handler(CommandHandler("dates", dates_command))
''',
    "Telegram selftest command handler",
)
replace_once(
    "src/marine_track/telegram_bot.py",
    '''    app.add_handler(CallbackQueryHandler(calibration_callback, pattern=f"^{CALIBRATION_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(scene_scene_page_callback, pattern=f"^{PAGE_CALLBACK_PREFIX}:"))
''',
    '''    app.add_handler(CallbackQueryHandler(calibration_callback, pattern=f"^{CALIBRATION_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(selftest_callback, pattern=f"^{SELFTEST_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(scene_scene_page_callback, pattern=f"^{PAGE_CALLBACK_PREFIX}:"))
''',
    "Telegram selftest callback handler",
)

replace_once(
    "runtime_check.py",
    '''    "marine_track.resource_limits",
    "marine_track.sensor_preprocessing",
    "marine_track.provenance",
''',
    '''    "marine_track.resource_limits",
    "marine_track.sensor_preprocessing",
    "marine_track.provider_canary",
    "marine_track.provenance",
''',
    "runtime provider canary import",
)
replace_once(
    "runtime_check.py",
    '''    "marine_track.telegram_detection",
    "marine_track.telegram_ui",
''',
    '''    "marine_track.telegram_detection",
    "marine_track.telegram_selftest",
    "marine_track.telegram_ui",
''',
    "runtime Telegram selftest import",
)
replace_once(
    "runtime_check.py",
    '''    calibration_context = os.getenv("MARINE_TRACK_CALIBRATION_CONTEXT_GEOJSON", "").strip()
    if calibration_context and not project_path(calibration_context).is_file():
        errors.append(
            f"calibration context GeoJSON not found: {project_path(calibration_context)}"
        )
    local_track_csv = os.getenv("MARINE_TRACK_AIS_CSV", "").strip()
''',
    '''    calibration_context = os.getenv("MARINE_TRACK_CALIBRATION_CONTEXT_GEOJSON", "").strip()
    if calibration_context and not project_path(calibration_context).is_file():
        errors.append(
            f"calibration context GeoJSON not found: {project_path(calibration_context)}"
        )
    canary_aoi = os.getenv("MARINE_TRACK_CANARY_AOI", "").strip()
    if canary_aoi and not project_path(canary_aoi).is_file():
        errors.append(f"canary AOI GeoJSON not found: {project_path(canary_aoi)}")
    local_track_csv = os.getenv("MARINE_TRACK_AIS_CSV", "").strip()
''',
    "runtime canary AOI path",
)
replace_once(
    "runtime_check.py",
    '''        "MARINE_TRACK_MAX_AOI_AREA_KM2",
        "MARINE_TRACK_RASTER_LOCK_TIMEOUT_S",
''',
    '''        "MARINE_TRACK_MAX_AOI_AREA_KM2",
        "MARINE_TRACK_RASTER_LOCK_TIMEOUT_S",
        "MARINE_TRACK_CANARY_SPAN_DEG",
''',
    "runtime canary float",
)
replace_once(
    "runtime_check.py",
    '''        "MARINE_TRACK_RASTER_LOCK_TIMEOUT_S",
        "MARINE_TRACK_MAX_AOI_AREA_KM2",
''',
    '''        "MARINE_TRACK_RASTER_LOCK_TIMEOUT_S",
        "MARINE_TRACK_CANARY_LOOKBACK_HOURS",
        "MARINE_TRACK_CANARY_MAX_RESULTS",
        "MARINE_TRACK_CANARY_SPAN_DEG",
        "MARINE_TRACK_MAX_AOI_AREA_KM2",
''',
    "runtime canary numeric names",
)

replace_once(
    ".env.example",
    '''# Remote GeoTIFF/COG range-read canary before materialization.
MARINE_TRACK_ASSET_PROBE_TIMEOUT_S=30
MARINE_TRACK_ASSET_PROBE_BYTES=4096
''',
    '''# Remote GeoTIFF/COG range-read canary before materialization.
MARINE_TRACK_ASSET_PROBE_TIMEOUT_S=30
MARINE_TRACK_ASSET_PROBE_BYTES=4096

# Explicit Sentinel-1 provider self-test. Never runs automatically on deploy/restart.
# When empty, a compact polygon is derived from MARINE_TRACK_DEFAULT_AOI.
MARINE_TRACK_CANARY_AOI=
MARINE_TRACK_CANARY_LOOKBACK_HOURS=336
MARINE_TRACK_CANARY_MAX_RESULTS=3
MARINE_TRACK_CANARY_SPAN_DEG=0.10
''',
    "environment canary settings",
)
