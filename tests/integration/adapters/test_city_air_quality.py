"""The city air quality adapter against recorded HTTP."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
import json
import logging

import pytest
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.air_quality import (
    CityAirQuality,
)
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.client import (
    CityClient,
)
from custom_components.zaragoza_open_data.api.errors import SourceUnavailableError
from custom_components.zaragoza_open_data.api.models import AirReading, Pollutant
from tests.fixtures import read_fixture
from tests.integration.contracts import check_air_quality_contract

BASE = "https://www.zaragoza.es/sede/servicio/"
USER_AGENT = "ZaragozaOpenData/test (+https://example.invalid)"
PATH = "calidad-aire/listado.json"
STATION_IDS = {"12", "1", "2", "7", "8", "9", "10", "11"}
NEWEST = datetime(2026, 11, 9, 11, 0, tzinfo=UTC)  # 12:00 Madrid (UTC+1)


@pytest.fixture
async def air(aioclient_mock: AiohttpClientMocker) -> AsyncIterator[CityAirQuality]:
    """Adapter whose HTTP replays the recorded station list."""
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield CityAirQuality(CityClient(session, USER_AGENT))
    await session.close()


def serve(aioclient_mock: AiohttpClientMocker, text: str | None = None) -> None:
    """Serve the recorded station list, or ``text``."""
    aioclient_mock.get(
        BASE + PATH,
        text=text or read_fixture("zaragoza_city/air_quality_stations.json"),
    )


def stations_json() -> dict[str, list[dict[str, object]]]:
    """The recorded list, parsed for in-memory edits."""
    parsed: dict[str, list[dict[str, object]]] = json.loads(
        read_fixture("zaragoza_city/air_quality_stations.json")
    )
    return parsed


def observation(magnitud: str, value: str, hour: str) -> dict[str, str]:
    """An hourly observation as the city publishes it."""
    return {
        "publicationDate": f"2026-11-09T{hour}:00:00",
        "value": value,
        "magnitud": magnitud,
        "estado": "Tiempo real",
        "periodo": "Horario",
    }


def reading(
    readings: tuple[AirReading, ...], station_id: str, pollutant: Pollutant
) -> AirReading:
    """The single reading of one pollutant at one station."""
    found = [
        r for r in readings if r.station_id == station_id and r.pollutant is pollutant
    ]
    assert len(found) == 1
    return found[0]


async def test_eight_stations_with_locations(
    air: CityAirQuality, aioclient_mock: AiohttpClientMocker
) -> None:
    """The list has 8 stations, keyed by the city's id, with WGS84 locations."""
    serve(aioclient_mock)

    stations = await air.stations()

    assert air.source_name == "zaragoza_city"
    assert len(stations) == 8
    by_id = {station.id: station for station in stations}
    assert set(by_id) == STATION_IDS
    assert by_id["12"].name == "Actur"
    assert by_id["12"].location.latitude == pytest.approx(41.675215945700614)
    assert by_id["12"].location.longitude == pytest.approx(-0.8868307240200246)
    assert by_id["9"].name == "Las Fuentes"
    assert by_id["11"].name == "Avda. Soria"


async def test_station_name_with_trailing_space_is_trimmed(
    air: CityAirQuality, aioclient_mock: AiohttpClientMocker
) -> None:
    """A station title published with stray whitespace is cleaned."""
    data = stations_json()
    data["result"][5]["title"] = "Las Fuentes \t"
    serve(aioclient_mock, json.dumps(data))

    names = {station.name for station in await air.stations()}

    assert "Las Fuentes" in names


async def test_report_is_one_request_with_user_agent(
    air: CityAirQuality, aioclient_mock: AiohttpClientMocker
) -> None:
    """Hours are on the station list: one WGS84 request, no ``fl``, the User-Agent.

    That one request brings every station and its readings.
    """
    serve(aioclient_mock)

    report = await air.report()

    assert {station.id for station in report.stations} == STATION_IDS
    assert {reading.station_id for reading in report.readings} == STATION_IDS
    (call,) = aioclient_mock.mock_calls
    assert call[1].path == "/sede/servicio/" + PATH
    assert call[1].query["srsname"] == "wgs84"
    assert "fl" not in call[1].query
    assert call[3]["User-Agent"] == USER_AGENT


async def test_newest_hour_wins_per_station_and_pollutant(
    air: CityAirQuality, aioclient_mock: AiohttpClientMocker
) -> None:
    """The two recorded hours collapse to one reading per station and pollutant."""
    serve(aioclient_mock)

    readings = (await air.report()).readings

    keys = [(r.station_id, r.pollutant) for r in readings]
    assert len(keys) == len(set(keys))
    assert {r.station_id for r in readings} == STATION_IDS
    # Actur at 12:00 (the 11:00 values were 16.18 NO2 and 40.7 O3).
    assert reading(readings, "12", Pollutant.NO2).value == 14.92
    assert reading(readings, "12", Pollutant.NO2).measured_at == NEWEST
    assert reading(readings, "12", Pollutant.O3).value == 43.36
    assert reading(readings, "12", Pollutant.PM25).value == 8.7


async def test_nitrogen_monoxide_is_read_at_each_station_that_measures_it(
    air: CityAirQuality, aioclient_mock: AiohttpClientMocker
) -> None:
    """The city's ``NO`` is nitrogen monoxide: the newest hour at 7 of the 8 stations."""
    serve(aioclient_mock)

    readings = (await air.report()).readings

    assert reading(readings, "12", Pollutant.NO).value == 21.05
    assert reading(readings, "12", Pollutant.NO).measured_at == NEWEST
    assert reading(readings, "11", Pollutant.NO).value == 59.84
    no_stations = {r.station_id for r in readings if r.pollutant is Pollutant.NO}
    assert no_stations == STATION_IDS - {"7"}


async def test_older_hour_listed_first_does_not_win(
    air: CityAirQuality, aioclient_mock: AiohttpClientMocker
) -> None:
    """Order in the array does not matter: the newest ``publicationDate`` wins."""
    data = stations_json()
    data["result"][0]["observation"] = [
        observation("O3", "10.0", "12"),
        observation("O3", "99.0", "09"),
    ]
    serve(aioclient_mock, json.dumps(data))

    readings = (await air.report()).readings

    assert reading(readings, "12", Pollutant.O3).value == 10.0


async def test_pollutant_missing_from_the_newest_hour_keeps_its_own_hour(
    air: CityAirQuality, aioclient_mock: AiohttpClientMocker
) -> None:
    """A pollutant not published at the newest hour keeps its last value and hour."""
    data = stations_json()
    data["result"][0]["observation"] = [
        observation("NO2", "14.92", "12"),
        observation("O3", "40.7", "11"),
    ]
    serve(aioclient_mock, json.dumps(data))

    readings = (await air.report()).readings

    ozone = reading(readings, "12", Pollutant.O3)
    assert ozone.measured_at == datetime(2026, 11, 9, 10, 0, tzinfo=UTC)
    assert reading(readings, "12", Pollutant.NO2).measured_at == NEWEST


async def test_pollutant_mapping_and_unknown_skipped(
    air: CityAirQuality,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``SH2`` is H2S, ``Benceno`` benzene; a pollutant with no sensor is skipped."""
    data = stations_json()
    data["result"][0]["observation"] = [
        observation("NO2", "14.92", "12"),
        observation("XYZ", "1.0", "12"),
    ]
    serve(aioclient_mock, json.dumps(data))

    with caplog.at_level(logging.DEBUG):
        readings = (await air.report()).readings

    assert {r.pollutant for r in readings} == {
        Pollutant.CO,
        Pollutant.NO,
        Pollutant.NO2,
        Pollutant.O3,
        Pollutant.SO2,
        Pollutant.PM10,
        Pollutant.PM25,
        Pollutant.H2S,
        Pollutant.BENZENE,
    }
    assert reading(readings, "1", Pollutant.H2S).value == 22.46
    assert reading(readings, "2", Pollutant.BENZENE).value == 0.33
    skipped = [r for r in caplog.records if "XYZ" in r.getMessage()]
    assert skipped
    assert {r.levelno for r in skipped} == {logging.DEBUG}


async def test_station_without_observations_has_no_readings(
    air: CityAirQuality, aioclient_mock: AiohttpClientMocker
) -> None:
    """A station with an empty or missing ``observation`` is listed but has no readings."""
    data = stations_json()
    data["result"][0]["observation"] = []
    del data["result"][1]["observation"]
    serve(aioclient_mock, json.dumps(data))

    report = await air.report()
    readings = report.readings

    assert len(report.stations) == 8
    assert {r.station_id for r in readings} == STATION_IDS - {"12", "1"}


async def test_value_that_is_not_a_number_is_source_unavailable(
    air: CityAirQuality, aioclient_mock: AiohttpClientMocker
) -> None:
    """A reading whose value is text means the city changed its format."""
    data = stations_json()
    data["result"][0]["observation"] = [observation("O3", "n/d", "12")]
    serve(aioclient_mock, json.dumps(data))

    with pytest.raises(SourceUnavailableError):
        await air.report()


async def test_error_body_with_http_200_is_source_unavailable(
    air: CityAirQuality, aioclient_mock: AiohttpClientMocker
) -> None:
    """The city's ``{"status": 400}`` body is an outage, for stations and the report."""
    serve(aioclient_mock, read_fixture("zaragoza_city/bus_error_200_derived.json"))

    with pytest.raises(SourceUnavailableError) as raised:
        await air.stations()
    assert raised.value.source == "zaragoza_city"
    with pytest.raises(SourceUnavailableError):
        await air.report()


async def test_air_quality_contract(
    air: CityAirQuality, aioclient_mock: AiohttpClientMocker
) -> None:
    """The city adapter meets the air quality contract."""
    serve(aioclient_mock)

    await check_air_quality_contract(air)
