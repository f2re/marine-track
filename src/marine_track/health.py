from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml


@dataclass(frozen=True)
class HealthCheck:
    name: str
    status: str
    critical: bool
    detail: str
    data: dict[str, Any] | None = None


@dataclass(frozen=True)
class HealthReport:
    status: str
    generated_at: str
    hostname: str
    package_version: str
    code_version: str
    release_id: str
    checks: list[HealthCheck]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "generated_at": self.generated_at,
            "hostname": self.hostname,
            "package_version": self.package_version,
            "code_version": self.code_version,
            "release_id": self.release_id,
            "checks": [asdict(check) for check in self.checks],
        }


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def collect_health(
    *,
    base_dir: Path | None = None,
    env_file: Path | None = None,
    check_telegram: bool = False,
) -> HealthReport:
    base_dir = (base_dir or Path.cwd()).resolve()
    if env_file is not None:
        load_env_file(env_file)

    checks: list[HealthCheck] = []
    processing_path = _resolve_path(
        os.getenv("MARINE_TRACK_PROCESSING_CONFIG", "config/processing.yaml"),
        base_dir,
    )
    checks.append(_processing_config_check(processing_path))
    checks.append(_sensor_capability_check())

    default_aoi = _resolve_path(
        os.getenv("MARINE_TRACK_DEFAULT_AOI", "data/aoi/example_black_sea.geojson"),
        base_dir,
    )
    checks.append(
        HealthCheck(
            name="default_aoi",
            status="ok" if default_aoi.is_file() else "failed",
            critical=True,
            detail="available" if default_aoi.is_file() else f"missing: {default_aoi.name}",
        )
    )

    output_dir = _resolve_path(
        os.getenv("MARINE_TRACK_OUTPUT_DIR", "runs/telegram"),
        base_dir,
    )
    cache_dir = _resolve_path(
        os.getenv("MARINE_TRACK_CACHE_DIR", "runs/cache"),
        base_dir,
    )
    checks.append(_writable_check("output_dir", output_dir))
    checks.append(_writable_check("cache_dir", cache_dir))
    checks.append(_disk_check(output_dir))
    checks.append(_registry_check(output_dir / "scene_registry.json"))
    checks.append(_calibration_check(output_dir))
    checks.append(_access_policy_check())

    if check_telegram:
        checks.append(_telegram_check())

    critical_failed = any(check.critical and check.status == "failed" for check in checks)
    degraded = any(check.status in {"warning", "failed"} for check in checks)
    status = "failed" if critical_failed else "degraded" if degraded else "ok"
    return HealthReport(
        status=status,
        generated_at=datetime.now(timezone.utc).isoformat(),
        hostname=socket.gethostname(),
        package_version=_package_version(),
        code_version=os.getenv("MARINE_TRACK_CODE_VERSION", "unknown") or "unknown",
        release_id=os.getenv("MARINE_TRACK_RELEASE_ID", "unknown") or "unknown",
        checks=checks,
    )


def _processing_config_check(path: Path) -> HealthCheck:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("root is not an object")
        detection = payload.get("ship_detection")
        if not isinstance(detection, dict):
            raise ValueError("ship_detection is missing")
        for section in ("sar", "optical"):
            config = detection.get(section)
            if not isinstance(config, dict):
                raise ValueError(f"ship_detection.{section} is missing")
            for name in (
                "threshold_sigma",
                "min_area_px",
                "max_area_px",
                "local_window_px",
                "guard_window_px",
            ):
                if name not in config:
                    raise ValueError(f"ship_detection.{section}.{name} is missing")
        return HealthCheck(
            name="processing_config",
            status="ok",
            critical=True,
            detail="validated",
            data={"path": path.name},
        )
    except Exception as exc:
        return HealthCheck(
            name="processing_config",
            status="failed",
            critical=True,
            detail=f"{type(exc).__name__}: {exc}",
        )


def _sensor_capability_check() -> HealthCheck:
    try:
        from marine_track.sensor_preprocessing import (
            sentinel2_single_band_enabled,
            wake_research_enabled,
        )

        s2_experimental = sentinel2_single_band_enabled()
        wake_experimental = wake_research_enabled()
    except Exception as exc:
        return HealthCheck(
            name="sensor_capabilities",
            status="failed",
            critical=True,
            detail=f"invalid preprocessing feature flags: {type(exc).__name__}",
        )
    experimental = s2_experimental or wake_experimental
    return HealthCheck(
        name="sensor_capabilities",
        status="warning" if experimental else "ok",
        critical=False,
        detail=(
            "Sentinel-1 operational baseline; explicit research overrides enabled"
            if experimental
            else "Sentinel-1 operational baseline; incomplete Sentinel-2/wake research paths disabled"
        ),
        data={
            "sentinel1": "operational_relative_or_provider_declared_backscatter",
            "sentinel2_single_band_experimental": s2_experimental,
            "wake_research": wake_experimental,
        },
    )


def _writable_check(name: str, path: Path) -> HealthCheck:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".health-", dir=path, delete=True) as file_obj:
            file_obj.write(b"ok")
            file_obj.flush()
        return HealthCheck(name=name, status="ok", critical=True, detail="writable")
    except Exception as exc:
        return HealthCheck(
            name=name,
            status="failed",
            critical=True,
            detail=f"not writable: {type(exc).__name__}",
        )


def _disk_check(path: Path) -> HealthCheck:
    try:
        free = shutil.disk_usage(path).free
        minimum_mb = int(os.getenv("MARINE_TRACK_HEALTH_MIN_FREE_MB", "512"))
        free_mb = free // (1024 * 1024)
        status = "ok" if free_mb >= minimum_mb else "failed"
        return HealthCheck(
            name="disk_free",
            status=status,
            critical=True,
            detail=f"{free_mb} MiB free; minimum {minimum_mb} MiB",
            data={"free_mb": free_mb, "minimum_mb": minimum_mb},
        )
    except Exception as exc:
        return HealthCheck(
            name="disk_free",
            status="failed",
            critical=True,
            detail=f"{type(exc).__name__}: {exc}",
        )


def _registry_check(path: Path) -> HealthCheck:
    if not path.is_file():
        return HealthCheck(
            name="scene_registry",
            status="warning",
            critical=False,
            detail="not created yet",
            data={"records": 0},
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("registry root is not an object")
        unscoped = [
            token
            for token, record in payload.items()
            if not isinstance(record, dict)
            or not isinstance(record.get("owner_user_id"), int)
            or not isinstance(record.get("owner_chat_id"), int)
        ]
        if unscoped:
            return HealthCheck(
                name="scene_registry",
                status="warning",
                critical=False,
                detail="legacy/unscoped records are ignored",
                data={"records": len(payload), "unscoped": len(unscoped)},
            )
        return HealthCheck(
            name="scene_registry",
            status="ok",
            critical=False,
            detail="valid and scoped",
            data={"records": len(payload), "unscoped": 0},
        )
    except Exception as exc:
        return HealthCheck(
            name="scene_registry",
            status="failed",
            critical=True,
            detail=f"invalid JSON/state: {type(exc).__name__}",
        )


def _calibration_check(output_dir: Path) -> HealthCheck:
    candidate = output_dir / "calibration" / "profile.json"
    active_profiles = list(output_dir.glob("**/active_profile.json"))
    files = ([candidate] if candidate.is_file() else []) + active_profiles
    if not files:
        return HealthCheck(
            name="calibration_profiles",
            status="warning",
            critical=False,
            detail="no active profile yet; baseline ranking remains in use",
            data={"profiles": 0},
        )
    invalid = 0
    active = 0
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                invalid += 1
                continue
            if payload.get("active") or path.name == "active_profile.json":
                active += 1
        except Exception:
            invalid += 1
    if invalid:
        return HealthCheck(
            name="calibration_profiles",
            status="failed",
            critical=True,
            detail="one or more profile files are invalid",
            data={"profiles": len(files), "invalid": invalid, "active": active},
        )
    return HealthCheck(
        name="calibration_profiles",
        status="ok" if active else "warning",
        critical=False,
        detail="active profile available" if active else "profiles exist but none is active",
        data={"profiles": len(files), "invalid": 0, "active": active},
    )


def _access_policy_check() -> HealthCheck:
    admin_ids = _parse_ids(os.getenv("TELEGRAM_ADMIN_IDS", ""))
    public = _env_bool(os.getenv("MARINE_TRACK_ALLOW_PUBLIC_BOT", "0"))
    if public is None:
        return HealthCheck(
            name="telegram_access_policy",
            status="failed",
            critical=True,
            detail="MARINE_TRACK_ALLOW_PUBLIC_BOT is not boolean",
        )
    if not admin_ids and not public:
        return HealthCheck(
            name="telegram_access_policy",
            status="failed",
            critical=True,
            detail="fail-closed: configure TELEGRAM_ADMIN_IDS or explicit public mode",
        )
    return HealthCheck(
        name="telegram_access_policy",
        status="ok",
        critical=True,
        detail="public explicit" if public else "administrator allowlist",
        data={"administrator_count": len(admin_ids), "public": public},
    )


def _telegram_check() -> HealthCheck:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return HealthCheck(
            name="telegram_get_me",
            status="failed",
            critical=True,
            detail="TELEGRAM_BOT_TOKEN is empty",
        )
    request = Request(
        f"https://api.telegram.org/bot{token}/getMe",
        headers={"User-Agent": "marine-track-health/0.1"},
    )
    try:
        with urlopen(request, timeout=15) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        result = payload.get("result") if isinstance(payload, dict) else None
        if not payload.get("ok") or not isinstance(result, dict):
            raise ValueError("Telegram returned ok=false")
        return HealthCheck(
            name="telegram_get_me",
            status="ok",
            critical=True,
            detail="Telegram API reachable and token accepted",
            data={"bot_id": result.get("id"), "username": result.get("username")},
        )
    except HTTPError as exc:
        detail = f"Telegram HTTP {exc.code}"
    except (URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        detail = f"Telegram check failed: {type(exc).__name__}"
    return HealthCheck(
        name="telegram_get_me",
        status="failed",
        critical=True,
        detail=detail,
    )


def _parse_ids(value: str) -> set[int]:
    output: set[int] = set()
    for part in value.replace(";", ",").replace(" ", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            output.add(int(part))
        except ValueError:
            return set()
    return output


def _env_bool(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    return None


def _resolve_path(raw: str, base_dir: Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else base_dir / path


def _package_version() -> str:
    try:
        return version("marine-track")
    except PackageNotFoundError:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Marine Track runtime health report")
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--env-file")
    parser.add_argument("--telegram", action="store_true", help="Call Telegram getMe")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    report = collect_health(
        base_dir=Path(args.base_dir),
        env_file=Path(args.env_file) if args.env_file else None,
        check_telegram=args.telegram,
    )
    if args.as_json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"Marine Track health: {report.status}")
        for check in report.checks:
            marker = "OK" if check.status == "ok" else "WARN" if check.status == "warning" else "FAIL"
            print(f"[{marker}] {check.name}: {check.detail}")
    return 1 if report.status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
