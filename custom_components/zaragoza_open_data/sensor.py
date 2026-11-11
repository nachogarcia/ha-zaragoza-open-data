"""Sensors: stop arrivals, Bizi counts, tram notices, and the city's information."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from homeassistant.components.sensor import (
    DOMAIN as SENSOR,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfDensity, UnitOfTime
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .api.air_index import AirQualityBand, air_index
from .api.models import (
    AirReading,
    Arrival,
    ArrivalBoard,
    BikeAvailability,
    BikeStation,
    PollenLevel,
    PollenReading,
    Pollutant,
    StationCode,
    Stop,
    StopCode,
)
from .const import (
    DOMAIN,
    SUBENTRY_BIZI_STATION,
    SUBENTRY_BUS_STOP,
    SUBENTRY_TRAM_STOP,
    Kind,
)
from .coordinator import (
    AirQualityCoordinator,
    BikeCoordinator,
    BusCoordinator,
    PharmaciesCoordinator,
    PollenCoordinator,
    RoadWorksCoordinator,
    TramCoordinator,
    local_text,
    turn_end,
)
from .directions import ATTR_DIRECTIONS, directions_url
from .entity import (
    BikeEntity,
    ZodEntity,
    add_as_they_appear,
    attribution_for,
    hub_device,
    place_attributes,
    service_device,
    stop_device,
)
from .markers import air_marker, marker_url
from .memory import AIR_QUALITY_KEY, memory, text_in
from .options import read_bizi_station, read_bus_stop, read_tram_stop
from .runtime import ZodConfigEntry

# Coordinators fetch the data; entities never ask a source themselves.
PARALLEL_UPDATES = 0

NEXT_ARRIVAL = SensorEntityDescription(
    key="next_arrival",
    translation_key="next_arrival",
    device_class=SensorDeviceClass.TIMESTAMP,
)
FOLLOWING_ARRIVAL = SensorEntityDescription(
    key="following_arrival",
    translation_key="following_arrival",
    device_class=SensorDeviceClass.TIMESTAMP,
)
# On by default: it is the number a badge or a picture card shows. It changes
# every minute; its lists stay out of the history.
MINUTES_TO_NEXT = SensorEntityDescription(
    key="minutes_to_next",
    translation_key="minutes_to_next",
    device_class=SensorDeviceClass.DURATION,
    native_unit_of_measurement=UnitOfTime.MINUTES,
    # Whole minutes: a duration in minutes would otherwise show two decimals.
    suggested_display_precision=0,
)
TRAM_NOTICES = SensorEntityDescription(
    key="tram_notices", translation_key="tram_notices"
)
ROAD_WORKS_NEARBY = SensorEntityDescription(
    key="road_works_nearby",
    translation_key="road_works_nearby",
    state_class=SensorStateClass.MEASUREMENT,
)
NEAREST_DUTY_PHARMACY = SensorEntityDescription(
    key="nearest_duty_pharmacy", translation_key="nearest_duty_pharmacy"
)
AIR_QUALITY_INDEX = SensorEntityDescription(
    key="air_quality_index",
    translation_key="air_quality_index",
    device_class=SensorDeviceClass.ENUM,
    options=[band.value for band in AirQualityBand],
)
POLLEN = SensorEntityDescription(
    key="pollen",
    translation_key="pollen",
    device_class=SensorDeviceClass.ENUM,
    options=[level.value for level in PollenLevel],
)

_MICROGRAMS = UnitOfDensity.MICROGRAMS_PER_CUBIC_METER


def _pollutant(
    pollutant: Pollutant,
    device_class: SensorDeviceClass | None,
    unit: UnitOfDensity = _MICROGRAMS,
) -> SensorEntityDescription:
    """Describe the sensor of one pollutant; without a device class it is named."""
    return SensorEntityDescription(
        key=pollutant.value,
        translation_key=pollutant.value,
        device_class=device_class,
        native_unit_of_measurement=unit,
        state_class=SensorStateClass.MEASUREMENT,
    )


# The city reports CO in mg/m³ and everything else in µg/m³.
POLLUTANT_SENSORS: Mapping[Pollutant, SensorEntityDescription] = MappingProxyType(
    {
        Pollutant.NO: _pollutant(Pollutant.NO, SensorDeviceClass.NITROGEN_MONOXIDE),
        Pollutant.NO2: _pollutant(Pollutant.NO2, SensorDeviceClass.NITROGEN_DIOXIDE),
        Pollutant.O3: _pollutant(Pollutant.O3, SensorDeviceClass.OZONE),
        Pollutant.SO2: _pollutant(Pollutant.SO2, SensorDeviceClass.SULPHUR_DIOXIDE),
        Pollutant.PM10: _pollutant(Pollutant.PM10, SensorDeviceClass.PM10),
        Pollutant.PM25: _pollutant(Pollutant.PM25, SensorDeviceClass.PM25),
        Pollutant.CO: _pollutant(
            Pollutant.CO,
            SensorDeviceClass.CO,
            UnitOfDensity.MILLIGRAMS_PER_CUBIC_METER,
        ),
        Pollutant.H2S: _pollutant(Pollutant.H2S, None),
        Pollutant.BENZENE: _pollutant(Pollutant.BENZENE, None),
    }
)


@dataclass(frozen=True, kw_only=True)
class BikeSensorDescription(SensorEntityDescription):
    """A Bizi station sensor and the figure it shows."""

    value_fn: Callable[[BikeAvailability], int | datetime | None]
    # Whether the sensor also says where the station is and how many docks it
    # has: one of the station's sensors does, the one a map card lists.
    placed: bool = False


BIKE_SENSORS = (
    BikeSensorDescription(
        key="bikes",
        translation_key="bikes",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda availability: availability.bikes,
        placed=True,
    ),
    # Electric and mechanical are unknown while the city's list stands in: it
    # doesn't split bikes by type.
    BikeSensorDescription(
        key="electric_bikes",
        translation_key="electric_bikes",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda availability: availability.electric,
    ),
    BikeSensorDescription(
        key="mechanical_bikes",
        translation_key="mechanical_bikes",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda availability: availability.mechanical,
    ),
    BikeSensorDescription(
        key="free_docks",
        translation_key="free_docks",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda availability: availability.docks,
    ),
    BikeSensorDescription(
        key="last_report",
        translation_key="last_report",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda availability: availability.reported_at,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZodConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the hub's tram notices, each stop's sensors and the city's information."""
    runtime = entry.runtime_data
    if runtime.tram is not None:
        async_add_entities([TramNoticesSensor(runtime.tram, entry.entry_id)])
    await _async_add_city_sensors(hass, entry, async_add_entities)
    for subentry in entry.subentries.values():
        sensors: list[SensorEntity]
        if subentry.subentry_type == SUBENTRY_TRAM_STOP and runtime.tram is not None:
            code = read_tram_stop(subentry)["code"]
            device = stop_device(Kind.TRAM, code, subentry, runtime.hub_device_id)
            sensors = _stop_sensors(
                runtime.tram, Kind.TRAM, code, None, device, runtime.places
            )
        elif subentry.subentry_type == SUBENTRY_BUS_STOP and runtime.bus is not None:
            stop = read_bus_stop(subentry)
            device = stop_device(
                Kind.BUS, stop["code"], subentry, runtime.hub_device_id
            )
            # No lines picked means every line.
            lines = frozenset(stop["lines"]) or None
            sensors = _stop_sensors(
                runtime.bus, Kind.BUS, stop["code"], lines, device, runtime.places
            )
        elif (
            subentry.subentry_type == SUBENTRY_BIZI_STATION and runtime.bizi is not None
        ):
            station = read_bizi_station(subentry)["code"]
            device = stop_device(Kind.BIZI, station, subentry, runtime.hub_device_id)
            sensors = [
                BikeSensor(runtime.bizi, description, station, device, runtime.places)
                for description in BIKE_SENSORS
            ]
        else:
            continue
        async_add_entities(sensors, config_subentry_id=subentry.subentry_id)


async def _async_add_city_sensors(
    hass: HomeAssistant,
    entry: ZodConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors of the enabled kinds of city information."""
    runtime = entry.runtime_data
    hub = runtime.hub_device_id
    if (road_works := runtime.road_works) is not None:
        async_add_entities(
            [RoadWorksNearbySensor(road_works, service_device(Kind.ROAD_WORKS, hub))]
        )
    if (pharmacies := runtime.pharmacies) is not None:
        async_add_entities(
            [NearestPharmacySensor(pharmacies, service_device(Kind.PHARMACIES, hub))]
        )
    # Each kind's device has its own name: the lambdas below run again on later
    # refreshes, when a shared name would hold the last kind's device.
    if (air := runtime.air_quality) is not None:
        air_device = service_device(Kind.AIR_QUALITY, hub)
        async_add_entities([AirQualityIndexSensor(air, air_device)])
        await _async_add_pollutant_sensors(
            hass, entry, air, air_device, async_add_entities
        )
    if (pollen := runtime.pollen) is not None:
        pollen_device = service_device(Kind.POLLEN, hub)
        add_as_they_appear(
            entry,
            pollen,
            lambda: [reading.plant_id for reading in pollen.data or ()],
            lambda plant: PollenSensor(pollen, plant, pollen_device),
            async_add_entities,
        )


def _chosen_readings(coordinator: AirQualityCoordinator) -> tuple[AirReading, ...]:
    """Return the readings of the station the sensors use; none before any data."""
    data = coordinator.data
    return () if data is None else data.readings_at(data.chosen.id)


def _pollutant_id(pollutant: str) -> str:
    """Return the unique id of a pollutant's sensor, such as ``air_quality_no2``."""
    return f"{Kind.AIR_QUALITY}_{pollutant}"


async def _async_add_pollutant_sensors(
    hass: HomeAssistant,
    entry: ZodConfigEntry,
    coordinator: AirQualityCoordinator,
    device: DeviceInfo,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a sensor per pollutant: those made before, and each one the station reports.

    The readings cover two hours, so an analyser silent that long keeps its
    sensor (unknown). The sensors go only when another station is in use: the
    one they were made for is remembered, and at the first readings after setup
    the sensors of pollutants the new station doesn't report are removed.
    """
    registry = er.async_get(hass)
    store = memory(hass, AIR_QUALITY_KEY)
    previous = text_in(await store.async_load(), "station")
    kept = {
        pollutant.value
        for pollutant in Pollutant
        if registry.async_get_entity_id(SENSOR, DOMAIN, _pollutant_id(pollutant))
    }
    added: set[str] = set()
    checked = False

    @callback
    def check_station() -> None:
        nonlocal checked
        data = coordinator.data
        if checked or data is None:
            return
        checked = True
        station = data.chosen.id
        if station == previous:
            return
        if previous is not None:
            reported = {
                reading.pollutant.value for reading in data.readings_at(station)
            }
            for pollutant in kept - reported:
                kept.discard(pollutant)
                # Should the new station report it later, it comes back.
                added.discard(pollutant)
                if entity_id := registry.async_get_entity_id(
                    SENSOR, DOMAIN, _pollutant_id(pollutant)
                ):
                    registry.async_remove(entity_id)
        entry.async_create_background_task(
            hass, store.async_save({"station": station}), f"{DOMAIN} air station"
        )

    # Before adding anything: the readings may be in already.
    check_station()
    entry.async_on_unload(coordinator.async_add_listener(check_station))
    add_as_they_appear(
        entry,
        coordinator,
        lambda: [
            *kept,
            *(reading.pollutant.value for reading in _chosen_readings(coordinator)),
        ],
        lambda key: PollutantSensor(coordinator, Pollutant(key), device),
        async_add_entities,
        added,
    )


def _stop_sensors(
    coordinator: TramCoordinator | BusCoordinator,
    kind: Kind,
    code: StopCode,
    lines: frozenset[str] | None,
    device: DeviceInfo,
    places: Mapping[str, Stop | BikeStation],
) -> list[SensorEntity]:
    """Return a tram or bus stop's sensors."""
    return [
        NextArrivalSensor(coordinator, kind, code, lines, device, places),
        FollowingArrivalSensor(coordinator, kind, code, lines, device),
        MinutesToNextSensor(coordinator, kind, code, lines, device),
    ]


class _StopSensor(ZodEntity[TramCoordinator | BusCoordinator], SensorEntity):
    """A sensor about the trams or buses coming to one stop.

    Unavailable while the stop has no board: the tram list no longer has it, or
    no source has answered for the bus stop in ``BUS_MAX_AGE``.
    """

    _description: SensorEntityDescription

    def __init__(
        self,
        coordinator: TramCoordinator | BusCoordinator,
        kind: Kind,
        code: StopCode,
        lines: frozenset[str] | None,
        device: DeviceInfo,
    ) -> None:
        """Watch stop ``code``, showing only ``lines`` (None: every line)."""
        super().__init__(coordinator, f"{kind}_{code}_{self._description.key}", device)
        self.entity_description = self._description
        self._kind = kind
        self._code = code
        self._lines = lines

    @property
    def available(self) -> bool:
        """Say whether the stop has a board to show."""
        return super().available and self._board() is not None

    @property
    def attribution(self) -> str | None:
        """Credit whoever answered for the stop."""
        board = self._board()
        return None if board is None else attribution_for(board.source)

    def _board(self) -> ArrivalBoard | None:
        return self.coordinator.board(self._code)

    def _arrivals(self) -> tuple[Arrival, ...]:
        """Return the stop's arrivals still to come on the lines shown, soonest first."""
        board = self._board()
        return () if board is None else board.upcoming(dt_util.utcnow(), self._lines)

    def _arrival(self, position: int) -> Arrival | None:
        arrivals = self._arrivals()
        return arrivals[position] if position < len(arrivals) else None


class NextArrivalSensor(_StopSensor):
    """When the next tram or bus comes, every one the stop lists, and where it is.

    This is the stop's sensor a map card lists, so it carries the coordinates and
    a tram or bus stop pin.
    """

    _description = NEXT_ARRIVAL
    # The list changes every minute and is long; history keeps the time and line.
    _unrecorded_attributes = frozenset({"arrivals"})

    def __init__(
        self,
        coordinator: TramCoordinator | BusCoordinator,
        kind: Kind,
        code: StopCode,
        lines: frozenset[str] | None,
        device: DeviceInfo,
        places: Mapping[str, Stop | BikeStation],
    ) -> None:
        """Watch stop ``code``; ``places`` says where the configured stops are."""
        super().__init__(coordinator, kind, code, lines, device)
        self._places = places
        self._marker = "tram_stop" if kind is Kind.TRAM else "bus_stop"

    @property
    def entity_picture(self) -> str:
        """Return the stop's pin picture, its URL naming the file's contents."""
        return marker_url(self.hass, self._marker)

    @property
    def native_value(self) -> datetime | None:
        """Return when the next one comes; unknown when nothing is coming."""
        arrival = self._arrival(0)
        return None if arrival is None else arrival.expected_at

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return its line and destination, all arrivals, and who answered (bus)."""
        arrivals = self._arrivals()
        first = arrivals[0] if arrivals else None
        attributes: dict[str, object] = {
            "line": None if first is None else first.line,
            "destination": None if first is None else first.destination,
            "arrivals": [
                # No minutes: they would change the state every minute, and each
                # change is a row in the history.
                {
                    "line": arrival.line,
                    "destination": arrival.destination,
                    # As text, like every time Home Assistant sends out.
                    "time": dt_util.as_local(arrival.expected_at).isoformat(),
                }
                for arrival in arrivals
            ],
            # Night, an arrival-only platform, or no bus on the way.
            "no_service": not arrivals,
        }
        board = self._board()
        if self._kind is Kind.BUS and board is not None:
            attributes["source"] = board.source
        attributes.update(
            place_attributes(
                self._places.get(f"{self._kind}_{self._code}"), directions=True
            )
        )
        return attributes


class FollowingArrivalSensor(_StopSensor):
    """When the one after the next comes."""

    _description = FOLLOWING_ARRIVAL

    @property
    def native_value(self) -> datetime | None:
        """Return when the second one comes; unknown if fewer are listed."""
        arrival = self._arrival(1)
        return None if arrival is None else arrival.expected_at

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return its line and destination."""
        arrival = self._arrival(1)
        return {
            "line": None if arrival is None else arrival.line,
            "destination": None if arrival is None else arrival.destination,
        }


class MinutesToNextSensor(_StopSensor):
    """Whole minutes until the next one, as the source counts them.

    For a badge or a picture card: ``following`` is the minutes to the one after,
    ``arrivals`` every one coming with its minutes. Both change every minute, so
    history keeps only the number. Counted again at each whole minute after the
    source's reading, so it never disagrees with ``get_arrivals`` between refreshes.
    """

    _description = MINUTES_TO_NEXT
    _unrecorded_attributes = frozenset({"following", "arrivals"})
    # Cancels the timer that counts again when the minutes next drop.
    _cancel_recount: CALLBACK_TYPE | None = None

    async def async_added_to_hass(self) -> None:
        """Start counting again at each drop of the minutes, until removed."""
        await super().async_added_to_hass()
        self.async_on_remove(self._stop_recount)
        self._schedule_recount()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Write the new board's minutes and count again from its reading."""
        super()._handle_coordinator_update()
        self._schedule_recount()

    @callback
    def _recount(self, _now: datetime) -> None:
        """Write the minutes as they stand now, then wait for the next drop."""
        self._cancel_recount = None
        self.async_write_ha_state()
        self._schedule_recount()

    @callback
    def _schedule_recount(self) -> None:
        """Count again when the minutes next drop, while available and anything comes.

        Unavailable (the source failing), nothing is counted: the coordinator's next
        good update arms it again.
        """
        self._stop_recount()
        board = self._board()
        now = dt_util.utcnow()
        if self.available and board is not None and board.upcoming(now, self._lines):
            self._cancel_recount = async_track_point_in_utc_time(
                self.hass, self._recount, board.minutes_change_at(now)
            )

    @callback
    def _stop_recount(self) -> None:
        """Cancel the next count, if one is due."""
        if self._cancel_recount is not None:
            self._cancel_recount()
            self._cancel_recount = None

    def _counted(self) -> list[tuple[Arrival, int]]:
        """Return the arrivals still to come on the lines shown, with their minutes."""
        board = self._board()
        now = dt_util.utcnow()
        return (
            []
            if board is None
            else [
                (arrival, board.minutes_to(arrival, now))
                for arrival in board.upcoming(now, self._lines)
            ]
        )

    @property
    def native_value(self) -> int | None:
        """Return the source's minutes to the next one; unknown when nothing comes."""
        counted = self._counted()
        return counted[0][1] if counted else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the minutes to the one after, and every one coming."""
        counted = self._counted()
        return {
            "following": counted[1][1] if len(counted) > 1 else None,
            "arrivals": [
                {
                    "line": arrival.line,
                    "destination": arrival.destination,
                    "minutes": minutes,
                    "time": dt_util.as_local(arrival.expected_at).isoformat(),
                }
                for arrival, minutes in counted
            ],
        }


class BikeSensor(BikeEntity, SensorEntity):
    """A count or the last report of one Bizi station."""

    entity_description: BikeSensorDescription

    def __init__(
        self,
        coordinator: BikeCoordinator,
        description: BikeSensorDescription,
        code: StationCode,
        device: DeviceInfo,
        places: Mapping[str, Stop | BikeStation],
    ) -> None:
        """Watch station ``code``; ``places`` says where the configured ones are."""
        super().__init__(coordinator, code, description.key, device)
        self.entity_description = description
        self._places = places

    @property
    def extra_state_attributes(self) -> dict[str, object] | None:
        """Return where the station is and its docks, if this sensor carries them."""
        if not self.entity_description.placed:
            return None
        station = self._places.get(f"{Kind.BIZI}_{self._code}")
        attributes = place_attributes(station, directions=True)
        if isinstance(station, BikeStation):
            attributes["capacity"] = station.capacity
        return attributes

    @property
    def native_value(self) -> int | datetime | None:
        """Return the figure."""
        availability = self._availability()
        return (
            None
            if availability is None
            else self.entity_description.value_fn(availability)
        )


class TramNoticesSensor(ZodEntity[TramCoordinator], SensorEntity):
    """How many notices the tram has posted, and what they say."""

    entity_description = TRAM_NOTICES
    # The texts can be long; history keeps how many there were.
    _unrecorded_attributes = frozenset({"notices"})

    def __init__(self, coordinator: TramCoordinator, entry_id: str) -> None:
        """Live on the hub: the notices are about the whole line."""
        super().__init__(coordinator, TRAM_NOTICES.key, hub_device(entry_id))

    @property
    def attribution(self) -> str | None:
        """Credit the city, which publishes the tram list."""
        data = self.coordinator.data
        if not data:
            return None
        return attribution_for(next(iter(data.values())).source)

    @property
    def native_value(self) -> int:
        """Return how many notices there are."""
        return len(self.coordinator.notices())

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the notices."""
        return {"notices": list(self.coordinator.notices())}


class RoadWorksNearbySensor(ZodEntity[RoadWorksCoordinator], SensorEntity):
    """How many road works the map layer shows."""

    entity_description = ROAD_WORKS_NEARBY

    def __init__(self, coordinator: RoadWorksCoordinator, device: DeviceInfo) -> None:
        """Live on the road works device."""
        super().__init__(coordinator, ROAD_WORKS_NEARBY.key, device)
        self._attr_attribution = attribution_for(coordinator.source_name)

    @property
    def native_value(self) -> int | None:
        """Return how many works are within the distance; unknown before any list."""
        data = self.coordinator.data
        return None if data is None else len(data)


class NearestPharmacySensor(ZodEntity[PharmaciesCoordinator], SensorEntity):
    """The pharmacy on duty nearest the layer's centre: its name, and how to get there."""

    entity_description = NEAREST_DUTY_PHARMACY

    def __init__(self, coordinator: PharmaciesCoordinator, device: DeviceInfo) -> None:
        """Live on the pharmacies device."""
        super().__init__(
            coordinator, f"{Kind.PHARMACIES}_{NEAREST_DUTY_PHARMACY.key}", device
        )
        self._attr_attribution = attribution_for(coordinator.source_name)

    @property
    def native_value(self) -> str | None:
        """Return its name; unknown when none is within the distance."""
        nearest = self.coordinator.nearest()
        return None if nearest is None else nearest.name

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return its address, phone, hours, distance, duty date, closing time, directions."""
        nearest = self.coordinator.nearest()
        if nearest is None:
            return {}
        distance_m = self.coordinator.centre.distance_to(nearest.location)
        return {
            "address": nearest.address,
            "phone": nearest.phone,
            "hours": nearest.hours,
            "distance_km": round(distance_m / 1000, 1),
            "on_duty": nearest.day.isoformat(),
            "open_until": local_text(turn_end(nearest.day)),
            ATTR_DIRECTIONS: directions_url(nearest.location),
        }


class _AirSensor(ZodEntity[AirQualityCoordinator], SensorEntity):
    """A sensor about the air at the station in use, which says where it is."""

    def __init__(
        self,
        coordinator: AirQualityCoordinator,
        description: SensorEntityDescription,
        unique_id: str,
        device: DeviceInfo,
    ) -> None:
        """Live on the air quality device."""
        super().__init__(coordinator, unique_id, device)
        self.entity_description = description
        self._attr_attribution = attribution_for(coordinator.source_name)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return where the station is."""
        data = self.coordinator.data
        return place_attributes(None if data is None else data.chosen)


class PollutantSensor(_AirSensor):
    """One pollutant's latest hourly reading at the station in use."""

    def __init__(
        self,
        coordinator: AirQualityCoordinator,
        pollutant: Pollutant,
        device: DeviceInfo,
    ) -> None:
        """Show ``pollutant``."""
        super().__init__(
            coordinator,
            POLLUTANT_SENSORS[pollutant],
            _pollutant_id(pollutant),
            device,
        )
        self._pollutant = pollutant

    @property
    def native_value(self) -> float | None:
        """Return the reading; unknown when the station sent none this time."""
        reading = self._reading()
        return None if reading is None else reading.value

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return where the station is and when the city published the reading.

        The city's reuse terms ask for its data's date; it changes with the
        reading, hourly.
        """
        reading = self._reading()
        return {
            **super().extra_state_attributes,
            "published_at": None
            if reading is None
            else local_text(reading.measured_at),
        }

    def _reading(self) -> AirReading | None:
        return next(
            (
                reading
                for reading in _chosen_readings(self.coordinator)
                if reading.pollutant is self._pollutant
            ),
            None,
        )


class AirQualityIndexSensor(_AirSensor):
    """The European air quality index at the station in use, with a coloured pin."""

    def __init__(self, coordinator: AirQualityCoordinator, device: DeviceInfo) -> None:
        """Live on the air quality device."""
        super().__init__(coordinator, AIR_QUALITY_INDEX, AIR_QUALITY_INDEX.key, device)

    @property
    def native_value(self) -> str | None:
        """Return the band; unknown when no indexed pollutant was read."""
        band = air_index(_chosen_readings(self.coordinator)).band
        return None if band is None else band.value

    @property
    def entity_picture(self) -> str:
        """Return the air pin in the band's colour (grey without data)."""
        band = air_index(_chosen_readings(self.coordinator)).band
        return marker_url(self.hass, air_marker(band))

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the pollutant that set the band, its reading's date, where.

        Also whether the data suffices for the index.
        """
        readings = _chosen_readings(self.coordinator)
        index = air_index(readings)
        setting = next(
            (reading for reading in readings if reading.pollutant is index.pollutant),
            None,
        )
        return {
            "pollutant": None if index.pollutant is None else index.pollutant.value,
            "complete": index.complete,
            "published_at": None
            if setting is None
            else local_text(setting.measured_at),
            **super().extra_state_attributes,
        }


class PollenSensor(ZodEntity[PollenCoordinator], SensorEntity):
    """One plant's pollen level, named as the city names the plant."""

    entity_description = POLLEN

    def __init__(
        self, coordinator: PollenCoordinator, plant_id: str, device: DeviceInfo
    ) -> None:
        """Watch the plant ``plant_id``."""
        super().__init__(coordinator, f"{Kind.POLLEN}_{plant_id}", device)
        self._plant_id = plant_id
        self._attr_attribution = attribution_for(coordinator.source_name)
        reading = self._reading()
        if reading is not None:
            self._attr_name = reading.plant_name

    @property
    def available(self) -> bool:
        """Say whether the city still lists the plant."""
        return super().available and self._reading() is not None

    @property
    def native_value(self) -> str | None:
        """Return the level; unknown when the city's word for it is new."""
        reading = self._reading()
        return None if reading is None or reading.level is None else reading.level.value

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the day the level was published."""
        reading = self._reading()
        return (
            {}
            if reading is None
            else {"published_on": reading.published_on.isoformat()}
        )

    def _reading(self) -> PollenReading | None:
        return self.coordinator.reading(self._plant_id)
