"""What Home Assistant shows for the integration's devices and entities."""

from custom_components.zaragoza_open_data.const import DOMAIN
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr, entity_registry as er


def entity_id(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    """Return the entity id registered for ``unique_id`` on ``platform``."""
    found = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert found is not None, f"No {platform} entity with unique id {unique_id}"
    return found


def state_of(hass: HomeAssistant, platform: str, unique_id: str) -> State:
    """Return the current state of the entity registered for ``unique_id``."""
    state = hass.states.get(entity_id(hass, platform, unique_id))
    assert state is not None
    return state


def device(hass: HomeAssistant, identifier: str) -> dr.DeviceEntry | None:
    """Return the device registered as ``(DOMAIN, identifier)``, if any."""
    found = dr.async_get(hass).async_get_devices(identifiers={(DOMAIN, identifier)})
    assert len(found) <= 1
    return found[0] if found else None


def device_snapshot(hass: HomeAssistant, identifier: str) -> dict[str, object]:
    """Return a device, its entities' registry entries and their states.

    A disabled entity has a registry entry and no state.
    """
    found = device(hass, identifier)
    assert found is not None
    entries = sorted(
        er.async_entries_for_device(
            er.async_get(hass), found.id, include_disabled_entities=True
        ),
        key=lambda entry: entry.entity_id,
    )
    return {
        "device": found,
        "entities": {
            entry.entity_id: {"entry": entry, "state": hass.states.get(entry.entity_id)}
            for entry in entries
        },
    }


def geo_events(hass: HomeAssistant, source: str) -> dict[str, State]:
    """Return the map events of ``source`` by unique id, such as ``road_works_25688``."""
    registry = er.async_get(hass)
    events: dict[str, State] = {}
    for state in hass.states.async_all("geo_location"):
        if state.attributes.get("source") != source:
            continue
        registered = registry.async_get(state.entity_id)
        assert registered is not None, f"{state.entity_id} is not registered"
        events[registered.unique_id] = state
    return events
