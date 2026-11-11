"""Bizi station names: both providers write the public number first (``"1-Palacio"``)."""

import logging
import re

from ..models import StationCode

_LOGGER = logging.getLogger(__name__)
# The city writes "191- Pza. Aragón", GBFS "1-Palacio" and, once, "160 - Jardines".
_NAME = re.compile(r"\s*(\d+)\s*-\s*(\S.*?)\s*")


def split_station_name(raw: str, source: str) -> tuple[StationCode, str] | None:
    """Return ``(code, name)``, or None (logged at debug level) without a number prefix."""
    match = _NAME.fullmatch(raw)
    if match is None:
        _LOGGER.debug("Skipping %s station without a number prefix: %s", source, raw)
        return None
    return StationCode(match.group(1)), match.group(2)
