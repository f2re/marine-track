from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"marker not found in {relative}: {old[:140]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


(ROOT / "src/marine_track/live_canary.py").write_text(
    dedent(
        '''\
        from __future__ import annotations

        import argparse
        import json
        import os
        import re
        import time
        from collections.abc import Callable
        from contextlib import contextmanager
        from dataclasses import asdict, dataclass
        from datetime import datetime, timezone
        from pathlib import Path
        from typing import Any

        from marine_track.detection_pipeline import run_detection_for_token
        from marine_track.detection_scene_search import search_detection_capable_scenes
        from marine_track.models import Sensor
        from marine_track.resource_limits import ResourceLimits, validate_geojson_payload
        from marine_track.scene_materializer import (
            prepare_asset_access,
            probe_raster_asset,
            safe_url,
            select_processing_asset_record,
        )
        from marine_track.telegram_scene_browser import (
            register_scenes,
            run_dir,
            utc_window,
            write_temp_aoi,
        )

        ProgressCallback = Callable[[str, str], None]
        CANARY_SCHEMA_VERSION = 1
        URL_PATTERN = re.compile(r"https?://[^\\s<>]+", re.IGNORECASE)
        SECRET_PATTERN = re.compile(
            r"(?i)(authorization|bearer|token|secret|password|api[_-]?key)"
            r"(\\s*[:=]\\s*)([^\\s,;]+)"
        )


        @dataclass(frozen=True)
        class CanaryStage:
            name: str
            status: str
            critical: bool
            detail: str
            duration_ms: int
            data: dict[str, Any] | None = None


        @dataclass(frozen=True)
        class LiveCanaryReport:
            schema_version: int
            status: str
            mode: str
            generated_at: str
            sensor: str
            aoi_source: str
            stages: list[CanaryStage]

            def to_dict(self) -> dict[str, Any]:
                return {
                    "schema_version": self.schema_version,
                    "status": self.status,
                    "mode": self.mode,
                    "generated_at": self.generated_at,
                    "sensor": self.sensor,
                    "aoi_source": self.aoi_source,
                    "stages": [asdict(stage) for stage in self.stages],
                }


        @dataclass(frozen=True)
        class LiveCanaryResult:
            report: LiveCanaryReport
            report_path: Path
            detection_report: Path | None = None


        def run_live_canary(
            *,
            output_dir: str | Path,
            default_aoi: str | Path,
            mode: str = "asset",
            canary_aoi: str | Path | None = None,
            hours: int = 720,
            max_results: int = 3,
            max_span_deg: float = 0.08,
            max_area_km2: float = 150.0,
            owner_user_id: int = 1,
            owner_chat_id: int = -1,
            land_mask_geojson: str | Path | None = None,
            shoreline_buffer_m: float = 0.0,
            progress_callback: ProgressCallback | None = None,
        ) -> LiveCanaryResult:
            normalized_mode = str(mode).strip().lower()
            if normalized_mode not in {"asset", "detection"}:
                raise ValueError("canary mode must be 'asset' or 'detection'")
            if hours <= 0 or hours > 24 * 60:
                raise ValueError("canary hours must be in 1..1440")
            max_results = max(1, min(int(max_results), 5))
            output_dir = Path(output_dir)
            canary_root = output_dir / "canary"
            canary_root.mkdir(parents=True, exist_ok=True)
            stages: list[CanaryStage] = []
            detection_report: Path | None = None

            _progress(progress_callback, "configuration", "подготовка компактного AOI")
            started = time.monotonic()
            try:
                aoi_payload, aoi_source = resolve_canary_aoi(
                    default_aoi=Path(default_aoi),
                    canary_aoi=Path(canary_aoi) if canary_aoi else None,
                    max_span_deg=max_span_deg,
                    max_area_km2=max_area_km2,
                )
                metrics = validate_geojson_payload(
                    aoi_payload,
                    ResourceLimits(max_aoi_area_km2=max_area_km2),
                )
                stages.append(
                    _stage(
                        "configuration",
                        "ok",
                        True,
                        "compact WGS84 AOI validated",
                        started,
                        {
                            "area_km2": round(metrics.area_km2, 3),
                            "vertices": metrics.vertex_count,
                        },
                    )
                )
            except Exception as exc:
                stages.append(
                    _stage(
                        "configuration",
                        "failed",
                        True,
                        sanitize_detail(exc),
                        started,
                    )
                )
                return _finish(canary_root, normalized_mode, "unknown", stages, None)

            temporary_aoi = write_temp_aoi(aoi_payload)
            try:
                _progress(progress_callback, "provider_search", "поиск Sentinel-1 COG")
                started = time.monotonic()
                try:
                    start, end = utc_window(hours)
                    search_dir = run_dir(canary_root, "search")
                    search_result = search_detection_capable_scenes(
                        temporary_aoi,
                        start,
                        end,
                        Sensor.SENTINEL1,
                        search_dir,
                        max_results,
                    )
                    scene = search_result.scenes[0]
                    stages.append(
                        _stage(
                            "provider_search",
                            "ok",
                            True,
                            "detection-capable Sentinel-1 scene found",
                            started,
                            {
                                "provider": search_result.provider,
                                "product_id": str(scene.product_id),
                                "acquisition_time": scene.acquisition_time.isoformat(),
                                "scene_count": len(search_result.scenes),
                                "cache_hit": bool(search_result.cache_hit),
                            },
                        )
                    )
                except Exception as exc:
                    stages.append(
                        _stage(
                            "provider_search",
                            "failed",
                            True,
                            sanitize_detail(exc),
                            started,
                        )
                    )
                    return _finish(canary_root, normalized_mode, aoi_source, stages, None)

                _progress(progress_callback, "asset_probe", "runtime signing/OAuth и range-read")
                started = time.monotonic()
                try:
                    selected = select_processing_asset_record(scene)
                    if selected is None:
                        raise RuntimeError("selected scene has no processable raster asset")
                    asset_key, asset, href = selected
                    access_href, headers = prepare_asset_access(
                        href,
                        search_result.provider,
                        asset,
                    )
                    probe = probe_raster_asset(access_href, headers=headers)
                    probe_status = "ok" if probe.range_supported is not False else "warning"
                    detail = (
                        "TIFF range-read succeeded"
                        if probe_status == "ok"
                        else "TIFF access succeeded, but byte-range support was not confirmed"
                    )
                    stages.append(
                        _stage(
                            "asset_probe",
                            probe_status,
                            True,
                            detail,
                            started,
                            {
                                "asset_key": asset_key,
                                "href": safe_url(access_href),
                                "media_type": asset.media_type,
                                "auth_mode": asset.auth_mode,
                                "http_status": probe.status,
                                "bytes_checked": probe.bytes_checked,
                                "range_supported": probe.range_supported,
                            },
                        )
                    )
                except Exception as exc:
                    stages.append(
                        _stage(
                            "asset_probe",
                            "failed",
                            True,
                            sanitize_detail(exc),
                            started,
                        )
                    )
                    return _finish(canary_root, normalized_mode, aoi_source, stages, None)

                if normalized_mode == "detection":
                    _progress(progress_callback, "detection", "малый AOI end-to-end")
                    started = time.monotonic()
                    try:
                        if owner_user_id <= 0 or owner_chat_id == 0:
                            raise ValueError(
                                "detection canary requires non-zero owner user/chat ids"
                            )
                        tokens = register_scenes(
                            output_dir,
                            search_result.provider,
                            search_result.sensor,
                            [scene],
                            search_result.scenes_json,
                            search_result.asset_manifest,
                            owner_user_id=owner_user_id,
                            owner_chat_id=owner_chat_id,
                            aoi_geojson=aoi_payload,
                            search_hours=hours,
                        )
                        if not tokens:
                            raise RuntimeError("scene registry returned no canary token")
                        with _temporary_env("MARINE_TRACK_ENABLE_WAKE_RESEARCH", "0"):
                            detection = run_detection_for_token(
                                token=tokens[0],
                                output_dir=output_dir,
                                owner_user_id=owner_user_id,
                                owner_chat_id=owner_chat_id,
                                max_crops=0,
                                land_mask_geojson=land_mask_geojson,
                                shoreline_buffer_m=shoreline_buffer_m,
                            )
                        detection_report = detection.report_json
                        preprocessing = getattr(detection, "preprocessing_plan", None)
                        preprocessing_data = (
                            preprocessing.as_report_dict()
                            if preprocessing is not None
                            and hasattr(preprocessing, "as_report_dict")
                            else None
                        )
                        stages.append(
                            _stage(
                                "detection",
                                "ok",
                                True,
                                "compact AOI detection completed",
                                started,
                                {
                                    "candidate_count": len(detection.detections),
                                    "report_file": detection.report_json.name,
                                    "preprocessing": preprocessing_data,
                                    "wake_research": False,
                                },
                            )
                        )
                    except Exception as exc:
                        stages.append(
                            _stage(
                                "detection",
                                "failed",
                                True,
                                sanitize_detail(exc),
                                started,
                            )
                        )
            finally:
                temporary_aoi.unlink(missing_ok=True)

            return _finish(
                canary_root,
                normalized_mode,
                aoi_source,
                stages,
                detection_report,
            )


        def resolve_canary_aoi(
            *,
            default_aoi: Path,
            canary_aoi: Path | None,
            max_span_deg: float,
            max_area_km2: float,
        ) -> tuple[dict[str, Any], str]:
            if canary_aoi is not None:
                if not canary_aoi.is_file():
                    raise FileNotFoundError(f"canary AOI not found: {canary_aoi}")
                payload = json.loads(canary_aoi.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("canary AOI must be a GeoJSON object")
                validate_geojson_payload(
                    payload,
                    ResourceLimits(max_aoi_area_km2=max_area_km2),
                )
                return payload, "configured_canary_aoi"
            if not default_aoi.is_file():
                raise FileNotFoundError(f"default AOI not found: {default_aoi}")
            payload = json.loads(default_aoi.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("default AOI must be a GeoJSON object")
            return compact_canary_geojson(payload, max_span_deg), "derived_default_aoi"


        def compact_canary_geojson(
            payload: dict[str, Any],
            max_span_deg: float = 0.08,
        ) -> dict[str, Any]:
            try:
                from shapely.geometry import GeometryCollection, box, mapping, shape
                from shapely.ops import unary_union
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("shapely is required for canary AOI derivation") from exc
            span = float(max_span_deg)
            if not 0.005 <= span <= 1.0:
                raise ValueError("canary max_span_deg must be in [0.005, 1.0]")
            geometries = []
            geo_type = payload.get("type")
            if geo_type == "FeatureCollection":
                for feature in payload.get("features") or []:
                    if isinstance(feature, dict) and isinstance(feature.get("geometry"), dict):
                        geometries.append(shape(feature["geometry"]))
            elif geo_type == "Feature" and isinstance(payload.get("geometry"), dict):
                geometries.append(shape(payload["geometry"]))
            else:
                geometries.append(shape(payload))
            geometries = [geometry for geometry in geometries if not geometry.is_empty]
            if not geometries:
                raise ValueError("AOI has no non-empty geometry")
            combined = unary_union(geometries)
            if not combined.is_valid:
                raise ValueError("AOI geometry is topologically invalid")
            point = combined.representative_point()
            half = span / 2.0
            clip = box(point.x - half, point.y - half, point.x + half, point.y + half)
            compact = combined.intersection(clip)
            if isinstance(compact, GeometryCollection):
                polygons = [
                    geometry
                    for geometry in compact.geoms
                    if geometry.geom_type in {"Polygon", "MultiPolygon"}
                ]
                compact = unary_union(polygons) if polygons else compact
            if compact.is_empty or compact.geom_type not in {"Polygon", "MultiPolygon"}:
                raise ValueError("cannot derive a compact polygonal canary AOI")
            return {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "name": "marine_track_live_canary",
                            "source": "derived_default_aoi",
                        },
                        "geometry": mapping(compact),
                    }
                ],
            }


        def sanitize_detail(value: object) -> str:
            text = str(value).replace("\\n", " ").replace("\\r", " ")
            text = URL_PATTERN.sub(lambda match: safe_url(match.group(0)), text)
            text = SECRET_PATTERN.sub(lambda match: f"{match.group(1)}{match.group(2)}<redacted>", text)
            return " ".join(text.split())[:700]


        def _stage(
            name: str,
            status: str,
            critical: bool,
            detail: str,
            started: float,
            data: dict[str, Any] | None = None,
        ) -> CanaryStage:
            return CanaryStage(
                name=name,
                status=status,
                critical=critical,
                detail=sanitize_detail(detail),
                duration_ms=max(0, int(round((time.monotonic() - started) * 1000))),
                data=data,
            )


        def _finish(
            canary_root: Path,
            mode: str,
            aoi_source: str,
            stages: list[CanaryStage],
            detection_report: Path | None,
        ) -> LiveCanaryResult:
            critical_failed = any(
                stage.critical and stage.status == "failed" for stage in stages
            )
            warning = any(stage.status == "warning" for stage in stages)
            status = "failed" if critical_failed else "degraded" if warning else "ok"
            generated_at = datetime.now(timezone.utc)
            report = LiveCanaryReport(
                schema_version=CANARY_SCHEMA_VERSION,
                status=status,
                mode=mode,
                generated_at=generated_at.isoformat(),
                sensor=Sensor.SENTINEL1.value,
                aoi_source=aoi_source,
                stages=stages,
            )
            stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
            path = canary_root / f"live_canary_{mode}_{stamp}.json"
            _atomic_write_json(path, report.to_dict())
            return LiveCanaryResult(report, path, detection_report)


        def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\\n",
                encoding="utf-8",
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)


        def _progress(callback: ProgressCallback | None, stage: str, detail: str) -> None:
            if callback is not None:
                callback(stage, detail)


        @contextmanager
        def _temporary_env(name: str, value: str):
            previous = os.environ.get(name)
            os.environ[name] = value
            try:
                yield
            finally:
                if previous is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = previous


        def _load_env_file(path: Path) -> None:
            if not path.is_file():
                return
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                parsed = value.strip().strip('"').strip("'")
                if key not in os.environ or not os.environ[key].strip():
                    os.environ[key] = parsed


        def main(argv: list[str] | None = None) -> int:
            parser = argparse.ArgumentParser(
                description="Marine Track live Sentinel-1 provider/asset canary"
            )
            parser.add_argument("--mode", choices=("asset", "detection"), default="asset")
            parser.add_argument("--env-file", default="/etc/marine-track/marine-track.env")
            parser.add_argument("--default-aoi", default=None)
            parser.add_argument("--canary-aoi", default=None)
            parser.add_argument("--output-dir", default=None)
            parser.add_argument("--hours", type=int, default=None)
            parser.add_argument("--max-results", type=int, default=None)
            parser.add_argument("--owner-user-id", type=int, default=1)
            parser.add_argument("--owner-chat-id", type=int, default=-1)
            args = parser.parse_args(argv)
            _load_env_file(Path(args.env_file))
            default_aoi = Path(
                args.default_aoi
                or os.getenv(
                    "MARINE_TRACK_DEFAULT_AOI",
                    "data/aoi/example_black_sea.geojson",
                )
            )
            output_dir = Path(
                args.output_dir
                or os.getenv("MARINE_TRACK_OUTPUT_DIR", "runs/telegram")
            )
            canary_aoi = args.canary_aoi or os.getenv("MARINE_TRACK_CANARY_AOI", "")
            result = run_live_canary(
                output_dir=output_dir,
                default_aoi=default_aoi,
                mode=args.mode,
                canary_aoi=canary_aoi or None,
                hours=args.hours
                or int(os.getenv("MARINE_TRACK_CANARY_HOURS", "720")),
                max_results=args.max_results
                or int(os.getenv("MARINE_TRACK_CANARY_MAX_RESULTS", "3")),
                max_span_deg=float(
                    os.getenv("MARINE_TRACK_CANARY_MAX_SPAN_DEG", "0.08")
                ),
                max_area_km2=float(
                    os.getenv("MARINE_TRACK_CANARY_MAX_AREA_KM2", "150")
                ),
                owner_user_id=args.owner_user_id,
                owner_chat_id=args.owner_chat_id,
                land_mask_geojson=os.getenv("MARINE_TRACK_LAND_MASK_GEOJSON") or None,
                shoreline_buffer_m=float(
                    os.getenv("MARINE_TRACK_SHORELINE_BUFFER_M", "0") or 0
                ),
            )
            print(json.dumps(result.report.to_dict(), ensure_ascii=False, indent=2))
            print(f"report_path={result.report_path}")
            return 1 if result.report.status == "failed" else 0


        if __name__ == "__main__":
            raise SystemExit(main())
        '''
    ),
    encoding="utf-8",
)

(ROOT / "src/marine_track/telegram_selftest.py").write_text(
    dedent(
        '''\
        from __future__ import annotations

        import asyncio
        import html
        import os
        from pathlib import Path

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
        from telegram.constants import ParseMode
        from telegram.ext import ContextTypes

        from marine_track.live_canary import LiveCanaryResult, run_live_canary
        from marine_track.telegram_config import TelegramBotConfig
        from marine_track.telegram_ui import ACTION_MENU, MENU_CALLBACK_PREFIX

        SELFTEST_CALLBACK_PREFIX = "mtself"
        ACTION_MENU_SELFTEST = "menu"
        ACTION_ASSET = "asset"
        ACTION_DETECTION_CONFIRM = "detect_confirm"
        ACTION_DETECTION = "detect"


        def effective_user_id(update: Update) -> int:
            return int(getattr(update.effective_user, "id", 0) or 0)


        def effective_chat_id(update: Update) -> int:
            return int(getattr(update.effective_chat, "id", 0) or 0)


        def is_admin(update: Update, config: TelegramBotConfig) -> bool:
            return effective_user_id(update) in config.admin_ids


        def selftest_menu_markup() -> InlineKeyboardMarkup:
            return InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔌 Каталог + COG range-read",
                            callback_data=_cb(ACTION_ASSET),
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🛰 Полный тест малого AOI",
                            callback_data=_cb(ACTION_DETECTION_CONFIRM),
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🏠 Меню",
                            callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_MENU}",
                        )
                    ],
                ]
            )


        def confirmation_markup() -> InlineKeyboardMarkup:
            return InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Запустить 1 сцену",
                            callback_data=_cb(ACTION_DETECTION),
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "⬅️ Самопроверка",
                            callback_data=_cb(ACTION_MENU_SELFTEST),
                        )
                    ],
                ]
            )


        async def selftest_command(
            update: Update,
            context: ContextTypes.DEFAULT_TYPE,
            config: TelegramBotConfig,
        ) -> None:
            del context
            target = _target(update)
            if not target:
                return
            if not is_admin(update, config):
                await target.reply_text(
                    f"Самопроверка доступна только администраторам. Ваш id: {effective_user_id(update)}."
                )
                return
            await target.reply_text(
                "🩺 <b>Live self-test Marine Track</b>\\n"
                "Первый режим проверяет реальный Sentinel-1 search, runtime signing/OAuth и "
                "TIFF byte-range без загрузки полного raster.\\n\\n"
                "Полный режим дополнительно скачивает и обрабатывает один компактный AOI; "
                "он запускается только после отдельного подтверждения.",
                parse_mode=ParseMode.HTML,
                reply_markup=selftest_menu_markup(),
            )


        async def selftest_callback(
            update: Update,
            context: ContextTypes.DEFAULT_TYPE,
            config: TelegramBotConfig,
        ) -> None:
            del context
            query = update.callback_query
            if not query or not query.data:
                return
            await query.answer()
            if not is_admin(update, config):
                await query.message.reply_text("Недостаточно прав для live self-test.")
                return
            parts = query.data.split(":")
            if len(parts) != 2 or parts[0] != SELFTEST_CALLBACK_PREFIX:
                return
            action = parts[1]
            if action == ACTION_MENU_SELFTEST:
                await selftest_command(update, ContextTypes.DEFAULT_TYPE, config)  # type: ignore[arg-type]
                return
            if action == ACTION_DETECTION_CONFIRM:
                await query.message.reply_text(
                    "⚠️ <b>Полный live test</b>\\n"
                    "Будет найдена, подписана/авторизована и обработана одна Sentinel-1 сцена "
                    "для малого AOI. Это расходует сеть, дисковый cache и provider quota.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=confirmation_markup(),
                )
                return
            if action in {ACTION_ASSET, ACTION_DETECTION}:
                await run_selftest(update, config, "asset" if action == ACTION_ASSET else "detection")
                return
            await query.message.reply_text(
                "Кнопка устарела. Откройте /selftest заново.",
                reply_markup=selftest_menu_markup(),
            )


        async def run_selftest(
            update: Update,
            config: TelegramBotConfig,
            mode: str,
        ) -> None:
            target = _target(update)
            if not target:
                return
            status = await target.reply_text(
                "⏳ Live self-test: инициализация",
            )
            loop = asyncio.get_running_loop()

            def progress(stage: str, detail: str) -> None:
                asyncio.run_coroutine_threadsafe(
                    status.edit_text(
                        f"⏳ Live self-test · {stage}\\n{detail}"[:4000]
                    ),
                    loop,
                )

            try:
                result = await asyncio.to_thread(
                    run_live_canary,
                    output_dir=config.output_dir,
                    default_aoi=config.default_aoi,
                    mode=mode,
                    canary_aoi=os.getenv("MARINE_TRACK_CANARY_AOI", "") or None,
                    hours=_env_int("MARINE_TRACK_CANARY_HOURS", 720, 1, 1440),
                    max_results=_env_int("MARINE_TRACK_CANARY_MAX_RESULTS", 3, 1, 5),
                    max_span_deg=_env_float(
                        "MARINE_TRACK_CANARY_MAX_SPAN_DEG", 0.08, 0.005, 1.0
                    ),
                    max_area_km2=_env_float(
                        "MARINE_TRACK_CANARY_MAX_AREA_KM2", 150.0, 1.0, 5000.0
                    ),
                    owner_user_id=effective_user_id(update),
                    owner_chat_id=effective_chat_id(update),
                    land_mask_geojson=config.land_mask_geojson,
                    shoreline_buffer_m=config.shoreline_buffer_m,
                    progress_callback=progress,
                )
            except Exception as exc:  # noqa: BLE001 - administrator-facing boundary
                await status.edit_text(
                    f"⛔ Live self-test не запущен\\n<code>{html.escape(str(exc))}</code>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=selftest_menu_markup(),
                )
                return
            await status.edit_text(
                result_text(result),
                parse_mode=ParseMode.HTML,
                reply_markup=result_markup(result),
            )


        def result_text(result: LiveCanaryResult) -> str:
            symbols = {"ok": "✅", "degraded": "⚠️", "failed": "⛔", "warning": "⚠️"}
            lines = [
                f"{symbols.get(result.report.status, 'ℹ️')} <b>Live self-test: "
                f"{html.escape(result.report.status)}</b>",
                f"mode: <code>{html.escape(result.report.mode)}</code>",
                f"report: <code>{html.escape(result.report_path.name)}</code>",
                "",
            ]
            for stage in result.report.stages:
                lines.append(
                    f"{symbols.get(stage.status, 'ℹ️')} <b>{html.escape(stage.name)}</b> · "
                    f"<code>{stage.duration_ms} ms</code>\\n"
                    f"{html.escape(stage.detail)}"
                )
            return "\\n".join(lines)[:4000]


        def result_markup(result: LiveCanaryResult) -> InlineKeyboardMarkup:
            rows = []
            if result.report.mode == "asset" and result.report.status != "failed":
                rows.append(
                    [
                        InlineKeyboardButton(
                            "🛰 Подтвердить полный тест",
                            callback_data=_cb(ACTION_DETECTION_CONFIRM),
                        )
                    ]
                )
            rows.append(
                [
                    InlineKeyboardButton(
                        "↻ Повторить",
                        callback_data=_cb(
                            ACTION_ASSET
                            if result.report.mode == "asset"
                            else ACTION_DETECTION_CONFIRM
                        ),
                    )
                ]
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        "🏠 Меню",
                        callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_MENU}",
                    )
                ]
            )
            return InlineKeyboardMarkup(rows)


        def _target(update: Update):
            return update.effective_message or (
                update.callback_query.message if update.callback_query else None
            )


        def _cb(action: str) -> str:
            return f"{SELFTEST_CALLBACK_PREFIX}:{action}"


        def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
            try:
                value = int(os.getenv(name, str(default)) or default)
            except ValueError:
                value = default
            return max(minimum, min(maximum, value))


        def _env_float(
            name: str,
            default: float,
            minimum: float,
            maximum: float,
        ) -> float:
            try:
                value = float(os.getenv(name, str(default)) or default)
            except ValueError:
                value = default
            return max(minimum, min(maximum, value))
        '''
    ),
    encoding="utf-8",
)

replace_once(
    "pyproject.toml",
    'marine-track-health = "marine_track.health:main"\n',
    'marine-track-health = "marine_track.health:main"\n'
    'marine-track-live-check = "marine_track.live_canary:main"\n',
)

replace_once(
    "runtime_check.py",
    '    "marine_track.health",\n',
    '    "marine_track.health",\n'
    '    "marine_track.live_canary",\n'
    '    "marine_track.telegram_selftest",\n',
)

ui = ROOT / "src/marine_track/telegram_ui.py"
text = ui.read_text(encoding="utf-8")
if 'ACTION_SELFTEST = "selftest"' not in text:
    text = text.replace(
        'ACTION_CALIBRATION = "calibration"\n',
        'ACTION_CALIBRATION = "calibration"\nACTION_SELFTEST = "selftest"\n',
        1,
    )
old_admin = '''    if is_admin:
        marker = "⚠️ " if calibration_needed else ""
        rows.append(
            [
                InlineKeyboardButton(
                    f"{marker}🧪 Калибровка",
                    callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_CALIBRATION}",
                )
            ]
        )
'''
new_admin = '''    if is_admin:
        marker = "⚠️ " if calibration_needed else ""
        rows.append(
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
'''
if old_admin not in text:
    raise RuntimeError("telegram_ui admin menu marker not found")
text = text.replace(old_admin, new_admin, 1)
text = text.replace(
    '<code>/calibrate</code> — интерфейс разметки для администратора.\\n\\n',
    '<code>/calibrate</code> — интерфейс разметки для администратора.\\n'
    '<code>/selftest</code> — live Sentinel-1 provider/COG проверка администратора.\\n\\n',
    1,
)
ui.write_text(text, encoding="utf-8")

bot = ROOT / "src/marine_track/telegram_bot.py"
text = bot.read_text(encoding="utf-8")
text = text.replace(
    "from marine_track.telegram_scene_browser import (\n",
    "from marine_track.telegram_selftest import (\n"
    "    SELFTEST_CALLBACK_PREFIX,\n"
    "    selftest_callback as admin_selftest_callback,\n"
    "    selftest_command as admin_selftest_command,\n"
    ")\n"
    "from marine_track.telegram_scene_browser import (\n",
    1,
)
text = text.replace(
    "    ACTION_STATUS,\n",
    "    ACTION_STATUS,\n    ACTION_SELFTEST,\n",
    1,
)
command_marker = '''async def calibrate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_calibration_command(update, context, get_config())


'''
command_block = '''async def calibrate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_calibration_command(update, context, get_config())


async def selftest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_selftest_command(update, context, get_config())


'''
if command_marker not in text:
    raise RuntimeError("telegram_bot calibrate command marker not found")
text = text.replace(command_marker, command_block, 1)
menu_marker = '''    if action == ACTION_CALIBRATION:
        await admin_calibration_command(update, context, get_config())
        return
'''
menu_block = '''    if action == ACTION_CALIBRATION:
        await admin_calibration_command(update, context, get_config())
        return
    if action == ACTION_SELFTEST:
        await admin_selftest_command(update, context, get_config())
        return
'''
if menu_marker not in text:
    raise RuntimeError("telegram_bot menu calibration marker not found")
text = text.replace(menu_marker, menu_block, 1)
callback_marker = '''async def calibration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_calibration_callback(update, context, get_config())


'''
callback_block = '''async def calibration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_calibration_callback(update, context, get_config())


async def selftest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_selftest_callback(update, context, get_config())


'''
if callback_marker not in text:
    raise RuntimeError("telegram_bot calibration callback marker not found")
text = text.replace(callback_marker, callback_block, 1)
text = text.replace(
    '    app.add_handler(CommandHandler("calibrate", calibrate_command))\n',
    '    app.add_handler(CommandHandler("calibrate", calibrate_command))\n'
    '    app.add_handler(CommandHandler("selftest", selftest_command))\n',
    1,
)
text = text.replace(
    '    app.add_handler(CallbackQueryHandler(calibration_callback, pattern=f"^{CALIBRATION_CALLBACK_PREFIX}:"))\n',
    '    app.add_handler(CallbackQueryHandler(calibration_callback, pattern=f"^{CALIBRATION_CALLBACK_PREFIX}:"))\n'
    '    app.add_handler(CallbackQueryHandler(selftest_callback, pattern=f"^{SELFTEST_CALLBACK_PREFIX}:"))\n',
    1,
)
bot.write_text(text, encoding="utf-8")

example = ROOT / ".env.example"
text = example.read_text(encoding="utf-8")
marker = "# Administrator human-in-the-loop candidate calibration.\n"
canary = '''# Administrator-triggered live Sentinel-1 canary. Never runs automatically on restart.
MARINE_TRACK_CANARY_AOI=
MARINE_TRACK_CANARY_HOURS=720
MARINE_TRACK_CANARY_MAX_RESULTS=3
MARINE_TRACK_CANARY_MAX_SPAN_DEG=0.08
MARINE_TRACK_CANARY_MAX_AREA_KM2=150

'''
if marker not in text:
    raise RuntimeError(".env canary insertion marker not found")
example.write_text(text.replace(marker, canary + marker, 1), encoding="utf-8")

runtime = ROOT / "runtime_check.py"
text = runtime.read_text(encoding="utf-8")
float_marker = '        "MARINE_TRACK_MAX_AOI_AREA_KM2",\n'
if float_marker in text and '        "MARINE_TRACK_CANARY_MAX_SPAN_DEG",\n' not in text:
    text = text.replace(
        float_marker,
        float_marker
        + '        "MARINE_TRACK_CANARY_MAX_SPAN_DEG",\n'
        + '        "MARINE_TRACK_CANARY_MAX_AREA_KM2",\n',
        1,
    )
numeric_marker = '        "MARINE_TRACK_MAX_CANDIDATES",\n'
if numeric_marker in text and '        "MARINE_TRACK_CANARY_HOURS",\n' not in text:
    text = text.replace(
        numeric_marker,
        numeric_marker
        + '        "MARINE_TRACK_CANARY_HOURS",\n'
        + '        "MARINE_TRACK_CANARY_MAX_RESULTS",\n'
        + '        "MARINE_TRACK_CANARY_MAX_SPAN_DEG",\n'
        + '        "MARINE_TRACK_CANARY_MAX_AREA_KM2",\n',
        1,
    )
runtime.write_text(text, encoding="utf-8")

(ROOT / "docs/LIVE_CANARY.md").write_text(
    dedent(
        '''\
        # Live Sentinel-1 canary

        Unit tests and offline health checks cannot prove that the deployed host can currently reach a
        provider, acquire an OAuth token/sign a URL, or read a real COG. The live canary is an explicit
        administrator action and never runs automatically during restart or deployment.

        ## Safe asset mode

        ```bash
        /opt/marine_track/current/.venv/bin/marine-track-live-check \\
          --mode asset \\
          --env-file /etc/marine-track/marine-track.env
        ```

        It derives a compact polygon from `MARINE_TRACK_CANARY_AOI` or the configured default AOI,
        searches the normal Sentinel-1 provider fallback, selects a typed processing asset, applies
        runtime signing/OAuth and requests TIFF bytes using HTTP Range. It does not download the full
        raster.

        ## Full detection mode

        ```bash
        /opt/marine_track/current/.venv/bin/marine-track-live-check \\
          --mode detection \\
          --env-file /etc/marine-track/marine-track.env
        ```

        This additionally registers one scoped scene token, materializes the compact AOI and runs the
        operational Sentinel-1 detector with wake research forced off. It consumes provider quota,
        network, cache and CPU, so Telegram requires a separate confirmation.

        Telegram administrators use `/selftest` or `🩺 Self-test` in the main menu. Reports are written
        as mode `0600` JSON files below `MARINE_TRACK_OUTPUT_DIR/canary/`. Report fields contain only
        sanitized URLs and file names; bearer tokens, signed query strings, passwords and absolute
        detection report paths are not included.

        `degraded` means access succeeded but byte-range support was not confirmed. `failed` identifies
        the exact configuration, search, asset-probe or detection stage and returns a non-zero CLI exit
        code.
        '''
    ),
    encoding="utf-8",
)

(ROOT / "tests/test_live_canary.py").write_text(
    dedent(
        '''\
        from __future__ import annotations

        import json
        from datetime import datetime, timezone
        from pathlib import Path
        from types import SimpleNamespace

        import pytest
        from shapely.geometry import shape

        from marine_track.live_canary import (
            compact_canary_geojson,
            run_live_canary,
            sanitize_detail,
        )
        from marine_track.models import Sensor
        from marine_track.scene_materializer import AssetProbe


        def _aoi(path: Path) -> Path:
            path.write_text(
                json.dumps(
                    {
                        "type": "Polygon",
                        "coordinates": [
                            [[30.0, 43.0], [31.0, 43.0], [31.0, 44.0], [30.0, 44.0], [30.0, 43.0]]
                        ],
                    }
                ),
                encoding="utf-8",
            )
            return path


        def test_compact_canary_aoi_stays_inside_source():
            source = {
                "type": "Polygon",
                "coordinates": [
                    [[30.0, 43.0], [31.0, 43.0], [31.0, 44.0], [30.0, 44.0], [30.0, 43.0]]
                ],
            }
            compact = compact_canary_geojson(source, 0.08)
            source_shape = shape(source)
            compact_shape = shape(compact["features"][0]["geometry"])
            assert source_shape.covers(compact_shape)
            minx, miny, maxx, maxy = compact_shape.bounds
            assert maxx - minx <= pytest.approx(0.08, abs=1e-9)
            assert maxy - miny <= pytest.approx(0.08, abs=1e-9)


        def test_asset_canary_redacts_signed_query_and_writes_private_report(
            tmp_path, monkeypatch
        ):
            scene = SimpleNamespace(
                product_id="S1_TEST",
                acquisition_time=datetime(2026, 7, 10, tzinfo=timezone.utc),
            )
            search = SimpleNamespace(
                provider="planetary_computer",
                sensor=Sensor.SENTINEL1,
                scenes=[scene],
                scenes_json=tmp_path / "scenes.json",
                asset_manifest=tmp_path / "assets.csv",
                cache_hit=False,
            )
            asset = SimpleNamespace(
                media_type="image/tiff; application=geotiff; profile=cloud-optimized",
                auth_mode="runtime_signing",
            )
            monkeypatch.setattr(
                "marine_track.live_canary.search_detection_capable_scenes",
                lambda *args, **kwargs: search,
            )
            monkeypatch.setattr(
                "marine_track.live_canary.select_processing_asset_record",
                lambda _scene: ("vv", asset, "https://example.test/s1.tif"),
            )
            monkeypatch.setattr(
                "marine_track.live_canary.prepare_asset_access",
                lambda href, provider, selected: (
                    href + "?sig=SECRET&token=SECRET",
                    {"Authorization": "Bearer SECRET"},
                ),
            )
            monkeypatch.setattr(
                "marine_track.live_canary.probe_raster_asset",
                lambda href, headers=None: AssetProbe(True, 206, "image/tiff", 4096, True),
            )
            result = run_live_canary(
                output_dir=tmp_path / "out",
                default_aoi=_aoi(tmp_path / "aoi.geojson"),
                mode="asset",
            )
            assert result.report.status == "ok"
            payload = result.report_path.read_text(encoding="utf-8")
            assert "SECRET" not in payload
            assert "?sig=" not in payload
            assert result.report_path.stat().st_mode & 0o777 == 0o600


        def test_detection_canary_forces_wake_research_off(tmp_path, monkeypatch):
            scene = SimpleNamespace(
                product_id="S1_TEST",
                acquisition_time=datetime(2026, 7, 10, tzinfo=timezone.utc),
            )
            search = SimpleNamespace(
                provider="test",
                sensor=Sensor.SENTINEL1,
                scenes=[scene],
                scenes_json=tmp_path / "scenes.json",
                asset_manifest=tmp_path / "assets.csv",
                cache_hit=True,
            )
            asset = SimpleNamespace(media_type="image/tiff", auth_mode="public")
            monkeypatch.setattr(
                "marine_track.live_canary.search_detection_capable_scenes",
                lambda *args, **kwargs: search,
            )
            monkeypatch.setattr(
                "marine_track.live_canary.select_processing_asset_record",
                lambda _scene: ("vv", asset, "https://example.test/s1.tif"),
            )
            monkeypatch.setattr(
                "marine_track.live_canary.prepare_asset_access",
                lambda href, provider, selected: (href, {}),
            )
            monkeypatch.setattr(
                "marine_track.live_canary.probe_raster_asset",
                lambda href, headers=None: AssetProbe(True, 206, "image/tiff", 4096, True),
            )
            monkeypatch.setattr(
                "marine_track.live_canary.register_scenes",
                lambda *args, **kwargs: ["token"],
            )
            seen = {}

            def fake_detection(**kwargs):
                seen["wake"] = __import__("os").environ.get(
                    "MARINE_TRACK_ENABLE_WAKE_RESEARCH"
                )
                report = tmp_path / "report.json"
                report.write_text("{}", encoding="utf-8")
                return SimpleNamespace(
                    detections=[],
                    report_json=report,
                    preprocessing_plan=SimpleNamespace(
                        as_report_dict=lambda: {"output_domain": "relative_backscatter_db"}
                    ),
                )

            monkeypatch.setattr(
                "marine_track.live_canary.run_detection_for_token",
                fake_detection,
            )
            result = run_live_canary(
                output_dir=tmp_path / "out",
                default_aoi=_aoi(tmp_path / "aoi.geojson"),
                mode="detection",
                owner_user_id=10,
                owner_chat_id=20,
            )
            assert result.report.status == "ok"
            assert seen["wake"] == "0"
            assert result.detection_report is not None


        def test_sanitize_detail_removes_url_query_and_secret_values():
            text = sanitize_detail(
                "GET https://example.test/a.tif?sig=abc token=abc Authorization:Bearer-abc"
            )
            assert "sig=abc" not in text
            assert "token=abc" not in text
            assert "Bearer-abc" not in text
        '''
    ),
    encoding="utf-8",
)

(ROOT / "tests/test_telegram_selftest.py").write_text(
    dedent(
        '''\
        from marine_track.telegram_selftest import (
            confirmation_markup,
            result_markup,
            selftest_menu_markup,
        )
        from marine_track.live_canary import LiveCanaryReport, LiveCanaryResult
        from pathlib import Path


        def _callbacks(markup):
            return [
                button.callback_data
                for row in markup.inline_keyboard
                for button in row
                if button.callback_data
            ]


        def test_selftest_callback_payloads_fit_telegram_limit():
            for markup in (selftest_menu_markup(), confirmation_markup()):
                callbacks = _callbacks(markup)
                assert callbacks
                assert all(len(value.encode("utf-8")) <= 64 for value in callbacks)


        def test_asset_result_offers_explicit_full_test_confirmation(tmp_path):
            report = LiveCanaryReport(1, "ok", "asset", "now", "sentinel1", "test", [])
            result = LiveCanaryResult(report, Path(tmp_path) / "report.json")
            callbacks = _callbacks(result_markup(result))
            assert "mtself:detect_confirm" in callbacks
            assert "mtself:detect" not in callbacks
        '''
    ),
    encoding="utf-8",
)

print("live canary and Telegram self-test migration applied")
