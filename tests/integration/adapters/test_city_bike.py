"""The city bike adapter against recorded HTTP."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
import json
import logging

import pytest
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.bike import (
    CityBike,
)
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.client import (
    CityClient,
)
from custom_components.zaragoza_open_data.api.errors import SourceUnavailableError
from custom_components.zaragoza_open_data.api.models import StationCode
from tests.fixtures import read_fixture

BASE = "https://www.zaragoza.es/sede/servicio/"
USER_AGENT = "ZaragozaOpenData/test (+https://example.invalid)"
BIKE = "urbanismo-infraestructuras/estacion-bicicleta.json"


@pytest.fixture
async def bike(aioclient_mock: AiohttpClientMocker) -> AsyncIterator[CityBike]:
    """Adapter whose HTTP replays the recorded station list."""
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield CityBike(CityClient(session, USER_AGENT))
    await session.close()


def serve(
    aioclient_mock: AiohttpClientMocker, fixture: str = "bizi_city_stations.json"
) -> None:
    """Serve a recorded station list."""
    aioclient_mock.get(BASE + BIKE, text=read_fixture(f"zaragoza_city/{fixture}"))


async def test_city_parses_276_stations_without_type_split(
    bike: CityBike, aioclient_mock: AiohttpClientMocker
) -> None:
    """The city lists every station (276 on 2026-11-09) but not electric vs mechanical."""
    serve(aioclient_mock)

    stations = await bike.stations()
    availability = await bike.availability()

    assert bike.source_name == "zaragoza_city"
    assert len(stations) == 276
    assert len(availability) == 276
    station = next(s for s in stations if s.code == "164")
    assert station.name == "Rosales: Illueca"
    assert station.location.latitude == pytest.approx(41.63949478993624)
    assert station.location.longitude == pytest.approx(-0.8760426512715722)
    assert (station.capacity, station.address) == (None, None)
    entry = availability[StationCode("164")]
    assert (entry.bikes, entry.docks) == (5, 14)
    assert (entry.electric, entry.mechanical) == (None, None)
    assert (entry.renting, entry.returning) == (True, True)
    # lastUpdated 13:40:08 Madrid (UTC+1).
    assert entry.reported_at == datetime(2026, 11, 9, 12, 40, 8, tzinfo=UTC)
    assert entry.source == "zaragoza_city"


async def test_city_requests_only_the_fields_it_reads(
    bike: CityBike, aioclient_mock: AiohttpClientMocker
) -> None:
    """The list is one request with ``fl`` and the User-Agent."""
    serve(aioclient_mock)

    await bike.availability()

    assert len(aioclient_mock.mock_calls) == 1
    call = aioclient_mock.mock_calls[0]
    assert call[1].query["fl"] == (
        "id,title,estado,bicisDisponibles,anclajesDisponibles,geometry,lastUpdated"
    )
    assert call[1].query["rows"] == "500"
    assert call[3]["User-Agent"] == USER_AGENT


async def test_city_station_out_of_service_is_not_renting_or_returning(
    bike: CityBike, aioclient_mock: AiohttpClientMocker
) -> None:
    """Any ``estado`` other than IN_SERVICE blocks both renting and returning."""
    data = json.loads(read_fixture("zaragoza_city/bizi_city_stations.json"))
    next(r for r in data["result"] if r["title"].startswith("164"))["estado"] = (
        "OUT_OF_SERVICE"
    )
    aioclient_mock.get(BASE + BIKE, text=json.dumps(data))

    entry = (await bike.availability())[StationCode("164")]

    assert (entry.renting, entry.returning) == (False, False)


@pytest.mark.parametrize(
    "missing",
    [
        ("bicisDisponibles",),
        ("anclajesDisponibles",),
        ("bicisDisponibles", "anclajesDisponibles"),
    ],
)
async def test_closed_station_without_counts_keeps_its_place_but_has_no_availability(
    bike: CityBike,
    aioclient_mock: AiohttpClientMocker,
    missing: tuple[str, ...],
) -> None:
    """Maintenance may omit counts; the healthy stations and catalogue still work."""
    data = json.loads(read_fixture("zaragoza_city/bizi_city_stations.json"))
    row = next(r for r in data["result"] if r["title"].startswith("164"))
    row["estado"] = "MAINTENANCE"
    for key in missing:
        del row[key]
    aioclient_mock.get(BASE + BIKE, text=json.dumps(data))

    stations = await bike.stations()
    availability = await bike.availability()

    assert "164" in {station.code for station in stations}
    assert StationCode("164") not in availability
    assert len(availability) == 275
    assert availability[StationCode("1")].bikes == 7
    assert availability[StationCode("1")].docks == 12


@pytest.mark.parametrize("missing", ["bicisDisponibles", "anclajesDisponibles"])
async def test_active_station_without_counts_is_source_unavailable(
    bike: CityBike, aioclient_mock: AiohttpClientMocker, missing: str
) -> None:
    """Only a closed station may omit its counts; an active one must report them."""
    data = json.loads(read_fixture("zaragoza_city/bizi_city_stations.json"))
    del data["result"][0][missing]
    aioclient_mock.get(BASE + BIKE, text=json.dumps(data))

    with pytest.raises(SourceUnavailableError):
        await bike.availability()


async def test_station_without_number_prefix_is_skipped(
    bike: CityBike,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A station whose title has no ``N-`` prefix is left out; the rest is parsed."""
    serve(aioclient_mock, "bizi_city_stations_no_prefix_derived.json")

    with caplog.at_level(logging.DEBUG):
        stations = await bike.stations()
        availability = await bike.availability()

    assert len(stations) == 275
    assert "164" not in {s.code for s in stations}
    assert len(availability) == 275
    assert StationCode("164") not in availability
    skipped = [r for r in caplog.records if "Rosales: Illueca" in r.getMessage()]
    assert skipped
    assert {r.levelno for r in skipped} == {logging.DEBUG}


async def test_city_error_body_with_http_200_is_source_unavailable(
    bike: CityBike, aioclient_mock: AiohttpClientMocker
) -> None:
    """The city's ``{"status": 400}`` body is an outage, not a parse crash."""
    aioclient_mock.get(
        BASE + BIKE, text=read_fixture("zaragoza_city/bus_error_200_derived.json")
    )

    with pytest.raises(SourceUnavailableError) as raised:
        await bike.stations()

    assert raised.value.source == "zaragoza_city"


async def test_city_station_with_wrong_shape_is_source_unavailable(
    bike: CityBike, aioclient_mock: AiohttpClientMocker
) -> None:
    """A station whose counts are not integers means the city changed its format."""
    data = json.loads(read_fixture("zaragoza_city/bizi_city_stations.json"))
    data["result"][0]["bicisDisponibles"] = "many"
    aioclient_mock.get(BASE + BIKE, text=json.dumps(data))

    with pytest.raises(SourceUnavailableError):
        await bike.availability()
