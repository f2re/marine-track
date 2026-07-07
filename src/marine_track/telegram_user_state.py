from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from marine_track.models import Sensor

STATE_FILE = "telegram_user_state.json"


@dataclass(frozen=True)
class LastBbox:
    sensor: Sensor
    west: float
    south: float
    east: float
    north: float
    hours: int
    updated_at: str


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


def save_last_bbox(
    output_dir: Path,
    user_id: int,
    sensor: Sensor,
    west: float,
    south: float,
    east: float,
    north: float,
    hours: int,
) -> None:
    state = load_state(output_dir)
    users = state.setdefault("users", {})
    if not isinstance(users, dict):
        users = {}
        state["users"] = users
    record = LastBbox(
        sensor=sensor,
        west=west,
        south=south,
        east=east,
        north=north,
        hours=hours,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    current = users.get(user_key(user_id))
    if not isinstance(current, dict):
        current = {}
    current["last_bbox"] = record.__dict__ | {"sensor": sensor.value}
    users[user_key(user_id)] = current
    save_state(output_dir, state)


def get_last_bbox(output_dir: Path, user_id: int) -> LastBbox | None:
    state = load_state(output_dir)
    users = state.get("users")
    if not isinstance(users, dict):
        return None
    current = users.get(user_key(user_id))
    if not isinstance(current, dict):
        return None
    raw = current.get("last_bbox")
    if not isinstance(raw, dict):
        return None
    try:
        return LastBbox(
            sensor=Sensor(str(raw["sensor"])),
            west=float(raw["west"]),
            south=float(raw["south"]),
            east=float(raw["east"]),
            north=float(raw["north"]),
            hours=int(raw["hours"]),
            updated_at=str(raw.get("updated_at") or ""),
        )
    except Exception:
        return None


def bbox_command_args(bbox: LastBbox) -> list[str]:
    return [
        bbox.sensor.value,
        str(bbox.west),
        str(bbox.south),
        str(bbox.east),
        str(bbox.north),
        str(bbox.hours),
    ]


def bbox_label(bbox: LastBbox) -> str:
    return (
        f"{bbox.sensor.value} "
        f"{bbox.west:g},{bbox.south:g},{bbox.east:g},{bbox.north:g} "
        f"за {bbox.hours} ч"
    )
