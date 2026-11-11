"""What the integration remembers across restarts, beside the registries.

Two small stores: the air quality station the pollutant sensors were made for,
and the road works seen lately. Removing the entry forgets both.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_VERSION = 1
AIR_QUALITY_KEY = f"{DOMAIN}.air_quality"
ROAD_WORKS_KEY = f"{DOMAIN}.road_works"

# Stored JSON, read back through the narrowing helpers below.
type Memory = dict[str, object]


def memory(hass: HomeAssistant, key: str) -> Store[Memory]:
    """Return the store saved under ``key``."""
    return Store(hass, _VERSION, key)


def text_in(saved: Memory | None, key: str) -> str | None:
    """Return the text saved under ``key``; None when missing or not text."""
    value = None if saved is None else saved.get(key)
    return value if isinstance(value, str) else None


def texts_in(saved: Memory | None, key: str) -> dict[str, str]:
    """Return the text-to-text mapping saved under ``key``, skipping anything else."""
    value = None if saved is None else saved.get(key)
    items = value.items() if isinstance(value, dict) else ()
    return {
        name: text
        for name, text in items
        if isinstance(name, str) and isinstance(text, str)
    }


async def async_forget_everything(hass: HomeAssistant) -> None:
    """Remove both stores."""
    for key in (AIR_QUALITY_KEY, ROAD_WORKS_KEY):
        await memory(hass, key).async_remove()
