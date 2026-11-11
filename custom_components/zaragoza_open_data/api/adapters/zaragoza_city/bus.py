"""Bus stops and arrivals from the city's ``poste-autobus`` endpoints."""

from datetime import timedelta
import re

from ...errors import SourceUnavailableError
from ...models import Arrival, ArrivalBoard, Mode, Stop, StopCode
from ..json import obj_list, opt_str, point, req_str
from ..minutes import parse_minutes
from .client import CityClient
from .names import madrid, tidy

PATH = "urbanismo-infraestructuras/transporte-urbano/poste-autobus"
# "(688) P. Reyes De Aragón N.º 24 Líneas: 58": code, name, then optional lines.
_TITLE = re.compile(r"\((\d+)\)\s*(.*?)(?:\s*L[ií]neas:\s*(.*))?", re.DOTALL)
# The list mixes two networks: the urban buses ("tuzsa-688"), whose arrivals the
# operator and the city serve, and others ("rural-1", line 501 among them) with
# no arrivals anywhere. 175 numbers are in both (measured 2026-11-09).
_URBAN = "tuzsa-"
# Tram platforms are listed as urban stops with this as their only line.
_TRAM = "TRA"


class CityBusStops:
    """``BusStopCatalog`` backed by the city API."""

    def __init__(self, client: CityClient) -> None:
        """Keep the client."""
        self._client = client

    @property
    def source_name(self) -> str:
        """Provider name."""
        return self._client.source_name

    async def stops(self) -> tuple[Stop, ...]:
        """Return every urban bus stop (about 1,000 of 1,300 rows, three pages).

        Each number is one stop: should the city list one twice, the first row
        stands.
        """
        source = self.source_name
        rows = await self._client.get_all(PATH + ".json", {"fl": "id,title,geometry"})
        stops: dict[StopCode, Stop] = {}
        for row in rows:
            if not req_str(row, "id", source).startswith(_URBAN):
                continue
            match = _TITLE.fullmatch(req_str(row, "title", source).strip())
            if match is None:
                raise SourceUnavailableError(source)
            code, name, lines = match.groups()
            listed = lines.replace(",", " ").split() if lines else []
            buses = tuple(line for line in listed if line != _TRAM)
            if listed and not buses:
                continue
            stops.setdefault(
                StopCode(code),
                Stop(
                    mode=Mode.BUS,
                    code=StopCode(code),
                    name=tidy(name),
                    location=point(row, source),
                    direction=None,
                    lines=buses,
                ),
            )
        return tuple(stops.values())


class CityBusArrivals:
    """``BusArrivalsSource`` backed by the city API."""

    def __init__(self, client: CityClient) -> None:
        """Keep the client."""
        self._client = client

    @property
    def source_name(self) -> str:
        """Provider name, copied into the boards."""
        return self._client.source_name

    async def board(self, code: StopCode) -> ArrivalBoard:
        """Return the board of one stop."""
        source = self.source_name
        # No ``fl``: the real-time fields are not part of the stop list's field set.
        row = await self._client.get(f"{PATH}/tuzsa-{code}.json", {"srsname": "wgs84"})
        observed_at = madrid(req_str(row, "lastUpdated", source))
        arrivals: list[Arrival] = []
        for item in obj_list(row, "destinos", source):
            line = req_str(item, "linea", source)
            destination = req_str(item, "destino", source).rstrip(", ")
            for key in ("primero", "segundo"):
                text = opt_str(item, key, source)
                minutes = None if text is None else parse_minutes(text)
                # Text that is no time ("Sin estimación") means no estimate yet.
                if minutes is not None:
                    arrivals.append(
                        Arrival(
                            line=line,
                            destination=destination,
                            expected_at=observed_at + timedelta(minutes=minutes),
                        )
                    )
        return ArrivalBoard(
            stop_code=code,
            arrivals=tuple(arrivals),
            observed_at=observed_at,
            source=source,
        )
