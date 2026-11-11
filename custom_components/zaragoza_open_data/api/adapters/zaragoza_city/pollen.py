"""Pollen levels from the city's ``informacion-polen`` list."""

import logging

from ...models import JsonObject, PollenLevel, PollenReading
from ..json import obj_list, req_str
from .client import CityClient
from .names import clean, madrid

_LOGGER = logging.getLogger(__name__)

PATH = "informacion-polen.json"


class CityPollen:
    """``PollenSource`` backed by the city API."""

    def __init__(self, client: CityClient) -> None:
        """Keep the client."""
        self._client = client

    @property
    def source_name(self) -> str:
        """Provider name."""
        return self._client.source_name

    async def readings(self) -> tuple[PollenReading, ...]:
        """Return the latest level of each plant."""
        rows = await self._client.get_all(PATH, {})
        readings = (self._parse(row) for row in rows)
        return tuple(reading for reading in readings if reading is not None)

    def _parse(self, row: JsonObject) -> PollenReading | None:
        source = self.source_name
        plant_id = req_str(row, "id", source)
        observations = obj_list(row, "observation", source)
        if not observations:
            _LOGGER.debug("Skipping plant %s without an observation", plant_id)
            return None
        latest = observations[0]
        text = req_str(latest, "value", source)
        try:
            level: PollenLevel | None = PollenLevel(text.replace(" ", "_"))
        except ValueError:
            _LOGGER.debug("Unknown pollen level %r for plant %s", text, plant_id)
            level = None
        return PollenReading(
            plant_id=plant_id,
            plant_name=clean(req_str(row, "title", source)),
            level=level,
            published_on=madrid(req_str(latest, "publicationDate", source)).date(),
        )
