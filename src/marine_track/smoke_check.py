from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from marine_track.telegram_config import load_telegram_config
from marine_track.telegram_ui import main_menu_markup

VALID_PROVIDER_PROFILES = {"all", "scene", "aux", "core"}


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def project_path(raw: Path, base_dir: Path) -> Path:
    return raw if raw.is_absolute() else base_dir / raw


def writable_dir(path: Path) -> str | None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".smoke_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception as exc:
        return str(exc)
    return None


def run_smoke_check(base_dir: Path, env_file: Path) -> list[str]:
    load_dotenv(env_file)
    errors: list[str] = []
    try:
        config = load_telegram_config()
    except Exception as exc:
        return [str(exc)]

    aoi = project_path(config.default_aoi, base_dir)
    if not aoi.is_file():
        errors.append(f"default AOI not found: {aoi}")

    output_dir = project_path(config.output_dir, base_dir)
    if error := writable_dir(output_dir):
        errors.append(f"output dir is not writable: {output_dir}: {error}")

    cache_dir = project_path(Path(os.getenv("MARINE_TRACK_CACHE_DIR", "runs/cache")), base_dir)
    if error := writable_dir(cache_dir):
        errors.append(f"cache dir is not writable: {cache_dir}: {error}")

    try:
        main_menu_markup(has_last_bbox=False)
    except Exception as exc:
        errors.append(f"telegram UI/menu failed: {exc}")

    profile = os.getenv("MARINE_TRACK_PROVIDER_PROFILE", "all").strip().lower()
    if profile not in VALID_PROVIDER_PROFILES:
        errors.append(f"invalid MARINE_TRACK_PROVIDER_PROFILE: {profile!r}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Marine Track local smoke check")
    parser.add_argument("--base-dir", default=".", help="Project/install directory for relative paths")
    parser.add_argument("--env-file", default=".env", help="Env file to read")
    args = parser.parse_args(argv)

    base_dir = Path(args.base_dir).resolve()
    env_file = Path(args.env_file)
    if not env_file.is_absolute():
        env_file = base_dir / env_file
    errors = run_smoke_check(base_dir, env_file)
    if errors:
        print("Smoke check failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("Smoke check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
