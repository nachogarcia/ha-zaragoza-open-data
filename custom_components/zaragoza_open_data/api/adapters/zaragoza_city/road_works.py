"""Road works and closures from the city's ``via-publica`` lists."""

import logging

from ...models import JsonObject, RoadWork, RoadWorkCategory
from ..json import opt_str, point, req_id, req_obj, req_str
from .client import CityClient
from .names import clean, clean_or_none, madrid

_LOGGER = logging.getLogger(__name__)

INCIDENTS_PATH = "via-publica/incidencia.json"
MAINTENANCE_PATH = "via-publica/incidencia/conservacion-hoy.json"
_CATEGORIES = {
    "Cortes de Tráfico": RoadWorkCategory.TRAFFIC_CLOSURE,
    "Cortes de Agua": RoadWorkCategory.WATER_CUT,
    "Afecciones Importantes": RoadWorkCategory.MAJOR_DISRUPTION,
    "Afecciones al Transporte Público": RoadWorkCategory.PUBLIC_TRANSPORT_DISRUPTION,
    "Conservación de Infraestructuras": RoadWorkCategory.MAINTENANCE,
}


class CityRoadWorks:
    """``RoadWorksSource`` backed by the city's incident and maintenance lists."""

    def __init__(self, client: CityClient) -> None:
        """Keep the client."""
        self._client = client

    @property
    def source_name(self) -> str:
        """Provider name."""
        return self._client.source_name

    async def road_works(self) -> tuple[RoadWork, ...]:
        """Return incidents and today's maintenance, the first occurrence of an id wins."""
        # No ``fl``: the city silently drops fields on some endpoints.
        params = {"srsname": "wgs84"}
        incidents = await self._client.get_all(INCIDENTS_PATH, params)
        maintenance = await self._client.get_all(MAINTENANCE_PATH, params)
        works: dict[str, RoadWork] = {}
        for row in (*incidents, *maintenance):
            # A few maintenance jobs are published without a location: they cannot be
            # placed on a map, so they are left out and the rest is kept.
            if row.get("geometry") is None:
                _LOGGER.debug("Skipping road work %s without a location", row.get("id"))
                continue
            work = self._parse(row)
            works.setdefault(work.id, work)
        return tuple(works.values())

    def _parse(self, row: JsonObject) -> RoadWork:
        source = self.source_name
        kind = req_obj(row, "tipo", source)
        starts = opt_str(row, "inicio", source)
        ends = opt_str(row, "fin", source)
        return RoadWork(
            id=req_id(row, "id", source),
            title=clean(req_str(row, "title", source)),
            street=clean(req_str(row, "calle", source)),
            reason=clean_or_none(opt_str(row, "motivo", source)),
            stretch=clean_or_none(opt_str(row, "tramo", source)),
            detour=clean_or_none(opt_str(row, "observaciones", source)),
            starts=madrid(starts) if starts else None,
            ends=madrid(ends) if ends else None,
            category=_CATEGORIES.get(
                clean(req_str(kind, "title", source)), RoadWorkCategory.OTHER
            ),
            location=point(row, source),
        )
