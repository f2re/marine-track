from __future__ import annotations

import math
from dataclasses import dataclass

KNOTS_PER_MPS = 1.9438444924406046
EARTH_RADIUS_M = 6_371_008.8


@dataclass(frozen=True)
class LonLat:
    lon: float
    lat: float


def normalize_heading_deg(value: float) -> float:
    return value % 360.0


def bearing_deg(start: LonLat, end: LonLat) -> float:
    """Initial bearing from start to end in degrees clockwise from north."""
    lat1 = math.radians(start.lat)
    lat2 = math.radians(end.lat)
    dlon = math.radians(end.lon - start.lon)
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return normalize_heading_deg(math.degrees(math.atan2(x, y)))


def haversine_distance_m(a: LonLat, b: LonLat) -> float:
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def speed_from_displacement(distance_m: float, delta_t_s: float) -> tuple[float, float]:
    if delta_t_s <= 0:
        raise ValueError("delta_t_s must be positive")
    speed_mps = distance_m / delta_t_s
    return speed_mps, speed_mps * KNOTS_PER_MPS


def speed_from_sentinel2_centroids(a: LonLat, b: LonLat, delta_t_s: float) -> tuple[float, float, float]:
    distance = haversine_distance_m(a, b)
    speed_mps, speed_knots = speed_from_displacement(distance, delta_t_s)
    heading = bearing_deg(a, b)
    return speed_mps, speed_knots, heading


def speed_from_kelvin_wavelength(wavelength_m: float, gravity_mps2: float = 9.80665) -> tuple[float, float]:
    """Deep-water Kelvin wake speed estimate.

    Uses V = sqrt(g * Lmax / (2*pi)). This estimates speed through water and must
    be corrected by current vector to obtain speed over ground.
    """
    if wavelength_m <= 0:
        raise ValueError("wavelength_m must be positive")
    speed_mps = math.sqrt(gravity_mps2 * wavelength_m / (2.0 * math.pi))
    return speed_mps, speed_mps * KNOTS_PER_MPS


def reciprocal_heading_deg(wake_axis_deg: float) -> float:
    """Convert wake tail direction into vessel heading direction."""
    return normalize_heading_deg(wake_axis_deg + 180.0)
