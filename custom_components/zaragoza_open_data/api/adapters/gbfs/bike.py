"""Bizi stations and availability from the operator's GBFS feed."""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import logging

import aiohttp

from ...errors import SourceUnavailableError
from ...models import BikeAvailability, BikeStation, GeoPoint, JsonObject, StationCode
from ..bizi import split_station_name
from ..json import (
    obj_list,
    opt_int,
    opt_str,
    req_bool,
    req_float,
    req_int,
    req_obj,
    req_str,
)

_LOGGER = logging.getLogger(__name__)

SOURCE = "gbfs"
BASE_URL = "https://zaragoza.publicbikesystem.net/customer/gbfs/v2/en/"
_TIMEOUT_S = 10
_TIMEOUT = aiohttp.ClientTimeout(total=_TIMEOUT_S)
# Stations rarely change: one list a day is plenty (the status feed has ``ttl`` 0).
_INFORMATION_TTL = timedelta(hours=24)
_ELECTRIC = frozenset({"EFIT", "BOOST"})
_MECHANICAL = "ICONIC"


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class _Information:
    fetched_at: datetime
    stations: tuple[BikeStation, ...]
    # GBFS station ids ("2") are internal; the public number comes from the name.
    codes: Mapping[str, StationCode]


class GbfsBike:
    """``BikeSource`` backed by the operator's GBFS feed."""

    source_name = SOURCE

    def __init__(
        self,
        session: aiohttp.ClientSession,
        user_agent: str,
        base_url: str = BASE_URL,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Keep the shared session (owned by the caller) and the clock."""
        self._session = session
        self._user_agent = user_agent
        self._base_url = base_url
        self._now = now
        self._information: _Information | None = None
        self._lock = asyncio.Lock()

    async def stations(self) -> tuple[BikeStation, ...]:
        """Return every station that has a number in its name."""
        return (await self._load_information()).stations

    async def availability(self) -> Mapping[StationCode, BikeAvailability]:
        """Return the availability of every station present in the station list."""
        codes = (await self._load_information()).codes
        rows = await self._rows("station_status.json")
        result: dict[StationCode, BikeAvailability] = {}
        for row in rows:
            code = codes.get(req_str(row, "station_id", SOURCE))
            # Unknown or unnumbered stations cannot be mapped to a public code.
            if code is None:
                continue
            electric, mechanical = _split_types(row)
            result[code] = BikeAvailability(
                code=code,
                bikes=req_int(row, "num_bikes_available", SOURCE),
                electric=electric,
                mechanical=mechanical,
                docks=req_int(row, "num_docks_available", SOURCE),
                renting=req_bool(row, "is_renting", SOURCE),
                returning=req_bool(row, "is_returning", SOURCE),
                reported_at=_epoch(req_int(row, "last_reported", SOURCE)),
                source=SOURCE,
            )
        return result

    async def _load_information(self) -> _Information:
        async with self._lock:
            now = self._now()
            cached = self._information
            if cached is not None and now - cached.fetched_at < _INFORMATION_TTL:
                return cached
            stations: list[BikeStation] = []
            codes: dict[str, StationCode] = {}
            for row in await self._rows("station_information.json"):
                named = split_station_name(req_str(row, "name", SOURCE), SOURCE)
                if named is None:
                    continue
                code, name = named
                codes[req_str(row, "station_id", SOURCE)] = code
                stations.append(
                    BikeStation(
                        code=code,
                        name=name,
                        location=GeoPoint(
                            latitude=req_float(row, "lat", SOURCE),
                            longitude=req_float(row, "lon", SOURCE),
                        ),
                        capacity=opt_int(row, "capacity", SOURCE),
                        address=opt_str(row, "address", SOURCE),
                        source=SOURCE,
                    )
                )
            self._information = _Information(now, tuple(stations), codes)
            return self._information

    async def _rows(self, feed: str) -> list[JsonObject]:
        """GET one feed and return ``data.stations``.

        Each failure's cause is logged at debug: a short failure is not an outage.
        """
        url = self._base_url + feed
        try:
            async with self._session.get(
                url,
                headers={"User-Agent": self._user_agent},
                timeout=_TIMEOUT,
            ) as response:
                status = response.status
                raw = await response.read()
        except TimeoutError as err:
            _LOGGER.debug("No answer from %s in %d s", url, _TIMEOUT_S)
            raise SourceUnavailableError(SOURCE) from err
        except aiohttp.ClientError as err:
            _LOGGER.debug("Can't reach %s: %s", url, err)
            raise SourceUnavailableError(SOURCE) from err
        if status != 200:
            _LOGGER.debug("%s answered HTTP %s", url, status)
            raise SourceUnavailableError(SOURCE)
        try:
            body = json.loads(raw)
        except ValueError as err:
            _LOGGER.debug("%s answered no JSON", url)
            raise SourceUnavailableError(SOURCE) from err
        if not isinstance(body, Mapping):
            _LOGGER.debug("%s answered JSON that is not an object", url)
            raise SourceUnavailableError(SOURCE)
        return obj_list(req_obj(body, "data", SOURCE), "stations", SOURCE)


def _split_types(row: JsonObject) -> tuple[int | None, int | None]:
    """Count electric (EFIT, BOOST) and mechanical (ICONIC) bikes; None if unreported."""
    if row.get("vehicle_types_available") is None:
        return None, None
    electric = mechanical = 0
    for item in obj_list(row, "vehicle_types_available", SOURCE):
        kind = req_str(item, "vehicle_type_id", SOURCE)
        count = req_int(item, "count", SOURCE)
        if kind in _ELECTRIC:
            electric += count
        elif kind == _MECHANICAL:
            mechanical += count
    return electric, mechanical


def _epoch(seconds: int) -> datetime:
    try:
        return datetime.fromtimestamp(seconds, UTC)
    except OverflowError, OSError, ValueError:
        raise SourceUnavailableError(SOURCE) from None
