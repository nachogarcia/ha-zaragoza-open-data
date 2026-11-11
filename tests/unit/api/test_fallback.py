"""Behaviour of the operator-first, city-fallback policy."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.zaragoza_open_data.api.errors import SourceUnavailableError
from custom_components.zaragoza_open_data.api.fallback import (
    FallbackBikeSource,
    FallbackBusArrivals,
    FallbackPolicy,
)
from custom_components.zaragoza_open_data.api.models import (
    ArrivalBoard,
    BikeAvailability,
    BikeStation,
    GeoPoint,
    StationCode,
    StopCode,
)
from custom_components.zaragoza_open_data.api.ports import BikeSource, BusArrivalsSource

from .stubs import StubBike, StubBusArrivals

START = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
STOP = StopCode("688")
STATION = StationCode("164")


class Clock:
    """A controllable clock."""

    def __init__(self) -> None:
        """Start at a fixed instant."""
        self.current = START

    def __call__(self) -> datetime:
        """Return the current instant."""
        return self.current

    def advance(self, delta: timedelta) -> None:
        """Move time forward."""
        self.current += delta


def _board(source: str) -> ArrivalBoard:
    return ArrivalBoard(stop_code=STOP, arrivals=(), observed_at=START, source=source)


def _availability(source: str) -> BikeAvailability:
    return BikeAvailability(
        code=STATION,
        bikes=3,
        electric=1,
        mechanical=2,
        docks=5,
        renting=True,
        returning=True,
        reported_at=START,
        source=source,
    )


def _bus(
    primary: StubBusArrivals, fallback: StubBusArrivals, clock: Clock
) -> BusArrivalsSource:
    return FallbackBusArrivals(primary, fallback, FallbackPolicy(now=clock))


async def test_uses_primary_when_it_works() -> None:
    """A healthy primary answers and the fallback is never called."""
    primary = StubBusArrivals("avanza", _board("avanza"))
    fallback = StubBusArrivals("zaragoza_city", _board("zaragoza_city"))

    board = await _bus(primary, fallback, Clock()).board(STOP)

    assert board.source == "avanza"
    assert fallback.calls == 0


async def test_falls_back_when_primary_fails() -> None:
    """A failing primary is covered by the fallback in the same call."""
    primary = StubBusArrivals("avanza", fail=True)
    fallback = StubBusArrivals("zaragoza_city", _board("zaragoza_city"))

    board = await _bus(primary, fallback, Clock()).board(STOP)

    assert board.source == "zaragoza_city"
    assert (primary.calls, fallback.calls) == (1, 1)


async def test_skips_primary_for_five_minutes_after_failure() -> None:
    """The primary is not tried again until five minutes have passed."""
    clock = Clock()
    primary = StubBusArrivals("avanza", fail=True)
    fallback = StubBusArrivals("zaragoza_city", _board("zaragoza_city"))
    source = _bus(primary, fallback, clock)
    await source.board(STOP)

    clock.advance(timedelta(minutes=4, seconds=59))
    await source.board(STOP)
    assert primary.calls == 1

    clock.advance(timedelta(seconds=1))
    await source.board(STOP)
    assert primary.calls == 2


async def test_returns_to_primary_once_it_recovers() -> None:
    """After the retry window a working primary answers again."""
    clock = Clock()
    failing = StubBusArrivals("avanza", fail=True)
    fallback = StubBusArrivals("zaragoza_city", _board("zaragoza_city"))
    policy = FallbackPolicy(now=clock)
    healthy = StubBusArrivals("avanza", _board("avanza"))

    async def primary() -> ArrivalBoard:
        return await (healthy if clock.current > START else failing).board(STOP)

    async def other() -> ArrivalBoard:
        return await fallback.board(STOP)

    assert (await policy.run(primary, other)).source == "zaragoza_city"
    clock.advance(timedelta(minutes=5))
    assert (await policy.run(primary, other)).source == "avanza"


async def test_raises_when_both_fail() -> None:
    """With both sources down the fallback's error reaches the caller."""
    primary = StubBusArrivals("avanza", fail=True)
    fallback = StubBusArrivals("zaragoza_city", fail=True)

    with pytest.raises(SourceUnavailableError) as raised:
        await _bus(primary, fallback, Clock()).board(STOP)

    assert raised.value.source == fallback.source_name


async def test_board_reports_which_source_answered() -> None:
    """The board keeps the answering adapter's name; the composite names both."""
    primary = StubBusArrivals("avanza", fail=True)
    fallback = StubBusArrivals("zaragoza_city", _board("zaragoza_city"))
    source = _bus(primary, fallback, Clock())

    board = await source.board(STOP)

    assert board.source == "zaragoza_city"
    assert source.source_name == "avanza+zaragoza_city"


async def test_bike_stations_and_availability_share_the_fallback_window() -> None:
    """A failure on either bike call moves both calls to the fallback."""
    clock = Clock()
    station = BikeStation(
        code=STATION,
        name="Plaza",
        location=GeoPoint(41.65, -0.88),
        capacity=20,
        address=None,
        source="zaragoza_city",
    )
    primary = StubBike("gbfs", fail=True)
    fallback = StubBike(
        "zaragoza_city",
        (station,),
        {STATION: _availability("zaragoza_city")},
    )
    source: BikeSource = FallbackBikeSource(
        primary, fallback, FallbackPolicy(now=clock)
    )

    stations = await source.stations()
    availability = await source.availability()

    assert stations == (station,)
    assert availability[STATION].source == "zaragoza_city"
    assert primary.calls == 1
    assert source.source_name == "gbfs+zaragoza_city"
