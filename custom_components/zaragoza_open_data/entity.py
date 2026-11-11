"""What every entity shares: translated names, its device and the data's attribution.

Every entity's unique id starts with its kind (``tram_2502_next_arrival``,
``road_works_25688``), which is how setup finds what a disabled kind left.
"""

from collections.abc import Callable, Collection

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.models import AirStation, BikeAvailability, BikeStation, StationCode, Stop
from .const import DOMAIN, Kind
from .coordinator import (
    BikeCoordinator,
    BusCoordinator,
    CityCoordinator,
    TramCoordinator,
)
from .directions import ATTR_DIRECTIONS, directions_url

# Where the data comes from, by the source that answered. The city's reuse terms
# ask for the source to be cited and suggest this wording (zaragoza.es, Aviso
# Legal, "Condiciones generales para la reutilización"). The other two state no
# licence, and get the same plain line.
_ATTRIBUTION = {
    "zaragoza_city": "Origen de los datos: Ayuntamiento de Zaragoza",
    "gbfs": "Origen de los datos: Bizi Zaragoza",
    "avanza": "Origen de los datos: Avanza Zaragoza",
}


def attribution_for(source: str) -> str | None:
    """Return the line naming where data from ``source`` comes from."""
    return _ATTRIBUTION.get(source)


def place_attributes(
    place: Stop | BikeStation | AirStation | None, *, directions: bool = False
) -> dict[str, object]:
    """Return where a place is, for a map card; nothing when unknown.

    ``directions`` adds the Google Maps link to it, for stops and stations.
    """
    if place is None:
        return {}
    attributes: dict[str, object] = {
        ATTR_LATITUDE: place.location.latitude,
        ATTR_LONGITUDE: place.location.longitude,
    }
    if directions:
        attributes[ATTR_DIRECTIONS] = directions_url(place.location)
    return attributes


def stop_device(
    kind: Kind, code: str, subentry: ConfigSubentry, hub_device_id: str
) -> DeviceInfo:
    """Return the device of a stop or station the user added, under the hub."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{kind}_{code}")},
        name=subentry.title,
        entry_type=DeviceEntryType.SERVICE,
        via_device_id=hub_device_id,
    )


def hub_device(entry_id: str) -> DeviceInfo:
    """Return the hub device, created when the entry is set up."""
    return DeviceInfo(identifiers={(DOMAIN, entry_id)})


def service_device(kind: Kind, hub_device_id: str) -> DeviceInfo:
    """Return the device of a kind of city information, such as "Polen", under the hub."""
    return DeviceInfo(
        identifiers={(DOMAIN, kind.value)},
        translation_key=kind.value,
        entry_type=DeviceEntryType.SERVICE,
        via_device_id=hub_device_id,
    )


@callback
def add_as_they_appear(
    entry: ConfigEntry,
    coordinator: CityCoordinator,
    keys: Callable[[], Collection[str]],
    make: Callable[[str], Entity],
    async_add_entities: AddConfigEntryEntitiesCallback,
    added: set[str] | None = None,
) -> set[str]:
    """Add an entity per key now, and one for each key a later refresh brings.

    For data whose items are only known from the source (plants, pollutants,
    map items). Returns the keys added so far (``added``, if given), which a
    caller removing entities shrinks so the key can come back.
    """
    added = set() if added is None else added

    @callback
    def refreshed() -> None:
        if not coordinator.last_update_success:
            return
        new: list[str] = []
        for key in keys():
            # A list naming an item twice still gets one entity for it.
            if key not in added:
                added.add(key)
                new.append(key)
        if new:
            async_add_entities([make(key) for key in new])

    refreshed()
    entry.async_on_unload(coordinator.async_add_listener(refreshed))
    return added


class ZodEntity[
    C: TramCoordinator | BusCoordinator | BikeCoordinator | CityCoordinator
](CoordinatorEntity[C]):
    """An entity named from translations, on its device, fed by a coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: C, unique_id: str, device_info: DeviceInfo) -> None:
        """Place the entity on its device; subclasses add their description."""
        super().__init__(coordinator)
        self._attr_unique_id = unique_id
        self._attr_device_info = device_info


class BikeEntity(ZodEntity[BikeCoordinator]):
    """An entity about one Bizi station.

    Unavailable while the answering source doesn't list the station: the city's
    list, standing in for the operator's, covers only some.
    """

    def __init__(
        self,
        coordinator: BikeCoordinator,
        code: StationCode,
        key: str,
        device_info: DeviceInfo,
    ) -> None:
        """Watch station ``code``; ``key`` tells this entity from the station's others."""
        super().__init__(coordinator, f"{Kind.BIZI}_{code}_{key}", device_info)
        self._code = code

    @property
    def available(self) -> bool:
        """Say whether the answering source lists the station."""
        return super().available and self._availability() is not None

    @property
    def attribution(self) -> str | None:
        """Credit whoever answered."""
        availability = self._availability()
        return None if availability is None else attribution_for(availability.source)

    def _availability(self) -> BikeAvailability | None:
        data = self.coordinator.data
        return None if data is None else data.get(self._code)
