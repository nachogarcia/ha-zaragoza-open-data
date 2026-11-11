"""The city pollen adapter against recorded HTTP."""

import asyncio
from collections.abc import AsyncIterator
from datetime import date
import json
import logging

import pytest
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.client import (
    CityClient,
)
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.pollen import (
    CityPollen,
)
from custom_components.zaragoza_open_data.api.errors import SourceUnavailableError
from custom_components.zaragoza_open_data.api.models import PollenLevel
from tests.fixtures import read_fixture
from tests.integration.contracts import check_pollen_contract

BASE = "https://www.zaragoza.es/sede/servicio/"
USER_AGENT = "ZaragozaOpenData/test (+https://example.invalid)"
PATH = "informacion-polen.json"


@pytest.fixture
async def pollen(aioclient_mock: AiohttpClientMocker) -> AsyncIterator[CityPollen]:
    """Adapter whose HTTP replays the recorded list."""
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield CityPollen(CityClient(session, USER_AGENT))
    await session.close()


def serve(aioclient_mock: AiohttpClientMocker, text: str | None = None) -> None:
    """Serve the recorded pollen list, or ``text``."""
    aioclient_mock.get(
        BASE + PATH, text=text or read_fixture("zaragoza_city/pollen.json")
    )


async def test_pollen_fourteen_plants_levels(
    pollen: CityPollen, aioclient_mock: AiohttpClientMocker
) -> None:
    """14 plants; ``nulo`` is NONE, ``bajo`` LOW; the date is the observation's."""
    serve(aioclient_mock)

    readings = await pollen.readings()

    assert pollen.source_name == "zaragoza_city"
    assert len(readings) == 14
    by_id = {r.plant_id: r for r in readings}
    assert by_id["Cupressaceae"].level is PollenLevel.LOW
    assert by_id["Cupressaceae"].plant_name == "Cupresaceas"
    assert by_id["Pinus"].level is PollenLevel.NONE
    assert by_id["Plantago"].plant_name == "Plántago"
    assert all(r.published_on == date(2026, 11, 1) for r in readings)
    assert {r.level for r in readings} == {PollenLevel.LOW, PollenLevel.NONE}


async def test_every_published_level_maps(
    pollen: CityPollen, aioclient_mock: AiohttpClientMocker
) -> None:
    """``moderado``, ``alto`` and ``muy alto`` (with a space) map to their levels."""
    data = json.loads(read_fixture("zaragoza_city/pollen.json"))
    for row, value in zip(
        data["result"], ("moderado", "alto", "muy alto", "bajo", "nulo"), strict=False
    ):
        row["observation"][0]["value"] = value
    serve(aioclient_mock, json.dumps(data))

    levels = [r.level for r in (await pollen.readings())[:5]]

    assert levels == [
        PollenLevel.MODERATE,
        PollenLevel.HIGH,
        PollenLevel.VERY_HIGH,
        PollenLevel.LOW,
        PollenLevel.NONE,
    ]


async def test_unknown_level_text_is_none_and_logged_at_debug(
    pollen: CityPollen,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A level the city adds later is ``None``; the other plants are kept."""
    data = json.loads(read_fixture("zaragoza_city/pollen.json"))
    data["result"][0]["observation"][0]["value"] = "extremo"
    serve(aioclient_mock, json.dumps(data))

    with caplog.at_level(logging.DEBUG):
        readings = await pollen.readings()

    assert readings[0].level is None
    assert len(readings) == 14
    logged = [r for r in caplog.records if "extremo" in r.getMessage()]
    assert logged
    assert {r.levelno for r in logged} == {logging.DEBUG}


async def test_plant_without_an_observation_is_skipped(
    pollen: CityPollen,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A plant with no observation yet has no level to show: left out, debug log."""
    data = json.loads(read_fixture("zaragoza_city/pollen.json"))
    data["result"][1]["observation"] = []
    serve(aioclient_mock, json.dumps(data))

    with caplog.at_level(logging.DEBUG):
        readings = await pollen.readings()

    assert len(readings) == 13
    assert "Artemisia_vulgaris" not in {r.plant_id for r in readings}
    assert any("Artemisia_vulgaris" in r.getMessage() for r in caplog.records)


async def test_requests_the_pollen_list_with_user_agent(
    pollen: CityPollen, aioclient_mock: AiohttpClientMocker
) -> None:
    """One request to the pollen list, with the integration's User-Agent."""
    serve(aioclient_mock)

    await pollen.readings()

    (call,) = aioclient_mock.mock_calls
    assert call[1].path == "/sede/servicio/" + PATH
    assert call[3]["User-Agent"] == USER_AGENT


async def test_malformed_date_is_source_unavailable(
    pollen: CityPollen, aioclient_mock: AiohttpClientMocker
) -> None:
    """A date that is not a timestamp means the city changed its format."""
    data = json.loads(read_fixture("zaragoza_city/pollen.json"))
    data["result"][0]["observation"][0]["publicationDate"] = "last week"
    serve(aioclient_mock, json.dumps(data))

    with pytest.raises(SourceUnavailableError):
        await pollen.readings()


async def test_error_body_with_http_200_is_source_unavailable(
    pollen: CityPollen, aioclient_mock: AiohttpClientMocker
) -> None:
    """The city's ``{"status": 400}`` body is an outage."""
    serve(aioclient_mock, read_fixture("zaragoza_city/bus_error_200_derived.json"))

    with pytest.raises(SourceUnavailableError) as raised:
        await pollen.readings()

    assert raised.value.source == "zaragoza_city"


async def test_pollen_contract(
    pollen: CityPollen, aioclient_mock: AiohttpClientMocker
) -> None:
    """The city adapter meets the pollen contract."""
    serve(aioclient_mock)

    await check_pollen_contract(pollen)
