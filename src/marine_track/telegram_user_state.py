from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from marine_track.models import Sensor

STATE_FILE = "telegram_user_state.json"
MAX_SAVED_BBOXES_PER_USER = 10
BBOX_COORD_PRECISION = 6
OUTPUT_MODE_ALL = "all"
OUTPUT_MODE_IMAGES = "images"
OUTPUT_MODE_FILES = "files"
OUTPUT_MODES = {OUTPUT_MODE_ALL, OUTPUT_MODE_IMAGES, OUTPUT_MODE_FILES}
DEFAULT_OUTPUT_MODE = OUTPUT_MODE_ALL


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


def state_path(output_dir: Path) -> Path:
    return output_dir / STATE_FILE


def load_state(output_dir: Path) -> dict[str, object]:
    path = state_path(output_dir)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def save_state(output_dir: Path, state: dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path(output_dir).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def user_key(user_id: int) -> str:
    return str(user_id or 0)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_coord(value: float) -> float:
    return round(float(value), BBOX_COORD_PRECISION)


def _bbox_key(sensor: Sensor, west: float, south: float, east: float, north: float, hours: int) -> str:
    parts = [
        sensor.value,
        f"{_norm_coord(west):.{BBOX_COORD_PRECISION}f}",
        f"{_norm_coord(south):.{BBOX_COORD_PRECISION}f}",
        f"{_norm_coord(east):.{BBOX_COORD_PRECISION}f}",
        f"{_norm_coord(north):.{BBOX_COORD_PRECISION}f}",
        str(int(hours)),
    ]
    return "|".join(parts)


def _bbox_id(sensor: Sensor, west: float, south: float, east: float, north: float, hours: int) -> str:
    digest = hashlib.sha1(_bbox_key(sensor, west, south, east, north, hours).encode("utf-8")).hexdigest()
    return digest[:10]


def _saved_label(sensor: Sensor, west: float, south: float, east: float, north: float, hours: int) -> str:
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
    except Exception:
        return None


def _user_record(state: dict[str, object], user_id: int) -> dict[str, object]:
    users = state.setdefault("users", {})
    if not isinstance(users, dict):
        users = {}
        state["users"] = users
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
    state = load_state(output_dir)
    current = _user_record(state, user_id)
    now = _now()
    normalized_key = _bbox_key(sensor, west, south, east, north, hours)
    saved = get_saved_bboxes_from_user(current)
    existing = next(
        (
            item
            for item in saved
            if _bbox_key(item.sensor, item.west, item.south, item.east, item.north, item.hours) == normalized_key
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
        if _bbox_key(item.sensor, item.west, item.south, item.east, item.north, item.hours) != normalized_key
    ]
    saved.insert(0, record)
    saved = saved[:MAX_SAVED_BBOXES_PER_USER]
    current["saved_bboxes"] = [_saved_bbox_payload(item) for item in saved]
    save_state(output_dir, state)
    return record


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
    state = load_state(output_dir)
    users = state.get("users")
    if not isinstance(users, dict):
        return []
    current = users.get(user_key(user_id))
    if not isinstance(current, dict):
        return []
    return get_saved_bboxes_from_user(current)


def get_saved_bbox(output_dir: Path, user_id: int, bbox_id: str) -> SavedBbox | None:
    for bbox in get_saved_bboxes(output_dir, user_id):
        if bbox.id == bbox_id:
            return bbox
    return None


def delete_saved_bbox(output_dir: Path, user_id: int, bbox_id: str) -> bool:
    state = load_state(output_dir)
    current = _user_record(state, user_id)
    saved = get_saved_bboxes_from_user(current)
    kept = [item for item in saved if item.id != bbox_id]
    if len(kept) == len(saved):
        return False
    current["saved_bboxes"] = [_saved_bbox_payload(item) for item in kept]
    save_state(output_dir, state)
    return True


def get_last_bbox(output_dir: Path, user_id: int) -> SavedBbox | None:
    saved = get_saved_bboxes(output_dir, user_id)
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
    state = load_state(output_dir)
    users = state.get("users")
    if not isinstance(users, dict):
        return DEFAULT_OUTPUT_MODE
    current = users.get(user_key(user_id))
    if not isinstance(current, dict):
        return DEFAULT_OUTPUT_MODE
    return normalize_output_mode(str(current.get("output_mode") or DEFAULT_OUTPUT_MODE))


def set_output_mode(output_dir: Path, user_id: int, mode: str) -> str:
    normalized = normalize_output_mode(mode)
    state = load_state(output_dir)
    current = _user_record(state, user_id)
    current["output_mode"] = normalized
    save_state(output_dir, state)
    return normalized
