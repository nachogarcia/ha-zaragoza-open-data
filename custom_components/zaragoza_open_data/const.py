"""Constants shared across the integration."""

from collections.abc import Mapping
from enum import StrEnum
import json
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from homeassistant.const import Platform

DOMAIN = "zaragoza_open_data"
NAME = "Zaragoza Open Data"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.GEO_LOCATION,
    Platform.SENSOR,
]


class Kind(StrEnum):
    """A kind of data the user can switch on or off; actions and the card use these too."""

    TRAM = "tram"
    BUS = "bus"
    BIZI = "bizi"
    ROAD_WORKS = "road_works"
    PHARMACIES = "pharmacies"
    AIR_QUALITY = "air_quality"
    POLLEN = "pollen"


# The kinds with stops or stations the user adds.
type StopKind = Literal[Kind.TRAM, Kind.BUS, Kind.BIZI]

# Subentry types: each stop or station the user adds is one subentry.
SUBENTRY_TRAM_STOP = "tram_stop"
SUBENTRY_BUS_STOP = "bus_stop"
SUBENTRY_BIZI_STATION = "bizi_station"
# The kind each subentry type belongs to.
SUBENTRY_KINDS: Mapping[str, Kind] = MappingProxyType(
    {
        SUBENTRY_TRAM_STOP: Kind.TRAM,
        SUBENTRY_BUS_STOP: Kind.BUS,
        SUBENTRY_BIZI_STATION: Kind.BIZI,
    }
)

# Option keys, read only through ``options.ZodOptions``.
CONF_KINDS = "kinds"
CONF_ROAD_WORKS_RADIUS_KM = "road_works_radius_km"
CONF_ROAD_WORKS_CENTRE = "road_works_centre"
CONF_ROAD_WORKS_CATEGORIES = "road_works_categories"
CONF_PHARMACIES_RADIUS_KM = "pharmacies_radius_km"
CONF_PHARMACIES_CENTRE = "pharmacies_centre"
CONF_AIR_STATION = "air_station"
CONF_REFRESH = "refresh"

DEFAULT_ROAD_WORKS_RADIUS_KM = 2.0
# About seven pharmacies are on duty at once, so the whole city is a short list.
DEFAULT_PHARMACIES_RADIUS_KM = 0.0
DEFAULT_CENTRE = "zone.home"

# Fired for each road work on the map layer that the integration has never seen.
EVENT_NEW_ROAD_WORK = f"{DOMAIN}_new_road_work"

# Where the map pin pictures are served; ``markers.marker_url`` builds their URLs.
MARKERS_PATH = "/zaragoza_open_data/markers"

# Where the search card is served; every dashboard loads it.
CARD_URL = "/zaragoza_open_data/zaragoza-open-data-card.js"


def _manifest_version() -> str:
    """Read the version from manifest.json so there is a single place to bump."""
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text("utf-8"))
    version = manifest["version"]
    assert isinstance(version, str)
    return version


VERSION = _manifest_version()

# Identifies us to the city's servers without a personal email address.
USER_AGENT = (
    f"ZaragozaOpenData/{VERSION} "
    "(+https://github.com/nachogarcia/ha-zaragoza-open-data)"
)
