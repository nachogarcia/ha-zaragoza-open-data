"""Provider HTTP for acceptance tests, answered from the recorded fixtures."""

import json

from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from tests.fixtures import read_fixture

CITY = "https://www.zaragoza.es/sede/servicio/"
TRAM_LIST = CITY + "urbanismo-infraestructuras/transporte-urbano/parada-tranvia.json"
BUS_STOPS = CITY + "urbanismo-infraestructuras/transporte-urbano/poste-autobus.json"
CITY_BUS = (
    CITY + "urbanismo-infraestructuras/transporte-urbano/poste-autobus/tuzsa-{}.json"
)
CITY_BIZI = CITY + "urbanismo-infraestructuras/estacion-bicicleta.json"
AIR_STATIONS = CITY + "calidad-aire/listado.json"
ROAD_WORKS = CITY + "via-publica/incidencia.json"
ROAD_WORKS_TODAY = CITY + "via-publica/incidencia/conservacion-hoy.json"
PHARMACIES = CITY + "farmacia.json"
POLLEN = CITY + "informacion-polen.json"
AVANZA = "https://zaragoza-pasobus.avanzagrupo.com/frm_esquemaparadatime.php"
GBFS = "https://zaragoza.publicbikesystem.net/customer/gbfs/v2/en/"
GBFS_STATIONS = GBFS + "station_information.json"
GBFS_STATUS = GBFS + "station_status.json"


def serve_tram_list(
    aioclient_mock: AiohttpClientMocker,
    status: int = 200,
    fixture: str = "tram_list.json",
) -> None:
    """Answer the city's tram list (all 50 platforms), or fail with ``status``.

    ``fixture`` picks a recorded variant, such as ``tram_list_night_derived.json``.
    """
    aioclient_mock.get(
        TRAM_LIST,
        text=read_fixture(f"zaragoza_city/{fixture}") if status == 200 else "",
        status=status,
    )


def serve_bus_stops(
    aioclient_mock: AiohttpClientMocker,
    status: int = 200,
    empty_page: int | None = None,
) -> None:
    """Answer the city's bus stop list (three pages, keyed by ``start``), or fail.

    ``empty_page`` (1 to 3) comes back with no stops and its ``totalCount`` kept, as
    when the city drops a page of the list.
    """
    if status != 200:
        aioclient_mock.get(BUS_STOPS, text="", status=status)
        return
    for start, page in (("0", 1), ("500", 2), ("1000", 3)):
        text = read_fixture(f"zaragoza_city/bus_stops_page_{page}.json")
        if page == empty_page:
            answer = json.loads(text)
            answer["result"] = []
            text = json.dumps(answer)
        aioclient_mock.get(BUS_STOPS, params={"start": start}, text=text)


def serve_avanza(
    aioclient_mock: AiohttpClientMocker, stop: str, status: int = 200
) -> None:
    """Answer the operator's page for ``stop`` (688 or 1231), or fail with ``status``."""
    aioclient_mock.get(
        AVANZA,
        params={"poste": stop},
        text=read_fixture(f"avanza/stop_{stop}.html") if status == 200 else "",
        status=status,
    )


def serve_city_bus(
    aioclient_mock: AiohttpClientMocker, stop: str, status: int = 200
) -> None:
    """Answer the city's real-time page for ``stop`` (688), or its error body.

    The city reports its failures as ``{"status": 400, ...}``, here with ``status``.
    """
    aioclient_mock.get(
        CITY_BUS.format(stop),
        text=read_fixture(
            f"zaragoza_city/bus_realtime_{stop}.json"
            if status == 200
            else "zaragoza_city/bus_error_200_derived.json"
        ),
        status=status,
    )


def serve_bike_stations(
    aioclient_mock: AiohttpClientMocker,
    status: int = 200,
    fixture: str = "station_information.json",
) -> None:
    """Answer the operator's GBFS station list, or fail with ``status``.

    ``fixture`` picks a recorded variant, such as the list without station 164.
    """
    aioclient_mock.get(
        GBFS_STATIONS,
        text=read_fixture(f"gbfs/{fixture}") if status == 200 else "",
        status=status,
    )


def serve_bike_status(aioclient_mock: AiohttpClientMocker, status: int = 200) -> None:
    """Answer the operator's GBFS station status, or fail with ``status``."""
    aioclient_mock.get(
        GBFS_STATUS,
        text=read_fixture("gbfs/station_status.json") if status == 200 else "",
        status=status,
    )


def serve_city_bizi(
    aioclient_mock: AiohttpClientMocker, fixture: str = "bizi_city_stations.json"
) -> None:
    """Answer the city's Bizi list, the fallback; ``fixture`` picks a variant."""
    aioclient_mock.get(CITY_BIZI, text=read_fixture(f"zaragoza_city/{fixture}"))


def serve_air_stations(
    aioclient_mock: AiohttpClientMocker,
    status: int = 200,
    fixture: str = "air_quality_stations.json",
) -> None:
    """Answer the city's air quality station list (8 stations), or fail with ``status``.

    The list carries each station's readings. ``fixture`` picks a recorded variant.
    """
    aioclient_mock.get(
        AIR_STATIONS,
        text=read_fixture(f"zaragoza_city/{fixture}") if status == 200 else "",
        status=status,
    )


def serve_road_works(
    aioclient_mock: AiohttpClientMocker,
    status: int = 200,
    incidents: str = "road_works_incidencia.json",
) -> None:
    """Answer both road works lists (incidents, today's maintenance), or fail both.

    ``incidents`` picks a recorded variant of the incidents list.
    """
    for url, fixture in (
        (ROAD_WORKS, incidents),
        (ROAD_WORKS_TODAY, "road_works_conservacion_hoy.json"),
    ):
        aioclient_mock.get(
            url,
            text=read_fixture(f"zaragoza_city/{fixture}") if status == 200 else "",
            status=status,
        )


def serve_pharmacies(
    aioclient_mock: AiohttpClientMocker,
    status: int = 200,
    fixture: str = "pharmacies_on_duty.json",
) -> None:
    """Answer the city's pharmacies on duty (7 on 2026-11-09), or fail with ``status``.

    ``fixture`` picks a recorded variant, such as the next shift's.
    """
    aioclient_mock.get(
        PHARMACIES,
        text=read_fixture(f"zaragoza_city/{fixture}") if status == 200 else "",
        status=status,
    )


def serve_pollen(aioclient_mock: AiohttpClientMocker, status: int = 200) -> None:
    """Answer the city's pollen levels (14 plants), or fail with ``status``."""
    aioclient_mock.get(
        POLLEN,
        text=read_fixture("zaragoza_city/pollen.json") if status == 200 else "",
        status=status,
    )


def serve_failing_once(
    aioclient_mock: AiohttpClientMocker, url: str, fixture: str
) -> None:
    """Fail the first request to ``url`` with HTTP 500, then answer ``fixture``."""
    asked: list[URL] = []

    async def answer(method: str, sent: URL, data: object) -> AiohttpClientMockResponse:
        asked.append(sent)
        if len(asked) == 1:
            return AiohttpClientMockResponse(method, sent, status=500, text="")
        return AiohttpClientMockResponse(method, sent, text=read_fixture(fixture))

    aioclient_mock.get(url, side_effect=answer)


def requests_to(aioclient_mock: AiohttpClientMocker, url: str) -> int:
    """Count the requests sent to ``url``, whatever their query."""
    return sum(
        1
        for _method, sent, _data, _headers in aioclient_mock.mock_calls
        if str(sent.with_query(None)) == url
    )


def serve_recordings(aioclient_mock: AiohttpClientMocker) -> None:
    """Answer every request the coordinators and stop lists make, as recorded.

    The acceptance tests fall back on these for anything they don't serve
    themselves (see ``conftest.py``).
    """
    serve_tram_list(aioclient_mock)
    serve_bus_stops(aioclient_mock)
    serve_avanza(aioclient_mock, "1231")
    # Any other stop gets 688's page.
    aioclient_mock.get(AVANZA, text=read_fixture("avanza/stop_688.html"))
    serve_bike_stations(aioclient_mock)
    serve_bike_status(aioclient_mock)
    serve_road_works(aioclient_mock)
    serve_pharmacies(aioclient_mock)
    serve_air_stations(aioclient_mock)
    serve_pollen(aioclient_mock)
