"""Typed models shared by every provider adapter. Plain Python, no Home Assistant."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from math import asin, cos, radians, sin, sqrt
from typing import NewType

StopCode = NewType("StopCode", str)
StationCode = NewType("StationCode", str)

type JsonObject = Mapping[str, object]

_EARTH_RADIUS_M = 6_371_000
# A vehicle due up to this long ago may still be at the stop ("En la parada."
# reads 0 minutes); one due earlier has gone.
_DEPARTED_AFTER = timedelta(minutes=1)
_MINUTE = timedelta(minutes=1)


def _require_aware(*values: datetime | None) -> None:
    """Reject naive datetimes: everything handed to Home Assistant has a zone."""
    if any(value is not None and value.tzinfo is None for value in values):
        msg = "Datetime must be timezone-aware"
        raise ValueError(msg)


class Mode(StrEnum):
    """Kind of public transport."""

    TRAM = "tram"
    BUS = "bus"


@dataclass(frozen=True, slots=True)
class GeoPoint:
    """A WGS84 coordinate."""

    latitude: float
    longitude: float

    def distance_to(self, other: GeoPoint) -> float:
        """Return the great-circle distance to ``other`` in metres (haversine)."""
        lat1, lat2 = radians(self.latitude), radians(other.latitude)
        d_lat = lat2 - lat1
        d_lon = radians(other.longitude - self.longitude)
        h = sin(d_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(d_lon / 2) ** 2
        return 2 * _EARTH_RADIUS_M * asin(sqrt(h))


@dataclass(frozen=True, slots=True)
class Area:
    """A circle around a centre; no radius means the whole city."""

    centre: GeoPoint
    radius_m: float | None

    def contains(self, point: GeoPoint) -> bool:
        """Say whether ``point`` lies within the radius (always, with no radius)."""
        return self.radius_m is None or self.centre.distance_to(point) <= self.radius_m


@dataclass(frozen=True, slots=True)
class Stop:
    """A tram platform or bus stop."""

    mode: Mode
    code: StopCode
    name: str
    location: GeoPoint
    # None for an arrival-only tram platform, or for a bus stop.
    direction: str | None
    lines: tuple[str, ...]

    def search_terms(self) -> tuple[str, ...]:
        """Return the texts a user may type to find this stop."""
        direction = () if self.direction is None else (self.direction,)
        return (self.code, self.name, *direction, *self.lines)


@dataclass(frozen=True, slots=True)
class Arrival:
    """One vehicle expected at a stop."""

    line: str
    destination: str
    expected_at: datetime

    def __post_init__(self) -> None:
        """Reject a naive ``expected_at``."""
        _require_aware(self.expected_at)


@dataclass(frozen=True, slots=True)
class ArrivalBoard:
    """What one provider reported for one stop at one moment."""

    stop_code: StopCode
    arrivals: tuple[Arrival, ...]
    observed_at: datetime
    source: str
    notices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Reject a naive ``observed_at``."""
        _require_aware(self.observed_at)

    def upcoming(
        self, now: datetime, lines: frozenset[str] | None = None
    ) -> tuple[Arrival, ...]:
        """Return the arrivals not yet gone at ``now``, soonest first.

        A board can be minutes old (a bus stop's is kept while nobody answers),
        so the vehicles it lists may have left. With ``lines``, only theirs.
        """
        return tuple(
            sorted(
                (
                    arrival
                    for arrival in self.arrivals
                    if (lines is None or arrival.line in lines)
                    and now - arrival.expected_at <= _DEPARTED_AFTER
                ),
                key=lambda arrival: arrival.expected_at,
            )
        )

    def minutes_to(self, arrival: Arrival, now: datetime) -> int:
        """Return whole minutes to ``arrival`` as the source counts them, at ``now``.

        Every source counts whole minutes at ``observed_at`` ("4 minutos", MIN 4,
        "En la parada." 0). That number stands until a whole minute has passed,
        then each one takes one off, so right after a refresh it is the source's
        own and a kept board keeps counting down. Never negative.
        """
        counted = (arrival.expected_at - self.observed_at) // _MINUTE
        return max(0, counted - self._minutes_since(now))

    def minutes_change_at(self, now: datetime) -> datetime:
        """Return when ``minutes_to`` next drops: the next whole minute of the reading."""
        return self.observed_at + (self._minutes_since(now) + 1) * _MINUTE

    def _minutes_since(self, now: datetime) -> int:
        """Return the whole minutes since the source counted (none before it did)."""
        return max(timedelta(0), now - self.observed_at) // _MINUTE

    def is_usable_at(self, now: datetime, max_age: timedelta) -> bool:
        """Say whether the board is still younger than ``max_age`` at ``now``."""
        return now - self.observed_at < max_age


@dataclass(frozen=True, slots=True)
class BikeStation:
    """A Bizi docking station, as the provider that answered lists it."""

    code: StationCode
    name: str
    location: GeoPoint
    capacity: int | None
    address: str | None
    source: str

    def search_terms(self) -> tuple[str, ...]:
        """Return the texts a user may type to find this station."""
        address = () if self.address is None else (self.address,)
        return (self.code, self.name, *address)


@dataclass(frozen=True, slots=True)
class BikeAvailability:
    """Live bike and dock counts for one Bizi station."""

    code: StationCode
    bikes: int
    electric: int | None
    mechanical: int | None
    docks: int
    renting: bool
    returning: bool
    reported_at: datetime
    source: str

    def __post_init__(self) -> None:
        """Reject a naive ``reported_at``."""
        _require_aware(self.reported_at)


class RoadWorkCategory(StrEnum):
    """What kind of disruption a road work causes."""

    TRAFFIC_CLOSURE = "traffic_closure"
    WATER_CUT = "water_cut"
    MAJOR_DISRUPTION = "major_disruption"
    PUBLIC_TRANSPORT_DISRUPTION = "public_transport_disruption"
    MAINTENANCE = "maintenance"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class RoadWork:
    """A road work or street disruption."""

    id: str
    title: str
    street: str
    reason: str | None
    stretch: str | None
    detour: str | None
    starts: datetime | None
    ends: datetime | None
    category: RoadWorkCategory
    location: GeoPoint

    def __post_init__(self) -> None:
        """Reject naive ``starts`` or ``ends``."""
        _require_aware(self.starts, self.ends)


@dataclass(frozen=True, slots=True)
class DutyPharmacy:
    """A pharmacy on duty on a given day."""

    id: str
    name: str
    address: str
    phone: str | None
    hours: str
    sector: str | None
    location: GeoPoint
    day: date


class Pollutant(StrEnum):
    """Air pollutants reported by the city's stations."""

    NO = "no"
    NO2 = "no2"
    O3 = "o3"
    CO = "co"
    SO2 = "so2"
    PM10 = "pm10"
    PM25 = "pm25"
    H2S = "h2s"
    BENZENE = "benzene"


@dataclass(frozen=True, slots=True)
class AirStation:
    """An air quality measuring station."""

    id: str
    name: str
    location: GeoPoint


@dataclass(frozen=True, slots=True)
class AirReading:
    """One pollutant measurement at one station."""

    station_id: str
    pollutant: Pollutant
    value: float
    measured_at: datetime

    def __post_init__(self) -> None:
        """Reject a naive ``measured_at``."""
        _require_aware(self.measured_at)


@dataclass(frozen=True, slots=True)
class AirQualityReport:
    """Every station and the latest reading of each pollutant at each, read together."""

    stations: tuple[AirStation, ...]
    readings: tuple[AirReading, ...]


class PollenLevel(StrEnum):
    """Pollen concentration band, valued as the city publishes it."""

    NONE = "nulo"
    LOW = "bajo"
    MODERATE = "moderado"
    HIGH = "alto"
    VERY_HIGH = "muy_alto"


@dataclass(frozen=True, slots=True)
class PollenReading:
    """Pollen level of one plant on the day it was published."""

    plant_id: str
    plant_name: str
    level: PollenLevel | None
    published_on: date
