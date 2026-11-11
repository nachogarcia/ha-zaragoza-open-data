"""What a loaded entry keeps while it runs, and what outlives its reloads."""

import asyncio
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Literal, overload

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
from homeassistant.util.hass_dict import HassKey

from .api.errors import SourceUnavailableError
from .api.models import AirStation, BikeStation, Stop
from .api.providers import BIKE_OPERATOR, Providers, build_providers
from .const import DOMAIN, USER_AGENT, Kind, StopKind
from .coordinator import (
    AirQualityCoordinator,
    BikeCoordinator,
    BusCoordinator,
    PharmaciesCoordinator,
    PollenCoordinator,
    RoadWorksCoordinator,
    TramCoordinator,
)
from .options import ZodOptions

_LOGGER = logging.getLogger(__name__)

# A list that couldn't place the configured stops is asked again after this:
# the bus list alone is three requests.
PLACE_RETRY = timedelta(hours=1)

# Stops and stations barely change: one list a day keeps pickers and actions quick
# and spares the sources (the bus list alone is three requests). The air quality
# stations come with every refresh's readings; the options form shows the latest.
CATALOGUE_TTL = timedelta(hours=24)
# When the day's fetch fails, the last good list keeps serving and the source is
# asked again this long after: a city that is down isn't asked at every use. A
# Bizi list from the city, standing in for the operator's, is kept only this long
# too, and so are the places taken from it.
CATALOGUE_RETRY = timedelta(minutes=10)


def providers_for(hass: HomeAssistant) -> Providers:
    """Wire the providers to Home Assistant's shared session.

    The only place on the Home Assistant side that builds providers.
    """
    return build_providers(async_get_clientsession(hass), USER_AGENT)


def _whole_day(_items: object) -> timedelta:
    """Keep any list for the day."""
    return CATALOGUE_TTL


def _from_operator(stations: Collection[BikeStation]) -> bool:
    """Say whether a Bizi list is the operator's, which lists every station.

    The city's list, the fallback, holds a varying subset of them.
    """
    return all(station.source == BIKE_OPERATOR for station in stations)


def _bizi_kept_for(stations: tuple[BikeStation, ...]) -> timedelta:
    """Keep the operator's list for the day, the city's stand-in until the retry."""
    return CATALOGUE_TTL if _from_operator(stations) else CATALOGUE_RETRY


class _Memo[T]:
    """One list, fetched at most once per ``kept_for`` of the list it has.

    Callers asking at the same time wait for a single fetch. A failed fetch
    keeps the last good list, tried again after ``CATALOGUE_RETRY``. With no
    good list yet the failure reaches the caller, who may ask again at once:
    a picker's retry is submitting its form.

    So two good lists are always at least ``kept_for`` the first apart: a day,
    unless ``kept_for`` says the list is only standing in.
    """

    def __init__(self, kept_for: Callable[[T], timedelta] = _whole_day) -> None:
        self._kept_for = kept_for
        self._lock = asyncio.Lock()
        # The last good list, and when to fetch it again.
        self._cached: tuple[datetime, T] | None = None
        # When the last good list came.
        self._fetched_at: datetime | None = None

    async def get(self, fetch: Callable[[], Awaitable[T]]) -> T:
        """Return the list, fetching it with ``fetch`` when missing or due.

        Raises ``SourceUnavailableError`` only while there is no good list.
        """
        async with self._lock:
            now = dt_util.utcnow()
            if self._cached is not None and now < self._cached[0]:
                return self._cached[1]
            try:
                items = await fetch()
            except SourceUnavailableError as err:
                if self._cached is None:
                    raise
                _LOGGER.debug(
                    "No new list from %s: keeping the last one for now", err.source
                )
                self._cached = (now + CATALOGUE_RETRY, self._cached[1])
                return self._cached[1]
            self._cached = (now + self._kept_for(items), items)
            self._fetched_at = now
            return items

    def offer(self, items: T) -> None:
        """Take ``items``, fetched along with something else, as a new good list."""
        now = dt_util.utcnow()
        self._cached = (now + self._kept_for(items), items)
        self._fetched_at = now

    @property
    def due_at(self) -> datetime | None:
        """Return when the list is fetched again; None while there is no list."""
        return None if self._cached is None else self._cached[0]

    @property
    def has_list(self) -> bool:
        """Say whether a good list ever came."""
        return self._cached is not None

    def fresh_since(self) -> datetime | None:
        """Return when the list served came, if under ``CATALOGUE_TTL`` ago.

        None while there is no list, and for a list kept after failed fetches:
        that one may be days old.
        """
        if (
            self._fetched_at is None
            or dt_util.utcnow() - self._fetched_at >= CATALOGUE_TTL
        ):
            return None
        return self._fetched_at


class StopCatalogues:
    """The tram, bus, Bizi and air quality station lists, each with its own lock.

    Kept in ``hass.data`` because adding or removing a stop reloads the entry.
    """

    def __init__(self) -> None:
        """Start with nothing fetched."""
        self.tram: _Memo[tuple[Stop, ...]] = _Memo()
        self.bus: _Memo[tuple[Stop, ...]] = _Memo()
        self.bizi: _Memo[tuple[BikeStation, ...]] = _Memo(_bizi_kept_for)
        self.air: _Memo[tuple[AirStation, ...]] = _Memo()


_CATALOGUES: HassKey[StopCatalogues] = HassKey(f"{DOMAIN}_catalogues")


def catalogues_for(hass: HomeAssistant) -> StopCatalogues:
    """Return the integration's stop lists, created on first use."""
    catalogues = hass.data.get(_CATALOGUES)
    if catalogues is None:
        catalogues = hass.data[_CATALOGUES] = StopCatalogues()
    return catalogues


async def air_stations(
    catalogues: StopCatalogues, providers: Providers
) -> tuple[AirStation, ...]:
    """Return every air quality station from the day's list; never an empty list.

    While the day's fetch fails, the last good list stands in, however old.
    An empty list counts as a failed fetch, so it is never kept. Raises
    ``SourceUnavailableError`` only while no good list ever came.
    """
    source = providers.air_quality

    async def fetch() -> tuple[AirStation, ...]:
        stations = await source.stations()
        if not stations:
            raise SourceUnavailableError(source.source_name)
        return stations

    return await catalogues.air.get(fetch)


def _settled(place: Stop | BikeStation | None) -> bool:
    """Say whether a place is for good: any stop's, a Bizi station's from the operator."""
    if isinstance(place, BikeStation):
        return place.source == BIKE_OPERATOR
    return place is not None


@dataclass(frozen=True, slots=True)
class Listing:
    """The codes in a fresh stop or station list, and when that list came."""

    fetched_at: datetime
    codes: frozenset[str]


@dataclass
class ZodRuntime:
    """The providers, the options in force and one coordinator per enabled kind."""

    providers: Providers
    options: ZodOptions
    catalogues: StopCatalogues
    # The hub device, which every stop's device hangs from.
    hub_device_id: str
    # One coordinator per kind, None while that kind is disabled.
    tram: TramCoordinator | None = None
    bus: BusCoordinator | None = None
    bizi: BikeCoordinator | None = None
    road_works: RoadWorksCoordinator | None = None
    pharmacies: PharmaciesCoordinator | None = None
    air_quality: AirQualityCoordinator | None = None
    pollen: PollenCoordinator | None = None
    # The configured stops and stations as their lists describe them (where they
    # are, a station's docks), by device identifier such as ``bus_688``.
    places: dict[str, Stop | BikeStation] = field(default_factory=dict)
    # When each kind's list may be asked again for stops it couldn't place.
    _place_after: dict[Kind, datetime] = field(default_factory=dict, init=False)
    _placing: set[Kind] = field(default_factory=set, init=False)

    def unplaced(self, kind: Kind, codes: Collection[str]) -> frozenset[str]:
        """Return those of ``codes`` whose stop of ``kind`` has no place yet.

        A Bizi station placed from the city's stand-in list counts as unplaced:
        that list has no docks, and the operator's place replaces it once back.
        """
        return frozenset(
            code for code in codes if not _settled(self.places.get(f"{kind}_{code}"))
        )

    async def async_place(self, kind: StopKind, codes: Collection[str]) -> bool:
        """Look the stops of ``kind`` without a place up in the day's list.

        Return whether any was placed. When the list can't be fetched, or lacks
        some of them, it isn't asked again for ``PLACE_RETRY``; when it is the
        city's Bizi stand-in, until that list is due again.
        """
        missing = self.unplaced(kind, codes)
        now = dt_util.utcnow()
        if (
            not missing
            or kind in self._placing
            or now < self._place_after.get(kind, now)
        ):
            return False
        self._placing.add(kind)
        try:
            items = await self.stops_for(kind)
        except SourceUnavailableError:
            _LOGGER.debug("No %s list to place the configured stops on", kind)
            self._place_after[kind] = now + PLACE_RETRY
            return False
        finally:
            self._placing.discard(kind)
        found = [item for item in items if item.code in missing]
        for item in found:
            self.places[f"{kind}_{item.code}"] = item
        if not all(_settled(item) for item in items):
            # The city's Bizi list, standing in: the operator is asked when that
            # list is due, which may be sooner than a retry from now.
            self._place_after[kind] = (
                self.catalogues.bizi.due_at or now + CATALOGUE_RETRY
            )
        elif len(found) < len(missing):
            self._place_after[kind] = now + PLACE_RETRY
        return bool(found)

    @overload
    async def stops_for(
        self, kind: Literal[Kind.TRAM, Kind.BUS]
    ) -> tuple[Stop, ...]: ...

    @overload
    async def stops_for(self, kind: Literal[Kind.BIZI]) -> tuple[BikeStation, ...]: ...

    async def stops_for(
        self, kind: StopKind
    ) -> tuple[Stop, ...] | tuple[BikeStation, ...]:
        """Return every tram platform, bus stop or Bizi station, from the day's list.

        While the day's fetch fails, the last good list stands in, however old.
        Raises ``SourceUnavailableError`` only while no good list ever came.
        """
        if kind is Kind.TRAM:
            return await self.catalogues.tram.get(self.providers.tram.stops)
        if kind is Kind.BUS:
            return await self.catalogues.bus.get(self.providers.bus_stops.stops)
        return await self.catalogues.bizi.get(self.providers.bike.stations)

    async def fresh_listing(self, kind: StopKind) -> Listing | None:
        """Return the codes in the day's list of ``kind``, if it can tell a stop is gone.

        It can when fetched under a day ago, not empty and, for Bizi, from the
        operator: the city's list, the fallback, holds a varying subset of the
        stations. A list kept after failed fetches says nothing about today, and
        one with nothing in it is a bad answer, not news. Otherwise None, as for
        no list at all; none is fetched for it here, as placing the stops asks for
        the first list, after a good refresh and then hourly.
        """
        memo: _Memo[tuple[Stop, ...]] | _Memo[tuple[BikeStation, ...]]
        if kind is Kind.TRAM:
            memo = self.catalogues.tram
        elif kind is Kind.BUS:
            memo = self.catalogues.bus
        else:
            memo = self.catalogues.bizi
        if not memo.has_list:
            return None
        # Fetches the day's list if due; with a good list kept, never raises.
        codes: frozenset[str]
        if kind is Kind.BIZI:
            stations = await self.stops_for(kind)
            if not _from_operator(stations):
                return None
            codes = frozenset(station.code for station in stations)
        else:
            codes = frozenset(stop.code for stop in await self.stops_for(kind))
        if not codes:
            return None
        fetched_at = memo.fresh_since()
        if fetched_at is None:
            return None
        return Listing(fetched_at, codes)


type ZodConfigEntry = ConfigEntry[ZodRuntime]
