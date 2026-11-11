"""Set up Zaragoza Open Data, change its options and add its stops."""

from abc import abstractmethod
import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import replace

import probatio

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    LocationSelector,
    LocationSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.helpers.translation import async_get_translations

from .api.errors import SourceUnavailableError
from .api.models import AirStation, BikeStation, GeoPoint, RoadWorkCategory, Stop
from .const import (
    CONF_AIR_STATION,
    CONF_KINDS,
    CONF_PHARMACIES_CENTRE,
    CONF_PHARMACIES_RADIUS_KM,
    CONF_REFRESH,
    CONF_ROAD_WORKS_CATEGORIES,
    CONF_ROAD_WORKS_CENTRE,
    CONF_ROAD_WORKS_RADIUS_KM,
    DOMAIN,
    NAME,
    SUBENTRY_BIZI_STATION,
    SUBENTRY_BUS_STOP,
    SUBENTRY_KINDS,
    SUBENTRY_TRAM_STOP,
    Kind,
)
from .coordinator import home_of
from .options import (
    REFRESH_SETTINGS,
    BiziStationData,
    BusStopData,
    TramStopData,
    ZodOptions,
    read_bus_stop,
    refresh_below_minimum,
)
from .runtime import (
    ZodConfigEntry,
    ZodRuntime,
    air_stations,
    catalogues_for,
    providers_for,
)
from .search import label, rank, resolve_typed

# The form's value for "the station nearest to home", stored as "". A select option
# needs a non-empty value to carry a translated label.
NEAREST_AIR_STATION = "nearest"

# The stop picker's first entry, "Near another place…". The underscores keep it
# apart from anything a user can type, stop numbers included.
NEAR_PLACE = "__near_place__"
# Form fields of the stop flows.
CONF_STOP = "stop"
CONF_STATION = "station"
CONF_LOCATION = "location"
CONF_LINES = "lines"
# How long adding or changing a stop waits for the entry to finish starting.
# Saving a stop starts the entry again, and the next "Add" can come at once.
ENTRY_START_WAIT_S = 30


def _kinds_selector() -> SelectSelector:
    """A checklist of the kinds of data, with translated names."""
    return SelectSelector(
        SelectSelectorConfig(
            options=[kind.value for kind in Kind],
            multiple=True,
            mode=SelectSelectorMode.LIST,
            translation_key="kind",
        )
    )


def _air_station_choices(
    stations: tuple[AirStation, ...], configured: str | None
) -> list[SelectOptionDict]:
    """List "nearest" and the stations by name, keeping the configured one.

    The configured station stays selectable (labelled by its id) when the city
    can't be reached or no longer lists it, so the form always opens and saves.
    """
    choices = [
        SelectOptionDict(value=NEAREST_AIR_STATION, label=NEAREST_AIR_STATION),
        *(
            SelectOptionDict(value=station.id, label=station.name)
            for station in sorted(stations, key=lambda station: station.name)
        ),
    ]
    if configured is not None and all(station.id != configured for station in stations):
        choices.append(SelectOptionDict(value=configured, label=configured))
    return choices


def _options_schema(air_stations: list[SelectOptionDict]) -> probatio.Schema:
    """The options form; floors are checked by the step, so it can say why."""
    distance = NumberSelector(
        NumberSelectorConfig(
            min=0,
            step=0.1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement=UnitOfLength.KILOMETERS,
        )
    )
    zone = EntitySelector(EntitySelectorConfig(domain="zone"))
    return probatio.Schema(
        {
            probatio.Required(CONF_KINDS): _kinds_selector(),
            probatio.Required(CONF_ROAD_WORKS_RADIUS_KM): distance,
            probatio.Required(CONF_ROAD_WORKS_CENTRE): zone,
            probatio.Required(CONF_ROAD_WORKS_CATEGORIES): SelectSelector(
                SelectSelectorConfig(
                    options=[category.value for category in RoadWorkCategory],
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                    translation_key="road_work_category",
                )
            ),
            probatio.Required(CONF_PHARMACIES_RADIUS_KM): distance,
            probatio.Required(CONF_PHARMACIES_CENTRE): zone,
            probatio.Required(CONF_AIR_STATION): SelectSelector(
                SelectSelectorConfig(
                    options=air_stations,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="air_station",
                )
            ),
            probatio.Required(CONF_REFRESH): section(
                probatio.Schema(
                    {
                        probatio.Required(setting.key): NumberSelector(
                            NumberSelectorConfig(
                                max=setting.ceiling,
                                step=1,
                                mode=NumberSelectorMode.BOX,
                                unit_of_measurement=setting.unit,
                            )
                        )
                        for setting in REFRESH_SETTINGS
                    }
                ),
                {"collapsed": True},
            ),
        }
    )


def _form_values(options: ZodOptions) -> dict[str, object]:
    """Return what the options form shows for ``options``."""
    return {
        **options.to_mapping(),
        CONF_AIR_STATION: options.air_station or NEAREST_AIR_STATION,
    }


def _read_form(user_input: Mapping[str, object]) -> ZodOptions:
    """Return the options the submitted form describes."""
    options = ZodOptions.from_mapping(user_input)
    if options.air_station == NEAREST_AIR_STATION:
        return replace(options, air_station=None)
    return options


async def _check_sources(hass: HomeAssistant, kinds: frozenset[Kind]) -> None:
    """Ask the sources of ``kinds`` once; raise ``SourceUnavailableError`` if one fails.

    One enabled city kind checks the city's shared API, and the Bizi operator is
    asked only when Bizi is ticked: kinds left out make no requests.
    """
    providers = providers_for(hass)
    city_checks: dict[Kind, Callable[[], Awaitable[object]]] = {
        Kind.TRAM: providers.tram.stops,
        Kind.BUS: providers.bus_stops.stops,
        Kind.ROAD_WORKS: providers.road_works.road_works,
        Kind.PHARMACIES: providers.pharmacies.on_duty,
        Kind.AIR_QUALITY: providers.air_quality.stations,
        Kind.POLLEN: providers.pollen.readings,
    }
    for kind, check in city_checks.items():
        if kind in kinds:
            await check()
            break
    if Kind.BIZI in kinds:
        await providers.bike.stations()


class ZodConfigFlow(ConfigFlow, domain=DOMAIN):
    """One screen: tick the kinds of data to bring in."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ZodConfigEntry) -> ZodOptionsFlow:
        """Change what the integration shows and how often it asks."""
        return ZodOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Offer adding tram stops, bus stops and Bizi stations.

        All three, whatever the kinds: Home Assistant works these out once per
        entry and doesn't refresh them when the options change, so each flow
        checks that its kind is on.
        """
        return dict(_STOP_FLOWS)

    async def async_step_user(
        self, user_input: dict[str, object] | None = None
    ) -> ConfigFlowResult:
        """Show the checklist, all ticked; create the entry once the sources answer."""
        errors: dict[str, str] = {}
        if user_input is not None:
            options = ZodOptions.from_mapping(user_input)
            if not options.kinds:
                errors[CONF_KINDS] = "no_kinds"
            else:
                try:
                    await _check_sources(self.hass, options.kinds)
                except SourceUnavailableError:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(
                        title=NAME, data={}, options=options.to_mapping()
                    )
        schema = probatio.Schema(
            {
                probatio.Required(
                    CONF_KINDS, default=[kind.value for kind in Kind]
                ): _kinds_selector()
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )


class ZodOptionsFlow(OptionsFlow):
    """Kinds, map distances and centres, categories, air station and refresh."""

    # Fetched once per form, so showing it again after an error asks nobody.
    _air_stations: list[SelectOptionDict] | None = None

    async def async_step_init(
        self, user_input: dict[str, object] | None = None
    ) -> ConfigFlowResult:
        """Show the options in force; save them unless an interval is too short."""
        errors: dict[str, str] = {}
        if user_input is not None:
            options = _read_form(user_input)
            if refresh_below_minimum(user_input):
                errors["base"] = "refresh_below_minimum"
            if not options.kinds:
                errors[CONF_KINDS] = "no_kinds"
            elif self._kinds_with_stops() - options.kinds:
                errors[CONF_KINDS] = "remove_stops_first"
            if not errors:
                return self.async_create_entry(data=options.to_mapping())
        current = ZodOptions.from_mapping(self.config_entry.options)
        if self._air_stations is None:
            stations: tuple[AirStation, ...] = ()
            if Kind.AIR_QUALITY in current.kinds:
                with suppress(SourceUnavailableError):
                    # The stations the sensors' latest refresh brought, if any.
                    stations = await air_stations(
                        catalogues_for(self.hass), providers_for(self.hass)
                    )
            self._air_stations = _air_station_choices(stations, current.air_station)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                _options_schema(self._air_stations),
                user_input if user_input is not None else _form_values(current),
            ),
            errors=errors,
        )

    def _kinds_with_stops(self) -> set[Kind]:
        """Return the kinds that still have stops: they can't be switched off."""
        return {
            SUBENTRY_KINDS[subentry.subentry_type]
            for subentry in self.config_entry.subentries.values()
        }


def _read_point(value: object) -> GeoPoint:
    """Read a location selector's value, already checked to be two numbers."""
    assert isinstance(value, Mapping)
    return GeoPoint(value["latitude"], value["longitude"])


async def _near_place_label(hass: HomeAssistant) -> str:
    """Return "Near another place…" in the home language, like the stop labels.

    Translated here because ``NEAR_PLACE`` can't be a translation key (those can't
    start with an underscore), so the frontend can't translate it.
    """
    translations = await async_get_translations(
        hass, hass.config.language, "selector", [DOMAIN]
    )
    return translations[f"component.{DOMAIN}.selector.stop_picker.options.near_place"]


def _lines_schema(lines: Sequence[str]) -> probatio.Schema:
    """A checklist of a bus stop's lines; none ticked shows every line."""
    return probatio.Schema(
        {
            probatio.Optional(CONF_LINES): SelectSelector(
                SelectSelectorConfig(
                    options=list(lines), multiple=True, mode=SelectSelectorMode.LIST
                )
            )
        }
    )


def _ticked(offered: Sequence[str], user_input: Mapping[str, object]) -> list[str]:
    """Return the ticked lines in the order offered (empty: every line)."""
    ticked = user_input.get(CONF_LINES)
    return [line for line in offered if isinstance(ticked, list) and line in ticked]


class _StopPickerFlow[T: Stop | BikeStation](ConfigSubentryFlow):
    """Pick one of every stop or station, nearest first, or type its number.

    The list is ranked from home, or from a map pin after "Near another place…".
    The frontend searches it as the user types, so it is offered whole.
    """

    # The kind of stop, which must be on in the options.
    _kind: Kind
    # The picker's form field.
    _field = CONF_STOP
    # Where the list is ranked from; None means home.
    _origin: GeoPoint | None = None

    @abstractmethod
    async def _async_list(self, runtime: ZodRuntime) -> tuple[T, ...]:
        """Return everything the picker offers; raise if the source is down."""

    @abstractmethod
    async def _async_picked(self, item: T) -> SubentryFlowResult:
        """Carry on with ``item``, which the entry doesn't have yet."""

    async def _async_unavailable(self) -> str | None:
        """Return why stops of this kind can't be added or changed now, if so.

        An entry being set up or started again is waited for, up to
        ``ENTRY_START_WAIT_S``; one that isn't starting (failed, or not set up)
        answers at once.
        """
        entry = self._get_entry()
        if self._kind not in ZodOptions.from_mapping(entry.options).kinds:
            return "kind_disabled"
        # Home Assistant holds the entry's setup lock while it sets it up,
        # unloads it or reloads it: getting the lock means that is over.
        if entry.setup_lock.locked():
            with suppress(TimeoutError):
                async with asyncio.timeout(ENTRY_START_WAIT_S), entry.setup_lock:
                    pass
        if entry.state is not ConfigEntryState.LOADED:
            return "entry_not_loaded"
        return None

    def _runtime(self) -> ZodRuntime:
        """Return the running entry's runtime."""
        entry: ZodConfigEntry = self._get_entry()
        return entry.runtime_data

    def _unique_id(self, code: str) -> str:
        """Return a stop's unique id, such as ``bus_688``.

        The kind is part of it because the same number can be a bus stop and a
        Bizi station, and Home Assistant wants unique ids unique across the entry.
        """
        return f"{self._kind}_{code}"

    async def async_step_user(
        self, user_input: dict[str, object] | None = None
    ) -> SubentryFlowResult:
        """Show the list; accept a picked or typed number."""
        if (reason := await self._async_unavailable()) is not None:
            return self.async_abort(reason=reason)
        try:
            items = await self._async_list(self._runtime())
        except SourceUnavailableError:
            # No field to fill in: submitting the form is the retry.
            return self.async_show_form(
                step_id="user", errors={"base": "cannot_connect"}
            )
        errors: dict[str, str] = {}
        choice = (user_input or {}).get(self._field)
        if choice == NEAR_PLACE:
            return await self.async_step_place()
        if isinstance(choice, str):
            item = resolve_typed(items, choice)
            if item is None:
                errors[self._field] = "pick_from_list"
            elif any(
                subentry.unique_id == self._unique_id(item.code)
                for subentry in self._get_entry().subentries.values()
            ):
                return self.async_abort(reason="already_configured")
            else:
                return await self._async_picked(item)
        language = self.hass.config.language
        options = [
            SelectOptionDict(
                value=NEAR_PLACE, label=await _near_place_label(self.hass)
            ),
            *(
                SelectOptionDict(value=item.code, label=label(item, distance, language))
                for item, distance in rank(items, self._origin or home_of(self.hass))
            ),
        ]
        picker = SelectSelector(
            SelectSelectorConfig(
                options=options,
                # The frontend makes a searchable list only of a custom-value
                # dropdown, and keeps the nearest-first order only unsorted.
                custom_value=True,
                mode=SelectSelectorMode.DROPDOWN,
                sort=False,
            )
        )
        return self.async_show_form(
            step_id="user",
            data_schema=probatio.Schema({probatio.Required(self._field): picker}),
            errors=errors,
        )

    async def async_step_place(
        self, user_input: dict[str, object] | None = None
    ) -> SubentryFlowResult:
        """Ask for a map pin, then show the list sorted from it."""
        if user_input is not None:
            self._origin = _read_point(user_input[CONF_LOCATION])
            return await self.async_step_user()
        origin = self._origin or home_of(self.hass)
        schema = probatio.Schema(
            {
                probatio.Required(CONF_LOCATION): LocationSelector(
                    LocationSelectorConfig(radius=False)
                )
            }
        )
        return self.async_show_form(
            step_id="place",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {
                    CONF_LOCATION: {
                        "latitude": origin.latitude,
                        "longitude": origin.longitude,
                    }
                },
            ),
        )

    def _async_create(
        self, item: T, data: TramStopData | BusStopData | BiziStationData
    ) -> SubentryFlowResult:
        """Save ``item``, titled by its label without the distance."""
        return self.async_create_entry(
            title=label(item, None, self.hass.config.language),
            data=data,
            unique_id=self._unique_id(item.code),
        )


class TramStopFlow(_StopPickerFlow[Stop]):
    """Add a tram platform: one direction of a tram stop."""

    _kind = Kind.TRAM

    async def _async_list(self, runtime: ZodRuntime) -> tuple[Stop, ...]:
        """Return every tram platform."""
        return await runtime.stops_for(Kind.TRAM)

    async def _async_picked(self, item: Stop) -> SubentryFlowResult:
        """Save the platform."""
        return self._async_create(item, TramStopData(code=item.code))


class BusStopFlow(_StopPickerFlow[Stop]):
    """Add a bus stop with an optional line filter, which can be changed later."""

    _kind = Kind.BUS
    _stop: Stop | None = None

    async def _async_list(self, runtime: ZodRuntime) -> tuple[Stop, ...]:
        """Return every bus stop."""
        return await runtime.stops_for(Kind.BUS)

    async def _async_picked(self, item: Stop) -> SubentryFlowResult:
        """Ask for the lines, unless the city lists none for the stop."""
        if not item.lines:
            return self._async_create(item, BusStopData(code=item.code, lines=[]))
        self._stop = item
        return await self.async_step_lines()

    async def async_step_lines(
        self, user_input: dict[str, object] | None = None
    ) -> SubentryFlowResult:
        """Offer the stop's lines; save the stop with those ticked."""
        stop = self._stop
        assert stop is not None
        if user_input is not None:
            return self._async_create(
                stop, BusStopData(code=stop.code, lines=_ticked(stop.lines, user_input))
            )
        return self.async_show_form(
            step_id="lines", data_schema=_lines_schema(stop.lines)
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, object] | None = None
    ) -> SubentryFlowResult:
        """Change the lines a saved stop shows; the update listener reloads."""
        if (reason := await self._async_unavailable()) is not None:
            return self.async_abort(reason=reason)
        try:
            stops = await self._runtime().stops_for(Kind.BUS)
        except SourceUnavailableError:
            return self.async_abort(reason="cannot_connect")
        subentry = self._get_reconfigure_subentry()
        saved = read_bus_stop(subentry)
        listed = next((s.lines for s in stops if s.code == saved["code"]), ())
        # Lines saved earlier stay offered if the city stops listing them.
        offered = [*listed, *(line for line in saved["lines"] if line not in listed)]
        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                data=BusStopData(
                    code=saved["code"], lines=_ticked(offered, user_input)
                ),
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _lines_schema(offered), {CONF_LINES: saved["lines"]}
            ),
        )


class BiziStationFlow(_StopPickerFlow[BikeStation]):
    """Add a Bizi station."""

    _kind = Kind.BIZI
    _field = CONF_STATION

    async def _async_list(self, runtime: ZodRuntime) -> tuple[BikeStation, ...]:
        """Return every Bizi station."""
        return await runtime.stops_for(Kind.BIZI)

    async def _async_picked(self, item: BikeStation) -> SubentryFlowResult:
        """Save the station."""
        return self._async_create(item, BiziStationData(code=item.code))


# The "Add" buttons of the entry, one per transport kind.
_STOP_FLOWS: dict[str, type[ConfigSubentryFlow]] = {
    SUBENTRY_TRAM_STOP: TramStopFlow,
    SUBENTRY_BUS_STOP: BusStopFlow,
    SUBENTRY_BIZI_STATION: BiziStationFlow,
}
