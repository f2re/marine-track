from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]

(ROOT / "src/marine_track/telegram_user_state.py").write_text(
    dedent(
        '''\
        from __future__ import annotations

        import fcntl
        import hashlib
        import json
        import os
        import threading
        from contextlib import contextmanager
        from dataclasses import dataclass
        from datetime import datetime, timezone
        from pathlib import Path
        from typing import Iterator

        from marine_track.models import Sensor

        STATE_FILE = "telegram_user_state.json"
        STATE_LOCK_FILE = ".telegram_user_state.lock"
        STATE_SCHEMA_VERSION = 1
        MAX_SAVED_BBOXES_PER_USER = 10
        BBOX_COORD_PRECISION = 6
        OUTPUT_MODE_ALL = "all"
        OUTPUT_MODE_IMAGES = "images"
        OUTPUT_MODE_FILES = "files"
        OUTPUT_MODES = {OUTPUT_MODE_ALL, OUTPUT_MODE_IMAGES, OUTPUT_MODE_FILES}
        DEFAULT_OUTPUT_MODE = OUTPUT_MODE_ALL
        _THREAD_LOCK = threading.RLock()


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


        def state_lock_path(output_dir: Path) -> Path:
            return output_dir / STATE_LOCK_FILE


        def load_state(output_dir: Path) -> dict[str, object]:
            with _locked_state(output_dir):
                return _load_state_unlocked(output_dir, quarantine_corrupt=True)


        def save_state(output_dir: Path, state: dict[str, object]) -> None:
            with _locked_state(output_dir):
                _save_state_unlocked(output_dir, state)


        @contextmanager
        def state_transaction(output_dir: Path) -> Iterator[dict[str, object]]:
            with _locked_state(output_dir):
                state = _load_state_unlocked(output_dir, quarantine_corrupt=True)
                yield state
                _save_state_unlocked(output_dir, state)


        @contextmanager
        def _locked_state(output_dir: Path) -> Iterator[None]:
            output_dir.mkdir(parents=True, exist_ok=True)
            lock_path = state_lock_path(output_dir)
            with _THREAD_LOCK:
                with lock_path.open("a+b") as lock_file:
                    os.chmod(lock_path, 0o600)
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


        def _new_state() -> dict[str, object]:
            return {"schema_version": STATE_SCHEMA_VERSION, "users": {}}


        def _load_state_unlocked(
            output_dir: Path,
            *,
            quarantine_corrupt: bool,
        ) -> dict[str, object]:
            path = state_path(output_dir)
            if not path.is_file():
                return _new_state()
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("state root is not an object")
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                if quarantine_corrupt:
                    _quarantine_state(path)
                return _new_state()
            payload.setdefault("schema_version", STATE_SCHEMA_VERSION)
            users = payload.get("users")
            if not isinstance(users, dict):
                payload["users"] = {}
            return payload


        def _save_state_unlocked(output_dir: Path, state: dict[str, object]) -> None:
            output_dir.mkdir(parents=True, exist_ok=True)
            state["schema_version"] = STATE_SCHEMA_VERSION
            if not isinstance(state.get("users"), dict):
                state["users"] = {}
            path = state_path(output_dir)
            temporary = path.with_name(
                f".{path.name}.tmp.{os.getpid()}.{threading.get_ident()}"
            )
            payload = json.dumps(
                state,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n"
            try:
                with temporary.open("w", encoding="utf-8", newline="\n") as file_obj:
                    file_obj.write(payload)
                    file_obj.flush()
                    os.fsync(file_obj.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, path)
                _fsync_directory(output_dir)
            finally:
                temporary.unlink(missing_ok=True)


        def _quarantine_state(path: Path) -> Path | None:
            if not path.exists():
                return None
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            quarantine = path.with_name(
                f"{path.stem}.corrupt.{stamp}.{os.getpid()}{path.suffix}"
            )
            try:
                os.replace(path, quarantine)
                os.chmod(quarantine, 0o600)
                _fsync_directory(path.parent)
                return quarantine
            except OSError:
                return None


        def _fsync_directory(directory: Path) -> None:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            try:
                descriptor = os.open(directory, flags)
            except OSError:
                return
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)


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
                return SavedBbox(
                    id=str(raw["id"]),
                    label=str(raw["label"]),
                    sensor=sensor,
                    west=west,
                    south=south,
                    east=east,
                    north=north,
                    hours=hours,
                    created_at=str(raw["created_at"]),
                    updated_at=str(raw["updated_at"]),
                    use_count=max(0, int(raw["use_count"])),
                )
            except Exception:  # noqa: BLE001 - legacy rows are skipped independently
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
            with state_transaction(output_dir) as state:
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
                    id=(
                        existing.id
                        if existing
                        else _bbox_id(sensor, west, south, east, north, hours)
                    ),
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
                    _saved_bbox_payload(item)
                    for item in saved[:MAX_SAVED_BBOXES_PER_USER]
                ]
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


        def get_saved_bbox(
            output_dir: Path,
            user_id: int,
            bbox_id: str,
        ) -> SavedBbox | None:
            return next(
                (
                    bbox
                    for bbox in get_saved_bboxes(output_dir, user_id)
                    if bbox.id == bbox_id
                ),
                None,
            )


        def delete_saved_bbox(output_dir: Path, user_id: int, bbox_id: str) -> bool:
            with state_transaction(output_dir) as state:
                current = _user_record(state, user_id)
                saved = get_saved_bboxes_from_user(current)
                kept = [item for item in saved if item.id != bbox_id]
                if len(kept) == len(saved):
                    return False
                current["saved_bboxes"] = [
                    _saved_bbox_payload(item) for item in kept
                ]
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
            return normalize_output_mode(
                str(current.get("output_mode") or DEFAULT_OUTPUT_MODE)
            )


        def set_output_mode(output_dir: Path, user_id: int, mode: str) -> str:
            normalized = normalize_output_mode(mode)
            with state_transaction(output_dir) as state:
                current = _user_record(state, user_id)
                current["output_mode"] = normalized
            return normalized
        '''
    ),
    encoding="utf-8",
)

health = ROOT / "src/marine_track/health.py"
text = health.read_text(encoding="utf-8")
marker = '    checks.append(_registry_check(output_dir / "scene_registry.json"))\n'
if marker not in text:
    raise RuntimeError("health registry marker not found")
text = text.replace(
    marker,
    marker + '    checks.append(_user_state_check(output_dir / "telegram_user_state.json"))\n',
    1,
)
insert_before = "\ndef _calibration_check(output_dir: Path) -> HealthCheck:\n"
if insert_before not in text:
    raise RuntimeError("health calibration marker not found")
user_state_check = dedent(
    '''

    def _user_state_check(path: Path) -> HealthCheck:
        quarantined = len(list(path.parent.glob("telegram_user_state.corrupt.*.json")))
        if not path.is_file():
            return HealthCheck(
                name="telegram_user_state",
                status="warning",
                critical=False,
                detail="not created yet",
                data={"users": 0, "quarantined": quarantined},
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("state root is not an object")
            users = payload.get("users")
            if users is None:
                users = {}
            if not isinstance(users, dict):
                raise ValueError("users is not an object")
            status = "warning" if quarantined else "ok"
            detail = "valid" if not quarantined else "valid; quarantined copies retained"
            return HealthCheck(
                name="telegram_user_state",
                status=status,
                critical=False,
                detail=detail,
                data={
                    "users": len(users),
                    "schema_version": payload.get("schema_version", "legacy"),
                    "quarantined": quarantined,
                },
            )
        except Exception as exc:
            return HealthCheck(
                name="telegram_user_state",
                status="warning",
                critical=False,
                detail=f"invalid state: {type(exc).__name__}",
                data={"quarantined": quarantined},
            )
    '''
)
text = text.replace(insert_before, user_state_check + insert_before, 1)
health.write_text(text, encoding="utf-8")

(ROOT / "docs/STATE_STORAGE.md").write_text(
    dedent(
        '''\
        # Runtime state storage

        Telegram user preferences and saved bboxes are stored in
        `MARINE_TRACK_OUTPUT_DIR/telegram_user_state.json`. Every mutation is a single transaction:

        1. acquire a process-wide thread lock;
        2. acquire an inter-process `flock` on `.telegram_user_state.lock`;
        3. load and validate the current JSON;
        4. apply the mutation;
        5. write a unique mode-0600 temporary file, flush and `fsync` it;
        6. atomically replace the visible state and `fsync` the parent directory.

        Readers use the same lock and therefore never observe a partial temporary file. Existing files
        without `schema_version` are accepted and upgraded on the next mutation.

        Invalid JSON is never overwritten in place. It is atomically renamed to
        `telegram_user_state.corrupt.<UTC timestamp>.<pid>.json`, after which a new empty state may be
        created. The health report exposes only counts and validity; it does not publish filesystem
        paths or state contents.
        '''
    ),
    encoding="utf-8",
)

(ROOT / "tests/test_telegram_user_state_transaction.py").write_text(
    dedent(
        '''\
        from __future__ import annotations

        import json
        import multiprocessing
        from pathlib import Path

        from marine_track.models import Sensor
        from marine_track.telegram_user_state import (
            STATE_SCHEMA_VERSION,
            get_output_mode,
            get_saved_bboxes,
            save_last_bbox,
            set_output_mode,
            state_path,
        )


        def _save_bbox_worker(output_dir: str, index: int) -> None:
            save_last_bbox(
                Path(output_dir),
                100,
                Sensor.SENTINEL1,
                30.0 + index / 100.0,
                43.0,
                30.005 + index / 100.0,
                43.005,
                72,
            )


        def test_parallel_process_updates_do_not_lose_bboxes(tmp_path):
            context = multiprocessing.get_context("fork")
            processes = [
                context.Process(target=_save_bbox_worker, args=(str(tmp_path), index))
                for index in range(6)
            ]
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=20)
                assert process.exitcode == 0
            saved = get_saved_bboxes(tmp_path, 100)
            assert len(saved) == 6
            assert len({item.id for item in saved}) == 6


        def test_state_write_is_private_atomic_and_has_single_final_newline(tmp_path):
            set_output_mode(tmp_path, 5, "images")
            path = state_path(tmp_path)
            raw = path.read_bytes()
            assert raw.endswith(b"\n")
            assert not raw.endswith(b"\n\n")
            assert path.stat().st_mode & 0o777 == 0o600
            payload = json.loads(raw)
            assert payload["schema_version"] == STATE_SCHEMA_VERSION
            assert payload["users"]["5"]["output_mode"] == "images"
            assert not list(tmp_path.glob(".telegram_user_state.json.tmp.*"))


        def test_corrupt_state_is_quarantined_before_recovery(tmp_path):
            path = state_path(tmp_path)
            path.write_text("{broken", encoding="utf-8")
            assert get_saved_bboxes(tmp_path, 1) == []
            assert not path.exists()
            quarantined = list(tmp_path.glob("telegram_user_state.corrupt.*.json"))
            assert len(quarantined) == 1
            assert quarantined[0].read_text(encoding="utf-8") == "{broken"
            set_output_mode(tmp_path, 1, "files")
            assert get_output_mode(tmp_path, 1) == "files"


        def test_legacy_state_is_read_and_upgraded_on_mutation(tmp_path):
            path = state_path(tmp_path)
            path.write_text(
                json.dumps({"users": {"9": {"output_mode": "images"}}}),
                encoding="utf-8",
            )
            assert get_output_mode(tmp_path, 9) == "images"
            set_output_mode(tmp_path, 9, "files")
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert payload["schema_version"] == STATE_SCHEMA_VERSION
            assert payload["users"]["9"]["output_mode"] == "files"
        '''
    ),
    encoding="utf-8",
)

health_test = ROOT / "tests/test_health.py"
text = health_test.read_text(encoding="utf-8")
text += dedent(
    '''


    def test_user_state_health_does_not_expose_path(tmp_path):
        import json

        from marine_track.health import _user_state_check

        path = tmp_path / "telegram_user_state.json"
        path.write_text(
            json.dumps({"schema_version": 1, "users": {"1": {}}}),
            encoding="utf-8",
        )
        check = _user_state_check(path)
        assert check.status == "ok"
        assert check.data == {"users": 1, "schema_version": 1, "quarantined": 0}
        assert str(tmp_path) not in check.detail


    def test_invalid_user_state_is_noncritical_warning(tmp_path):
        from marine_track.health import _user_state_check

        path = tmp_path / "telegram_user_state.json"
        path.write_text("not-json", encoding="utf-8")
        check = _user_state_check(path)
        assert check.status == "warning"
        assert check.critical is False
        assert "JSON" in check.detail
        assert str(tmp_path) not in check.detail
    '''
)
health_test.write_text(text, encoding="utf-8")

print("transactional Telegram user state migration applied")
