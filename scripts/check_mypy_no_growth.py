#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ERROR_RE = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+)(?::(?P<column>\d+))?: error: "
    r"(?P<message>.*?)(?:  \[(?P<code>[^\]]+)\])?$"
)
SUMMARY_RE = re.compile(r"^Found (?P<count>\d+) errors? in .+ files? \(checked .+ source files?\)$")
SUCCESS_RE = re.compile(r"^Success: no issues found in .+ source files?$", re.MULTILINE)


@dataclass(frozen=True, order=True)
class ErrorFingerprint:
    path: str
    code: str
    message: str


def normalize_source_path(raw: str) -> str:
    value = raw.replace("\\", "/")
    marker = "/src/"
    if marker in value:
        return "src/" + value.split(marker, 1)[1]
    if value.startswith("src/"):
        return value
    src_index = value.find("src/")
    if src_index >= 0:
        return value[src_index:]
    return value


def parse_mypy_output(path: Path) -> Counter[ErrorFingerprint]:
    text = path.read_text(encoding="utf-8", errors="replace")
    errors: Counter[ErrorFingerprint] = Counter()
    summary_count: int | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        match = ERROR_RE.match(line)
        if match:
            errors[
                ErrorFingerprint(
                    path=normalize_source_path(match.group("path")),
                    code=match.group("code") or "unclassified",
                    message=match.group("message"),
                )
            ] += 1
            continue
        summary = SUMMARY_RE.match(line)
        if summary:
            summary_count = int(summary.group("count"))

    if summary_count is None:
        if SUCCESS_RE.search(text):
            summary_count = 0
        else:
            raise ValueError(f"{path} does not contain a complete mypy result")
    parsed_count = sum(errors.values())
    if parsed_count != summary_count:
        raise ValueError(
            f"{path} reports {summary_count} errors but {parsed_count} were parsed"
        )
    return errors


def check_no_growth(
    baseline: Counter[ErrorFingerprint],
    current: Counter[ErrorFingerprint],
) -> list[tuple[ErrorFingerprint, int, int]]:
    growth: list[tuple[ErrorFingerprint, int, int]] = []
    for fingerprint, current_count in current.items():
        baseline_count = baseline.get(fingerprint, 0)
        if current_count > baseline_count:
            growth.append((fingerprint, baseline_count, current_count))
    growth.sort(key=lambda item: item[0])
    return growth


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail when mypy errors grow relative to the current main baseline."
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        baseline = parse_mypy_output(args.baseline)
        current = parse_mypy_output(args.current)
    except (OSError, ValueError) as exc:
        print(f"mypy baseline check failed: {exc}", file=sys.stderr)
        return 2

    baseline_total = sum(baseline.values())
    current_total = sum(current.values())
    print(f"mypy baseline errors: {baseline_total}")
    print(f"mypy current errors: {current_total}")

    growth = check_no_growth(baseline, current)
    if growth:
        print("new or increased mypy errors:", file=sys.stderr)
        for fingerprint, baseline_count, current_count in growth:
            delta = current_count - baseline_count
            print(
                f"  +{delta} {fingerprint.path} [{fingerprint.code}] "
                f"{fingerprint.message} (baseline={baseline_count}, current={current_count})",
                file=sys.stderr,
            )
        return 1

    print("mypy no-growth baseline passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
