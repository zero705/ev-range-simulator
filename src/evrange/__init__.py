"""Energy consumption and range of electric cars on standard drive cycles, from official data."""

from evrange.calibration import Calibration, CalibrationError, calibrate
from evrange.cycles import CYCLE_SPECS, DriveCycle, load_cycle, load_cycles
from evrange.model import BREAKDOWN, EnergyUse, Powertrain, energy_use
from evrange.physics import WheelWork, steady_work, wheel_work
from evrange.study import Conditions, Study, load_study
from evrange.vehicles import RoadLoad, Vehicle, load_vehicles

__version__ = "0.1.0"

__all__ = [
    "BREAKDOWN",
    "CYCLE_SPECS",
    "Calibration",
    "CalibrationError",
    "Conditions",
    "DriveCycle",
    "EnergyUse",
    "Powertrain",
    "RoadLoad",
    "Study",
    "Vehicle",
    "WheelWork",
    "__version__",
    "calibrate",
    "energy_use",
    "load_cycle",
    "load_cycles",
    "load_study",
    "load_vehicles",
    "steady_work",
    "wheel_work",
]
