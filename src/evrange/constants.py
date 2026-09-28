"""Unit conversions and the regulatory definitions the model relies on.

The conversions are the exact factors of NIST Special Publication 811, Appendix B, and the
regulatory values those of the regulations named below. Both are quoted in
data/reference_values.json, where tools/verify_references.py checks each quote against the
fingerprinted document; tests/test_constants.py ties the numbers below to those quotes, so a
typo here fails the tests.
"""

from __future__ import annotations

# Exact conversions (NIST SP 811, Appendix B and its footnotes 22 and 23).
MILE_M = 1609.344
MPH_MS = 0.44704
KMH_MS = 1 / 3.6
LBF_N = 4.4482216152605
LB_KG = 0.45359237
J_PER_WH = 3600.0

# UN GTR No. 15, para. 3.2.9: reference atmospheric conditions for road load.
WLTP_PRESSURE_PA = 100_000.0
WLTP_TEMPERATURE_K = 293.0
WLTP_AIR_DENSITY = 1.189  # kg/m^3, dry air

# 40 CFR 1066.305: road load is specified "under reference conditions of 20 °C, 98.21 kPa".
EPA_PRESSURE_PA = 98_210.0
EPA_TEMPERATURE_K = 293.15

# UN GTR No. 15, para. 3.2.6: mass of the driver.
DRIVER_MASS_KG = 75.0

# UN GTR No. 15, Annex 4: the rotating mass "may be estimated to be three per cent of the mass
# in running order plus 25 kg". Regulation (EU) 2017/1151, Annex XXI, Sub-Annex 4, states the
# reading used here: "3 per cent of the sum of the mass in running order and 25 kg".
ROTATING_MASS_FRACTION = 0.03
ROTATING_MASS_OFFSET_KG = 25.0


def air_density(pressure_pa: float, temperature_k: float) -> float:
    """Dry-air density, kg/m^3, by the ideal-gas law anchored on the GTR 15 reference point.

    Density is proportional to pressure over temperature; scaling from the regulation's own
    reference (1.189 kg/m^3 at 100 kPa and 293 K) avoids importing a gas constant from
    elsewhere.
    """
    if pressure_pa <= 0 or temperature_k <= 0:
        raise ValueError("pressure and temperature must be positive")
    return (
        WLTP_AIR_DENSITY * (pressure_pa / WLTP_PRESSURE_PA) * (WLTP_TEMPERATURE_K / temperature_k)
    )


EPA_AIR_DENSITY = air_density(EPA_PRESSURE_PA, EPA_TEMPERATURE_K)


def rotating_mass_kg(mass_in_running_order_kg: float) -> float:
    """Equivalent mass of the parts that turn with the wheels (GTR 15 estimate)."""
    return ROTATING_MASS_FRACTION * (mass_in_running_order_kg + ROTATING_MASS_OFFSET_KG)
