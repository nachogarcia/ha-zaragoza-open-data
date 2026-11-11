"""The city client against recorded and injected HTTP."""

import asyncio
from collections.abc import AsyncIterator
from http import HTTPStatus
import json
import logging

import aiohttp
import pytest
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.client import (
    CityClient,
)
from custom_components.zaragoza_open_data.api.errors import SourceUnavailableError
from tests.fixtures import read_fixture

BASE = "https://www.zaragoza.es/sede/servicio/"
USER_AGENT = "ZaragozaOpenData/test (+https://example.invalid)"
TRAM = "urbanismo-infraestructuras/transporte-urbano/parada-tranvia.json"
BUS_STOPS = "urbanismo-infraestructuras/transporte-urbano/poste-autobus.json"


@pytest.fixture
async def client(aioclient_mock: AiohttpClientMocker) -> AsyncIterator[CityClient]:
    """Client."""
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield CityClient(session, USER_AGENT)
    await session.close()


async def test_get_returns_json(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Get returns json."""
    aioclient_mock.get(BASE + TRAM, text=read_fixture("zaragoza_city/tram_list.json"))

    body = await client.get(TRAM, {"srsname": "wgs84"})

    assert body["totalCount"] == 50
    assert isinstance(body["result"], list)
    assert len(body["result"]) == 50


async def test_get_all_pages_until_total_count(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Get all pages until total count."""
    for page, start in enumerate((0, 500, 1000), start=1):
        aioclient_mock.get(
            BASE + BUS_STOPS,
            params={"start": str(start)},
            text=read_fixture(f"zaragoza_city/bus_stops_page_{page}.json"),
        )

    stops = await client.get_all(BUS_STOPS, {"fl": "id,title,geometry"})

    assert len(stops) == 1271
    assert stops[0]["id"] != stops[-1]["id"]
    assert [call[1].query["start"] for call in aioclient_mock.mock_calls] == [
        "0",
        "500",
        "1000",
    ]
    assert {call[1].query["rows"] for call in aioclient_mock.mock_calls} == {"500"}
    assert {call[1].query["fl"] for call in aioclient_mock.mock_calls} == {
        "id,title,geometry"
    }


async def test_get_all_short_of_its_total_count_raises_source_unavailable(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A list that ends on an empty page before its totalCount was not read whole.

    It stops there, so a server that over-reports totalCount can't make it loop.
    """
    aioclient_mock.get(
        BASE + BUS_STOPS,
        params={"start": "0"},
        json={"totalCount": 900, "result": [{"id": "1"}]},
    )
    aioclient_mock.get(
        BASE + BUS_STOPS,
        params={"start": "500"},
        json={"totalCount": 900, "result": []},
    )

    with pytest.raises(SourceUnavailableError) as raised:
        await client.get_all(BUS_STOPS, {})

    assert raised.value.source == "zaragoza_city"
    assert len(aioclient_mock.mock_calls) == 2


async def test_get_all_of_an_empty_list_is_empty(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A list whose totalCount is 0 is read whole with no rows."""
    aioclient_mock.get(BASE + BUS_STOPS, json={"totalCount": 0, "result": []})

    assert await client.get_all(BUS_STOPS, {}) == []


async def test_error_body_with_http_200_raises_source_unavailable(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Error body with http 200 raises source unavailable."""
    aioclient_mock.get(
        BASE + "bus.json",
        status=HTTPStatus.OK,
        text=read_fixture("zaragoza_city/bus_error_200_derived.json"),
    )

    with pytest.raises(SourceUnavailableError) as raised:
        await client.get("bus.json", {})

    assert raised.value.source == "zaragoza_city"


async def test_error_body_with_http_400_raises_source_unavailable(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Error body with http 400 raises source unavailable."""
    aioclient_mock.get(
        BASE + "bus.json",
        status=HTTPStatus.BAD_REQUEST,
        text=read_fixture("zaragoza_city/bus_error_200_derived.json"),
    )

    with pytest.raises(SourceUnavailableError):
        await client.get("bus.json", {})


async def test_html_page_raises_source_unavailable(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Html page raises source unavailable."""
    aioclient_mock.get(
        BASE + "bus.json", text="<html><body>Mantenimiento</body></html>"
    )

    with pytest.raises(SourceUnavailableError):
        await client.get("bus.json", {})


async def test_json_that_is_not_an_object_raises_source_unavailable(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Json that is not an object raises source unavailable."""
    aioclient_mock.get(BASE + "bus.json", text=json.dumps([1, 2]))

    with pytest.raises(SourceUnavailableError):
        await client.get("bus.json", {})


async def test_server_error_without_body_raises_source_unavailable(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Server error without body raises source unavailable."""
    aioclient_mock.get(BASE + "bus.json", status=HTTPStatus.BAD_GATEWAY, json={})

    with pytest.raises(SourceUnavailableError):
        await client.get("bus.json", {})


@pytest.mark.parametrize("failure", [TimeoutError(), aiohttp.ClientConnectionError()])
async def test_network_failure_raises_source_unavailable(
    client: CityClient, aioclient_mock: AiohttpClientMocker, failure: Exception
) -> None:
    """Network failure raises source unavailable."""
    aioclient_mock.get(BASE + "bus.json", exc=failure)

    with pytest.raises(SourceUnavailableError) as raised:
        await client.get("bus.json", {})

    assert raised.value.source == "zaragoza_city"


def client_log(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return what the client logged, as "LEVEL message" lines."""
    return [
        f"{record.levelname} {record.getMessage()}"
        for record in caplog.records
        if record.name.endswith("zaragoza_city.client")
    ]


async def test_timeout_is_logged_at_debug_with_its_cause_kept(
    client: CityClient,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A city that doesn't answer in time: the debug log says so, the cause is kept.

    A blip is not an outage, so nothing above debug; the cause stays on the error
    for Home Assistant's own debug line.
    """
    aioclient_mock.get(BASE + TRAM, exc=TimeoutError())

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(SourceUnavailableError) as raised,
    ):
        await client.get(TRAM, {})

    assert client_log(caplog) == [f"DEBUG No answer from {BASE + TRAM} in 10 s"]
    assert isinstance(raised.value.__cause__, TimeoutError)


async def test_http_503_is_logged_at_debug(
    client: CityClient,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A city answering 503 (with its HTML page): the debug log names the status."""
    aioclient_mock.get(
        BASE + TRAM,
        status=HTTPStatus.SERVICE_UNAVAILABLE,
        text="<html><body>Service Unavailable</body></html>",
    )

    with caplog.at_level(logging.DEBUG), pytest.raises(SourceUnavailableError):
        await client.get(TRAM, {})

    assert client_log(caplog) == [f"DEBUG {BASE + TRAM} answered HTTP 503"]


async def test_connection_error_is_logged_at_debug_with_its_cause_kept(
    client: CityClient,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A city that can't be reached: the debug log carries aiohttp's reason."""
    aioclient_mock.get(
        BASE + TRAM, exc=aiohttp.ClientConnectionError("Connection reset by peer")
    )

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(SourceUnavailableError) as raised,
    ):
        await client.get(TRAM, {})

    assert client_log(caplog) == [
        f"DEBUG Can't reach {BASE + TRAM}: Connection reset by peer"
    ]
    assert isinstance(raised.value.__cause__, aiohttp.ClientConnectionError)


@pytest.mark.parametrize(
    ("body", "logged"),
    [
        ("<html><body>Mantenimiento</body></html>", "answered no JSON"),
        (json.dumps([1, 2]), "answered JSON that is not an object"),
        (
            read_fixture("zaragoza_city/bus_error_200_derived.json"),
            "answered an error: 400",
        ),
    ],
    ids=["html", "not_an_object", "error_body"],
)
async def test_unexpected_body_is_logged_at_debug(
    client: CityClient,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
    body: str,
    logged: str,
) -> None:
    """A 200 whose body isn't the expected JSON object: the debug log says what came."""
    aioclient_mock.get(BASE + TRAM, text=body)

    with caplog.at_level(logging.DEBUG), pytest.raises(SourceUnavailableError):
        await client.get(TRAM, {})

    (line,) = client_log(caplog)
    assert line.startswith(f"DEBUG {BASE + TRAM} {logged}")


async def test_short_list_is_logged_at_debug(
    client: CityClient,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A list that ends before its totalCount: the debug log says how far it got."""
    aioclient_mock.get(
        BASE + BUS_STOPS,
        params={"start": "0"},
        json={"totalCount": 900, "result": [{"id": "1"}]},
    )
    aioclient_mock.get(
        BASE + BUS_STOPS,
        params={"start": "500"},
        json={"totalCount": 900, "result": []},
    )

    with caplog.at_level(logging.DEBUG), pytest.raises(SourceUnavailableError):
        await client.get_all(BUS_STOPS, {})

    assert client_log(caplog) == [f"DEBUG {BASE + BUS_STOPS} ended after 1 of 900 rows"]


async def test_sends_user_agent(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Sends user agent."""
    aioclient_mock.get(BASE + TRAM, json={"totalCount": 0, "result": []})

    await client.get(TRAM, {})

    assert aioclient_mock.mock_calls[0][3]["User-Agent"] == USER_AGENT


async def test_source_name_is_zaragoza_city(client: CityClient) -> None:
    """Source name is zaragoza city."""
    assert client.source_name == "zaragoza_city"
