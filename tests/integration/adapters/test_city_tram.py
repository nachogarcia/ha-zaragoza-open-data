"""The city tram adapter against recorded HTTP."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.client import (
    CityClient,
)
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.tram import (
    CityTram,
)
from custom_components.zaragoza_open_data.api.errors import SourceUnavailableError
from custom_components.zaragoza_open_data.api.models import Mode, Stop, StopCode
from tests.fixtures import read_fixture
from tests.integration.contracts import check_tram_contract

BASE = "https://www.zaragoza.es/sede/servicio/"
USER_AGENT = "ZaragozaOpenData/test (+https://example.invalid)"
TRAM = "urbanismo-infraestructuras/transporte-urbano/parada-tranvia.json"
# Fixture instant: lastUpdated 2026-11-09T13:40:02 Madrid (UTC+1).
OBSERVED = datetime(2026, 11, 9, 12, 40, 2, tzinfo=UTC)


class Clock:
    """A settable clock handed to the adapter."""

    def __init__(self) -> None:
        """Start at the moment the fixtures were recorded."""
        self.value = OBSERVED

    def __call__(self) -> datetime:
        """Return the current fake time."""
        return self.value


@pytest.fixture
def clock() -> Clock:
    """Clock."""
    return Clock()


@pytest.fixture
async def tram(
    aioclient_mock: AiohttpClientMocker, clock: Clock
) -> AsyncIterator[CityTram]:
    """Adapter whose HTTP replays the recorded tram list."""
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield CityTram(CityClient(session, USER_AGENT), clock)
    await session.close()


def serve(aioclient_mock: AiohttpClientMocker, fixture: str = "tram_list.json") -> None:
    """Serve a recorded tram list."""
    aioclient_mock.get(BASE + TRAM, text=read_fixture(f"zaragoza_city/{fixture}"))


def by_code(stops: tuple[Stop, ...], code: str) -> Stop:
    """Pick one stop."""
    return next(stop for stop in stops if stop.code == code)


async def test_meets_tram_contract(
    tram: CityTram, aioclient_mock: AiohttpClientMocker
) -> None:
    """Meets tram contract."""
    serve(aioclient_mock)

    await check_tram_contract(tram, StopCode("2502"))


async def test_parses_fifty_platforms_with_direction(
    tram: CityTram, aioclient_mock: AiohttpClientMocker
) -> None:
    """Parses fifty platforms with direction."""
    serve(aioclient_mock)

    stops = await tram.stops()

    assert len(stops) == 50
    assert all(stop.mode is Mode.TRAM for stop in stops)
    mago = by_code(stops, "2502")
    assert mago.name == "Mago de Oz"
    assert mago.direction == "Avenida de la Academia"
    assert mago.lines == ("L1",)
    assert mago.location.latitude == pytest.approx(41.6243756)
    assert mago.location.longitude == pytest.approx(-0.9364509)
    plaza = by_code(stops, "1311")
    assert plaza.name == "Plaza Aragon"
    assert plaza.direction == "Mago de Oz"


async def test_arrival_only_platform_has_no_direction(
    tram: CityTram, aioclient_mock: AiohttpClientMocker
) -> None:
    """Arrival only platform has no direction."""
    serve(aioclient_mock)

    stops = await tram.stops()

    assert by_code(stops, "2501").direction is None
    assert by_code(stops, "102").direction is None


async def test_unknown_last_digit_gives_no_direction(
    tram: CityTram, aioclient_mock: AiohttpClientMocker
) -> None:
    """Unknown last digit gives no direction."""
    serve(aioclient_mock, "tram_list_unknown_digit_derived.json")

    stops = await tram.stops()

    assert by_code(stops, "2603").direction is None
    assert by_code(stops, "2603").name == "Mago de Oz"


async def test_board_expected_times_are_observed_plus_minutes(
    tram: CityTram, aioclient_mock: AiohttpClientMocker
) -> None:
    """Board expected times are observed plus minutes."""
    serve(aioclient_mock)

    board = (await tram.boards())[StopCode("2502")]

    assert board.source == "zaragoza_city"
    assert board.observed_at == OBSERVED
    assert [a.expected_at for a in board.arrivals] == [
        OBSERVED + timedelta(minutes=4),
        OBSERVED + timedelta(minutes=8),
    ]
    assert {(a.line, a.destination) for a in board.arrivals} == {
        ("L1", "Avenida Academia")
    }


async def test_missing_destinos_gives_empty_board(
    tram: CityTram, aioclient_mock: AiohttpClientMocker
) -> None:
    """Missing destinos gives empty board."""
    serve(aioclient_mock)

    board = (await tram.boards())[StopCode("102")]

    assert board.arrivals == ()


async def test_night_every_board_empty_without_error(
    tram: CityTram, aioclient_mock: AiohttpClientMocker
) -> None:
    """Night every board empty without error."""
    serve(aioclient_mock, "tram_list_night_derived.json")

    boards = await tram.boards()
    stops = await tram.stops()

    assert len(boards) == 50
    assert all(board.arrivals == () for board in boards.values())
    assert len(stops) == 50


async def test_boilerplate_notices_removed_real_notice_kept(
    tram: CityTram, aioclient_mock: AiohttpClientMocker
) -> None:
    """Boilerplate notices removed real notice kept."""
    serve(aioclient_mock, "tram_list_notice_derived.json")

    boards = await tram.boards()

    assert boards[StopCode("101")].notices == (
        "Por obras, el servicio entre Parque Goya y Valdespartera se presta en "
        "autobús hasta nuevo aviso.",
    )
    assert boards[StopCode("2502")].notices == ()


async def test_one_request_serves_stops_and_boards_within_30_s(
    tram: CityTram, aioclient_mock: AiohttpClientMocker, clock: Clock
) -> None:
    """One request serves stops and boards within 30 s."""
    serve(aioclient_mock)

    await tram.stops()
    await tram.boards()
    clock.value += timedelta(seconds=29)
    await tram.boards()

    assert aioclient_mock.call_count == 1
    query = aioclient_mock.mock_calls[0][1].query
    assert query["rows"] == "500"
    assert "fl" not in query

    clock.value += timedelta(seconds=2)
    await tram.boards()

    assert aioclient_mock.call_count == 2


async def test_malformed_timestamp_is_source_unavailable(
    tram: CityTram, aioclient_mock: AiohttpClientMocker
) -> None:
    """Malformed timestamp is source unavailable."""
    serve(aioclient_mock, "tram_list_bad_timestamp_derived.json")

    with pytest.raises(SourceUnavailableError) as raised:
        await tram.boards()

    assert raised.value.source == "zaragoza_city"


async def test_error_body_is_source_unavailable(
    tram: CityTram, aioclient_mock: AiohttpClientMocker
) -> None:
    """Error body is source unavailable."""
    aioclient_mock.get(
        BASE + TRAM, text=read_fixture("zaragoza_city/bus_error_200_derived.json")
    )

    with pytest.raises(SourceUnavailableError):
        await tram.stops()
