"""Both bus arrival providers meet the same contract (leaf adapters, never a composite)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.zaragoza_open_data.api.adapters.avanza.bus import (
    AvanzaBusArrivals,
)
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.bus import (
    CityBusArrivals,
)
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.client import (
    CityClient,
)
from custom_components.zaragoza_open_data.api.models import StopCode
from custom_components.zaragoza_open_data.api.ports import BusArrivalsSource
from tests.fixtures import FIXTURES, read_fixture
from tests.integration.contracts import check_bus_arrivals_contract

USER_AGENT = "ZaragozaOpenData/test (+https://example.invalid)"
CITY = (
    "https://www.zaragoza.es/sede/servicio/urbanismo-infraestructuras/"
    "transporte-urbano/poste-autobus/tuzsa-688.json"
)
AVANZA = "https://zaragoza-pasobus.avanzagrupo.com/frm_esquemaparadatime.php"


@pytest.fixture(params=["avanza", "zaragoza_city"])
async def source(
    request: pytest.FixtureRequest, aioclient_mock: AiohttpClientMocker
) -> AsyncIterator[BusArrivalsSource]:
    """Each provider on its recorded answer for stop 688."""
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    adapter: BusArrivalsSource
    if request.param == "avanza":
        aioclient_mock.get(
            AVANZA, content=(FIXTURES / "avanza" / "stop_688.html").read_bytes()
        )
        adapter = AvanzaBusArrivals(
            session, USER_AGENT, lambda: datetime(2026, 11, 9, 12, 41, tzinfo=UTC)
        )
    else:
        aioclient_mock.get(
            CITY, text=read_fixture("zaragoza_city/bus_realtime_688.json")
        )
        adapter = CityBusArrivals(CityClient(session, USER_AGENT))
    yield adapter
    await session.close()


async def test_bus_arrivals_contract(source: BusArrivalsSource) -> None:
    """Every bus arrivals provider returns a board for a known stop."""
    await check_bus_arrivals_contract(source, StopCode("688"))
