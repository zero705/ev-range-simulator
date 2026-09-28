"""Work at the wheels over a speed trace.

Over each one-second interval the car moves at the mean of the two sampled speeds and
accelerates at their difference. With that choice the inertial term telescopes exactly,
sum(m * a * v_mean) = m/2 * (v_end^2 - v_start^2), so a cycle that starts and ends at rest
returns all its kinetic energy and the net work equals the road-load work exactly. Road load
acts only while the car moves.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike

from evrange.vehicles import RoadLoad


@dataclass(frozen=True)
class WheelWork:
    """Work at the wheels, in joules, over a trace."""

    positive_j: float
    """Work the wheels deliver while the car is driven."""
    negative_j: float
    """Work the wheels must absorb while the car slows faster than road load alone would
    slow it (a positive number): the braking the car has to do."""
    rolling_j: float
    """Work against the constant and linear road-load terms."""
    aero_j: float
    """Work against the quadratic road-load term."""
    distance_m: float
    duration_s: float

    @property
    def net_j(self) -> float:
        return self.positive_j - self.negative_j


def wheel_work(
    speed_ms: ArrayLike, road_load: RoadLoad, inertial_mass_kg: float, step_s: float = 1.0
) -> WheelWork:
    """Integrate wheel power over a speed trace sampled every step_s seconds."""
    speed = np.asarray(speed_ms, dtype=np.float64)
    if speed.ndim != 1 or speed.size < 2:
        raise ValueError("a speed trace needs at least two samples")
    if inertial_mass_kg <= 0 or step_s <= 0:
        raise ValueError("mass and time step must be positive")
    v = (speed[:-1] + speed[1:]) / 2
    accel = np.diff(speed) / step_s
    moving = v > 0
    rolling = np.where(moving, road_load.f0 + road_load.f1 * v, 0.0)
    aero = np.where(moving, road_load.f2 * v * v, 0.0)
    work = (rolling + aero + inertial_mass_kg * accel) * v * step_s
    return WheelWork(
        positive_j=float(work[work > 0].sum()),
        negative_j=float(-work[work < 0].sum()),
        rolling_j=float(np.sum(rolling * v) * step_s),
        aero_j=float(np.sum(aero * v) * step_s),
        distance_m=float(v.sum() * step_s),
        duration_s=float(v.size * step_s),
    )


def steady_work(speed_ms: float, road_load: RoadLoad, distance_m: float = 1000.0) -> WheelWork:
    """Work at the wheels to cover a distance at constant speed (no acceleration)."""
    if speed_ms <= 0 or distance_m <= 0:
        raise ValueError("speed and distance must be positive")
    rolling = (road_load.f0 + road_load.f1 * speed_ms) * distance_m
    aero = road_load.f2 * speed_ms**2 * distance_m
    total = rolling + aero
    if total < 0:
        raise ValueError("road load is negative at this speed")
    return WheelWork(
        positive_j=total,
        negative_j=0.0,
        rolling_j=rolling,
        aero_j=aero,
        distance_m=distance_m,
        duration_s=distance_m / speed_ms,
    )
