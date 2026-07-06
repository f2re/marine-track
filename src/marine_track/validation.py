from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhysicalValidationResult:
    ok: bool
    reason: str


def validate_speed_knots(speed_knots: float | None, max_reasonable_knots: float = 80.0) -> PhysicalValidationResult:
    if speed_knots is None:
        return PhysicalValidationResult(ok=True, reason="speed_not_estimated")
    if speed_knots < 0:
        return PhysicalValidationResult(ok=False, reason="negative_speed")
    if speed_knots > max_reasonable_knots:
        return PhysicalValidationResult(ok=False, reason="speed_above_reasonable_limit")
    return PhysicalValidationResult(ok=True, reason="ok")


def angular_difference_deg(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def validate_heading_alignment(
    hull_heading_deg: float | None,
    wake_heading_deg: float | None,
    tolerance_deg: float = 25.0,
) -> PhysicalValidationResult:
    if hull_heading_deg is None or wake_heading_deg is None:
        return PhysicalValidationResult(ok=True, reason="not_enough_heading_sources")
    diff = angular_difference_deg(hull_heading_deg, wake_heading_deg)
    if diff > tolerance_deg:
        return PhysicalValidationResult(ok=False, reason=f"heading_mismatch_{diff:.1f}_deg")
    return PhysicalValidationResult(ok=True, reason="ok")
