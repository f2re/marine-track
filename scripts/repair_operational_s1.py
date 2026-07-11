from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"repair marker not found: {label}")
    return text.replace(old, new, 1)


path = Path("src/marine_track/scene_materializer.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from contextlib import contextmanager, nullcontext\n",
    "from contextlib import contextmanager, nullcontext, suppress\n",
    "contextlib suppress import",
)
text = replace_once(
    text,
    '''                try:
                    os.utime(lock_path, None)
                except OSError:
                    pass
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise MaterializationError(
                        f"Timed out waiting for raster cache lock: {target.name}"
                    )
''',
    '''                with suppress(OSError):
                    os.utime(lock_path, None)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise MaterializationError(
                        f"Timed out waiting for raster cache lock: {target.name}"
                    ) from exc
''',
    "lock timeout exception chaining",
)
path.write_text(text, encoding="utf-8")

materialization_test = Path("tests/test_materialization_safety.py")
test_text = materialization_test.read_text(encoding="utf-8")
test_text = replace_once(
    test_text,
    '''    with pytest.raises(MaterializationError, match="finite and positive"):
        with materialization_lock(tmp_path / "scene.tif", float("nan")):
            pass
''',
    '''    with (
        pytest.raises(MaterializationError, match="finite and positive"),
        materialization_lock(tmp_path / "scene.tif", float("nan")),
    ):
        pass
''',
    "SIM117 combined context managers",
)
materialization_test.write_text(test_text, encoding="utf-8")

health = Path("src/marine_track/health.py").read_text(encoding="utf-8")
if 'release_id=os.getenv("MARINE_TRACK_RELEASE_ID", "unknown") or "unknown"' not in health:
    raise RuntimeError("retry-safe deployment release identity was lost")

env = Path(".env.example").read_text(encoding="utf-8")
for required in (
    "MARINE_TRACK_RELEASE_ID=",
    "MARINE_TRACK_S1_SPECKLE_FILTER=lee",
    "MARINE_TRACK_ENABLE_SENTINEL2_SINGLE_BAND_EXPERIMENTAL=0",
    "MARINE_TRACK_ENABLE_WAKE_RESEARCH=0",
):
    if required not in env:
        raise RuntimeError(f"required environment contract missing: {required}")
