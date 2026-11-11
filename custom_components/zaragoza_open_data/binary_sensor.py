"""Binary sensors: whether a Bizi station rents bikes and takes them back."""

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.models import BikeAvailability, StationCode
from .const import SUBENTRY_BIZI_STATION, Kind
from .coordinator import BikeCoordinator
from .entity import BikeEntity, stop_device
from .options import read_bizi_station
from .runtime import ZodConfigEntry

# Coordinators fetch the data; entities never ask a source themselves.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class BikeBinarySensorDescription(BinarySensorEntityDescription):
    """A Bizi station's yes-or-no and where it comes from."""

    value_fn: Callable[[BikeAvailability], bool]


BIKE_BINARY_SENSORS = (
    BikeBinarySensorDescription(
        key="renting",
        translation_key="renting",
        value_fn=lambda availability: availability.renting,
    ),
    BikeBinarySensorDescription(
        key="returning",
        translation_key="returning",
        value_fn=lambda availability: availability.returning,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZodConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add each Bizi station's binary sensors."""
    runtime = entry.runtime_data
    if runtime.bizi is None:
        return
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_BIZI_STATION:
            continue
        code = read_bizi_station(subentry)["code"]
        device = stop_device(Kind.BIZI, code, subentry, runtime.hub_device_id)
        async_add_entities(
            [
                BikeBinarySensor(runtime.bizi, description, code, device)
                for description in BIKE_BINARY_SENSORS
            ],
            config_subentry_id=subentry.subentry_id,
        )


class BikeBinarySensor(BikeEntity, BinarySensorEntity):
    """Whether a Bizi station rents or takes back bikes."""

    entity_description: BikeBinarySensorDescription

    def __init__(
        self,
        coordinator: BikeCoordinator,
        description: BikeBinarySensorDescription,
        code: StationCode,
        device: DeviceInfo,
    ) -> None:
        """Watch station ``code``."""
        super().__init__(coordinator, code, description.key, device)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the yes or no."""
        availability = self._availability()
        return (
            None
            if availability is None
            else self.entity_description.value_fn(availability)
        )
