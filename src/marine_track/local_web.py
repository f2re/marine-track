from __future__ import annotations

import argparse
import json
import mimetypes
import os
import threading
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from marine_track.models import Sensor
from marine_track.telegram_scene_browser import (
    bbox_geojson,
    download_preview,
    find_scene,
    parse_scene_hours,
    parse_scene_sensor,
    register_scenes,
    run_dir,
    select_preview_asset,
    utc_window,
    write_temp_aoi,
)

LOCAL_OWNER_USER_ID = 1
LOCAL_OWNER_CHAT_ID = 1
MAX_REQUEST_BYTES = 64 * 1024
WEB_ROOT = Path(__file__).with_name("local_web_assets")


def load_local_env(path: Path | None = None) -> Path | None:
    """Load local-console settings without overriding the parent environment."""

    env_path = path
    if env_path is None:
        configured = os.getenv("MARINE_TRACK_ENV_FILE", ".env").strip() or ".env"
        env_path = Path(configured)
    if not env_path.is_file():
        return None
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env_path


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise RuntimeError(f"{name} must be boolean, got {raw!r}")


@dataclass(frozen=True)
class LocalWebConfig:
    output_dir: Path = Path("runs/local")
    host: str = "127.0.0.1"
    port: int = 8080
    max_results: int = 10
    max_concurrent_jobs: int = 1
    detection_max_crops: int = 10
    detection_job_timeout_s: int = 300
    land_mask_geojson: Path | None = Path("data/masks/land.geojson")
    shoreline_buffer_m: float = 500.0
    auto_update_land_mask: bool = True
    threshold_sigma: float = 4.5
    min_contrast_sigma: float = 5.0
    min_area_px: int = 3


def load_local_web_config() -> LocalWebConfig:
    land_mask_raw = os.getenv("MARINE_TRACK_LAND_MASK_GEOJSON", "").strip()
    auto_land_mask = _env_bool("MARINE_TRACK_LOCAL_AUTO_LAND_MASK", True)
    land_mask = (
        Path(land_mask_raw)
        if land_mask_raw
        else Path("data/masks/land.geojson") if auto_land_mask else None
    )
    return LocalWebConfig(
        output_dir=Path(os.getenv("MARINE_TRACK_LOCAL_OUTPUT_DIR", "runs/local")),
        host=os.getenv("MARINE_TRACK_LOCAL_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=_env_int("MARINE_TRACK_LOCAL_PORT", 8080, 1, 65535),
        max_results=_env_int("MARINE_TRACK_MAX_RESULTS", 10, 1, 100),
        max_concurrent_jobs=_env_int("MARINE_TRACK_MAX_CONCURRENT_JOBS", 1, 1, 10),
        detection_max_crops=_env_int("MARINE_TRACK_DETECTION_MAX_CROPS", 10, 0, 100),
        detection_job_timeout_s=_env_int(
            "MARINE_TRACK_DETECTION_JOB_TIMEOUT_S", 300, 10, 3600
        ),
        land_mask_geojson=land_mask,
        shoreline_buffer_m=_env_float(
            "MARINE_TRACK_SHORELINE_BUFFER_M", 500.0, 0.0, 100_000.0
        ),
        auto_update_land_mask=auto_land_mask,
        threshold_sigma=_env_float(
            "MARINE_TRACK_LOCAL_DETECTION_THRESHOLD_SIGMA", 4.5, 0.1, 100.0
        ),
        min_contrast_sigma=_env_float(
            "MARINE_TRACK_LOCAL_DETECTION_MIN_CONTRAST_SIGMA", 5.0, 0.0, 100.0
        ),
        min_area_px=_env_int("MARINE_TRACK_LOCAL_DETECTION_MIN_AREA_PX", 3, 1, 1000),
    )


@dataclass(frozen=True)
class SearchRequestPayload:
    sensor: Sensor
    hours: int
    max_results: int
    bbox: tuple[float, float, float, float]

    @classmethod
    def from_json(cls, body: object) -> SearchRequestPayload:
        if not isinstance(body, dict):
            raise ValueError("request body must be a JSON object")
        bbox_value = body.get("bbox")
        if not isinstance(bbox_value, dict):
            raise ValueError("bbox must be an object with west, south, east and north")
        try:
            west = float(bbox_value["west"])
            south = float(bbox_value["south"])
            east = float(bbox_value["east"])
            north = float(bbox_value["north"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("bbox coordinates must be numeric") from exc
        bbox_geojson(west, south, east, north)
        sensor = parse_scene_sensor(str(body.get("sensor") or "auto"), Sensor.AUTO)
        try:
            hours = parse_scene_hours(str(body.get("hours", 72)))
        except ValueError as exc:
            raise ValueError(f"hours: {exc}") from exc
        try:
            max_results = int(body.get("max_results", 10))
        except (TypeError, ValueError) as exc:
            raise ValueError("max_results must be an integer") from exc
        if not 1 <= max_results <= 100:
            raise ValueError("max_results must be in 1..100")
        return cls(
            sensor=sensor,
            hours=hours,
            max_results=max_results,
            bbox=(west, south, east, north),
        )


@dataclass
class JobRecord:
    job_id: str
    kind: str
    status: str = "queued"
    progress: str = "Ожидает запуска"
    result: dict[str, object] | None = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class JobManager:
    def __init__(self, max_workers: int) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="marine-track-local",
        )
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, operation) -> JobRecord:
        job = JobRecord(job_id=uuid.uuid4().hex, kind=kind)
        with self._lock:
            self._jobs[job.job_id] = job
        self._executor.submit(self._run, job.job_id, operation)
        return job

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return JobRecord(**job.__dict__)

    def update_progress(self, job_id: str, progress: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.progress = progress
            job.updated_at = datetime.now(timezone.utc).isoformat()

    def _run(self, job_id: str, operation) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "running"
            job.updated_at = datetime.now(timezone.utc).isoformat()
        try:
            result = operation(lambda text: self.update_progress(job_id, text))
        except Exception as exc:  # noqa: BLE001 - job boundary returns a safe error to the UI
            with self._lock:
                job = self._jobs[job_id]
                job.status = "failed"
                job.error = _safe_error(exc)
                job.updated_at = datetime.now(timezone.utc).isoformat()
            return
        with self._lock:
            job = self._jobs[job_id]
            job.status = "completed"
            job.progress = "Готово"
            job.result = result
            job.updated_at = datetime.now(timezone.utc).isoformat()


def _safe_error(exc: BaseException) -> str:
    from marine_track.provenance import redact_value

    return str(redact_value(f"{type(exc).__name__}: {exc}"))[:1200]


class LocalFlowService:
    def __init__(self, config: LocalWebConfig) -> None:
        self.config = config
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self.jobs = JobManager(config.max_concurrent_jobs)

    def start_search(self, payload: SearchRequestPayload) -> JobRecord:
        return self.jobs.submit("search", lambda progress: self._search(payload, progress))

    def start_detection(self, token: str) -> JobRecord:
        if not token or len(token) > 64:
            raise ValueError("scene token is invalid")
        if self.find_scene(token) is None:
            raise ValueError("scene token not found; run search again")
        return self.jobs.submit("detection", lambda progress: self._detect(token, progress))

    def find_scene(self, token: str):
        return find_scene(
            self.config.output_dir,
            token,
            owner_user_id=LOCAL_OWNER_USER_ID,
            owner_chat_id=LOCAL_OWNER_CHAT_ID,
        )

    def preview_path(self, token: str) -> Path:
        found = self.find_scene(token)
        if found is None:
            raise ValueError("scene token not found; run search again")
        scene, _record = found
        preview = select_preview_asset(scene)
        if preview is None:
            raise ValueError("preview/quicklook is unavailable for this scene")
        _asset_key, href = preview
        return download_preview(href, self.config.output_dir / "previews", token)

    def _search(self, payload: SearchRequestPayload, progress) -> dict[str, object]:
        from marine_track.detection_scene_search import search_detection_capable_scenes

        west, south, east, north = payload.bbox
        aoi_geojson = bbox_geojson(west, south, east, north)
        aoi_path = write_temp_aoi(aoi_geojson)
        start, end = utc_window(payload.hours)
        output = run_dir(self.config.output_dir, "local_search")
        progress("1/3 · Проверяем bbox и доступные провайдеры")
        try:
            result = search_detection_capable_scenes(
                aoi_path,
                start,
                end,
                payload.sensor,
                output,
                min(payload.max_results, self.config.max_results),
            )
            progress("2/3 · Регистрируем найденные сцены")
            tokens = register_scenes(
                self.config.output_dir,
                result.provider,
                result.sensor,
                result.scenes,
                result.scenes_json,
                result.asset_manifest,
                owner_user_id=LOCAL_OWNER_USER_ID,
                owner_chat_id=LOCAL_OWNER_CHAT_ID,
                aoi_geojson=aoi_geojson,
                search_hours=payload.hours,
            )
        finally:
            aoi_path.unlink(missing_ok=True)
        progress("3/3 · Готовим карточки снимков")
        scenes = [
            _serialize_scene(token, scene)
            for token, scene in zip(tokens, result.scenes, strict=True)
        ]
        return {
            "provider": result.provider,
            "sensor": result.sensor.value,
            "cache_hit": result.cache_hit,
            "count": len(scenes),
            "hours": payload.hours,
            "bbox": {"west": west, "south": south, "east": east, "north": north},
            "scenes": scenes,
        }

    def _detect(self, token: str, progress) -> dict[str, object]:
        from marine_track.bounded_detection import run_detection_in_subprocess

        land_mask = self._prepare_land_mask(progress)
        result = run_detection_in_subprocess(
            token=token,
            output_dir=self.config.output_dir,
            owner_user_id=LOCAL_OWNER_USER_ID,
            owner_chat_id=LOCAL_OWNER_CHAT_ID,
            max_crops=self.config.detection_max_crops,
            threshold_sigma=self.config.threshold_sigma,
            min_area_px=self.config.min_area_px,
            min_contrast_sigma=self.config.min_contrast_sigma,
            land_mask_geojson=land_mask,
            shoreline_buffer_m=self.config.shoreline_buffer_m,
            timeout_s=float(self.config.detection_job_timeout_s),
            progress_callback=progress,
        )
        return _serialize_detection_result(result, self.config.output_dir)

    def _prepare_land_mask(self, progress) -> Path | None:
        path = self.config.land_mask_geojson
        if path is None:
            return None
        if path.is_file():
            return path
        if not self.config.auto_update_land_mask:
            raise ValueError(f"land mask not found: {path}")
        from marine_track.land_mask_update import update_land_mask

        progress("1/5 · Загружаем Natural Earth land mask")
        result = update_land_mask(output_path=path)
        return result.output_path


def _serialize_scene(token: str, scene) -> dict[str, object]:
    preview = select_preview_asset(scene)
    return {
        "token": token,
        "provider": scene.provider,
        "sensor": scene.sensor.value,
        "product_id": scene.product_id,
        "acquisition_time": scene.acquisition_time.isoformat(),
        "beam_mode": scene.beam_mode,
        "polarization": scene.polarization_label(),
        "asset_keys": sorted(scene.assets),
        "has_preview": preview is not None,
        "preview_url": f"/api/scenes/{token}/preview" if preview is not None else None,
    }


def _file_url(path: Path, output_dir: Path) -> str:
    relative = path.resolve().relative_to(output_dir.resolve())
    return "/files/" + "/".join(relative.parts)


def _serialize_detection_result(result, output_dir: Path) -> dict[str, object]:
    scene = result.materialized.scene
    detections = [item.model_dump(mode="json") for item in result.detections]
    return {
        "token": result.token,
        "provider": result.materialized.provider,
        "sensor": scene.sensor.value,
        "product_id": scene.product_id,
        "acquisition_time": scene.acquisition_time.isoformat(),
        "candidate_count": len(detections),
        "detections": detections,
        "overview_url": _file_url(result.overview_png, output_dir),
        "crop_urls": [_file_url(path, output_dir) for path in result.crop_pngs],
        "downloads": {
            "GeoJSON": _file_url(result.geojson, output_dir),
            "CSV": _file_url(result.csv, output_dir),
            "Parquet": _file_url(result.parquet, output_dir),
            "Report JSON": _file_url(result.report_json, output_dir),
        },
        "raster_cache_hit": result.materialized.cache_hit,
        "aoi_cropped": result.materialized.cropped,
        "wake_research_enabled": result.wake_research_enabled,
    }


def resolve_output_file(output_dir: Path, relative_path: str) -> Path:
    base = output_dir.resolve()
    candidate = (base / unquote(relative_path)).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError("requested file is outside the output directory") from exc
    if not candidate.is_file():
        raise FileNotFoundError(candidate.name)
    return candidate


class LocalWebApplication:
    def __init__(self, config: LocalWebConfig) -> None:
        self.config = config
        self.service = LocalFlowService(config)

    def handle_api_get(self, path: str) -> tuple[int, dict[str, object]]:
        if path == "/api/config":
            return HTTPStatus.OK, {
                "host": self.config.host,
                "port": self.config.port,
                "max_results": self.config.max_results,
                "output_dir": str(self.config.output_dir),
                "default": {
                    "sensor": "sentinel1",
                    "hours": 168,
                    "bbox": {"west": 33.95, "south": 43.23, "east": 34.11, "north": 43.37},
                },
                "detection_profile": {
                    "asset": "VV",
                    "threshold_sigma": self.config.threshold_sigma,
                    "min_contrast_sigma": self.config.min_contrast_sigma,
                    "min_area_px": self.config.min_area_px,
                    "land_mask": str(self.config.land_mask_geojson)
                    if self.config.land_mask_geojson
                    else None,
                },
            }
        if path.startswith("/api/jobs/"):
            job_id = path.removeprefix("/api/jobs/")
            job = self.service.jobs.get(job_id)
            if job is None:
                return HTTPStatus.NOT_FOUND, {"error": "job not found"}
            return HTTPStatus.OK, job.as_dict()
        return HTTPStatus.NOT_FOUND, {"error": "API endpoint not found"}

    def handle_api_post(self, path: str, body: object) -> tuple[int, dict[str, object]]:
        if path == "/api/search":
            payload = SearchRequestPayload.from_json(body)
            job = self.service.start_search(payload)
            return HTTPStatus.ACCEPTED, job.as_dict()
        if path == "/api/detect":
            if not isinstance(body, dict):
                raise ValueError("request body must be a JSON object")
            token = str(body.get("token") or "").strip()
            job = self.service.start_detection(token)
            return HTTPStatus.ACCEPTED, job.as_dict()
        return HTTPStatus.NOT_FOUND, {"error": "API endpoint not found"}


def make_handler(application: LocalWebApplication):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MarineTrackLocal/0.1"

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            try:
                if path.startswith("/api/scenes/") and path.endswith("/preview"):
                    token = path.removeprefix("/api/scenes/").removesuffix("/preview").strip("/")
                    self._send_file(application.service.preview_path(token), cache=False)
                    return
                if path.startswith("/api/"):
                    status, payload = application.handle_api_get(path)
                    self._send_json(status, payload)
                    return
                if path.startswith("/files/"):
                    relative_path = path.removeprefix("/files/")
                    self._send_file(resolve_output_file(application.config.output_dir, relative_path))
                    return
                self._send_static(path)
            except FileNotFoundError:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "file not found"})
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001 - HTTP boundary
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": _safe_error(exc)})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            try:
                body = self._read_json()
                status, payload = application.handle_api_post(path, body)
                self._send_json(status, payload)
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001 - HTTP boundary
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": _safe_error(exc)})

        def log_message(self, format_string: str, *args: object) -> None:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] {self.address_string()} {format_string % args}")

        def _read_json(self) -> object:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("invalid Content-Length") from exc
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("JSON request body is empty or too large")
            try:
                return json.loads(self.rfile.read(length))
            except json.JSONDecodeError as exc:
                raise ValueError("request body is not valid JSON") from exc

        def _send_json(self, status: int, payload: dict[str, object]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path, *, cache: bool = True) -> None:
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "private, max-age=300" if cache else "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, path: str) -> None:
            names = {"/": "index.html", "/app.css": "app.css", "/app.js": "app.js"}
            name = names.get(path)
            if name is None:
                raise FileNotFoundError(path)
            self._send_file(WEB_ROOT / name)

    return Handler


def serve(config: LocalWebConfig, *, open_browser: bool = False) -> None:
    application = LocalWebApplication(config)
    server = ThreadingHTTPServer((config.host, config.port), make_handler(application))
    url = f"http://{config.host}:{config.port}"
    print(f"Marine Track local console: {url}")
    print(f"Outputs: {config.output_dir.resolve()}")
    print("Telegram token is not used. Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Marine Track local console")
    finally:
        server.server_close()


def main() -> None:
    load_local_env()
    defaults = load_local_web_config()
    parser = argparse.ArgumentParser(description="Run Marine Track locally without Telegram")
    parser.add_argument("--host", default=defaults.host)
    parser.add_argument("--port", type=int, default=defaults.port)
    parser.add_argument("--open", action="store_true", help="open the console in the default browser")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be in 1..65535")
    serve(
        LocalWebConfig(
            **{
                **defaults.__dict__,
                "host": args.host,
                "port": args.port,
            }
        ),
        open_browser=args.open,
    )


if __name__ == "__main__":
    main()
