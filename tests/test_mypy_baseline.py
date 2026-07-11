from __future__ import annotations

from collections import Counter

import pytest

from scripts.check_mypy_no_growth import (
    ErrorFingerprint,
    check_no_growth,
    normalize_source_path,
    parse_mypy_output,
)


def test_normalize_source_path_removes_worktree_prefix() -> None:
    assert (
        normalize_source_path("/tmp/marine-track-main/src/marine_track/example.py")
        == "src/marine_track/example.py"
    )
    assert normalize_source_path("src/marine_track/example.py") == "src/marine_track/example.py"


def test_parse_mypy_output_ignores_line_number_changes(tmp_path) -> None:
    output = tmp_path / "mypy.txt"
    output.write_text(
        "src/marine_track/example.py:17: error: incompatible value  [assignment]\n"
        "Found 1 error in 1 file (checked 2 source files)\n",
        encoding="utf-8",
    )

    parsed = parse_mypy_output(output)

    assert parsed == Counter(
        {
            ErrorFingerprint(
                path="src/marine_track/example.py",
                code="assignment",
                message="incompatible value",
            ): 1
        }
    )


def test_parse_mypy_output_requires_complete_summary(tmp_path) -> None:
    output = tmp_path / "mypy.txt"
    output.write_text("mypy: cannot read file\n", encoding="utf-8")

    with pytest.raises(ValueError, match="complete mypy result"):
        parse_mypy_output(output)


def test_no_growth_accepts_removed_errors_and_rejects_new_errors() -> None:
    existing = ErrorFingerprint("src/a.py", "assignment", "bad assignment")
    added = ErrorFingerprint("src/b.py", "arg-type", "bad argument")
    baseline = Counter({existing: 2})

    assert check_no_growth(baseline, Counter({existing: 1})) == []
    assert check_no_growth(baseline, Counter({existing: 2, added: 1})) == [
        (added, 0, 1)
    ]
