from __future__ import annotations

import argparse
import os
import re
import stat
import tempfile
from pathlib import Path

KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_assignments(text: str) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    order: list[str] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            continue
        raw_key, raw_value = raw_line.split("=", 1)
        key = raw_key.strip()
        if not KEY_PATTERN.fullmatch(key):
            continue
        if key not in values:
            order.append(key)
        values[key] = raw_value.strip()
    return values, order


def value_is_nonempty(raw_value: str) -> bool:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return bool(value)


def parse_override(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise ValueError(f"override must use KEY=VALUE syntax: {raw!r}")
    key, value = raw.split("=", 1)
    key = key.strip()
    if not KEY_PATTERN.fullmatch(key):
        raise ValueError(f"invalid environment variable name: {key!r}")
    return key, value.strip()


def merge_env_text(
    template_text: str,
    current_text: str | None,
    legacy_texts: list[str],
    overrides: dict[str, str] | None = None,
) -> str:
    template_values, template_order = parse_assignments(template_text)
    current_values, current_order = parse_assignments(current_text or "")

    legacy_values: dict[str, str] = {}
    legacy_order: list[str] = []
    for legacy_text in legacy_texts:
        values, order = parse_assignments(legacy_text)
        for key in order:
            if key not in legacy_order:
                legacy_order.append(key)
            if value_is_nonempty(values[key]):
                legacy_values[key] = values[key]

    effective = dict(template_values)
    effective.update(legacy_values)
    for key, value in current_values.items():
        if value_is_nonempty(value) or key not in legacy_values:
            effective[key] = value
    effective.update(overrides or {})

    rendered: list[str] = []
    rendered_keys: set[str] = set()
    for raw_line in template_text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        if "=" not in raw_line or raw_line.lstrip().startswith("#"):
            rendered.append(raw_line.rstrip())
            continue
        raw_key, _raw_value = raw_line.split("=", 1)
        key = raw_key.strip()
        if not KEY_PATTERN.fullmatch(key):
            rendered.append(raw_line.rstrip())
            continue
        if key in rendered_keys:
            continue
        rendered.append(f"{key}={effective.get(key, '')}")
        rendered_keys.add(key)

    custom_order: list[str] = []
    for key in current_order + legacy_order + list((overrides or {}).keys()):
        if key not in rendered_keys and key not in custom_order:
            custom_order.append(key)
    if custom_order:
        while rendered and not rendered[-1]:
            rendered.pop()
        rendered.extend(["", "# Preserved deployment-specific values"])
        for key in custom_order:
            rendered.append(f"{key}={effective.get(key, '')}")
            rendered_keys.add(key)

    while rendered and not rendered[-1]:
        rendered.pop()
    return "\n".join(rendered) + "\n"


def merge_env_file(
    template: Path,
    target: Path,
    legacy_files: list[Path],
    overrides: dict[str, str] | None = None,
) -> list[str]:
    if not template.is_file():
        raise FileNotFoundError(f"environment template not found: {template}")

    template_text = template.read_text(encoding="utf-8")
    current_text = target.read_text(encoding="utf-8") if target.is_file() else None
    legacy_texts = [path.read_text(encoding="utf-8") for path in legacy_files if path.is_file()]
    merged = merge_env_text(template_text, current_text, legacy_texts, overrides)

    previous_values, _ = parse_assignments(current_text or "")
    merged_values, _ = parse_assignments(merged)
    changed_keys = sorted(
        key for key in set(previous_values) | set(merged_values) if previous_values.get(key) != merged_values.get(key)
    )

    target.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o640
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(merged)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return changed_keys


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge and normalize Marine Track environment files")
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--legacy", type=Path, action="append", default=[])
    parser.add_argument("--set", dest="overrides", action="append", default=[])
    args = parser.parse_args()

    override_values = dict(parse_override(raw) for raw in args.overrides)
    changed = merge_env_file(args.template, args.target, args.legacy, override_values)
    print(f"environment synchronized: {args.target} ({len(changed)} keys changed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
