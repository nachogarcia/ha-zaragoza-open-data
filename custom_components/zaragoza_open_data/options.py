"""What the user configured: the entry's options and each stop's subentry.

Everything else reads configuration through these typed objects, never through
``entry.options`` or ``subentry.data`` directly.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
import math
from typing import TypedDict

from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import UnitOfTime

from .api.models import RoadWorkCategory, StationCode, StopCode
from .const import (
    CONF_AIR_STATION,
    CONF_KINDS,
    CONF_PHARMACIES_CENTRE,
    CONF_PHARMACIES_RADIUS_KM,
    CONF_REFRESH,
    CONF_ROAD_WORKS_CATEGORIES,
    CONF_ROAD_WORKS_CENTRE,
    CONF_ROAD_WORKS_RADIUS_KM,
    DEFAULT_CENTRE,
    DEFAULT_PHARMACIES_RADIUS_KM,
    DEFAULT_ROAD_WORKS_RADIUS_KM,
    SUBENTRY_BIZI_STATION,
    SUBENTRY_BUS_STOP,
    SUBENTRY_TRAM_STOP,
    Kind,
    StopKind,
)

_UNIT_LENGTH = {
    UnitOfTime.SECONDS: timedelta(seconds=1),
    UnitOfTime.MINUTES: timedelta(minutes=1),
    UnitOfTime.HOURS: timedelta(hours=1),
}


def _number(value: object, default: float) -> float:
    """Return ``value`` as a float, or ``default`` if it is not a finite number."""
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
    ):
        return default
    return float(value)


def _section(options: Mapping[str, object]) -> Mapping[str, object]:
    """Return the stored refresh section, empty if there is none."""
    section = options.get(CONF_REFRESH)
    return section if isinstance(section, Mapping) else {}


def _text(value: object, default: str) -> str:
    """Return ``value`` if it is text, otherwise ``default``."""
    return value if isinstance(value, str) else default


def _members[E: StrEnum](enum: type[E], value: object) -> frozenset[E]:
    """Return the members named in a stored list, ignoring unknown names.

    No list at all means every member, which is the default for kinds and categories.
    """
    if not isinstance(value, list | tuple):
        return frozenset(enum)
    known = {member.value: member for member in enum}
    return frozenset(
        known[item] for item in value if isinstance(item, str) and item in known
    )


@dataclass(frozen=True, slots=True)
class RefreshSetting:
    """One refresh interval as stored and shown: its key, unit, floor and ceiling.

    The floor is also the default: a source can be asked less often, never more.
    """

    key: str
    unit: UnitOfTime
    floor: int
    ceiling: int

    def read(self, section: Mapping[str, object]) -> timedelta:
        """Return the stored interval, held between the floor and the ceiling.

        Missing means the default. A value outside the range (only possible by
        editing the stored options) reads as the nearest limit.
        """
        count = _number(section.get(self.key), self.floor)
        return min(max(count, self.floor), self.ceiling) * _UNIT_LENGTH[self.unit]

    def below_floor(self, section: Mapping[str, object]) -> bool:
        """Say whether ``section`` asks for this source more often than the floor."""
        return _number(section.get(self.key), self.floor) < self.floor

    def count(self, interval: timedelta) -> int:
        """Return ``interval`` in whole units, as stored."""
        return interval // _UNIT_LENGTH[self.unit]


# Ceilings: once a day for the live sources, once a week for pollen and pharmacies.
# Beyond that the data would be useless, and a huge number would overflow a timedelta.
TRAM_REFRESH = RefreshSetting("tram_s", UnitOfTime.SECONDS, 60, 86_400)
BUS_REFRESH = RefreshSetting("bus_s", UnitOfTime.SECONDS, 60, 86_400)
BIKE_REFRESH = RefreshSetting("bike_s", UnitOfTime.SECONDS, 120, 86_400)
ROAD_WORKS_REFRESH = RefreshSetting("road_works_min", UnitOfTime.MINUTES, 30, 1_440)
AIR_QUALITY_REFRESH = RefreshSetting("air_quality_min", UnitOfTime.MINUTES, 30, 1_440)
POLLEN_REFRESH = RefreshSetting("pollen_h", UnitOfTime.HOURS, 6, 168)
PHARMACIES_REFRESH = RefreshSetting("pharmacies_h", UnitOfTime.HOURS, 6, 168)
# In the order the options form shows them.
REFRESH_SETTINGS = (
    TRAM_REFRESH,
    BUS_REFRESH,
    BIKE_REFRESH,
    ROAD_WORKS_REFRESH,
    AIR_QUALITY_REFRESH,
    POLLEN_REFRESH,
    PHARMACIES_REFRESH,
)


def refresh_below_minimum(options: Mapping[str, object]) -> bool:
    """Say whether submitted options ask any source more often than its floor.

    Checked on the raw values: once read, an interval is never below its floor.
    """
    section = _section(options)
    return any(setting.below_floor(section) for setting in REFRESH_SETTINGS)


@dataclass(frozen=True, slots=True)
class RefreshOptions:
    """How often each source is asked."""

    tram: timedelta
    bus: timedelta
    bizi: timedelta
    road_works: timedelta
    air_quality: timedelta
    pollen: timedelta
    pharmacies: timedelta

    @classmethod
    def from_section(cls, section: Mapping[str, object]) -> RefreshOptions:
        """Read the stored refresh section; a missing interval takes its default."""
        return cls(
            tram=TRAM_REFRESH.read(section),
            bus=BUS_REFRESH.read(section),
            bizi=BIKE_REFRESH.read(section),
            road_works=ROAD_WORKS_REFRESH.read(section),
            air_quality=AIR_QUALITY_REFRESH.read(section),
            pollen=POLLEN_REFRESH.read(section),
            pharmacies=PHARMACIES_REFRESH.read(section),
        )

    def to_section(self) -> dict[str, int]:
        """Return the refresh section as stored."""
        return {setting.key: setting.count(value) for setting, value in self._pairs()}

    def _pairs(self) -> tuple[tuple[RefreshSetting, timedelta], ...]:
        return (
            (TRAM_REFRESH, self.tram),
            (BUS_REFRESH, self.bus),
            (BIKE_REFRESH, self.bizi),
            (ROAD_WORKS_REFRESH, self.road_works),
            (AIR_QUALITY_REFRESH, self.air_quality),
            (POLLEN_REFRESH, self.pollen),
            (PHARMACIES_REFRESH, self.pharmacies),
        )


@dataclass(frozen=True, slots=True)
class MapLayerOptions:
    """Which items a map layer shows: those within ``radius_km`` of a zone.

    A radius of 0 means the whole city.
    """

    radius_km: float
    centre_zone: str


@dataclass(frozen=True, slots=True)
class ZodOptions:
    """Everything the options form sets."""

    kinds: frozenset[Kind]
    road_works: MapLayerOptions
    pharmacies: MapLayerOptions
    road_work_categories: frozenset[RoadWorkCategory]
    # None means the station nearest to home.
    air_station: str | None
    refresh: RefreshOptions

    @classmethod
    def from_mapping(cls, options: Mapping[str, object]) -> ZodOptions:
        """Read stored options; a missing or unreadable value takes its default."""
        air_station = options.get(CONF_AIR_STATION)
        return cls(
            kinds=_members(Kind, options.get(CONF_KINDS)),
            road_works=MapLayerOptions(
                radius_km=_number(
                    options.get(CONF_ROAD_WORKS_RADIUS_KM), DEFAULT_ROAD_WORKS_RADIUS_KM
                ),
                centre_zone=_text(options.get(CONF_ROAD_WORKS_CENTRE), DEFAULT_CENTRE),
            ),
            pharmacies=MapLayerOptions(
                radius_km=_number(
                    options.get(CONF_PHARMACIES_RADIUS_KM), DEFAULT_PHARMACIES_RADIUS_KM
                ),
                centre_zone=_text(options.get(CONF_PHARMACIES_CENTRE), DEFAULT_CENTRE),
            ),
            road_work_categories=_members(
                RoadWorkCategory, options.get(CONF_ROAD_WORKS_CATEGORIES)
            ),
            air_station=air_station
            if isinstance(air_station, str) and air_station
            else None,
            refresh=RefreshOptions.from_section(_section(options)),
        )

    def to_mapping(self) -> dict[str, object]:
        """Return the options as stored in the entry."""
        return {
            CONF_KINDS: [kind.value for kind in Kind if kind in self.kinds],
            CONF_ROAD_WORKS_RADIUS_KM: self.road_works.radius_km,
            CONF_ROAD_WORKS_CENTRE: self.road_works.centre_zone,
            CONF_ROAD_WORKS_CATEGORIES: [
                category.value
                for category in RoadWorkCategory
                if category in self.road_work_categories
            ],
            CONF_PHARMACIES_RADIUS_KM: self.pharmacies.radius_km,
            CONF_PHARMACIES_CENTRE: self.pharmacies.centre_zone,
            CONF_AIR_STATION: self.air_station or "",
            CONF_REFRESH: self.refresh.to_section(),
        }


class TramStopData(TypedDict):
    """A tram platform the user added."""

    code: StopCode


class BusStopData(TypedDict):
    """A bus stop the user added, and the lines to show (empty: every line)."""

    code: StopCode
    lines: list[str]


class BiziStationData(TypedDict):
    """A Bizi station the user added."""

    code: StationCode


def _code(subentry: ConfigSubentry) -> str:
    """Return the subentry's public code, or raise if it has none."""
    code = subentry.data.get("code")
    if not isinstance(code, str) or not code:
        raise ValueError("Stop subentry has no code")
    return code


def read_tram_stop(subentry: ConfigSubentry) -> TramStopData:
    """Read a tram stop subentry; raise ``ValueError`` if its data is malformed."""
    return TramStopData(code=StopCode(_code(subentry)))


def read_bus_stop(subentry: ConfigSubentry) -> BusStopData:
    """Read a bus stop subentry; raise ``ValueError`` if its data is malformed."""
    code = StopCode(_code(subentry))
    lines = subentry.data.get("lines")
    if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
        raise ValueError("Bus stop subentry has no list of lines")
    return BusStopData(code=code, lines=list(lines))


def read_bizi_station(subentry: ConfigSubentry) -> BiziStationData:
    """Read a Bizi station subentry; raise ``ValueError`` if its data is malformed."""
    return BiziStationData(code=StationCode(_code(subentry)))


def read_stop(subentry: ConfigSubentry) -> tuple[StopKind, str] | None:
    """Read any stop or station subentry as its kind and code; None for any other.

    Raises ``ValueError`` if its data is malformed.
    """
    if subentry.subentry_type == SUBENTRY_TRAM_STOP:
        return Kind.TRAM, read_tram_stop(subentry)["code"]
    if subentry.subentry_type == SUBENTRY_BUS_STOP:
        return Kind.BUS, read_bus_stop(subentry)["code"]
    if subentry.subentry_type == SUBENTRY_BIZI_STATION:
        return Kind.BIZI, read_bizi_station(subentry)["code"]
    return None
