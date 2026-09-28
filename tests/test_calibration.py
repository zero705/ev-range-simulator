"""Calibration reproduces each car's EPA measurements with physically possible parameters."""

from __future__ import annotations

from dataclasses import replace

import pytest

from evrange import Study, calibrate
from evrange.calibration import CALIBRATION_CYCLES, CalibrationError, cycle_terms
from evrange.cycles import load_cycles
from evrange.model import energy_use
from evrange.physics import wheel_work

# Documented in docs/method.md; recomputed here from the data.
EXPECTED = {
    "tesla-model3-rwd": (0.9356, 0.7739),
    "volvo-ex30-sm-er": (0.8470, 0.9062),
    "polestar-2-lr-sm": (0.8830, 0.8898),
    "vw-id4-pro": (0.8925, 0.8151),
}


def test_calibrated_model_reproduces_the_epa_measurements(study: Study) -> None:
    for vehicle in study.vehicles:
        powertrain = study.calibrations[vehicle.id].powertrain()
        setup = vehicle.epa_setup()
        for key in CALIBRATION_CYCLES:
            work = wheel_work(study.cycles[key].speed_ms, setup.road_load, setup.inertial_mass_kg)
            modelled = energy_use(work, powertrain).battery_wh_per_km
            assert modelled == pytest.approx(vehicle.epa.dc_wh_per_km(key), rel=1e-9)


def test_parameters_are_physical_and_as_documented(study: Study) -> None:
    for vehicle_id, (eta, regen) in EXPECTED.items():
        calibration = study.calibrations[vehicle_id]
        assert calibration.drive_efficiency == pytest.approx(eta, abs=5e-5)
        assert calibration.regen_coefficient == pytest.approx(regen, abs=5e-5)
        assert 0 < calibration.drive_efficiency < 1
        assert 0 <= calibration.regen_coefficient <= 1
        assert calibration.auxiliary_w == study.auxiliary_w


def test_regeneration_coefficient_is_an_effective_value(study: Study) -> None:
    """For two cars k exceeds eta, which no single component efficiency would allow: both are
    effective values of a two-parameter model (docs/method.md, section 3)."""
    above = {v for v, c in study.calibrations.items() if c.regen_coefficient > c.drive_efficiency}
    assert above == {"volvo-ex30-sm-er", "polestar-2-lr-sm"}


def test_higher_auxiliary_load_lowers_the_identified_losses(study: Study) -> None:
    vehicle = study.vehicle("vw-id4-pro")
    low = calibrate(vehicle, study.cycles, 144.0)
    high = calibrate(vehicle, study.cycles, 226.0)
    assert high.drive_efficiency > low.drive_efficiency
    assert high.regen_coefficient > low.regen_coefficient


def test_powertrain_adds_climate_power(study: Study) -> None:
    calibration = study.calibrations["tesla-model3-rwd"]
    assert calibration.powertrain(1000.0).auxiliary_w == calibration.auxiliary_w + 1000.0
    with pytest.raises(ValueError, match="negative"):
        calibration.powertrain(-1.0)


def test_negative_auxiliary_load_is_refused(study: Study) -> None:
    with pytest.raises(ValueError, match="negative"):
        calibrate(study.vehicles[0], study.cycles, -1.0)


def test_impossible_measurements_are_refused(study: Study) -> None:
    vehicle = study.vehicle("polestar-2-lr-sm")
    terms = cycle_terms(vehicle, study.cycles["hwfet"], study.auxiliary_w)
    # Below the work the wheels need, the car would have to be more than 100 % efficient.
    frugal = replace(
        vehicle,
        epa=replace(vehicle.epa, hwfet_wh_per_km=terms.positive_wh_per_km * 0.8),
    )
    with pytest.raises(CalibrationError, match="above 100 %"):
        calibrate(frugal, study.cycles, study.auxiliary_w)
    # A city value this low would need more energy back from braking than braking absorbs.
    greedy = replace(vehicle, epa=replace(vehicle.epa, udds_wh_per_km=40.0))
    with pytest.raises(CalibrationError, match="regeneration coefficient"):
        calibrate(greedy, study.cycles, study.auxiliary_w)


def test_identical_cycles_cannot_separate_the_unknowns(study: Study) -> None:
    cycles = dict(load_cycles())
    cycles["hwfet"] = replace(cycles["udds"], key="hwfet")
    vehicle = study.vehicle("tesla-model3-rwd")
    with pytest.raises(CalibrationError, match="do not separate"):
        calibrate(vehicle, cycles, study.auxiliary_w)
