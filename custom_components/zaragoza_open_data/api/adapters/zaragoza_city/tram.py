"""Tram stops and arrivals from the city's ``parada-tranvia`` list."""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ...errors import SourceUnavailableError
from ...models import Arrival, ArrivalBoard, JsonObject, Mode, Stop, StopCode
from ..json import obj_list, point, req_int, req_str
from .client import CityClient
from .names import madrid, tidy

PATH = "urbanismo-infraestructuras/transporte-urbano/parada-tranvia.json"
_CACHE_TTL = timedelta(seconds=30)
# Each stop is two platforms; the last digit of the id says where its trams go.
_DIRECTIONS = {"1": "Mago de Oz", "2": "Avenida de la Academia"}
# Lines of boilerplate the city appends to every platform's messages.
_BOILERPLATE = ("tranviasdezaragoza.es", "codigo qr")


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class _Snapshot:
    fetched_at: datetime
    stops: tuple[Stop, ...]
    boards: Mapping[StopCode, ArrivalBoard]


class CityTram:
    """``TramSource`` backed by the city API; one request serves stops and boards."""

    def __init__(
        self, client: CityClient, now: Callable[[], datetime] = _utc_now
    ) -> None:
        """Keep the client and the clock (injectable for the 30 s cache)."""
        self._client = client
        self._now = now
        self._snapshot: _Snapshot | None = None
        self._lock = asyncio.Lock()

    @property
    def source_name(self) -> str:
        """Provider name, copied into the boards."""
        return self._client.source_name

    async def stops(self) -> tuple[Stop, ...]:
        """Return every tram platform."""
        return (await self._load()).stops

    async def boards(self) -> Mapping[StopCode, ArrivalBoard]:
        """Return the board of every platform."""
        return (await self._load()).boards

    async def _load(self) -> _Snapshot:
        async with self._lock:
            now = self._now()
            snapshot = self._snapshot
            if snapshot is not None and now - snapshot.fetched_at < _CACHE_TTL:
                return snapshot
            # No ``fl``: the city silently drops ``destinos`` and ``mensajes`` with it.
            rows = await self._client.get_all(PATH, {"srsname": "wgs84"})
            stops: list[Stop] = []
            boards: dict[StopCode, ArrivalBoard] = {}
            for row in rows:
                stop, board = self._parse(row)
                stops.append(stop)
                boards[stop.code] = board
            self._snapshot = _Snapshot(now, tuple(stops), boards)
            return self._snapshot

    def _parse(self, row: JsonObject) -> tuple[Stop, ArrivalBoard]:
        source = self.source_name
        code = StopCode(req_str(row, "id", source))
        name = tidy(req_str(row, "title", source))
        observed_at = madrid(req_str(row, "lastUpdated", source))
        destinations = obj_list(row, "destinos", source)
        arrivals = tuple(
            Arrival(
                line=req_str(item, "linea", source),
                destination=tidy(req_str(item, "destino", source)),
                expected_at=observed_at
                + timedelta(minutes=req_int(item, "minutos", source)),
            )
            for item in destinations
        )
        stop = Stop(
            mode=Mode.TRAM,
            code=code,
            name=name,
            location=point(row, source),
            direction=_direction(code, name),
            lines=tuple(sorted({arrival.line for arrival in arrivals})),
        )
        board = ArrivalBoard(
            stop_code=code,
            arrivals=arrivals,
            observed_at=observed_at,
            source=source,
            notices=_notices(row, source),
        )
        return stop, board


def _direction(code: StopCode, name: str) -> str | None:
    terminus = _DIRECTIONS.get(code[-1:])
    # The arrival platform of a terminus (2501, 102) has no departures to name.
    if terminus is None or tidy(terminus) == name:
        return None
    return terminus


def _notices(row: JsonObject, source: str) -> tuple[str, ...]:
    raw = row.get("mensajes")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise SourceUnavailableError(source)
    notices: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise SourceUnavailableError(source)
        text = item.lstrip(".").strip()
        if text and not any(mark in text.casefold() for mark in _BOILERPLATE):
            notices.append(text)
    return tuple(notices)
