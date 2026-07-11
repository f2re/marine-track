from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"marker not found for {label}: {path}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "src/marine_track/provider_canary.py",
    "from marine_track.models import Scene, Sensor\n",
    "from marine_track.models import Sensor\n",
    "remove unused Scene import",
)
replace_once(
    "src/marine_track/provider_canary.py",
    "    AssetProbe,\n    MaterializationError,\n    prepare_asset_access,\n",
    "    AssetProbe,\n    prepare_asset_access,\n",
    "remove unused MaterializationError import",
)

replace_once(
    "src/marine_track/detection_pipeline.py",
    "    shoreline_buffer_m: float = 0.0,\n    progress_callback: ProgressCallback | None = None,\n",
    "    shoreline_buffer_m: float = 0.0,\n    wake_research: bool | None = None,\n    progress_callback: ProgressCallback | None = None,\n",
    "explicit wake research override",
)
replace_once(
    "src/marine_track/detection_pipeline.py",
    "    wake_enabled = wake_research_enabled()\n",
    "    wake_enabled = wake_research_enabled() if wake_research is None else bool(wake_research)\n",
    "resolve wake research override",
)

replace_once(
    "src/marine_track/cli.py",
    "import json\nfrom pathlib import Path\n",
    "import json\nimport os\nfrom pathlib import Path\n",
    "CLI os import",
)
replace_once(
    "src/marine_track/cli.py",
    "from marine_track.processing_config import load_effective_detector_config\n",
    "from marine_track.processing_config import load_effective_detector_config\nfrom marine_track.provider_canary import CanaryMode, run_provider_canary\n",
    "CLI canary imports",
)
replace_once(
    "src/marine_track/cli.py",
    "\n@app.command(\"effective-config\")\ndef effective_config_command(\n",
    '''
@app.command("provider-canary")
def provider_canary_command(
    mode: CanaryMode = typer.Option(CanaryMode.ASSET, help="asset or detection"),
    output_dir: Path = typer.Option(
        Path(os.getenv("MARINE_TRACK_OUTPUT_DIR", "runs/telegram")),
        help="Runtime output directory",
    ),
    base_dir: Path = typer.Option(Path("."), help="Base for relative AOI/config paths"),
    default_aoi: Path = typer.Option(
        Path(os.getenv("MARINE_TRACK_DEFAULT_AOI", "data/aoi/example_black_sea.geojson")),
        help="Default AOI used when no dedicated canary AOI is configured",
    ),
    aoi: Path | None = typer.Option(
        None,
        exists=True,
        readable=True,
        help="Optional compact canary AOI; overrides MARINE_TRACK_CANARY_AOI",
    ),
    lookback_hours: int | None = typer.Option(None, min=1, max=720),
    max_results: int | None = typer.Option(None, min=1, max=20),
    owner_user_id: int = typer.Option(1, min=1, help="Isolated detection-registry owner"),
    owner_chat_id: int = typer.Option(1, help="Isolated detection-registry chat scope"),
) -> None:
    """Run an explicitly requested live Sentinel-1 provider canary."""
    land_mask = os.getenv("MARINE_TRACK_LAND_MASK_GEOJSON", "").strip() or None
    shoreline_raw = os.getenv("MARINE_TRACK_SHORELINE_BUFFER_M", "0").strip() or "0"
    result = run_provider_canary(
        mode=mode,
        output_dir=output_dir,
        default_aoi=default_aoi,
        base_dir=base_dir,
        explicit_aoi=aoi,
        lookback_hours=lookback_hours,
        max_results=max_results,
        owner_user_id=owner_user_id,
        owner_chat_id=owner_chat_id,
        land_mask_geojson=land_mask,
        shoreline_buffer_m=float(shoreline_raw),
    )
    console.print_json(data=result.report)
    if not result.ok:
        raise typer.Exit(code=1)


@app.command("effective-config")
def effective_config_command(
''',
    "CLI provider-canary command",
)

replace_once(
    "src/marine_track/telegram_ui.py",
    'ACTION_CALIBRATION = "calibration"\nACTION_MENU = "menu"\n',
    'ACTION_CALIBRATION = "calibration"\nACTION_SELFTEST = "selftest"\nACTION_MENU = "menu"\n',
    "Telegram selftest action",
)
replace_once(
    "src/marine_track/telegram_ui.py",
    '''        rows.append(
            [
                InlineKeyboardButton(
                    f"{marker}🧪 Калибровка",
                    callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_CALIBRATION}",
                )
            ]
        )
''',
    '''        rows.append(
            [
                InlineKeyboardButton(
                    f"{marker}🧪 Калибровка",
                    callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_CALIBRATION}",
                ),
                InlineKeyboardButton(
                    "🩺 Self-test",
                    callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_SELFTEST}",
                ),
            ]
        )
''',
    "Telegram admin selftest menu button",
)
replace_once(
    "src/marine_track/telegram_ui.py",
    '        "<code>/calibrate</code> — интерфейс разметки для администратора.\\n\\n"\n',
    '        "<code>/calibrate</code> — интерфейс разметки для администратора.\\n"\n        "<code>/selftest</code> — live Sentinel-1 provider/asset self-test для администратора.\\n\\n"\n',
    "Telegram help selftest command",
)

replace_once(
    "src/marine_track/telegram_bot.py",
    "from marine_track.telegram_config import TelegramBotConfig, load_telegram_config\n",
    '''from marine_track.telegram_config import TelegramBotConfig, load_telegram_config
from marine_track.telegram_selftest import SELFTEST_CALLBACK_PREFIX
from marine_track.telegram_selftest import selftest_callback as admin_selftest_callback
from marine_track.telegram_selftest import selftest_command as admin_selftest_command
''',
    "Telegram selftest imports",
)
replace_once(
    "src/marine_track/telegram_bot.py",
    "    ACTION_STATUS,\n    ACTION_WHOAMI,\n",
    "    ACTION_STATUS,\n    ACTION_SELFTEST,\n    ACTION_WHOAMI,\n",
    "Telegram selftest menu action import",
)
replace_once(
    "src/marine_track/telegram_bot.py",
    '''async def calibrate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_calibration_command(update, context, get_config())


async def menu_callback''',
    '''async def calibrate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_calibration_command(update, context, get_config())


async def selftest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with get_semaphore():
        await admin_selftest_command(update, context, get_config())


async def menu_callback''',
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
        async with get_semaphore():
            await admin_selftest_command(update, context, get_config())
        return
    if action == ACTION_OUTPUT_MODE:
''',
    "Telegram selftest main-menu action",
)
replace_once(
    "src/marine_track/telegram_bot.py",
    '''async def calibration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_calibration_callback(update, context, get_config())


async def notify_admins_on_startup''',
    '''async def calibration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_calibration_callback(update, context, get_config())


async def selftest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with get_semaphore():
        await admin_selftest_callback(update, context, get_config())


async def notify_admins_on_startup''',
    "Telegram selftest callback wrapper",
)
replace_once(
    "src/marine_track/telegram_bot.py",
    '    app.add_handler(CommandHandler("calibrate", calibrate_command))\n',
    '    app.add_handler(CommandHandler("calibrate", calibrate_command))\n    app.add_handler(CommandHandler("selftest", selftest_command))\n',
    "Telegram selftest command registration",
)
replace_once(
    "src/marine_track/telegram_bot.py",
    '    app.add_handler(CallbackQueryHandler(calibration_callback, pattern=f"^{CALIBRATION_CALLBACK_PREFIX}:"))\n',
    '    app.add_handler(CallbackQueryHandler(calibration_callback, pattern=f"^{CALIBRATION_CALLBACK_PREFIX}:"))\n    app.add_handler(CallbackQueryHandler(selftest_callback, pattern=f"^{SELFTEST_CALLBACK_PREFIX}:"))\n',
    "Telegram selftest callback registration",
)

replace_once(
    "runtime_check.py",
    '    "marine_track.sensor_preprocessing",\n    "marine_track.provenance",\n',
    '    "marine_track.sensor_preprocessing",\n    "marine_track.provider_canary",\n    "marine_track.provenance",\n',
    "runtime provider_canary import",
)
replace_once(
    "runtime_check.py",
    '    "marine_track.telegram_detection",\n    "marine_track.telegram_ui",\n',
    '    "marine_track.telegram_detection",\n    "marine_track.telegram_selftest",\n    "marine_track.telegram_ui",\n',
    "runtime telegram_selftest import",
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
    "runtime canary AOI path validation",
)
replace_once(
    "runtime_check.py",
    '        "MARINE_TRACK_RASTER_LOCK_TIMEOUT_S",\n    }\n',
    '        "MARINE_TRACK_RASTER_LOCK_TIMEOUT_S",\n        "MARINE_TRACK_CANARY_SIDE_KM",\n        "MARINE_TRACK_CANARY_MAX_AREA_KM2",\n    }\n',
    "runtime canary float variables",
)
replace_once(
    "runtime_check.py",
    '        "MARINE_TRACK_RASTER_LOCK_TIMEOUT_S",\n        "MARINE_TRACK_MAX_AOI_AREA_KM2",\n',
    '        "MARINE_TRACK_RASTER_LOCK_TIMEOUT_S",\n        "MARINE_TRACK_CANARY_LOOKBACK_HOURS",\n        "MARINE_TRACK_CANARY_MAX_RESULTS",\n        "MARINE_TRACK_CANARY_SIDE_KM",\n        "MARINE_TRACK_CANARY_MAX_AREA_KM2",\n        "MARINE_TRACK_MAX_AOI_AREA_KM2",\n',
    "runtime canary numeric variables",
)

replace_once(
    ".env.example",
    '''# Remote GeoTIFF/COG range-read canary before materialization.
MARINE_TRACK_ASSET_PROBE_TIMEOUT_S=30
MARINE_TRACK_ASSET_PROBE_BYTES=4096

# Administrator human-in-the-loop candidate calibration.
''',
    '''# Remote GeoTIFF/COG range-read canary before materialization.
MARINE_TRACK_ASSET_PROBE_TIMEOUT_S=30
MARINE_TRACK_ASSET_PROBE_BYTES=4096

# Explicit administrator/CLI live Sentinel-1 self-test. It is never run on startup.
# Leave AOI empty to derive a compact sector from MARINE_TRACK_DEFAULT_AOI.
MARINE_TRACK_CANARY_AOI=
MARINE_TRACK_CANARY_SIDE_KM=8
MARINE_TRACK_CANARY_MAX_AREA_KM2=100
MARINE_TRACK_CANARY_LOOKBACK_HOURS=168
MARINE_TRACK_CANARY_MAX_RESULTS=5

# Administrator human-in-the-loop candidate calibration.
''',
    "environment canary settings",
)
