"""Wheel work: the integration scheme conserves energy exactly."""

from __future__ import annotations

import numpy as np
import pytest

from evrange.cycles import load_cycles
from evrange.physics import steady_work, wheel_work
from evrange.vehicles import RoadLoad

LOAD = RoadLoad(130.0, 2.5, 0.35, 1.2)
MASS = 1900.0


@pytest.mark.parametrize("key", ["wltc", "udds", "hwfet", "wltc-low", "wltc-extra-high"])
def test_net_work_equals_road_load_work_on_a_closed_cycle(key: str) -> None:
    work = wheel_work(load_cycles()[key].speed_ms, LOAD, MASS)
    assert work.net_j == pytest.approx(work.rolling_j + work.aero_j, rel=1e-12)
    assert work.positive_j > 0
    assert work.negative_j > 0


def test_kinetic_energy_is_returned_exactly_without_road_load() -> None:
    speed = np.array([0.0, 3.0, 7.5, 12.0, 12.0, 6.0, 0.0])
    work = wheel_work(speed, RoadLoad(0.0, 0.0, 0.0, 1.2), MASS)
    assert work.positive_j == pytest.approx(0.5 * MASS * 12.0**2)
    assert work.negative_j == pytest.approx(0.5 * MASS * 12.0**2)


def test_constant_speed_matches_the_steady_formula() -> None:
    speed = np.full(101, 25.0)
    work = wheel_work(speed, LOAD, MASS)
    steady = steady_work(25.0, LOAD, distance_m=work.distance_m)
    assert work.positive_j == pytest.approx(steady.positive_j)
    assert work.rolling_j == pytest.approx(steady.rolling_j)
    assert work.aero_j == pytest.approx(steady.aero_j)
    assert work.duration_s == pytest.approx(steady.duration_s)
    assert work.negative_j == 0.0


def test_standstill_needs_no_work() -> None:
    work = wheel_work(np.zeros(61), LOAD, MASS)
    assert (work.positive_j, work.negative_j, work.distance_m) == (0.0, 0.0, 0.0)
    assert work.duration_s == 60.0


def test_time_step_scales_time_and_distance() -> None:
    speed = np.array([0.0, 10.0, 10.0, 0.0])
    one = wheel_work(speed, LOAD, MASS, step_s=1.0)
    two = wheel_work(speed, LOAD, MASS, step_s=2.0)
    assert two.distance_m == pytest.approx(2 * one.distance_m)
    assert two.duration_s == 2 * one.duration_s


def test_steady_work_splits_rolling_and_aero() -> None:
    work = steady_work(20.0, LOAD, distance_m=500.0)
    assert work.rolling_j == pytest.approx((130.0 + 2.5 * 20.0) * 500.0)
    assert work.aero_j == pytest.approx(0.35 * 400.0 * 500.0)
    assert work.duration_s == 25.0


@pytest.mark.parametrize(
    ("speed", "mass", "step"),
    [
        (np.array([1.0]), MASS, 1.0),
        (np.zeros((2, 2)), MASS, 1.0),
        (np.zeros(3), 0.0, 1.0),
        (np.zeros(3), MASS, 0.0),
    ],
)
def test_wheel_work_rejects_bad_input(speed: np.ndarray, mass: float, step: float) -> None:
    with pytest.raises(ValueError, match=r"samples|positive"):
        wheel_work(speed, LOAD, mass, step)


def test_steady_work_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="positive"):
        steady_work(0.0, LOAD)
    with pytest.raises(ValueError, match="positive"):
        steady_work(10.0, LOAD, distance_m=0.0)
    with pytest.raises(ValueError, match="negative"):
        steady_work(10.0, RoadLoad(-500.0, 0.0, 0.0, 1.2))
