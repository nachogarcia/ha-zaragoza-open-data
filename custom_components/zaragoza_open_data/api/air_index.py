"""The European Air Quality Index (EEA, in force since 2025-07-04), from 1-hour readings."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from .models import AirReading, Pollutant


class AirQualityBand(StrEnum):
    """Index bands, best to worst."""

    GOOD = "good"
    FAIR = "fair"
    MODERATE = "moderate"
    POOR = "poor"
    VERY_POOR = "very_poor"
    EXTREMELY_POOR = "extremely_poor"


BAND_COLOURS: Mapping[AirQualityBand, str] = MappingProxyType(
    {
        AirQualityBand.GOOD: "#50F0E6",
        AirQualityBand.FAIR: "#50CCAA",
        AirQualityBand.MODERATE: "#F0E641",
        AirQualityBand.POOR: "#FF5050",
        AirQualityBand.VERY_POOR: "#960032",
        AirQualityBand.EXTREMELY_POOR: "#7D2181",
    }
)
NO_DATA_COLOUR = "#6F6F6F"

# Inclusive upper limits (µg/m³, 1-hour) of GOOD..VERY_POOR; above the last is
# EXTREMELY_POOR. The only place the numbers appear.
_UPPER_LIMITS: Mapping[Pollutant, tuple[float, float, float, float, float]] = (
    MappingProxyType(
        {
            Pollutant.PM25: (5, 15, 50, 90, 140),
            Pollutant.PM10: (15, 45, 120, 195, 270),
            Pollutant.NO2: (10, 25, 60, 100, 150),
            Pollutant.O3: (60, 100, 120, 160, 180),
            Pollutant.SO2: (20, 40, 125, 190, 275),
        }
    )
)
_BANDS = tuple(AirQualityBand)


@dataclass(frozen=True, slots=True)
class AirIndex:
    """The overall band, the pollutant that set it, and whether the data suffices."""

    band: AirQualityBand | None
    pollutant: Pollutant | None
    complete: bool


def _band_of(pollutant: Pollutant, value: float) -> AirQualityBand:
    for band, limit in zip(_BANDS, _UPPER_LIMITS[pollutant], strict=False):
        if value <= limit:
            return band
    return AirQualityBand.EXTREMELY_POOR


def air_index(readings: Iterable[AirReading]) -> AirIndex:
    """Return the worst band among the indexed pollutants in ``readings``."""
    worst: tuple[int, Pollutant] | None = None
    present: set[Pollutant] = set()
    for item in readings:
        if item.pollutant not in _UPPER_LIMITS:
            continue
        present.add(item.pollutant)
        rank = _BANDS.index(_band_of(item.pollutant, item.value))
        # Strictly worse only, so the first pollutant wins a tie.
        if worst is None or rank > worst[0]:
            worst = (rank, item.pollutant)
    if worst is None:
        return AirIndex(None, None, False)
    complete = Pollutant.NO2 in present and bool(
        present & {Pollutant.PM25, Pollutant.PM10}
    )
    return AirIndex(_BANDS[worst[0]], worst[1], complete)
