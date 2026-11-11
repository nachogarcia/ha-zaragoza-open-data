"""Zaragoza Open Data: transport, bikes, road works, air quality and more."""

import asyncio
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from homeassistant.components import frontend

# Defined in .server; the package re-exports it implicitly, which mypy strict refuses.
from homeassistant.components.http.server import StaticPathConfig
from homeassistant.core import HassJob, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .const import (
    CARD_URL,
    DOMAIN,
    MARKERS_PATH,
    NAME,
    PLATFORMS,
    VERSION,
    Kind,
    StopKind,
)
from .coordinator import (
    AirQualityCoordinator,
    BikeCoordinator,
    BusCoordinator,
    CityCoordinator,
    PharmaciesCoordinator,
    PollenCoordinator,
    RoadWorksCoordinator,
    TramCoordinator,
)
from .markers import async_load_digests, short_digest
from .memory import async_forget_everything
from .options import ZodOptions, read_stop
from .repairs import VanishedStops, async_drop_issues_of_removed_stops
from .runtime import (
    CATALOGUE_TTL,
    ZodConfigEntry,
    ZodRuntime,
    catalogues_for,
    providers_for,
)
from .services import async_setup_services

# The first look for stops gone from their lists, once setup's own requests are
# done. Then a little over the day a list is kept, so each check finds the day's
# list fetched anew rather than racing the moment it falls due.
VANISHED_FIRST_CHECK = timedelta(minutes=5)
VANISHED_CHECK_INTERVAL = CATALOGUE_TTL + timedelta(minutes=5)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions, serve the map pin pictures and the search card.

    Done once for every entry. The actions answer while the entry is loaded, and
    say so when it isn't. Every dashboard loads the card.
    """
    async_setup_services(hass)
    here = Path(__file__).parent
    card = here / "frontend" / "zaragoza-open-data-card.js"
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(MARKERS_PATH, str(here / "markers"), cache_headers=True),
            StaticPathConfig(CARD_URL, str(card), cache_headers=True),
        ]
    )
    # Browsers keep the card for a month: a new release, or a card rebuilt
    # without one, has a new URL.
    digest = await hass.async_add_executor_job(short_digest, card)
    await async_load_digests(hass, here / "markers")
    frontend.add_extra_js_url(hass, f"{CARD_URL}?v={VERSION}-{digest}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ZodConfigEntry) -> bool:
    """Wire the providers, start a coordinator per enabled kind, add the entities.

    A source that can't be reached doesn't stop the entry: its entities stay
    unavailable until it answers, while the other kinds carry on. Only the tram
    and Bizi are waited for; the bus and the city's information fill in after.
    """
    providers = providers_for(hass)
    options = ZodOptions.from_mapping(entry.options)
    hub = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=NAME,
        entry_type=dr.DeviceEntryType.SERVICE,
    )
    runtime = ZodRuntime(
        providers=providers,
        options=options,
        catalogues=catalogues_for(hass),
        hub_device_id=hub.id,
    )
    if Kind.TRAM in options.kinds:
        runtime.tram = TramCoordinator(hass, entry, providers.tram)
    if Kind.BUS in options.kinds:
        runtime.bus = BusCoordinator(hass, entry, providers.bus_arrivals)
    if Kind.BIZI in options.kinds:
        runtime.bizi = BikeCoordinator(hass, entry, providers.bike)
    if Kind.ROAD_WORKS in options.kinds:
        runtime.road_works = RoadWorksCoordinator(hass, entry, providers.road_works)
    if Kind.PHARMACIES in options.kinds:
        runtime.pharmacies = PharmaciesCoordinator(hass, entry, providers.pharmacies)
    if Kind.AIR_QUALITY in options.kinds:
        # Each refresh's stations are the day's list, which the options show.
        runtime.air_quality = AirQualityCoordinator(
            hass, entry, providers.air_quality, runtime.catalogues.air.offer
        )
    if Kind.POLLEN in options.kinds:
        runtime.pollen = PollenCoordinator(hass, entry, providers.pollen)
    entry.runtime_data = runtime
    _remove_disabled_kinds(hass, entry, options.kinds)

    codes = _configured_codes(entry)
    if runtime.tram is not None:
        _place_after_refreshes(hass, entry, runtime, Kind.TRAM, runtime.tram, codes)
    if runtime.bus is not None:
        _place_after_refreshes(hass, entry, runtime, Kind.BUS, runtime.bus, codes)
    if runtime.bizi is not None:
        _place_after_refreshes(hass, entry, runtime, Kind.BIZI, runtime.bizi, codes)
    async_drop_issues_of_removed_stops(hass, entry.subentries)
    if entry.subentries:
        _check_vanished_stops(hass, entry)

    # Tram and Bizi are one or two quick requests each, to different servers:
    # wait for them, so the entities start with values.
    await asyncio.gather(
        *(
            coordinator.async_refresh()
            for coordinator in (runtime.tram, runtime.bizi)
            if coordinator is not None
        )
    )
    city = [
        coordinator
        for coordinator in (
            runtime.road_works,
            runtime.pharmacies,
            runtime.air_quality,
            runtime.pollen,
        )
        if coordinator is not None
    ]
    if city:
        # Six more requests to the tram's server, the city's: asked one after
        # another, after the tram's, without holding setup up. The map layers,
        # plants and pollutants, which only the data names, appear as they answer.
        entry.async_create_background_task(
            hass, _refresh_in_turn(city), f"{DOMAIN} first city refresh"
        )
    if runtime.bus is not None:
        # The bus asks its stops one at a time with a rest in between, which can
        # take a while: its entities fill in when it is done.
        entry.async_create_background_task(
            hass, runtime.bus.async_refresh(), f"{DOMAIN} first bus refresh"
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Options and stop subentries decide which coordinators, devices and entities
    # exist, so any change starts the entry again.
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _refresh_in_turn(coordinators: Sequence[CityCoordinator]) -> None:
    """Refresh each coordinator once the one before has answered (or failed)."""
    for coordinator in coordinators:
        await coordinator.async_refresh()


def _remove_disabled_kinds(
    hass: HomeAssistant, entry: ZodConfigEntry, kinds: frozenset[Kind]
) -> None:
    """Remove the entities and devices of the kinds switched off in the options.

    Every unique id starts with its kind; each kind of city information has its
    own device. A transport kind can only be off once its stops are removed.
    """
    disabled = [kind for kind in Kind if kind not in kinds]
    if not disabled:
        return
    entities = er.async_get(hass)
    for registered in er.async_entries_for_config_entry(entities, entry.entry_id):
        if registered.unique_id.startswith(tuple(f"{kind}_" for kind in disabled)):
            entities.async_remove(registered.entity_id)
    devices = dr.async_get(hass)
    for kind in disabled:
        if device := devices.async_get_device_by_identifier(
            (DOMAIN, kind.value), entry.entry_id
        ):
            devices.async_remove_device(device.id)


def _configured_codes(entry: ZodConfigEntry) -> dict[Kind, set[str]]:
    """Return the codes of the stops and stations the user added, by kind."""
    codes: dict[Kind, set[str]] = {Kind.TRAM: set(), Kind.BUS: set(), Kind.BIZI: set()}
    for subentry in entry.subentries.values():
        if (stop := read_stop(subentry)) is not None:
            kind, code = stop
            codes[kind].add(code)
    return codes


def _check_vanished_stops(hass: HomeAssistant, entry: ZodConfigEntry) -> None:
    """Look for stops gone from their lists 5 minutes after setup, then about daily.

    Each check runs in the background and stops with the entry.
    """
    vanished = VanishedStops(hass, entry)

    @callback
    def check(_now: datetime) -> None:
        entry.async_create_background_task(
            hass, vanished.async_check(), f"{DOMAIN} vanished stops check"
        )

    @callback
    def start(now: datetime) -> None:
        check(now)
        entry.async_on_unload(
            async_track_time_interval(
                hass,
                check,
                VANISHED_CHECK_INTERVAL,
                name=f"{DOMAIN} vanished stops check",
                cancel_on_shutdown=True,
            )
        )

    entry.async_on_unload(
        async_call_later(
            hass,
            VANISHED_FIRST_CHECK,
            HassJob(
                start, f"{DOMAIN} first vanished stops check", cancel_on_shutdown=True
            ),
        )
    )


def _place_after_refreshes(
    hass: HomeAssistant,
    entry: ZodConfigEntry,
    runtime: ZodRuntime,
    kind: StopKind,
    coordinator: TramCoordinator | BusCoordinator | BikeCoordinator,
    codes: dict[Kind, set[str]],
) -> None:
    """Place the configured stops of ``kind`` after a good refresh, until all are.

    Right after a good refresh the source is answering (and the tram list and
    the Bizi stations are cached, so placing costs no request); after a failed
    one nobody is asked. The bus list is three requests, so ``async_place``
    retries a list that failed only hourly.
    """
    wanted = codes[kind]
    if not wanted:
        return

    async def place() -> None:
        if await runtime.async_place(kind, wanted):
            # Show the places now rather than at the next refresh.
            coordinator.async_update_listeners()

    @callback
    def refreshed() -> None:
        if coordinator.last_update_success and runtime.unplaced(kind, wanted):
            entry.async_create_background_task(
                hass, place(), f"{DOMAIN} place {kind} stops"
            )

    entry.async_on_unload(coordinator.async_add_listener(refreshed))


async def async_unload_entry(hass: HomeAssistant, entry: ZodConfigEntry) -> bool:
    """Unload the platforms; the coordinators stop with the entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ZodConfigEntry) -> None:
    """Forget what the entry remembered: set up again, it starts afresh.

    Its stops go with it, and so do their issues.
    """
    async_drop_issues_of_removed_stops(hass, ())
    await async_forget_everything(hass)


async def _async_reload(hass: HomeAssistant, entry: ZodConfigEntry) -> None:
    """Start the entry again with its new options or stops."""
    await hass.config_entries.async_reload(entry.entry_id)
