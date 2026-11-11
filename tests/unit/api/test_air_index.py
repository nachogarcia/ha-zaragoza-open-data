"""Behaviour of the European air quality index."""

from datetime import UTC, datetime

import pytest

from custom_components.zaragoza_open_data.api.air_index import (
    BAND_COLOURS,
    NO_DATA_COLOUR,
    AirIndex,
    AirQualityBand,
    air_index,
)
from custom_components.zaragoza_open_data.api.models import AirReading, Pollutant

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def reading(pollutant: Pollutant, value: float, station: str = "1") -> AirReading:
    """Build a reading at a fixed time."""
    return AirReading(station, pollutant, value, NOW)


@pytest.mark.parametrize(
    ("value", "band"),
    [
        (10, AirQualityBand.GOOD),
        (10.1, AirQualityBand.FAIR),
        (25, AirQualityBand.FAIR),
        (60, AirQualityBand.MODERATE),
        (100, AirQualityBand.POOR),
        (150, AirQualityBand.VERY_POOR),
        (150.1, AirQualityBand.EXTREMELY_POOR),
    ],
)
def test_each_band_boundary_is_inclusive(value: float, band: AirQualityBand) -> None:
    """A value on a limit stays in the lower band."""
    assert air_index([reading(Pollutant.NO2, value)]).band is band


@pytest.mark.parametrize(
    ("pollutant", "limits"),
    [
        (Pollutant.PM25, (5, 15, 50, 90, 140)),
        (Pollutant.PM10, (15, 45, 120, 195, 270)),
        (Pollutant.NO2, (10, 25, 60, 100, 150)),
        (Pollutant.O3, (60, 100, 120, 160, 180)),
        (Pollutant.SO2, (20, 40, 125, 190, 275)),
    ],
)
def test_every_indexed_pollutant_uses_its_own_limits(
    pollutant: Pollutant, limits: tuple[int, ...]
) -> None:
    """Each pollutant's limits map onto the bands in order."""
    bands = list(AirQualityBand)
    for band, limit in zip(bands, limits, strict=False):
        assert air_index([reading(pollutant, limit)]).band is band
    assert air_index([reading(pollutant, limits[-1] + 1)]).band is bands[-1]


def test_worst_pollutant_sets_the_band_and_is_reported() -> None:
    """The worst pollutant decides the band and is named."""
    result = air_index([reading(Pollutant.NO2, 8), reading(Pollutant.PM10, 50)])

    assert result.band is AirQualityBand.MODERATE
    assert result.pollutant is Pollutant.PM10


def test_two_readings_of_one_pollutant_count_the_worst() -> None:
    """With two readings of a pollutant, the worse one counts."""
    result = air_index(
        [reading(Pollutant.NO2, 8, "1"), reading(Pollutant.NO2, 70, "2")]
    )

    assert result.band is AirQualityBand.POOR
    assert result.pollutant is Pollutant.NO2


def test_complete_needs_no2_and_particulates() -> None:
    """Complete means NO2 plus PM2.5 or PM10."""
    no2 = reading(Pollutant.NO2, 8)

    assert air_index([no2, reading(Pollutant.PM25, 3)]).complete
    assert air_index([no2, reading(Pollutant.PM10, 3)]).complete
    assert not air_index([no2]).complete
    assert not air_index([reading(Pollutant.PM10, 3)]).complete
    assert not air_index([no2, reading(Pollutant.O3, 3)]).complete


def test_ignores_pollutants_outside_the_index() -> None:
    """CO, NO, H2S and benzene never affect the index."""
    readings = [
        reading(p, 9999)
        for p in (Pollutant.CO, Pollutant.NO, Pollutant.H2S, Pollutant.BENZENE)
    ]

    assert air_index(readings) == AirIndex(None, None, False)


def test_no_readings_gives_unknown() -> None:
    """Without readings the index is unknown."""
    assert air_index([]) == AirIndex(None, None, False)


def test_every_band_has_a_colour_and_no_data_is_grey() -> None:
    """Each band has its colour; no data is grey."""
    assert set(BAND_COLOURS) == set(AirQualityBand)
    assert BAND_COLOURS[AirQualityBand.GOOD] == "#50F0E6"
    assert BAND_COLOURS[AirQualityBand.EXTREMELY_POOR] == "#7D2181"
    assert NO_DATA_COLOUR == "#6F6F6F"
