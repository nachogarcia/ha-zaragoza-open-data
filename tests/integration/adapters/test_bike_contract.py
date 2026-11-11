"""Both bike providers meet the same contract (leaf adapters, never a composite)."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.zaragoza_open_data.api.adapters.gbfs.bike import GbfsBike
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.bike import (
    CityBike,
)
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.client import (
    CityClient,
)
from custom_components.zaragoza_open_data.api.models import StationCode
from custom_components.zaragoza_open_data.api.ports import BikeSource
from tests.fixtures import read_fixture
from tests.integration.contracts import check_bike_contract

USER_AGENT = "ZaragozaOpenData/test (+https://example.invalid)"
GBFS = "https://zaragoza.publicbikesystem.net/customer/gbfs/v2/en/"
CITY = "https://www.zaragoza.es/sede/servicio/urbanismo-infraestructuras/"


def serve_all(aioclient_mock: AiohttpClientMocker) -> None:
    """Serve both providers' recorded answers."""
    aioclient_mock.get(
        GBFS + "station_information.json",
        text=read_fixture("gbfs/station_information.json"),
    )
    aioclient_mock.get(
        GBFS + "station_status.json", text=read_fixture("gbfs/station_status.json")
    )
    aioclient_mock.get(
        CITY + "estacion-bicicleta.json",
        text=read_fixture("zaragoza_city/bizi_city_stations.json"),
    )


@pytest.fixture(params=["gbfs", "zaragoza_city"])
async def source(
    request: pytest.FixtureRequest, aioclient_mock: AiohttpClientMocker
) -> AsyncIterator[BikeSource]:
    """Each provider on its recorded answers."""
    serve_all(aioclient_mock)
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    adapter: BikeSource
    if request.param == "gbfs":
        adapter = GbfsBike(session, USER_AGENT)
    else:
        adapter = CityBike(CityClient(session, USER_AGENT))
    yield adapter
    await session.close()


async def test_bike_contract(source: BikeSource) -> None:
    """Every bike provider lists stations and gives availability for station 164."""
    await check_bike_contract(source, StationCode("164"))


async def test_same_station_number_from_both_sources(
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Station 164 is the same place under the same code in both providers."""
    serve_all(aioclient_mock)
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    gbfs = GbfsBike(session, USER_AGENT)
    city = CityBike(CityClient(session, USER_AGENT))
    code = StationCode("164")

    gbfs_station = next(s for s in await gbfs.stations() if s.code == code)
    city_station = next(s for s in await city.stations() if s.code == code)
    gbfs_entry = (await gbfs.availability())[code]
    city_entry = (await city.availability())[code]
    await session.close()

    assert gbfs_station.name == city_station.name == "Rosales: Illueca"
    assert gbfs_station.location.distance_to(city_station.location) < 50
    assert (gbfs_entry.source, city_entry.source) == ("gbfs", "zaragoza_city")
