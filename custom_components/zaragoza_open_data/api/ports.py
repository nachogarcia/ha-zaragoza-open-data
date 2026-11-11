"""What each kind of data source must offer; adapters satisfy these structurally."""

from collections.abc import Mapping
from typing import Protocol

from .models import (
    AirQualityReport,
    AirStation,
    ArrivalBoard,
    BikeAvailability,
    BikeStation,
    DutyPharmacy,
    PollenReading,
    RoadWork,
    StationCode,
    Stop,
    StopCode,
)

# Every method raises ``SourceUnavailableError`` on a transport or format failure.


class TramSource(Protocol):
    """Tram stops and the arrivals of every platform."""

    @property
    def source_name(self) -> str:
        """Provider name, copied into the boards it returns."""
        ...

    async def stops(self) -> tuple[Stop, ...]:
        """Return every tram platform."""
        ...

    async def boards(self) -> Mapping[StopCode, ArrivalBoard]:
        """Return the board of every platform."""
        ...


class BusStopCatalog(Protocol):
    """The list of bus stops."""

    @property
    def source_name(self) -> str:
        """Provider name."""
        ...

    async def stops(self) -> tuple[Stop, ...]:
        """Return every bus stop, each number once."""
        ...


class BusArrivalsSource(Protocol):
    """Bus arrivals, one stop at a time."""

    @property
    def source_name(self) -> str:
        """Provider name, copied into the boards it returns."""
        ...

    async def board(self, code: StopCode) -> ArrivalBoard:
        """Return the board of one stop."""
        ...


class BikeSource(Protocol):
    """Bizi stations and their live availability."""

    @property
    def source_name(self) -> str:
        """Provider name, copied into the availability it returns."""
        ...

    async def stations(self) -> tuple[BikeStation, ...]:
        """Return every station."""
        ...

    async def availability(self) -> Mapping[StationCode, BikeAvailability]:
        """Return the availability of every station."""
        ...


class RoadWorksSource(Protocol):
    """Current road works."""

    @property
    def source_name(self) -> str:
        """Provider name."""
        ...

    async def road_works(self) -> tuple[RoadWork, ...]:
        """Return the road works in force."""
        ...


class PharmacySource(Protocol):
    """Pharmacies on duty."""

    @property
    def source_name(self) -> str:
        """Provider name."""
        ...

    async def on_duty(self) -> tuple[DutyPharmacy, ...]:
        """Return today's duty pharmacies."""
        ...


class AirQualitySource(Protocol):
    """Air quality stations and their readings."""

    @property
    def source_name(self) -> str:
        """Provider name."""
        ...

    async def stations(self) -> tuple[AirStation, ...]:
        """Return every station."""
        ...

    async def report(self) -> AirQualityReport:
        """Return every station and the latest reading of each pollutant at each."""
        ...


class PollenSource(Protocol):
    """Pollen levels."""

    @property
    def source_name(self) -> str:
        """Provider name."""
        ...

    async def readings(self) -> tuple[PollenReading, ...]:
        """Return the latest level of each plant."""
        ...
