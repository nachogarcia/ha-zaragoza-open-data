"""Every adapter's contract against the real servers (opt-in, run daily).

Only the leaf adapters are checked: a composite's ``source_name`` is "a+b" by design.
"""

from collections.abc import AsyncIterator

import aiohttp
import pytest

from custom_components.zaragoza_open_data.api.adapters.avanza.bus import (
    AvanzaBusArrivals,
)
from custom_components.zaragoza_open_data.api.adapters.gbfs.bike import GbfsBike
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.air_quality import (
    CityAirQuality,
)
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.bike import (
    CityBike,
)
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.bus import (
    CityBusArrivals,
    CityBusStops,
)
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.client import (
    CityClient,
)
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.pharmacies import (
    CityPharmacies,
)
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.pollen import (
    CityPollen,
)
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.road_works import (
    CityRoadWorks,
)
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.tram import (
    CityTram,
)
from custom_components.zaragoza_open_data.api.models import StationCode, StopCode
from custom_components.zaragoza_open_data.api.providers import build_providers
from tests.integration.contracts import (
    check_air_quality_contract,
    check_bike_contract,
    check_bus_arrivals_contract,
    check_bus_catalog_contract,
    check_pharmacy_contract,
    check_pollen_contract,
    check_road_works_contract,
    check_tram_contract,
)

pytestmark = pytest.mark.live

USER_AGENT = "ZaragozaOpenData/live-tests (+https://github.com/nachogarcia/ha-zaragoza-open-data)"
TRAM = StopCode("2502")
BUS = StopCode("688")
BIZI = StationCode("164")


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    """A real session, like the one Home Assistant shares."""
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as real:
        yield real


@pytest.fixture
def city(session: aiohttp.ClientSession) -> CityClient:
    """The city's HTTP client."""
    return CityClient(session, USER_AGENT)


async def test_live_providers_build_with_a_real_session(
    session: aiohttp.ClientSession,
) -> None:
    """The wiring accepts a real session and answers a bus board."""
    providers = build_providers(session, USER_AGENT)

    board = await providers.bus_arrivals.board(BUS)

    assert board.stop_code == BUS


async def test_live_city_tram(city: CityClient) -> None:
    """The city tram feed meets the tram contract."""
    await check_tram_contract(CityTram(city), TRAM)


async def test_live_city_bus_catalog(city: CityClient) -> None:
    """The city bus stop list meets the catalog contract."""
    await check_bus_catalog_contract(CityBusStops(city), BUS)


async def test_live_city_bus_arrivals(city: CityClient) -> None:
    """The city real-time bus feed meets the arrivals contract."""
    await check_bus_arrivals_contract(CityBusArrivals(city), BUS)


async def test_live_avanza_bus_arrivals(session: aiohttp.ClientSession) -> None:
    """The operator's page meets the arrivals contract."""
    await check_bus_arrivals_contract(AvanzaBusArrivals(session, USER_AGENT), BUS)


async def test_live_gbfs_bike(session: aiohttp.ClientSession) -> None:
    """The GBFS feeds meet the bike contract."""
    await check_bike_contract(GbfsBike(session, USER_AGENT), BIZI)


async def test_live_city_bike(city: CityClient) -> None:
    """The city's Bizi list meets the bike contract.

    The city lists a varying subset of stations through the day, so the station
    checked is one the city currently lists, not a fixed code.
    """
    source = CityBike(city)
    stations = await source.stations()
    assert stations
    await check_bike_contract(source, stations[0].code)


async def test_live_city_road_works(city: CityClient) -> None:
    """The city road works meet the contract."""
    await check_road_works_contract(CityRoadWorks(city))


async def test_live_city_pharmacies(city: CityClient) -> None:
    """The city duty pharmacies meet the contract."""
    await check_pharmacy_contract(CityPharmacies(city))


async def test_live_city_air_quality(city: CityClient) -> None:
    """The city air quality feed meets the contract."""
    await check_air_quality_contract(CityAirQuality(city))


async def test_live_city_pollen(city: CityClient) -> None:
    """The city pollen feed meets the contract."""
    await check_pollen_contract(CityPollen(city))
