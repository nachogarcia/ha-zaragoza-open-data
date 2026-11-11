"""Bizi stations and availability from the city's ``estacion-bicicleta`` list."""

from collections.abc import Mapping

from ...models import BikeAvailability, BikeStation, JsonObject, StationCode
from ..bizi import split_station_name
from ..json import point, req_int, req_str
from .client import CityClient
from .names import madrid

PATH = "urbanismo-infraestructuras/estacion-bicicleta.json"
# Checked on 2026-11-09: every one of these fields survives ``fl`` on this endpoint.
_FIELDS = "id,title,estado,bicisDisponibles,anclajesDisponibles,geometry,lastUpdated"
_IN_SERVICE = "IN_SERVICE"


class CityBike:
    """``BikeSource`` backed by the city API."""

    def __init__(self, client: CityClient) -> None:
        """Keep the client."""
        self._client = client

    @property
    def source_name(self) -> str:
        """Provider name, copied into the stations and the availability."""
        return self._client.source_name

    async def stations(self) -> tuple[BikeStation, ...]:
        """Return every station that has a number in its name."""
        stations: list[BikeStation] = []
        for row in await self._rows():
            named = self._named(row)
            if named is None:
                continue
            code, name = named
            stations.append(
                BikeStation(
                    code=code,
                    name=name,
                    location=point(row, self.source_name),
                    # Not in the fields the list is asked for.
                    capacity=None,
                    address=None,
                    source=self.source_name,
                )
            )
        return tuple(stations)

    async def availability(self) -> Mapping[StationCode, BikeAvailability]:
        """Return the availability of every station that has a number in its name."""
        source = self.source_name
        result: dict[StationCode, BikeAvailability] = {}
        for row in await self._rows():
            named = self._named(row)
            if named is None:
                continue
            code = named[0]
            in_service = req_str(row, "estado", source) == _IN_SERVICE
            # Maintenance stations stay in the catalogue but may omit both counts.
            # Missing availability makes only that station unavailable, not the feed.
            if not in_service and (
                row.get("bicisDisponibles") is None
                or row.get("anclajesDisponibles") is None
            ):
                continue
            result[code] = BikeAvailability(
                code=code,
                bikes=req_int(row, "bicisDisponibles", source),
                # The city does not split bikes by type.
                electric=None,
                mechanical=None,
                docks=req_int(row, "anclajesDisponibles", source),
                renting=in_service,
                returning=in_service,
                reported_at=madrid(req_str(row, "lastUpdated", source)),
                source=source,
            )
        return result

    async def _rows(self) -> list[JsonObject]:
        return await self._client.get_all(PATH, {"fl": _FIELDS, "srsname": "wgs84"})

    def _named(self, row: JsonObject) -> tuple[StationCode, str] | None:
        source = self.source_name
        return split_station_name(req_str(row, "title", source), source)
