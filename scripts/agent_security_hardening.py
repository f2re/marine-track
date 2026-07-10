from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one exact match, got {count}: {old[:120]!r}")
    write(path, content.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str) -> None:
    content = read(path)
    updated, count = re.subn(pattern, replacement, content, count=1, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{path}: expected one regex match, got {count}: {pattern!r}")
    write(path, updated)


replace_once(
    "src/marine_track/telegram_config.py",
    "    shoreline_buffer_m: int\n    calibration_min_labels: int = 20\n",
    "    shoreline_buffer_m: int\n    allow_public_access: bool = False\n    calibration_min_labels: int = 20\n",
)
replace_once(
    "src/marine_track/telegram_config.py",
    """        try:
            ids.add(int(value))
        except ValueError:
            continue
""",
    """        try:
            ids.add(int(value))
        except ValueError as exc:
            raise RuntimeError(
                f"TELEGRAM_ADMIN_IDS contains a non-integer value: {value!r}"
            ) from exc
""",
)
replace_once(
    "src/marine_track/telegram_config.py",
    """def env_optional_path(name: str) -> Path | None:
    raw = os.getenv(name, "").strip()
    return Path(raw) if raw else None
""",
    """def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise RuntimeError(f"{name} must be boolean, got {raw!r}")


def env_optional_path(name: str) -> Path | None:
    raw = os.getenv(name, "").strip()
    return Path(raw) if raw else None
""",
)
replace_once(
    "src/marine_track/telegram_config.py",
    "    sensor_raw = os.getenv(\"MARINE_TRACK_DEFAULT_SENSOR\", Sensor.AUTO.value).strip().lower()\n",
    """    admin_ids = parse_admin_ids(os.getenv("TELEGRAM_ADMIN_IDS"))
    allow_public_access = env_bool("MARINE_TRACK_ALLOW_PUBLIC_BOT", False)

    sensor_raw = os.getenv("MARINE_TRACK_DEFAULT_SENSOR", Sensor.AUTO.value).strip().lower()
""",
)
replace_once(
    "src/marine_track/telegram_config.py",
    "        admin_ids=parse_admin_ids(os.getenv(\"TELEGRAM_ADMIN_IDS\")),\n",
    "        admin_ids=admin_ids,\n",
)
replace_once(
    "src/marine_track/telegram_config.py",
    """        shoreline_buffer_m=env_int("MARINE_TRACK_SHORELINE_BUFFER_M", 500, 0, 100_000),
        calibration_min_labels=calibration_min_labels,
""",
    """        shoreline_buffer_m=env_int("MARINE_TRACK_SHORELINE_BUFFER_M", 500, 0, 100_000),
        allow_public_access=allow_public_access,
        calibration_min_labels=calibration_min_labels,
""",
)
replace_once(
    "src/marine_track/telegram_bot.py",
    "    return not config.admin_ids or effective_user_id(update) in config.admin_ids\n",
    "    return config.allow_public_access or effective_user_id(update) in config.admin_ids\n",
)

regex_once(
    "runtime_check.py",
    r"""def check_telegram_env\(\) -> list\[str\]:\n.*?\n\n\ndef check_numeric_env""",
    '''def env_flag(name: str) -> bool | None:
    raw = os.getenv(name)
    if raw is None:
        return False
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    return None


def check_telegram_env() -> list[str]:
    errors: list[str] = []
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        errors.append("TELEGRAM_BOT_TOKEN is empty; set it in /opt/marine_track/.env before deploy")

    raw_admin_ids = os.getenv("TELEGRAM_ADMIN_IDS", "")
    parsed_ids: set[int] = set()
    for part in raw_admin_ids.replace(";", ",").replace(" ", ",").split(","):
        value = part.strip()
        if not value:
            continue
        try:
            parsed_ids.add(int(value))
        except ValueError:
            errors.append(f"TELEGRAM_ADMIN_IDS contains a non-integer value: {value!r}")

    public_access = env_flag("MARINE_TRACK_ALLOW_PUBLIC_BOT")
    if public_access is None:
        errors.append("MARINE_TRACK_ALLOW_PUBLIC_BOT must be boolean")
    elif not parsed_ids and not public_access:
        errors.append(
            "Telegram access is fail-closed: set TELEGRAM_ADMIN_IDS or explicitly "
            "set MARINE_TRACK_ALLOW_PUBLIC_BOT=1"
        )
    return errors


def check_numeric_env''',
)

regex_once(
    "src/marine_track/cache_policy.py",
    r"""def search_cache_key\(\n.*?\n    return short_hash\(json.dumps\(payload, sort_keys=True\).encode\("utf-8"\), length=20\)\n""",
    '''def normalized_utc_iso(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def search_cache_key(
    aoi_path: Path,
    start: datetime,
    end: datetime,
    sensor: Sensor,
    max_results: int,
    *,
    purpose: str,
    capability: str,
) -> str:
    purpose = purpose.strip()
    capability = capability.strip()
    if not purpose or not capability:
        raise ValueError("purpose and capability must be non-empty")
    if end <= start:
        raise ValueError("search end must be after start")
    payload = {
        "schema_version": 2,
        "aoi_hash": aoi_hash_from_path(aoi_path),
        "sensor": sensor.value,
        "start_utc": normalized_utc_iso(start),
        "end_utc": normalized_utc_iso(end),
        "max_results": max_results,
        "purpose": purpose,
        "capability": capability,
    }
    return short_hash(json.dumps(payload, sort_keys=True).encode("utf-8"), length=20)
''',
)
replace_once(
    "src/marine_track/pipeline.py",
    "    cache_key = search_cache_key(aoi, start, end, sensor, max_results)\n",
    '''    cache_key = search_cache_key(
        aoi,
        start,
        end,
        sensor,
        max_results,
        purpose="catalog",
        capability="any_scene",
    )
''',
)
replace_once(
    "src/marine_track/detection_scene_search.py",
    "    cache_key = search_cache_key(aoi, start, end, sensor, max_results)\n",
    '''    cache_key = search_cache_key(
        aoi,
        start,
        end,
        sensor,
        max_results,
        purpose="detection",
        capability="processable_geotiff_cog",
    )
''',
)

replace_once(
    "src/marine_track/telegram_scene_browser.py",
    "import math\n",
    "import math\nimport threading\n",
)
replace_once(
    "src/marine_track/telegram_scene_browser.py",
    "REGISTRY_FILE = \"scene_registry.json\"\n",
    "REGISTRY_FILE = \"scene_registry.json\"\n_REGISTRY_LOCK = threading.Lock()\n",
)
replace_once(
    "src/marine_track/telegram_scene_browser.py",
    """class SceneRegistryRecord:
    token: str
    provider: str
""",
    """class SceneRegistryRecord:
    token: str
    owner_user_id: int
    owner_chat_id: int
    provider: str
""",
)
replace_once(
    "src/marine_track/telegram_scene_browser.py",
    """def effective_user_id(update: Update) -> int:
    return int(getattr(update.effective_user, "id", 0) or 0)


def scene_token(scene: Scene) -> str:
    raw = f"{scene.provider}|{scene.sensor.value}|{scene.product_id}|{scene.acquisition_time.isoformat()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
""",
    """def effective_user_id(update: Update) -> int:
    return int(getattr(update.effective_user, "id", 0) or 0)


def effective_chat_id(update: Update) -> int:
    return int(getattr(update.effective_chat, "id", 0) or 0)


def scene_token(scene: Scene, owner_user_id: int, owner_chat_id: int) -> str:
    raw = (
        f"{owner_user_id}|{owner_chat_id}|{scene.provider}|{scene.sensor.value}|"
        f"{scene.product_id}|{scene.acquisition_time.isoformat()}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
""",
)
replace_once(
    "src/marine_track/telegram_scene_browser.py",
    """def save_registry(output_dir: Path, registry: dict[str, dict[str, object]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    registry_path(output_dir).write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
""",
    """def save_registry(output_dir: Path, registry: dict[str, dict[str, object]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = registry_path(output_dir)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
""",
)
regex_once(
    "src/marine_track/telegram_scene_browser.py",
    r"""def register_scenes\(\n.*?\n    return tokens\n\n\ndef find_scene\(output_dir: Path, token: str\) -> tuple\[Scene, dict\[str, object\]\] \| None:\n.*?\n    return Scene.model_validate\(scene_payload\), record\n""",
    '''def register_scenes(
    output_dir: Path,
    provider: str,
    sensor: Sensor,
    scenes: list[Scene],
    scenes_json: Path,
    asset_manifest: Path | None,
    *,
    owner_user_id: int,
    owner_chat_id: int,
    aoi_geojson: dict[str, object] | None = None,
    search_hours: int | None = None,
) -> list[str]:
    if owner_user_id <= 0 or owner_chat_id == 0:
        raise ValueError("Telegram scene registry requires non-zero owner user/chat ids")
    tokens: list[str] = []
    created_at = datetime.now(timezone.utc).isoformat()
    with _REGISTRY_LOCK:
        registry = load_registry(output_dir)
        for scene in scenes:
            token = scene_token(scene, owner_user_id, owner_chat_id)
            record = SceneRegistryRecord(
                token=token,
                owner_user_id=owner_user_id,
                owner_chat_id=owner_chat_id,
                provider=provider,
                sensor=sensor.value,
                scene=scene.model_dump(mode="json"),
                scenes_json=str(scenes_json),
                asset_manifest=str(asset_manifest) if asset_manifest else None,
                created_at=created_at,
                aoi_geojson=aoi_geojson,
                search_hours=search_hours,
            )
            registry[token] = record.__dict__
            tokens.append(token)
        save_registry(output_dir, registry)
    return tokens


def find_scene(
    output_dir: Path,
    token: str,
    *,
    owner_user_id: int,
    owner_chat_id: int,
) -> tuple[Scene, dict[str, object]] | None:
    record = load_registry(output_dir).get(token)
    if not isinstance(record, dict):
        return None
    if record.get("owner_user_id") != owner_user_id or record.get("owner_chat_id") != owner_chat_id:
        return None
    scene_payload = record.get("scene")
    if not isinstance(scene_payload, dict):
        return None
    return Scene.model_validate(scene_payload), record
''',
)
replace_once(
    "src/marine_track/telegram_scene_browser.py",
    """def restore_scene_page(
    output_dir: Path,
    token: str,
    page: int,
    page_size: int = SCENE_PAGE_SIZE,
) -> ScenePage:
""",
    """def restore_scene_page(
    output_dir: Path,
    token: str,
    page: int,
    *,
    owner_user_id: int,
    owner_chat_id: int,
    page_size: int = SCENE_PAGE_SIZE,
) -> ScenePage:
""",
)
replace_once(
    "src/marine_track/telegram_scene_browser.py",
    """    if not isinstance(record, dict):
        raise FileNotFoundError("token not found in scene registry")
    scenes_json = record.get("scenes_json")
""",
    """    if not isinstance(record, dict):
        raise FileNotFoundError("token not found in scene registry")
    if record.get("owner_user_id") != owner_user_id or record.get("owner_chat_id") != owner_chat_id:
        raise FileNotFoundError("token not found in scene registry")
    scenes_json = record.get("scenes_json")
""",
)
replace_once(
    "src/marine_track/telegram_scene_browser.py",
    "    tokens = [scene_token(scene) for scene in scenes]\n",
    "    tokens = [scene_token(scene, owner_user_id, owner_chat_id) for scene in scenes]\n",
)
for _ in range(2):
    replace_once(
        "src/marine_track/telegram_scene_browser.py",
        """        result.asset_manifest,
        aoi_geojson=aoi_geojson,
        search_hours=hours,
""",
        """        result.asset_manifest,
        owner_user_id=effective_user_id(update),
        owner_chat_id=effective_chat_id(update),
        aoi_geojson=aoi_geojson,
        search_hours=hours,
""",
    )
replace_once(
    "src/marine_track/telegram_scene_browser.py",
    "    found = find_scene(config.output_dir, token)\n",
    """    found = find_scene(
        config.output_dir,
        token,
        owner_user_id=effective_user_id(update),
        owner_chat_id=effective_chat_id(update),
    )
""",
)
replace_once(
    "src/marine_track/telegram_scene_browser.py",
    "        scene_page = restore_scene_page(config.output_dir, token, page)\n",
    """        scene_page = restore_scene_page(
            config.output_dir,
            token,
            page,
            owner_user_id=effective_user_id(update),
            owner_chat_id=effective_chat_id(update),
        )
""",
)

replace_once(
    "src/marine_track/telegram_detection.py",
    """def effective_user_id(update: Update) -> int:
    return int(getattr(update.effective_user, "id", 0) or 0)


def menu_for_user""",
    """def effective_user_id(update: Update) -> int:
    return int(getattr(update.effective_user, "id", 0) or 0)


def effective_chat_id(update: Update) -> int:
    return int(getattr(update.effective_chat, "id", 0) or 0)


def menu_for_user""",
)
for _ in range(2):
    replace_once(
        "src/marine_track/telegram_detection.py",
        """            result.asset_manifest,
            aoi_geojson=aoi_geojson,
        )
""",
        """            result.asset_manifest,
            owner_user_id=effective_user_id(update),
            owner_chat_id=effective_chat_id(update),
            aoi_geojson=aoi_geojson,
        )
""",
    )
replace_once(
    "src/marine_track/telegram_detection.py",
    """            token=token,
            output_dir=config.output_dir,
            max_crops=config.detection_max_crops,
""",
    """            token=token,
            output_dir=config.output_dir,
            owner_user_id=effective_user_id(update),
            owner_chat_id=effective_chat_id(update),
            max_crops=config.detection_max_crops,
""",
)
replace_once(
    "src/marine_track/scene_materializer.py",
    """def materialize_scene_from_token(
    token: str,
    output_dir: Path,
    cache_dir: Path | None = None,
) -> MaterializedScene:
    found = find_scene(output_dir, token)
""",
    """def materialize_scene_from_token(
    token: str,
    output_dir: Path,
    *,
    owner_user_id: int,
    owner_chat_id: int,
    cache_dir: Path | None = None,
) -> MaterializedScene:
    found = find_scene(
        output_dir,
        token,
        owner_user_id=owner_user_id,
        owner_chat_id=owner_chat_id,
    )
""",
)
replace_once(
    "src/marine_track/detection_pipeline.py",
    """def run_detection_for_token(
    token: str,
    output_dir: Path,
    max_crops: int = 10,
""",
    """def run_detection_for_token(
    token: str,
    output_dir: Path,
    *,
    owner_user_id: int,
    owner_chat_id: int,
    max_crops: int = 10,
""",
)
replace_once(
    "src/marine_track/detection_pipeline.py",
    "    materialized = materialize_scene_from_token(token, output_dir)\n",
    """    materialized = materialize_scene_from_token(
        token,
        output_dir,
        owner_user_id=owner_user_id,
        owner_chat_id=owner_chat_id,
    )
""",
)

replace_once(
    ".env.example",
    """# SECURITY: current runtime treats an empty allowlist as public access.
# Set at least one numeric Telegram user id until fail-closed auth is implemented.
TELEGRAM_ADMIN_IDS=
""",
    """# Fail-closed by default: set at least one numeric Telegram user id.
TELEGRAM_ADMIN_IDS=
# Explicit opt-in for a public bot. Leave 0 for production/admin-only operation.
MARINE_TRACK_ALLOW_PUBLIC_BOT=0
""",
)

write(
    "docs/SECURITY_CACHE_HARDENING.md",
    """# Telegram access, scene token scope and search cache contract

## Access policy

Operational Telegram commands are fail-closed. A user is authorized only when their numeric ID
is present in `TELEGRAM_ADMIN_IDS` or `MARINE_TRACK_ALLOW_PUBLIC_BOT=1` is explicitly set.

`/start`, `/help`, `/status` and `/whoami` remain available for enrollment and diagnostics.
Detection, scene browsing, saved AOIs, output settings and calibration remain protected.

`runtime_check.py` rejects deployment when both the allowlist is empty and public mode is not
explicitly enabled. Invalid IDs and invalid boolean values are configuration errors.

## Scene registry isolation

Every registry record stores `owner_user_id` and `owner_chat_id`. The token hash includes both
values. Preview, pagination and detection resolve a token only for the matching Telegram user and
chat. Old unscoped records are intentionally invalid; repeat `/dates`, `/bboxdates` or
`/detectbbox` after deployment. Registry writes are atomic and guarded by an in-process lock.

## Search cache v2

The cache key includes AOI hash, sensor, absolute UTC start/end, result limit, purpose and required
capability. Catalog search uses `catalog/any_scene`; detection search uses
`detection/processable_geotiff_cog`. Equal-duration windows at different times and catalog versus
detection flows cannot reuse each other's entries.
""",
)

write(
    "tests/test_security_cache_hardening.py",
    """from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from marine_track.cache_policy import search_cache_key
from marine_track.models import Scene, Sensor
from marine_track.telegram_config import load_telegram_config
from marine_track.telegram_scene_browser import (
    find_scene,
    register_scenes,
    restore_scene_page,
    scene_token,
)


def test_telegram_access_is_fail_closed(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.delenv("TELEGRAM_ADMIN_IDS", raising=False)
    monkeypatch.delenv("MARINE_TRACK_ALLOW_PUBLIC_BOT", raising=False)
    config = load_telegram_config()

    import marine_track.telegram_bot as telegram_bot

    monkeypatch.setattr(telegram_bot, "CONFIG", config)
    update = SimpleNamespace(effective_user=SimpleNamespace(id=12345))
    assert telegram_bot.is_authorized(update) is False


def test_public_access_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.delenv("TELEGRAM_ADMIN_IDS", raising=False)
    monkeypatch.setenv("MARINE_TRACK_ALLOW_PUBLIC_BOT", "1")
    config = load_telegram_config()

    import marine_track.telegram_bot as telegram_bot

    monkeypatch.setattr(telegram_bot, "CONFIG", config)
    update = SimpleNamespace(effective_user=SimpleNamespace(id=12345))
    assert telegram_bot.is_authorized(update) is True


def test_invalid_admin_id_is_rejected(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123,not-a-number")
    with pytest.raises(RuntimeError, match="non-integer"):
        load_telegram_config()


def test_search_cache_key_uses_absolute_window_and_capability(tmp_path):
    aoi = tmp_path / "aoi.geojson"
    aoi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    start = datetime(2026, 7, 10, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=12)
    base = search_cache_key(
        aoi, start, end, Sensor.SENTINEL1, 10, purpose="catalog", capability="any_scene"
    )
    shifted = search_cache_key(
        aoi,
        start + timedelta(hours=1),
        end + timedelta(hours=1),
        Sensor.SENTINEL1,
        10,
        purpose="catalog",
        capability="any_scene",
    )
    detection = search_cache_key(
        aoi,
        start,
        end,
        Sensor.SENTINEL1,
        10,
        purpose="detection",
        capability="processable_geotiff_cog",
    )
    assert base != shifted
    assert base != detection


def test_scene_tokens_and_registry_are_user_chat_scoped(tmp_path):
    scene = Scene(
        provider="test",
        sensor=Sensor.SENTINEL1,
        product_id="scene-1",
        acquisition_time=datetime(2026, 7, 10, tzinfo=timezone.utc),
        assets={"vv": "https://example.invalid/scene.tif"},
    )
    scenes_json = tmp_path / "scenes.json"
    scenes_json.write_text(
        json.dumps([scene.model_dump(mode="json")], default=str), encoding="utf-8"
    )
    tokens = register_scenes(
        tmp_path,
        "test",
        Sensor.SENTINEL1,
        [scene],
        scenes_json,
        None,
        owner_user_id=100,
        owner_chat_id=200,
    )
    token = tokens[0]
    assert token == scene_token(scene, 100, 200)
    assert token != scene_token(scene, 101, 200)
    assert find_scene(tmp_path, token, owner_user_id=100, owner_chat_id=200) is not None
    assert find_scene(tmp_path, token, owner_user_id=101, owner_chat_id=200) is None
    assert find_scene(tmp_path, token, owner_user_id=100, owner_chat_id=201) is None

    page = restore_scene_page(
        tmp_path, token, 0, owner_user_id=100, owner_chat_id=200
    )
    assert page.tokens == [token]
    with pytest.raises(FileNotFoundError):
        restore_scene_page(
            tmp_path, token, 0, owner_user_id=101, owner_chat_id=200
        )
""",
)

print("security/cache hardening applied")
