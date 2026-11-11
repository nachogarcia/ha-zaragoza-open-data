"""Diagnostics: the settings, how each source is doing, what each stop shows."""

from dataclasses import asdict
from typing import Protocol

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api.errors import ZaragozaOpenDataError
from .api.models import ArrivalBoard, BikeAvailability
from .const import SUBENTRY_BIZI_STATION, SUBENTRY_BUS_STOP, SUBENTRY_TRAM_STOP, Kind
from .options import read_bizi_station, read_bus_stop, read_tram_stop
from .runtime import ZodConfigEntry, ZodRuntime

# Where each stop is would give home away.
TO_REDACT = frozenset({"latitude", "longitude"})


class _Polled(Protocol):
    """What diagnostics read from a coordinator."""

    @property
    def last_update_success(self) -> bool: ...

    @property
    def last_exception(self) -> BaseException | None: ...


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ZodConfigEntry
) -> dict[str, object]:
    """Return the options and stops, each source's last result, each stop's data."""
    runtime = entry.runtime_data
    return async_redact_data(
        {
            "options": dict(entry.options),
            "subentries": [
                subentry.as_dict() for subentry in entry.subentries.values()
            ],
            "coordinators": _coordinators(runtime),
            "stops": _stops(entry, runtime),
        },
        TO_REDACT,
    )


def _failure(error: BaseException | None) -> dict[str, object]:
    """Name an error and the one it came from; the latter's message if it is ours.

    Our errors' messages are fixed texts that never carry data; another's could
    hold an address or part of a page.
    """
    cause = None if error is None else error.__cause__
    return {
        "last_exception": None if error is None else type(error).__name__,
        "cause": None if cause is None else type(cause).__name__,
        "cause_message": str(cause)
        if isinstance(cause, ZaragozaOpenDataError)
        else None,
    }


def _coordinators(runtime: ZodRuntime) -> dict[str, dict[str, object]]:
    """Return whether each running kind's last refresh worked, and its last error.

    The last error, and what caused it, stay shown after the source recovers.
    """
    polled: tuple[tuple[Kind, _Polled | None], ...] = (
        (Kind.TRAM, runtime.tram),
        (Kind.BUS, runtime.bus),
        (Kind.BIZI, runtime.bizi),
        (Kind.ROAD_WORKS, runtime.road_works),
        (Kind.PHARMACIES, runtime.pharmacies),
        (Kind.AIR_QUALITY, runtime.air_quality),
        (Kind.POLLEN, runtime.pollen),
    )
    return {
        kind.value: {
            "last_update_success": coordinator.last_update_success,
            **_failure(coordinator.last_exception),
        }
        for kind, coordinator in polled
        if coordinator is not None
    }


def _latest[K, V](
    coordinator: DataUpdateCoordinator[dict[K, V]] | None, code: K
) -> V | None:
    """Return what ``coordinator`` last got for ``code``, however old; None if nothing."""
    if coordinator is None or coordinator.data is None:
        return None
    return coordinator.data.get(code)


def _stops(entry: ZodConfigEntry, runtime: ZodRuntime) -> dict[str, dict[str, object]]:
    """Return each stop's place in its list, its latest data and who sent it.

    By device identifier, such as ``bus_688``. A bus stop keeps its last good
    board while neither source answers, so its ``observed_at`` tells its age.
    """
    stops: dict[str, dict[str, object]] = {}
    for subentry in entry.subentries.values():
        latest: ArrivalBoard | BikeAvailability | None
        if subentry.subentry_type == SUBENTRY_TRAM_STOP:
            code = read_tram_stop(subentry)["code"]
            key, latest = f"{Kind.TRAM}_{code}", _latest(runtime.tram, code)
        elif subentry.subentry_type == SUBENTRY_BUS_STOP:
            code = read_bus_stop(subentry)["code"]
            key, latest = f"{Kind.BUS}_{code}", _latest(runtime.bus, code)
        elif subentry.subentry_type == SUBENTRY_BIZI_STATION:
            station = read_bizi_station(subentry)["code"]
            key, latest = f"{Kind.BIZI}_{station}", _latest(runtime.bizi, station)
        else:
            continue
        place = runtime.places.get(key)
        stops[key] = {
            "place": None if place is None else asdict(place),
            "latest": None if latest is None else asdict(latest),
            "source": None if latest is None else latest.source,
        }
    return stops
