"""Tiny stand-ins for ports, used only by the fallback unit tests."""

from collections.abc import Mapping

from custom_components.zaragoza_open_data.api.errors import SourceUnavailableError
from custom_components.zaragoza_open_data.api.models import (
    ArrivalBoard,
    BikeAvailability,
    BikeStation,
    StationCode,
    StopCode,
)


class StubBusArrivals:
    """A bus source that returns one board or fails, counting its calls."""

    def __init__(
        self,
        source_name: str,
        board: ArrivalBoard | None = None,
        *,
        fail: bool = False,
    ) -> None:
        """Set what to return (or ``fail=True``)."""
        self._source_name = source_name
        self._board = board
        self._fail = fail
        self.calls = 0

    @property
    def source_name(self) -> str:
        """Name of the stubbed provider."""
        return self._source_name

    async def board(self, code: StopCode) -> ArrivalBoard:
        """Return the board, or raise when told to fail."""
        self.calls += 1
        if self._fail or self._board is None:
            raise SourceUnavailableError(self._source_name)
        return self._board


class StubBike:
    """A bike source that returns fixed results or fails, counting its calls."""

    def __init__(
        self,
        source_name: str,
        stations: tuple[BikeStation, ...] = (),
        availability: Mapping[StationCode, BikeAvailability] | None = None,
        *,
        fail: bool = False,
    ) -> None:
        """Set what to return (or ``fail=True``)."""
        self._source_name = source_name
        self._stations = stations
        self._availability = availability or {}
        self._fail = fail
        self.calls = 0

    @property
    def source_name(self) -> str:
        """Name of the stubbed provider."""
        return self._source_name

    async def stations(self) -> tuple[BikeStation, ...]:
        """Return the stations, or raise when told to fail."""
        self.calls += 1
        if self._fail:
            raise SourceUnavailableError(self._source_name)
        return self._stations

    async def availability(self) -> Mapping[StationCode, BikeAvailability]:
        """Return the availability, or raise when told to fail."""
        self.calls += 1
        if self._fail:
            raise SourceUnavailableError(self._source_name)
        return self._availability
