"""Provider wiring: which source answers first, and who answers when it fails."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.zaragoza_open_data.api.models import StationCode, StopCode
from custom_components.zaragoza_open_data.api.providers import (
    Providers,
    build_providers,
)
from tests.fixtures import FIXTURES, read_fixture

USER_AGENT = "ZaragozaOpenData/test (+https://example.invalid)"
AVANZA = "https://zaragoza-pasobus.avanzagrupo.com/frm_esquemaparadatime.php"
CITY = "https://www.zaragoza.es/sede/servicio/"
CITY_BUS = (
    CITY + "urbanismo-infraestructuras/transporte-urbano/poste-autobus/tuzsa-688.json"
)
GBFS = "https://zaragoza.publicbikesystem.net/customer/gbfs/v2/en/"
CITY_BIKE = CITY + "urbanismo-infraestructuras/estacion-bicicleta.json"


@pytest.fixture
async def providers(aioclient_mock: AiohttpClientMocker) -> AsyncIterator[Providers]:
    """Providers whose HTTP is the recorded replay."""
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield build_providers(session, USER_AGENT)
    await session.close()


def serve_avanza(aioclient_mock: AiohttpClientMocker, status: int = 200) -> None:
    """Serve the recorded operator page for stop 688."""
    aioclient_mock.get(
        AVANZA,
        content=(FIXTURES / "avanza" / "stop_688.html").read_bytes(),
        status=status,
    )


def serve_city_bus(aioclient_mock: AiohttpClientMocker) -> None:
    """Serve the recorded city answer for stop 688."""
    aioclient_mock.get(
        CITY_BUS, text=read_fixture("zaragoza_city/bus_realtime_688.json")
    )


async def test_bus_board_asks_the_operator_first(
    providers: Providers, aioclient_mock: AiohttpClientMocker
) -> None:
    """With both up, the operator answers and the city is not asked."""
    serve_avanza(aioclient_mock)
    serve_city_bus(aioclient_mock)

    board = await providers.bus_arrivals.board(StopCode("688"))

    assert board.source == "avanza"
    assert [call[1].host for call in aioclient_mock.mock_calls] == [
        "zaragoza-pasobus.avanzagrupo.com"
    ]


async def test_bus_board_falls_back_to_the_city_when_the_operator_fails(
    providers: Providers, aioclient_mock: AiohttpClientMocker
) -> None:
    """The operator failing means the city answers, and the board says so."""
    serve_avanza(aioclient_mock, status=500)
    serve_city_bus(aioclient_mock)

    board = await providers.bus_arrivals.board(StopCode("688"))

    assert board.source == "zaragoza_city"
    assert [call[1].host for call in aioclient_mock.mock_calls] == [
        "zaragoza-pasobus.avanzagrupo.com",
        "www.zaragoza.es",
    ]


async def test_bikes_come_from_gbfs_first_then_the_city(
    providers: Providers, aioclient_mock: AiohttpClientMocker
) -> None:
    """GBFS answers while up; when it fails the city list answers."""
    aioclient_mock.get(
        GBFS + "station_information.json",
        text=read_fixture("gbfs/station_information.json"),
    )
    aioclient_mock.get(
        GBFS + "station_status.json", text=read_fixture("gbfs/station_status.json")
    )

    first = await providers.bike.availability()
    assert {entry.source for entry in first.values()} == {"gbfs"}
    assert StationCode("164") in first

    aioclient_mock.clear_requests()
    aioclient_mock.get(GBFS + "station_information.json", status=500)
    aioclient_mock.get(GBFS + "station_status.json", status=500)
    aioclient_mock.get(
        CITY_BIKE,
        text=read_fixture("zaragoza_city/bizi_city_stations.json"),
    )

    second = await providers.bike.availability()
    assert {entry.source for entry in second.values()} == {"zaragoza_city"}


async def test_each_composite_has_its_own_fallback_memory(
    providers: Providers, aioclient_mock: AiohttpClientMocker
) -> None:
    """A bus operator outage does not make the bikes skip GBFS."""
    serve_avanza(aioclient_mock, status=500)
    serve_city_bus(aioclient_mock)
    aioclient_mock.get(
        GBFS + "station_information.json",
        text=read_fixture("gbfs/station_information.json"),
    )
    aioclient_mock.get(
        GBFS + "station_status.json", text=read_fixture("gbfs/station_status.json")
    )

    await providers.bus_arrivals.board(StopCode("688"))
    availability = await providers.bike.availability()

    assert {entry.source for entry in availability.values()} == {"gbfs"}
