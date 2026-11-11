"""Which map pin picture goes with what; the files are in ``markers/``.

An entity's picture is ``marker_url(hass, name)`` with a name from here. The URL
carries the first digits of the file's SHA-256: the pictures are cached for a
month, so a marker that changes needs a new URL to reach the phones that have it.
"""

import hashlib
import logging
from pathlib import Path
from types import MappingProxyType

from homeassistant.core import HomeAssistant
from homeassistant.util.hass_dict import HassKey

from .api.air_index import AirQualityBand
from .api.models import RoadWorkCategory
from .const import DOMAIN, MARKERS_PATH

_LOGGER = logging.getLogger(__name__)

# Marker name to the first 8 hex digits of its file's SHA-256, read once at setup.
_DIGESTS: HassKey[MappingProxyType[str, str]] = HassKey(f"{DOMAIN}_marker_digests")

_ROAD_WORKS: MappingProxyType[RoadWorkCategory, str] = MappingProxyType(
    {
        RoadWorkCategory.TRAFFIC_CLOSURE: "road_closed",
        RoadWorkCategory.MAINTENANCE: "works",
        RoadWorkCategory.MAJOR_DISRUPTION: "major_disruption",
        RoadWorkCategory.PUBLIC_TRANSPORT_DISRUPTION: "transit_disruption",
        RoadWorkCategory.WATER_CUT: "water_cut",
        RoadWorkCategory.OTHER: "road_other",
    }
)


def marker_for(category: RoadWorkCategory) -> str:
    """Return the marker name for a road work of ``category``."""
    return _ROAD_WORKS[category]


def air_marker(band: AirQualityBand | None) -> str:
    """Return the marker name for an air station in ``band`` (None: no usable data)."""
    return "air_no_data" if band is None else f"air_{band}"


def short_digest(path: Path) -> str:
    """Return the first 8 hex digits of the SHA-256 of a file's contents.

    A URL cached for a month carries it, so a changed file gets a new URL. Reads
    the file: run in the executor.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def read_digests(folder: Path) -> MappingProxyType[str, str]:
    """Return each marker's short digest, by name. Reads files: run in the executor."""
    return MappingProxyType(
        {path.stem: short_digest(path) for path in sorted(folder.glob("*.svg"))}
    )


async def async_load_digests(hass: HomeAssistant, folder: Path) -> None:
    """Hash the marker files, off the event loop, and keep the digests for the entities."""
    hass.data[_DIGESTS] = await hass.async_add_executor_job(read_digests, folder)


def marker_url(hass: HomeAssistant, name: str) -> str:
    """Return the picture URL of marker ``name``, versioned by its file's contents.

    The one place a marker URL is built. Without a digest for it the URL is plain:
    the picture still shows, though a phone may keep an old one. With no digests
    read at all, that is logged once.
    """
    digests = hass.data.get(_DIGESTS)
    if digests is None:
        _LOGGER.warning(
            "The map pictures' files weren't read: their URLs carry no version, "
            "so phones may show old pictures"
        )
        digests = hass.data[_DIGESTS] = MappingProxyType({})
    digest = digests.get(name)
    plain = f"{MARKERS_PATH}/{name}.svg"
    return plain if digest is None else f"{plain}?v={digest}"
