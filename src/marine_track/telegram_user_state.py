from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

from marine_track.models import Sensor

STATE_FILE = "telegram_user_state.json"
STATE_SCHEMA_VERSION = 1
MAX_SAVED_BBOXES_PER_USER = 10
BBOX_COORD_PRECISION = 6
OUTPUT_MODE_ALL = "all"
OUTPUT_MODE_IMAGES = "images"
OUTPUT_MODE_FILES = "files"
OUTPUT_MODES = {OUTPUT_MODE_ALL, OUTPUT_MODE_IMAGES, OUTPUT_MODE_FILES}
DEFAULT_OUTPUT_MODE = OUTPUT_MODE_ALL
_LOCK_SUFFIX = ".lock"
_QUARANTINE_PREFIX = "telegram_user_state.corrupt-"
_PROCESS_LOCK = threading.RLock()
T = TypeVar("T")


class UserStateError(RuntimeError):
    """Base error for persistent Telegram user state."""


class UserStateCorruptionError(UserStateError):
    """Raised when the active state cannot be parsed as the supported JSON shape."""


class UserStateSchemaError(UserStateError):
    """Raised when the active state uses an unsupported versioned schema."""


@dataclass(frozen=True)
class SavedBbox:
    id: str
    label: str
    sensor: Sensor
    west: float
    south: float
    east: float
    north: float
    hours: int
    created_at: str
    updated_at: str
    use_count: int


@dataclass(frozen=True)
class UserStateInspection:
    exists: bool
    valid: bool
    schema_version: int | None
    user_count: int
    quarantine_count: int
    detail: str


def state_path(output_dir: Path) -> Path:
    return Path(output_dir) / STATE_FILE


def state_lock_path(output_dir: Path) -> Path:
    path = state_path(output_dir)
    return path.with_name(path.name + _LOCK_SUFFIX)


def quarantine_paths(output_dir: Path) -> list[Path]:
    root = Path(output_dir)
    if not root.is_dir():
        return []
    return sorted(root.glob(f"{_QUARANTINE_PREFIX}*.json"))


def load_state(output_dir: Path) -> dict[str, object]:
    """Read one complete state snapshot and quarantine malformed active JSON."""

    output_dir = Path(output_dir)
    path = state_path(output_dir)
    with _state_lock(output_dir, exclusive=False):
        try:
            return _read_state_unlocked(path)
        except UserStateCorruptionError:
            pass

    # Re-read after upgrading to the exclusive lock. Another process may have
    # repaired or replaced the state between the two lock acquisitions.
    with _state_lock(output_dir, exclusive=True):
        try:
            return _read_state_unlocked(path)
        except UserStateCorruptionError:
            _quarantine_unlocked(path)
            return {}


def save_state(output_dir: Path, state: dict[str, object]) -> None:
    """Atomically replace the complete state document under an exclusive lock."""

    if not isinstance(state, dict):
        raise TypeError("Telegram user state must be a mapping")
    output_dir = Path(output_dir)
    with _state_lock(output_dir, exclusive=True):
        path = state_path(output_dir)
        try:
            _read_state_unlocked(path)
        except UserStateCorruptionError:
            _quarantine_unlocked(path)
        _write_state_unlocked(path, _prepare_for_write(state))


def inspect_user_state(output_dir: Path) -> UserStateInspection:
    """Return redacted health metadata without exposing paths or user content."""

    output_dir = Path(output_dir)
    path = state_path(output_dir)
    with _state_lock(output_dir, exclusive=False):
        quarantined = len(quarantine_paths(output_dir))
        if not path.exists():
            detail = "not created yet"
            if quarantined:
                detail = "not created; quarantined corrupt snapshots exist"
            return UserStateInspection(
                exists=False,
                valid=True,
                schema_version=None,
                user_count=0,
                quarantine_count=quarantined,
                detail=detail,
            )
        try:
            payload = _read_state_unlocked(path)
        except (UserStateCorruptionError, UserStateSchemaError) as exc:
            return UserStateInspection(
                exists=True,
                valid=False,
                schema_version=None,
                user_count=0,
                quarantine_count=quarantined,
                detail=f"invalid state document: {exc}",
            )
        except UserStateError as exc:
            return UserStateInspection(
                exists=True,
                valid=False,
                schema_version=None,
                user_count=0,
                quarantine_count=quarantined,
                detail=f"state access failed: {exc}",
            )

    users = payload.get("users")
    user_count = len(users) if isinstance(users, dict) else 0
    schema_version = _validate_schema(payload)
    if schema_version == 0:
        detail = "valid legacy state; next mutation upgrades schema"
    elif quarantined:
        detail = "valid state; quarantined corrupt snapshots exist"
    else:
        detail = "valid transactional state"
    return UserStateInspection(
        exists=True,
        valid=True,
        schema_version=schema_version,
        user_count=user_count,
        quarantine_count=quarantined,
        detail=detail,
    )


def user_key(user_id: int) -> str:
    return str(user_id or 0)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_coord(value: float) -> float:
    return round(float(value), BBOX_COORD_PRECISION)


def _bbox_key(
    sensor: Sensor,
    west: float,
    south: float,
    east: float,
    north: float,
    hours: int,
) -> str:
    parts = [
        sensor.value,
        f"{_norm_coord(west):.{BBOX_COORD_PRECISION}f}",
        f"{_norm_coord(south):.{BBOX_COORD_PRECISION}f}",
        f"{_norm_coord(east):.{BBOX_COORD_PRECISION}f}",
        f"{_norm_coord(north):.{BBOX_COORD_PRECISION}f}",
        str(int(hours)),
    ]
    return "|".join(parts)


def _bbox_id(
    sensor: Sensor,
    west: float,
    south: float,
    east: float,
    north: float,
    hours: int,
) -> str:
    digest = hashlib.sha1(
        _bbox_key(sensor, west, south, east, north, hours).encode("utf-8")
    ).hexdigest()
    return digest[:10]


def _saved_label(
    sensor: Sensor,
    west: float,
    south: float,
    east: float,
    north: float,
    hours: int,
) -> str:
    return (
        f"{sensor.value} "
        f"{_norm_coord(west):g},{_norm_coord(south):g}-"
        f"{_norm_coord(east):g},{_norm_coord(north):g} "
        f"за {int(hours)} ч"
    )


def _saved_bbox_payload(bbox: SavedBbox) -> dict[str, object]:
    return {
        "id": bbox.id,
        "label": bbox.label,
        "sensor": bbox.sensor.value,
        "west": bbox.west,
        "south": bbox.south,
        "east": bbox.east,
        "north": bbox.north,
        "hours": bbox.hours,
        "created_at": bbox.created_at,
        "updated_at": bbox.updated_at,
        "use_count": bbox.use_count,
    }


def _parse_saved_bbox(raw: object) -> SavedBbox | None:
    if not isinstance(raw, dict):
        return None
    try:
        sensor = Sensor(str(raw["sensor"]))
        west = _norm_coord(float(raw["west"]))
        south = _norm_coord(float(raw["south"]))
        east = _norm_coord(float(raw["east"]))
        north = _norm_coord(float(raw["north"]))
        hours = int(raw["hours"])
        bbox_id = str(raw["id"])
        label = str(raw["label"])
        created_at = str(raw["created_at"])
        updated_at = str(raw["updated_at"])
        use_count = max(0, int(raw["use_count"]))
        return SavedBbox(
            id=bbox_id,
            label=label,
            sensor=sensor,
            west=west,
            south=south,
            east=east,
            north=north,
            hours=hours,
            created_at=created_at,
            updated_at=updated_at,
            use_count=use_count,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _user_record(state: dict[str, object], user_id: int) -> dict[str, object]:
    users = state.setdefault("users", {})
    if not isinstance(users, dict):
        raise UserStateCorruptionError("users must be a JSON object")
    current = users.get(user_key(user_id))
    if not isinstance(current, dict):
        current = {}
    users[user_key(user_id)] = current
    return current


def save_last_bbox(
    output_dir: Path,
    user_id: int,
    sensor: Sensor,
    west: float,
    south: float,
    east: float,
    north: float,
    hours: int,
) -> SavedBbox:
    def mutate(state: dict[str, object]) -> SavedBbox:
        current = _user_record(state, user_id)
        now = _now()
        normalized_key = _bbox_key(sensor, west, south, east, north, hours)
        saved = get_saved_bboxes_from_user(current)
        existing = next(
            (
                item
                for item in saved
                if _bbox_key(
                    item.sensor,
                    item.west,
                    item.south,
                    item.east,
                    item.north,
                    item.hours,
                )
                == normalized_key
            ),
            None,
        )
        record = SavedBbox(
            id=existing.id if existing else _bbox_id(sensor, west, south, east, north, hours),
            label=_saved_label(sensor, west, south, east, north, hours),
            sensor=sensor,
            west=_norm_coord(west),
            south=_norm_coord(south),
            east=_norm_coord(east),
            north=_norm_coord(north),
            hours=int(hours),
            created_at=existing.created_at if existing else now,
            updated_at=now,
            use_count=(existing.use_count + 1) if existing else 1,
        )
        saved = [
            item
            for item in saved
            if _bbox_key(
                item.sensor,
                item.west,
                item.south,
                item.east,
                item.north,
                item.hours,
            )
            != normalized_key
        ]
        saved.insert(0, record)
        current["saved_bboxes"] = [
            _saved_bbox_payload(item) for item in saved[:MAX_SAVED_BBOXES_PER_USER]
        ]
        return record

    return _mutate_state(Path(output_dir), mutate)


def get_saved_bboxes_from_user(current: dict[str, object]) -> list[SavedBbox]:
    raw_items = current.get("saved_bboxes")
    saved: list[SavedBbox] = []
    if isinstance(raw_items, list):
        for raw in raw_items:
            bbox = _parse_saved_bbox(raw)
            if bbox is not None:
                saved.append(bbox)
    return saved[:MAX_SAVED_BBOXES_PER_USER]


def get_saved_bboxes(output_dir: Path, user_id: int) -> list[SavedBbox]:
    state = load_state(Path(output_dir))
    users = state.get("users")
    if not isinstance(users, dict):
        return []
    current = users.get(user_key(user_id))
    if not isinstance(current, dict):
        return []
    return get_saved_bboxes_from_user(current)


def get_saved_bbox(output_dir: Path, user_id: int, bbox_id: str) -> SavedBbox | None:
    for bbox in get_saved_bboxes(Path(output_dir), user_id):
        if bbox.id == bbox_id:
            return bbox
    return None


def delete_saved_bbox(output_dir: Path, user_id: int, bbox_id: str) -> bool:
    def mutate(state: dict[str, object]) -> tuple[bool, bool]:
        current = _user_record(state, user_id)
        saved = get_saved_bboxes_from_user(current)
        kept = [item for item in saved if item.id != bbox_id]
        if len(kept) == len(saved):
            return False, False
        current["saved_bboxes"] = [_saved_bbox_payload(item) for item in kept]
        return True, True

    deleted, _dirty = _mutate_state_with_dirty(Path(output_dir), mutate)
    return deleted


def get_last_bbox(output_dir: Path, user_id: int) -> SavedBbox | None:
    saved = get_saved_bboxes(Path(output_dir), user_id)
    return saved[0] if saved else None


def bbox_command_args(bbox: SavedBbox) -> list[str]:
    return [
        bbox.sensor.value,
        str(bbox.west),
        str(bbox.south),
        str(bbox.east),
        str(bbox.north),
        str(bbox.hours),
    ]


def bbox_label(bbox: SavedBbox) -> str:
    return bbox.label


def normalize_output_mode(mode: str | None) -> str:
    value = (mode or DEFAULT_OUTPUT_MODE).strip().lower()
    return value if value in OUTPUT_MODES else DEFAULT_OUTPUT_MODE


def output_mode_label(mode: str) -> str:
    value = normalize_output_mode(mode)
    if value == OUTPUT_MODE_IMAGES:
        return "только картинки"
    if value == OUTPUT_MODE_FILES:
        return "только файлы"
    return "всё"


def get_output_mode(output_dir: Path, user_id: int) -> str:
    state = load_state(Path(output_dir))
    users = state.get("users")
    if not isinstance(users, dict):
        return DEFAULT_OUTPUT_MODE
    current = users.get(user_key(user_id))
    if not isinstance(current, dict):
        return DEFAULT_OUTPUT_MODE
    return normalize_output_mode(str(current.get("output_mode") or DEFAULT_OUTPUT_MODE))


def set_output_mode(output_dir: Path, user_id: int, mode: str) -> str:
    normalized = normalize_output_mode(mode)

    def mutate(state: dict[str, object]) -> str:
        current = _user_record(state, user_id)
        current["output_mode"] = normalized
        return normalized

    return _mutate_state(Path(output_dir), mutate)


def _mutate_state(output_dir: Path, mutator: Callable[[dict[str, object]], T]) -> T:
    def wrapped(state: dict[str, object]) -> tuple[T, bool]:
        return mutator(state), True

    result, _dirty = _mutate_state_with_dirty(output_dir, wrapped)
    return result


def _mutate_state_with_dirty(
    output_dir: Path,
    mutator: Callable[[dict[str, object]], tuple[T, bool]],
) -> tuple[T, bool]:
    with _state_lock(output_dir, exclusive=True):
        path = state_path(output_dir)
        try:
            state = _read_state_unlocked(path)
        except UserStateCorruptionError:
            _quarantine_unlocked(path)
            state = {}
        result, dirty = mutator(state)
        if dirty:
            _write_state_unlocked(path, _prepare_for_write(state))
        return result, dirty


def _prepare_for_write(state: dict[str, object]) -> dict[str, object]:
    payload = dict(state)
    payload["schema_version"] = STATE_SCHEMA_VERSION
    users = payload.get("users")
    if users is None:
        payload["users"] = {}
    elif not isinstance(users, dict):
        raise TypeError("Telegram user state users must be a mapping")
    return payload


def _validate_schema(payload: dict[str, object]) -> int:
    raw = payload.get("schema_version")
    if raw is None:
        return 0  # legacy pre-versioned schema
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise UserStateSchemaError("schema_version must be an integer")
    if raw != STATE_SCHEMA_VERSION:
        raise UserStateSchemaError(f"unsupported schema_version {raw}")
    return raw


def _read_state_unlocked(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise UserStateError("state file must not be a symbolic link")
    if not path.exists():
        return {}
    if not path.is_file():
        raise UserStateError("state path is not a regular file")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UserStateError(f"unable to read state file: {type(exc).__name__}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UserStateCorruptionError(
            f"invalid JSON at line {exc.lineno} column {exc.colno}"
        ) from exc
    if not isinstance(payload, dict):
        raise UserStateCorruptionError("root must be a JSON object")
    users = payload.get("users")
    if users is not None and not isinstance(users, dict):
        raise UserStateCorruptionError("users must be a JSON object")
    _validate_schema(payload)
    return payload


def _write_state_unlocked(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True).rstrip() + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.tmp-",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file_obj:
            descriptor = -1
            file_obj.write(serialized)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        if descriptor >= 0:
            with suppress(OSError):
                os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise


def _quarantine_unlocked(path: Path) -> Path | None:
    if not path.exists():
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    quarantine = path.with_name(
        f"{_QUARANTINE_PREFIX}{timestamp}-{os.getpid()}-{uuid.uuid4().hex[:8]}.json"
    )
    os.chmod(path, 0o600)
    os.replace(path, quarantine)
    _fsync_directory(path.parent)
    return quarantine


@contextmanager
def _state_lock(output_dir: Path, *, exclusive: bool) -> Iterator[None]:
    try:
        import fcntl
    except ImportError as exc:  # pragma: no cover - production target is Linux
        raise UserStateError("fcntl is required for Telegram user-state locking") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_lock_path(output_dir)
    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)

    with _PROCESS_LOCK:
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise UserStateError(
                f"unable to open user-state lock: {type(exc).__name__}"
            ) from exc
        try:
            os.fchmod(descriptor, 0o600)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise UserStateError("user-state lock is not a regular file")
            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(descriptor, operation)
            try:
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        with suppress(OSError):
            os.fsync(descriptor)
    finally:
        os.close(descriptor)
