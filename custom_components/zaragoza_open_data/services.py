"""The actions: find any stop, ask for its arrivals or a Bizi station's bikes, on the fly.

Registered once in ``async_setup``, they answer from the one loaded entry. The
search card uses nothing else; scripts, automations and Assist use them too.
"""

from collections.abc import Awaitable, Mapping, Sequence
from types import MappingProxyType

import probatio

from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .api.errors import SourceUnavailableError
from .api.models import BikeStation, GeoPoint, Stop
from .const import DOMAIN, Kind, StopKind
from .coordinator import home_of
from .responses import arrivals_response, bizi_response, find_stops_response
from .runtime import ZodConfigEntry, ZodRuntime
from .search import rank, resolve_typed

SERVICE_FIND_STOPS = "find_stops"
SERVICE_GET_ARRIVALS = "get_arrivals"
SERVICE_GET_BIZI_STATION = "get_bizi_station"

ATTR_KIND = "kind"
ATTR_QUERY = "query"
ATTR_LIMIT = "limit"
ATTR_MODE = "mode"
ATTR_STOP = "stop"
ATTR_STATION = "station"

DEFAULT_LIMIT = 8
MAX_LIMIT = 50

# The kinds with stops, by the value the actions name them with.
_STOP_KINDS: Mapping[str, StopKind] = MappingProxyType(
    {Kind.TRAM.value: Kind.TRAM, Kind.BUS.value: Kind.BUS, Kind.BIZI.value: Kind.BIZI}
)
_MODES = (Kind.TRAM.value, Kind.BUS.value)

FIND_STOPS_SCHEMA = probatio.Schema(
    {
        probatio.Required(ATTR_KIND): probatio.In(tuple(_STOP_KINDS)),
        probatio.Optional(ATTR_QUERY): cv.string,
        # A point is both coordinates or neither; without one, home.
        probatio.Inclusive(ATTR_LATITUDE, "point"): cv.latitude,
        probatio.Inclusive(ATTR_LONGITUDE, "point"): cv.longitude,
        probatio.Optional(ATTR_LIMIT, default=DEFAULT_LIMIT): probatio.All(
            probatio.Coerce(int), probatio.Range(min=1, max=MAX_LIMIT)
        ),
    }
)
GET_ARRIVALS_SCHEMA = probatio.Schema(
    {
        probatio.Required(ATTR_MODE): probatio.In(_MODES),
        probatio.Required(ATTR_STOP): cv.string,
    }
)
GET_BIZI_STATION_SCHEMA = probatio.Schema({probatio.Required(ATTR_STATION): cv.string})


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the three actions, each answering with response data only."""
    for name, handler, schema in (
        (SERVICE_FIND_STOPS, _async_find_stops, FIND_STOPS_SCHEMA),
        (SERVICE_GET_ARRIVALS, _async_get_arrivals, GET_ARRIVALS_SCHEMA),
        (SERVICE_GET_BIZI_STATION, _async_get_bizi_station, GET_BIZI_STATION_SCHEMA),
    ):
        hass.services.async_register(
            DOMAIN, name, handler, schema, supports_response=SupportsResponse.ONLY
        )


def _runtime(hass: HomeAssistant) -> ZodRuntime:
    """Return the running entry's runtime; there is never more than one entry."""
    entries: list[ZodConfigEntry] = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="not_loaded"
        )
    return entries[0].runtime_data


def _kind_disabled() -> ServiceValidationError:
    """Say that the kind asked about is switched off in the options."""
    return ServiceValidationError(
        translation_domain=DOMAIN, translation_key="kind_disabled"
    )


def _source_unavailable() -> HomeAssistantError:
    """Say that the source to answer from doesn't answer now."""
    return HomeAssistantError(
        translation_domain=DOMAIN, translation_key="source_unavailable"
    )


async def _from_source[T](request: Awaitable[T]) -> T:
    """Await a request to a source; one that doesn't answer is a translated error."""
    try:
        return await request
    except SourceUnavailableError as err:
        raise _source_unavailable() from err


def _unknown_stop(code: str) -> ServiceValidationError:
    """Say that no stop or station has ``code``."""
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="unknown_stop",
        translation_placeholders={"code": code.strip()},
    )


def _known[T: Stop | BikeStation](items: Sequence[T], code: str) -> T:
    """Return the stop or station with ``code`` (spaces around it ignored)."""
    item = resolve_typed(items, code)
    if item is None:
        raise _unknown_stop(code)
    return item


async def _async_find_stops(call: ServiceCall) -> ServiceResponse:
    """Rank the stops or stations of a kind by distance, matching any text given."""
    runtime = _runtime(call.hass)
    kind = _STOP_KINDS[call.data[ATTR_KIND]]
    if kind not in runtime.options.kinds:
        raise _kind_disabled()
    items: Sequence[Stop | BikeStation] = await _from_source(runtime.stops_for(kind))
    latitude = call.data.get(ATTR_LATITUDE)
    origin = (
        home_of(call.hass)
        if latitude is None
        else GeoPoint(latitude, call.data[ATTR_LONGITUDE])
    )
    return find_stops_response(
        rank(items, origin, call.data.get(ATTR_QUERY), call.data[ATTR_LIMIT])
    )


async def _async_get_arrivals(call: ServiceCall) -> ServiceResponse:
    """Return what comes next to any tram platform or bus stop."""
    runtime = _runtime(call.hass)
    code: str = call.data[ATTR_STOP]
    if call.data[ATTR_MODE] == Kind.TRAM:
        tram = runtime.tram
        if tram is None:
            raise _kind_disabled()
        stop = _known(await _from_source(runtime.stops_for(Kind.TRAM)), code)
        # One list serves every platform: no request of its own.
        boards = await tram.async_fresh_data()
        if boards is None:
            raise _source_unavailable()
        board = boards.get(stop.code)
        if board is None:
            # The day's stop list has it, the latest tram list no longer does.
            raise _unknown_stop(code)
    else:
        bus = runtime.bus
        if bus is None:
            raise _kind_disabled()
        stop = _known(await _from_source(runtime.stops_for(Kind.BUS)), code)
        board = await _from_source(bus.board_for(stop.code))
    return arrivals_response(stop, board, dt_util.utcnow())


async def _async_get_bizi_station(call: ServiceCall) -> ServiceResponse:
    """Return a Bizi station's bikes and free docks."""
    runtime = _runtime(call.hass)
    bizi = runtime.bizi
    if bizi is None:
        raise _kind_disabled()
    station = _known(
        await _from_source(runtime.stops_for(Kind.BIZI)), call.data[ATTR_STATION]
    )
    stations = await bizi.async_fresh_data()
    if stations is None:
        raise _source_unavailable()
    availability = stations.get(station.code)
    if availability is None:
        # The answering source, often the city's list standing in for the
        # operator's, lists it without counts (under maintenance) or not at all.
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="station_without_counts",
            translation_placeholders={"code": station.code},
        )
    return bizi_response(station, availability)
