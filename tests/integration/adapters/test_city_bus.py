"""The city bus adapters against recorded HTTP."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
import logging

import pytest
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.bus import (
    CityBusArrivals,
    CityBusStops,
)
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.client import (
    CityClient,
)
from custom_components.zaragoza_open_data.api.errors import SourceUnavailableError
from custom_components.zaragoza_open_data.api.models import Mode, StopCode
from tests.fixtures import read_fixture
from tests.integration.contracts import (
    check_bus_arrivals_contract,
    check_bus_catalog_contract,
)

BASE = "https://www.zaragoza.es/sede/servicio/"
USER_AGENT = "ZaragozaOpenData/test (+https://example.invalid)"
STOPS = "urbanismo-infraestructuras/transporte-urbano/poste-autobus.json"
REALTIME = "urbanismo-infraestructuras/transporte-urbano/poste-autobus/tuzsa-688.json"
# Fixture instant: lastUpdated 2026-11-09T13:41:19 Madrid (UTC+1).
OBSERVED = datetime(2026, 11, 9, 12, 41, 19, tzinfo=UTC)


@pytest.fixture
async def client(aioclient_mock: AiohttpClientMocker) -> AsyncIterator[CityClient]:
    """Client whose HTTP is the recorded replay."""
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield CityClient(session, USER_AGENT)
    await session.close()


def serve_stops(aioclient_mock: AiohttpClientMocker) -> None:
    """Serve the three recorded stop-list pages, keyed by ``start``."""
    pages = {
        "0": "bus_stops_page_1.json",
        "500": "bus_stops_page_2.json",
        "1000": "bus_stops_page_3.json",
    }

    for start, name in pages.items():
        aioclient_mock.get(
            BASE + STOPS,
            params={"start": start},
            text=read_fixture(f"zaragoza_city/{name}"),
        )


def serve_realtime(
    aioclient_mock: AiohttpClientMocker,
    fixture: str = "bus_realtime_688.json",
    status: int = 200,
) -> None:
    """Serve a recorded real-time answer for stop 688."""
    aioclient_mock.get(
        BASE + REALTIME, text=read_fixture(f"zaragoza_city/{fixture}"), status=status
    )


async def test_city_stop_list_parses_all_pages(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """The city stop list reads every page and parses code, name and lines."""
    serve_stops(aioclient_mock)

    stops = await CityBusStops(client).stops()

    # 1,271 rows: 983 urban stops, 5 of them tram platforms, and 288 that aren't.
    assert len(stops) == 978
    assert all(stop.mode is Mode.BUS for stop in stops)
    stop = next(s for s in stops if s.code == "688")
    assert stop.name == "P. Reyes de Aragón N.º 24"
    assert stop.lines == ("58",)
    assert stop.direction is None
    assert stop.location.latitude == pytest.approx(41.62702649728611)
    assert stop.location.longitude == pytest.approx(-0.9072975810322448)
    queries = [call[1].query for call in aioclient_mock.mock_calls]
    assert [q["start"] for q in queries] == ["0", "500", "1000"]
    assert all(q["fl"] == "id,title,geometry" for q in queries)


async def test_city_stop_list_has_only_urban_bus_stops(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """The list's other network and its tram platforms are left out.

    The city lists another network's stops ("rural-N", line 501 among them, with
    no real time anywhere) and tram platforms ("TRA" their only line) among the
    urban stops, and 175 numbers belong to both networks. Each number is one
    urban stop.
    """
    serve_stops(aioclient_mock)

    stops = await CityBusStops(client).stops()

    by_code = {stop.code: stop for stop in stops}
    assert len(by_code) == len(stops)
    # "(338) Esquina calle Atiliana Líneas: 501" comes first in the list.
    coso = by_code[StopCode("338")]
    assert coso.name == "Coso N.º 126"
    assert coso.lines == ("22", "35", "N1", "28", "21", "32")
    # "(1) Principio de Línea Líneas: 501" and "(1) Mago de Oz Líneas: TRA".
    assert StopCode("1") not in by_code
    # Tram platforms only: Mago de Oz, Plaza Aragón, Un americano en París.
    assert not {"2", "11", "12", "22"} & set(by_code)
    # Only in the other network: "(900) Terminal Líneas: 603, 605".
    assert StopCode("900") not in by_code
    assert all("TRA" not in stop.lines for stop in stops)


async def test_tram_dropped_from_a_bus_stops_lines(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A bus stop that also lists the tram keeps only its bus lines.

    No such row on 2026-11-09: this is stop 338's real row with "TRA" added.
    """
    aioclient_mock.get(
        BASE + STOPS,
        json={
            "totalCount": 1,
            "result": [
                {
                    "id": "tuzsa-338",
                    "title": "(338) Coso N.º 126 Líneas: 22, TRA, 35, N1",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [-0.875490310391522, 41.650876726538016],
                    },
                }
            ],
        },
    )

    (stop,) = await CityBusStops(client).stops()

    assert stop.lines == ("22", "35", "N1")


async def test_repeated_stop_number_keeps_the_first_quietly(
    client: CityClient,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A number listed twice among the urban stops is its first row; nothing is logged.

    No such pair on 2026-11-09: stop 338's real row, then a renamed copy.
    """
    geometry = {
        "type": "Point",
        "coordinates": [-0.875490310391522, 41.650876726538016],
    }
    aioclient_mock.get(
        BASE + STOPS,
        json={
            "totalCount": 2,
            "result": [
                {
                    "id": "tuzsa-338",
                    "title": "(338) Coso N.º 126 Líneas: 22, 35, N1, 28, 21, 32",
                    "geometry": geometry,
                },
                {
                    "id": "tuzsa-338",
                    "title": "(338) Repeated Stop Second Copy Líneas: 99",
                    "geometry": geometry,
                },
            ],
        },
    )

    with caplog.at_level(logging.DEBUG):
        (stop,) = await CityBusStops(client).stops()

    assert (stop.name, stop.lines) == (
        "Coso N.º 126",
        ("22", "35", "N1", "28", "21", "32"),
    )
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


async def test_title_without_lines(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A stop title without ``Líneas:`` gives no lines."""
    aioclient_mock.get(
        BASE + STOPS,
        json={
            "totalCount": 1,
            "result": [
                {
                    "id": "tuzsa-9",
                    "title": "(9) Calle Prueba 3",
                    "geometry": {"type": "Point", "coordinates": [-0.9, 41.6]},
                }
            ],
        },
    )

    (stop,) = await CityBusStops(client).stops()

    assert (stop.code, stop.name, stop.lines) == ("9", "Calle Prueba 3", ())


async def test_title_with_several_lines(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Several lines in a title are split, whatever the separator."""
    aioclient_mock.get(
        BASE + STOPS,
        json={
            "totalCount": 1,
            "result": [
                {
                    "id": "tuzsa-9",
                    "title": "(9) Calle Prueba 3 Líneas: 22, N1 40",
                    "geometry": {"type": "Point", "coordinates": [-0.9, 41.6]},
                }
            ],
        },
    )

    (stop,) = await CityBusStops(client).stops()

    assert stop.lines == ("22", "N1", "40")


async def test_stop_title_without_code_is_source_unavailable(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A title that does not start with ``(code)`` is a changed format."""
    aioclient_mock.get(
        BASE + STOPS,
        json={
            "totalCount": 1,
            "result": [
                {
                    "id": "tuzsa-9",
                    "title": "Calle Prueba 3",
                    "geometry": {"type": "Point", "coordinates": [-0.9, 41.6]},
                }
            ],
        },
    )

    with pytest.raises(SourceUnavailableError):
        await CityBusStops(client).stops()


async def test_city_catalog_meets_contract(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """The city catalog meets the catalog contract."""
    serve_stops(aioclient_mock)

    await check_bus_catalog_contract(CityBusStops(client), StopCode("688"))


async def test_city_arrivals_parse_minutes_and_at_stop(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Minutes text becomes expected times; ``En la parada.`` means now."""
    aioclient_mock.get(
        BASE + REALTIME,
        json={
            "lastUpdated": "2026-11-09T13:41:19",
            "destinos": [
                {
                    "linea": "58",
                    "destino": "FUENTE JUNQUERA,",
                    "primero": "En la parada.",
                    "segundo": "24 minutos.",
                }
            ],
        },
    )

    board = await CityBusArrivals(client).board(StopCode("688"))

    assert board.source == "zaragoza_city"
    assert board.observed_at == OBSERVED
    assert [(a.line, a.destination, a.expected_at) for a in board.arrivals] == [
        ("58", "FUENTE JUNQUERA", OBSERVED),
        ("58", "FUENTE JUNQUERA", OBSERVED + timedelta(minutes=24)),
    ]


async def test_city_arrivals_recorded_stop_688(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """The recorded answer for stop 688 gives two buses of line 58."""
    serve_realtime(aioclient_mock)

    board = await CityBusArrivals(client).board(StopCode("688"))

    assert [a.expected_at - OBSERVED for a in board.arrivals] == [
        timedelta(minutes=24),
        timedelta(minutes=48),
    ]
    call = aioclient_mock.mock_calls[0]
    assert "fl" not in call[1].query


async def test_city_unknown_time_text_is_skipped(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Estimates that are not times are skipped; the board is not an error."""
    serve_realtime(aioclient_mock, "bus_realtime_688_unknown_time_derived.json")

    board = await CityBusArrivals(client).board(StopCode("688"))

    assert [a.expected_at for a in board.arrivals] == [OBSERVED]


async def test_city_stop_without_destinos_gives_empty_board(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A stop with no destinos gives an empty board."""
    aioclient_mock.get(BASE + REALTIME, json={"lastUpdated": "2026-11-09T13:41:19"})

    board = await CityBusArrivals(client).board(StopCode("688"))

    assert board.arrivals == ()
    assert board.observed_at == OBSERVED


@pytest.mark.parametrize("status", [200, 400])
async def test_city_error_json_raises(
    client: CityClient, aioclient_mock: AiohttpClientMocker, status: int
) -> None:
    """The city's error body is source unavailable with HTTP 200 and with 400."""
    serve_realtime(aioclient_mock, "bus_error_200_derived.json", status)

    with pytest.raises(SourceUnavailableError) as raised:
        await CityBusArrivals(client).board(StopCode("688"))

    assert raised.value.source == "zaragoza_city"


async def test_city_arrivals_meet_contract(
    client: CityClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """The city arrivals meet the arrivals contract."""
    serve_realtime(aioclient_mock)

    await check_bus_arrivals_contract(CityBusArrivals(client), StopCode("688"))
