"""The energy balance from the wheels back to the mains closes exactly."""

from __future__ import annotations

import pytest

from evrange.constants import J_PER_WH
from evrange.cycles import load_cycle
from evrange.model import BREAKDOWN, Powertrain, energy_use
from evrange.physics import wheel_work
from evrange.vehicles import RoadLoad

POWERTRAIN = Powertrain(
    drive_efficiency=0.9, regen_coefficient=0.8, auxiliary_w=200.0, charging_efficiency=0.88
)
WORK = wheel_work(load_cycle("wltc").speed_ms, RoadLoad(130.0, 2.5, 0.35, 1.2), 1900.0)


def test_battery_and_mains_energy() -> None:
    use = energy_use(WORK, POWERTRAIN)
    positive, negative = WORK.positive_j / J_PER_WH, WORK.negative_j / J_PER_WH
    auxiliary = 200.0 * 1800 / J_PER_WH
    assert use.battery_wh == pytest.approx(positive / 0.9 - 0.8 * negative + auxiliary)
    assert use.mains_wh == pytest.approx(use.battery_wh / 0.88)
    assert use.auxiliary_wh == pytest.approx(auxiliary)
    assert use.regenerated_wh == pytest.approx(0.8 * negative)
    assert use.braking_loss_wh == pytest.approx(0.2 * negative)
    assert use.drive_loss_wh == pytest.approx(positive / 0.9 - positive)


def test_breakdown_adds_up_to_the_mains_energy() -> None:
    use = energy_use(WORK, POWERTRAIN)
    parts = use.breakdown_wh()
    assert list(parts) == list(BREAKDOWN)
    assert sum(parts.values()) == pytest.approx(use.mains_wh, rel=1e-12)
    assert all(value > 0 for value in parts.values())


def test_per_kilometre_values_and_range() -> None:
    use = energy_use(WORK, POWERTRAIN)
    assert use.distance_km == pytest.approx(23.26628, abs=1e-5)
    assert use.battery_wh_per_km == pytest.approx(use.battery_wh / use.distance_km)
    assert use.mains_wh_per_km == pytest.approx(use.mains_wh / use.distance_km)
    assert use.range_km(60_000.0) == pytest.approx(60_000.0 / use.battery_wh_per_km)
    with pytest.raises(ValueError, match="usable energy"):
        use.range_km(0.0)


def test_range_needs_energy_from_the_battery() -> None:
    free = energy_use(
        WORK,
        Powertrain(
            drive_efficiency=1.0, regen_coefficient=1.0, auxiliary_w=0.0, charging_efficiency=1.0
        ),
    )
    assert free.battery_wh == pytest.approx((WORK.rolling_j + WORK.aero_j) / J_PER_WH, rel=1e-12)
    idle = energy_use(
        wheel_work([0.0, 0.0], RoadLoad(0.0, 0.0, 0.0, 1.2), 1.0),
        Powertrain(
            drive_efficiency=1.0, regen_coefficient=0.0, auxiliary_w=0.0, charging_efficiency=1.0
        ),
    )
    with pytest.raises(ValueError, match="no energy"):
        idle.range_km(1000.0)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("drive_efficiency", 0.0, "drive efficiency"),
        ("drive_efficiency", 1.01, "drive efficiency"),
        ("regen_coefficient", -0.1, "regeneration"),
        ("regen_coefficient", 1.1, "regeneration"),
        ("auxiliary_w", -1.0, "auxiliary"),
        ("charging_efficiency", 0.0, "charging"),
        ("charging_efficiency", 1.5, "charging"),
    ],
)
def test_powertrain_validation(field: str, value: float, message: str) -> None:
    values = {
        "drive_efficiency": 0.9,
        "regen_coefficient": 0.8,
        "auxiliary_w": 200.0,
        "charging_efficiency": 0.9,
        field: value,
    }
    with pytest.raises(ValueError, match=message):
        Powertrain(**values)
