"""Map layers: road works, pharmacies on duty and the air quality stations.

One event per item, added and removed as the city lists them, so a map card
listing the layer's source shows them and the geolocation trigger sees them
arrive ("a new closure within 500 m of home").
"""

from abc import abstractmethod
from collections.abc import Callable, Collection

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import Platform, UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.air_index import air_index
from .api.models import GeoPoint
from .const import DOMAIN, Kind
from .coordinator import (
    AirQualityCoordinator,
    PharmaciesCoordinator,
    RoadWorksCoordinator,
    local_text,
    turn_end,
)
from .directions import ATTR_DIRECTIONS, directions_url
from .entity import add_as_they_appear, attribution_for
from .markers import air_marker, marker_for, marker_url
from .runtime import ZodConfigEntry

# Coordinators fetch the data; entities never ask a source themselves.
PARALLEL_UPDATES = 0

# What a map card lists in ``geo_location_sources`` to show a layer.
ROAD_WORKS_SOURCE = f"{DOMAIN}_{Kind.ROAD_WORKS}"
PHARMACIES_SOURCE = f"{DOMAIN}_{Kind.PHARMACIES}"
AIR_QUALITY_SOURCE = f"{DOMAIN}_{Kind.AIR_QUALITY}"

# Unique id prefixes: the kind, as for every entity, then the item's id.
_ROAD_WORK = f"{Kind.ROAD_WORKS}_"
_PHARMACY = f"{Kind.PHARMACIES}_"
_AIR_STATION = f"{Kind.AIR_QUALITY}_station_"

type LayerCoordinator = (
    RoadWorksCoordinator | PharmaciesCoordinator | AirQualityCoordinator
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZodConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Show each enabled layer's items, following them as they come and go."""
    runtime = entry.runtime_data
    if (road_works := runtime.road_works) is not None:
        _follow_layer(
            hass,
            entry,
            road_works,
            _ROAD_WORK,
            lambda: [work.id for work in road_works.data or ()],
            lambda work_id: RoadWorkEvent(road_works, work_id),
            async_add_entities,
        )
    if (pharmacies := runtime.pharmacies) is not None:
        _follow_layer(
            hass,
            entry,
            pharmacies,
            _PHARMACY,
            lambda: [pharmacy.id for pharmacy in pharmacies.data or ()],
            lambda pharmacy_id: PharmacyEvent(pharmacies, pharmacy_id),
            async_add_entities,
        )
    if (air := runtime.air_quality) is not None:
        _follow_layer(
            hass,
            entry,
            air,
            _AIR_STATION,
            lambda: [] if air.data is None else [s.id for s in air.data.stations],
            lambda station_id: AirStationEvent(air, station_id),
            async_add_entities,
        )


@callback
def _follow_layer(
    hass: HomeAssistant,
    entry: ZodConfigEntry,
    coordinator: LayerCoordinator,
    prefix: str,
    ids: Callable[[], Collection[str]],
    make: Callable[[str], GeolocationEvent],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add an event per item the layer shows; remove those it no longer shows.

    An item that goes is removed from the entity registry too, so none is left
    behind (also those that went while Home Assistant was off).
    """
    added = add_as_they_appear(entry, coordinator, ids, make, async_add_entities)
    registry = er.async_get(hass)

    @callback
    def remove_gone() -> None:
        # Before the first answer there is no list to compare with.
        if coordinator.data is None or not coordinator.last_update_success:
            return
        shown = {f"{prefix}{item_id}" for item_id in ids()}
        for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
            if (
                registered.domain == Platform.GEO_LOCATION
                and registered.unique_id.startswith(prefix)
                and registered.unique_id not in shown
            ):
                # Removing the registry entry removes the entity too.
                registry.async_remove(registered.entity_id)
                added.discard(registered.unique_id.removeprefix(prefix))

    remove_gone()
    entry.async_on_unload(coordinator.async_add_listener(remove_gone))


class _MapEvent[C: LayerCoordinator](CoordinatorEntity[C], GeolocationEvent):
    """One item on a map layer, at its distance from the layer's centre in km."""

    _attr_has_entity_name = True
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS
    # The marker the pin shows; its URL is built when read, once Home Assistant is known.
    _marker = ""

    def __init__(self, coordinator: C, prefix: str, item_id: str) -> None:
        """Show the item ``item_id``; named after it, so with no device."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{prefix}{item_id}"
        self._attr_attribution = attribution_for(coordinator.source_name)
        self._item_id = item_id
        self._show()

    @property
    def entity_picture(self) -> str:
        """Return the pin's picture, its URL naming the file's contents."""
        return marker_url(self.hass, self._marker)

    @abstractmethod
    def _show(self) -> bool:
        """Copy the item's details; return False if the layer no longer has it."""

    def _place(self, location: GeoPoint) -> None:
        """Put the event at ``location``, measured from the layer's centre."""
        self._attr_latitude = location.latitude
        self._attr_longitude = location.longitude
        self._attr_distance = self.coordinator.centre.distance_to(location) / 1000

    @callback
    def _handle_coordinator_update(self) -> None:
        """Show the item's new details; an item gone is left for its layer to remove."""
        if self._show():
            super()._handle_coordinator_update()


class RoadWorkEvent(_MapEvent[RoadWorksCoordinator]):
    """A road work or closure, with its category's road sign as the pin."""

    _attr_source = ROAD_WORKS_SOURCE
    _attr_translation_key = "road_work"
    # Long texts; history keeps where, when and what kind.
    _unrecorded_attributes = frozenset({"reason", "stretch", "detour"})

    def __init__(self, coordinator: RoadWorksCoordinator, work_id: str) -> None:
        """Show the road work ``work_id``."""
        super().__init__(coordinator, _ROAD_WORK, work_id)

    def _show(self) -> bool:
        work = self.coordinator.work(self._item_id)
        if work is None:
            return False
        self._attr_name = work.title
        self._place(work.location)
        self._marker = marker_for(work.category)
        self._attr_extra_state_attributes = {
            "street": work.street,
            "reason": work.reason,
            "stretch": work.stretch,
            "detour": work.detour,
            "starts": local_text(work.starts),
            "ends": local_text(work.ends),
            "category": work.category.value,
        }
        return True


class PharmacyEvent(_MapEvent[PharmaciesCoordinator]):
    """A pharmacy on duty, with the green pharmacy pin."""

    _attr_source = PHARMACIES_SOURCE
    _attr_translation_key = "pharmacy"
    _marker = "pharmacy"

    def __init__(self, coordinator: PharmaciesCoordinator, pharmacy_id: str) -> None:
        """Show the pharmacy ``pharmacy_id``."""
        super().__init__(coordinator, _PHARMACY, pharmacy_id)

    def _show(self) -> bool:
        pharmacy = self.coordinator.pharmacy(self._item_id)
        if pharmacy is None:
            return False
        self._attr_name = pharmacy.name
        self._place(pharmacy.location)
        self._attr_extra_state_attributes = {
            "address": pharmacy.address,
            "phone": pharmacy.phone,
            "hours": pharmacy.hours,
            "sector": pharmacy.sector,
            # The duty's own date in the city's list; it changes once a day.
            "on_duty": pharmacy.day.isoformat(),
            "open_until": local_text(turn_end(pharmacy.day)),
            ATTR_DIRECTIONS: directions_url(pharmacy.location),
        }
        return True


class AirStationEvent(_MapEvent[AirQualityCoordinator]):
    """An air quality station, its pin in its index colour, with its readings."""

    _attr_source = AIR_QUALITY_SOURCE
    _attr_translation_key = "air_station"

    def __init__(self, coordinator: AirQualityCoordinator, station_id: str) -> None:
        """Show the station ``station_id``."""
        super().__init__(coordinator, _AIR_STATION, station_id)

    def _show(self) -> bool:
        data = self.coordinator.data
        station = None if data is None else data.station(self._item_id)
        if data is None or station is None:
            return False
        readings = data.readings_at(station.id)
        band = air_index(readings).band
        self._attr_name = station.name
        self._place(station.location)
        self._marker = air_marker(band)
        newest = max((reading.measured_at for reading in readings), default=None)
        self._attr_extra_state_attributes = {
            "index": None if band is None else band.value,
            **{reading.pollutant.value: reading.value for reading in readings},
            # When the city published the newest of them; it changes hourly.
            "published_at": local_text(newest),
        }
        return True
