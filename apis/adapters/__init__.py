"""Adapters package for external farm monitoring and management systems."""

from apis.adapters.bolus import MockCbtBolusAdapter
from apis.adapters.climate import MockBarnClimateAdapter
from apis.adapters.collar import MockCollarImuAdapter
from apis.adapters.herd import MockHerdManagementAdapter
from apis.adapters.location import MockUwbLocationAdapter
from apis.adapters.milking import MockMilkingParlorAdapter
from apis.adapters.pedometer import MockAnklePedometerAdapter
from apis.adapters.weather import MockWeatherStationAdapter

__all__ = [
    "MockMilkingParlorAdapter",
    "MockCbtBolusAdapter",
    "MockBarnClimateAdapter",
    "MockAnklePedometerAdapter",
    "MockUwbLocationAdapter",
    "MockCollarImuAdapter",
    "MockWeatherStationAdapter",
    "MockHerdManagementAdapter",
]
