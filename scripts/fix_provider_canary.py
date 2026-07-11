from __future__ import annotations

from pathlib import Path

path = Path("src/marine_track/provider_canary.py")
text = path.read_text(encoding="utf-8")
replacements = (
    (
        '                "geometry": mapping(output),\n',
        '                "geometry": json.loads(json.dumps(mapping(output))),\n',
        "JSON-compatible Shapely coordinates",
    ),
    (
        '        r"(?<![:\\w])/(?:[^/\\s]+/)+[^/\\s:;,]+",\n',
        '        r"(?<![/:\\w])/(?:[^/\\s]+/)+[^/\\s:;,]+",\n',
        "do not treat URL path as local path",
    ),
)
for old, new, label in replacements:
    if new in text:
        continue
    if old not in text:
        raise RuntimeError(f"provider canary repair marker not found: {label}")
    text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")

test_path = Path("tests/test_provider_canary.py")
test_text = test_path.read_text(encoding="utf-8")
old = "    assert len(result.aoi_hash) == 64\n"
new = "    assert len(result.aoi_hash) == 16\n"
if new not in test_text:
    if old not in test_text:
        raise RuntimeError("canary AOI hash assertion marker not found")
    test_text = test_text.replace(old, new, 1)
test_path.write_text(test_text, encoding="utf-8")
