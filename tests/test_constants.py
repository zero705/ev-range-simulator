"""The constants are exact where they should be and match the quoted regulations."""

from __future__ import annotations

import math
import re

import pytest

from evrange import constants as c
from evrange.datafiles import reference_items

MINUS_SIGN = chr(0x2212)  # NIST SP 811 prints negative exponents with it, not with a hyphen


def _nist(item: str) -> float:
    """A value quoted from NIST SP 811, such as '4.535 923 7 E -01' or '9.806 65 m/s2'."""
    value = next(i for i in reference_items("unit_conversions") if i["item"] == item)["value"]
    number = str(value).removesuffix(" m/s2").replace(" ", "").replace(MINUS_SIGN, "-")
    return float(number)


def test_unit_conversions_are_the_exact_nist_factors() -> None:
    assert _nist("mile") == c.MILE_M
    assert _nist("mile_per_hour") == c.MPH_MS
    assert _nist("pound") == c.LB_KG
    assert _nist("pound_force") == c.LBF_N
    assert math.isclose(c.LBF_N, c.LB_KG * _nist("standard_gravity"), rel_tol=1e-15)
    assert math.isclose(c.MPH_MS, c.MILE_M / 3600, rel_tol=1e-15)
    assert math.isclose(c.KMH_MS * 3.6, 1.0, rel_tol=1e-15)
    assert c.J_PER_WH == 3600.0


def test_air_density_reproduces_the_regulation_reference_points() -> None:
    assert c.air_density(c.WLTP_PRESSURE_PA, c.WLTP_TEMPERATURE_K) == c.WLTP_AIR_DENSITY
    # 40 CFR 1066.305 conditions (98.21 kPa, 20 C); the ideal-gas value is 1.1671 kg/m^3.
    assert round(c.EPA_AIR_DENSITY, 4) == 1.1671


@pytest.mark.parametrize(("pressure", "temperature"), [(0.0, 293.0), (100e3, 0.0), (-1.0, 1.0)])
def test_air_density_rejects_impossible_states(pressure: float, temperature: float) -> None:
    with pytest.raises(ValueError, match="positive"):
        c.air_density(pressure, temperature)


def test_rotating_mass_is_three_percent_of_the_sum_of_mass_and_25_kg() -> None:
    assert c.rotating_mass_kg(1836.0) == pytest.approx(0.03 * (1836.0 + 25.0))


def _quoted(group: str, item: str) -> str:
    return str(next(i for i in reference_items(group) if i["item"] == item)["value"])


def _number(value: str) -> float:
    """The number a quoted value starts with; the GTR writes the decimal separator as a comma."""
    return float(value.split(maxsplit=1)[0].replace(",", "."))


def test_constants_match_the_verified_regulation_quotes() -> None:
    wltp, epa = "wltp_definitions", "epa_definitions"
    assert _number(_quoted(wltp, "reference_air_density")) == c.WLTP_AIR_DENSITY
    assert _quoted(wltp, "reference_pressure").endswith(" kPa")
    assert math.isclose(_number(_quoted(wltp, "reference_pressure")) * 1e3, c.WLTP_PRESSURE_PA)
    assert _quoted(wltp, "reference_temperature").endswith(" K")
    assert _number(_quoted(wltp, "reference_temperature")) == c.WLTP_TEMPERATURE_K
    assert _number(_quoted(wltp, "driver_mass")) == c.DRIVER_MASS_KG
    assert _quoted(epa, "road_load_reference_pressure").endswith(" kPa")
    assert math.isclose(
        _number(_quoted(epa, "road_load_reference_pressure")) * 1e3, c.EPA_PRESSURE_PA
    )
    assert _quoted(epa, "road_load_reference_temperature").endswith(" °C")
    assert math.isclose(
        _number(_quoted(epa, "road_load_reference_temperature")) + 273.15, c.EPA_TEMPERATURE_K
    )


def test_rotating_mass_follows_the_verified_rule() -> None:
    # The GTR wording, "three per cent of the mass in running order plus 25 kg", can be read
    # two ways; the EU text of the same rule states the reading the model uses.
    gtr = _quoted("wltp_definitions", "rotating_mass_estimate")
    assert gtr == "three per cent of the mass in running order plus 25 kg"
    eu = re.fullmatch(
        r"(\d+) per cent of the sum of the mass in running order and (\d+) kg",
        _quoted("wltp_definitions", "rotating_mass_estimate_eu"),
    )
    assert eu is not None
    assert float(eu.group(1)) / 100 == c.ROTATING_MASS_FRACTION
    assert float(eu.group(2)) == c.ROTATING_MASS_OFFSET_KG
