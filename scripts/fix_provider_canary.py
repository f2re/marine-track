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
