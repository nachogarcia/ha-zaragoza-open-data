"""Bizi stations: counts, the GBFS → city fallback, stations the fallback lacks."""

from datetime import timedelta
import json
import logging

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker
from syrupy.assertion import SnapshotAssertion

from custom_components.zaragoza_open_data.const import DOMAIN
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from tests.acceptance.clock import pass_time
from tests.acceptance.entry import bizi_station, change_options, set_up_entry
from tests.acceptance.logs import logged
from tests.acceptance.providers import (
    CITY_BIZI,
    GBFS_STATIONS,
    requests_to,
    serve_bike_stations,
    serve_bike_status,
    serve_city_bizi,
    serve_failing_once,
)
from tests.acceptance.states import device_snapshot, state_of
from tests.fixtures import read_fixture

pytestmark = pytest.mark.usefixtures("in_zaragoza")

NOW = "2026-11-09 12:40:30+00:00"
BIZI_ONLY = {"kinds": ["bizi"]}
ROSALES = bizi_station("164", "164 · Rosales: Illueca")
PALACIO = bizi_station("1", "1 · Palacio Congresos")
SENSORS = ("bikes", "electric_bikes", "mechanical_bikes", "free_docks", "last_report")
BINARY_SENSORS = ("renting", "returning")


@pytest.mark.freeze_time(NOW)
async def test_bizi_entities_snapshot(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
) -> None:
    """A station shows its bikes by type, free docks and whether it rents and returns."""
    serve_bike_stations(aioclient_mock)
    serve_bike_status(aioclient_mock)
    await set_up_entry(hass, BIZI_ONLY, [ROSALES])

    bikes = state_of(hass, "sensor", "bizi_164_bikes")
    assert bikes.state == "4"
    assert bikes.attributes["attribution"] == "Origen de los datos: Bizi Zaragoza"
    # No pin picture: a map card shows the number of bikes instead.
    assert "entity_picture" not in bikes.attributes
    assert state_of(hass, "sensor", "bizi_164_electric_bikes").state == "4"
    assert state_of(hass, "sensor", "bizi_164_mechanical_bikes").state == "0"
    assert state_of(hass, "sensor", "bizi_164_free_docks").state == "15"
    assert state_of(hass, "binary_sensor", "bizi_164_renting").state == STATE_ON
    assert device_snapshot(hass, "bizi_164") == snapshot
    # The city's list, the fallback, isn't asked while the operator answers.
    assert requests_to(aioclient_mock, CITY_BIZI) == 0


@pytest.mark.freeze_time(NOW)
async def test_bizi_gbfs_down_city_answers(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """With the operator's feed down, the city's list gives the counts, not the types."""
    serve_bike_stations(aioclient_mock, status=500)
    serve_bike_status(aioclient_mock, status=500)
    serve_city_bizi(aioclient_mock)
    await set_up_entry(hass, BIZI_ONLY, [ROSALES])

    bikes = state_of(hass, "sensor", "bizi_164_bikes")
    assert bikes.state == "5"
    assert (
        bikes.attributes["attribution"]
        == "Origen de los datos: Ayuntamiento de Zaragoza"
    )
    assert state_of(hass, "sensor", "bizi_164_free_docks").state == "14"
    assert state_of(hass, "sensor", "bizi_164_electric_bikes").state == STATE_UNKNOWN
    assert state_of(hass, "sensor", "bizi_164_mechanical_bikes").state == STATE_UNKNOWN
    assert state_of(hass, "binary_sensor", "bizi_164_returning").state == STATE_ON
    assert (
        state_of(hass, "sensor", "bizi_164_last_report").state
        == "2026-11-09T12:40:08+00:00"
    )


@pytest.mark.freeze_time(NOW)
async def test_bizi_station_missing_from_city_fallback_is_unavailable(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A station the city doesn't list is unavailable while the city stands in."""
    serve_bike_stations(aioclient_mock, status=500)
    serve_bike_status(aioclient_mock, status=500)
    serve_city_bizi(
        aioclient_mock, fixture="bizi_city_stations_missing_164_derived.json"
    )
    await set_up_entry(hass, BIZI_ONLY, [ROSALES, PALACIO])

    for key in SENSORS:
        assert state_of(hass, "sensor", f"bizi_164_{key}").state == STATE_UNAVAILABLE
    for key in BINARY_SENSORS:
        assert (
            state_of(hass, "binary_sensor", f"bizi_164_{key}").state
            == STATE_UNAVAILABLE
        )
    assert state_of(hass, "sensor", "bizi_1_bikes").state == "7"
    assert state_of(hass, "sensor", "bizi_1_free_docks").state == "12"
    assert state_of(hass, "sensor", "bizi_1_electric_bikes").state == STATE_UNKNOWN
    assert state_of(hass, "sensor", "bizi_1_mechanical_bikes").state == STATE_UNKNOWN
    assert state_of(hass, "binary_sensor", "bizi_1_renting").state == STATE_ON


@pytest.mark.freeze_time(NOW)
async def test_closed_station_without_counts_does_not_break_city_fallback(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A maintenance station is unavailable while the city's healthy stations work."""
    serve_bike_stations(aioclient_mock, status=500)
    serve_bike_status(aioclient_mock, status=500)
    data = json.loads(read_fixture("zaragoza_city/bizi_city_stations.json"))
    closed = next(row for row in data["result"] if row["title"].startswith("164"))
    closed["estado"] = "MAINTENANCE"
    del closed["bicisDisponibles"]
    del closed["anclajesDisponibles"]
    aioclient_mock.get(CITY_BIZI, text=json.dumps(data))

    await set_up_entry(hass, BIZI_ONLY, [ROSALES, PALACIO])

    for key in SENSORS:
        assert state_of(hass, "sensor", f"bizi_164_{key}").state == STATE_UNAVAILABLE
    for key in BINARY_SENSORS:
        assert (
            state_of(hass, "binary_sensor", f"bizi_164_{key}").state
            == STATE_UNAVAILABLE
        )
    assert state_of(hass, "sensor", "bizi_1_bikes").state == "7"
    assert state_of(hass, "sensor", "bizi_1_free_docks").state == "12"
    assert state_of(hass, "binary_sensor", "bizi_1_renting").state == STATE_ON


@pytest.mark.freeze_time(NOW)
async def test_bizi_unavailable_when_operator_and_city_are_down(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """With neither source answering, the station is unavailable and the log says why."""
    serve_bike_stations(aioclient_mock, status=500)
    serve_bike_status(aioclient_mock, status=500)
    aioclient_mock.get(CITY_BIZI, status=500)
    await set_up_entry(hass, BIZI_ONLY, [ROSALES])

    errors = [
        (record.getMessage(), record.exc_info)
        for record in caplog.records
        if record.name.startswith("custom_components.zaragoza_open_data")
        and record.levelno >= logging.ERROR
    ]
    # One plain line, no traceback: an outage is expected, not a bug.
    assert errors == [
        (
            "Error fetching Bizi data: Neither the Bizi operator nor the city's "
            "Bizi list can be reached",
            None,
        )
    ]

    assert state_of(hass, "sensor", "bizi_164_bikes").state == STATE_UNAVAILABLE
    assert (
        state_of(hass, "binary_sensor", "bizi_164_renting").state == STATE_UNAVAILABLE
    )


@pytest.mark.freeze_time(NOW)
async def test_bizi_counts_stand_in_for_two_failed_refreshes(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Neither source answering, the last counts stay shown for two refreshes.

    The third, 6 minutes after the last answer, is an outage, logged once.
    """
    serve_bike_stations(aioclient_mock)
    serve_bike_status(aioclient_mock)
    with caplog.at_level(logging.INFO, logger="custom_components.zaragoza_open_data"):
        await set_up_entry(hass, BIZI_ONLY, [ROSALES])
        aioclient_mock.clear_requests()
        serve_bike_status(aioclient_mock, status=500)
        aioclient_mock.get(CITY_BIZI, status=500)
        await pass_time(hass, freezer, timedelta(minutes=4), step=timedelta(minutes=1))

        # The operator failed first, then the city each time: still the operator's 4.
        assert requests_to(aioclient_mock, CITY_BIZI) == 2
        assert state_of(hass, "sensor", "bizi_164_bikes").state == "4"
        assert state_of(hass, "sensor", "bizi_164_electric_bikes").state == "4"
        assert logged(caplog) == []

        await pass_time(hass, freezer, timedelta(minutes=2), step=timedelta(minutes=1))

        assert state_of(hass, "sensor", "bizi_164_bikes").state == STATE_UNAVAILABLE

    assert logged(caplog) == [
        (
            "ERROR",
            "Error fetching Bizi data: Neither the Bizi operator nor the city's "
            "Bizi list can be reached",
        )
    ]


@pytest.mark.freeze_time(NOW)
async def test_bizi_station_carries_coordinates_and_capacity(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The bikes sensor says where the station is and how many docks it has."""
    serve_bike_stations(aioclient_mock)
    serve_bike_status(aioclient_mock)
    await set_up_entry(hass, BIZI_ONLY, [ROSALES])

    bikes = state_of(hass, "sensor", "bizi_164_bikes")
    assert bikes.attributes["latitude"] == 41.639471
    assert bikes.attributes["longitude"] == -0.876017
    assert bikes.attributes["capacity"] == 19
    assert bikes.attributes["directions"] == (
        "https://www.google.com/maps/dir/?api=1&destination=41.639471,-0.876017"
    )
    # The operator's station list is fetched once, for the counts and the places.
    assert requests_to(aioclient_mock, GBFS_STATIONS) == 1


@pytest.mark.freeze_time(NOW)
async def test_bizi_place_appears_once_the_station_list_answers(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Both sources down at start: the station gets its place when the operator is back.

    Nobody is asked for the place while the refreshes fail.
    """
    serve_bike_stations(aioclient_mock, status=500)
    serve_bike_status(aioclient_mock, status=500)
    aioclient_mock.get(CITY_BIZI, status=500)
    await set_up_entry(hass, BIZI_ONLY, [ROSALES])
    assert state_of(hass, "sensor", "bizi_164_bikes").state == STATE_UNAVAILABLE

    aioclient_mock.clear_requests()
    aioclient_mock.get(CITY_BIZI, status=500)
    serve_bike_stations(aioclient_mock)
    serve_bike_status(aioclient_mock)
    # The operator rests for 5 minutes after failing; the city stays down meanwhile.
    await pass_time(hass, freezer, timedelta(minutes=5), step=timedelta(minutes=1))
    assert requests_to(aioclient_mock, CITY_BIZI) == 2
    assert requests_to(aioclient_mock, GBFS_STATIONS) == 0

    await pass_time(hass, freezer, timedelta(minutes=1), step=timedelta(minutes=1))

    bikes = state_of(hass, "sensor", "bizi_164_bikes")
    assert bikes.state == "4"
    assert bikes.attributes["capacity"] == 19
    assert bikes.attributes["latitude"] == 41.639471
    # The station list fetched for the counts gave the place too.
    assert requests_to(aioclient_mock, GBFS_STATIONS) == 1


@pytest.mark.freeze_time(NOW)
async def test_city_station_list_stands_in_only_until_the_operator_is_back(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The operator failing once at setup, the city's partial list serves minutes, not a day.

    Within 11 minutes of the operator coming back, a station the city didn't list
    is found and answered from the operator, and the stations get the operator's
    place, docks included.
    """
    serve_failing_once(aioclient_mock, GBFS_STATIONS, "gbfs/station_information.json")
    serve_city_bizi(
        aioclient_mock, fixture="bizi_city_stations_missing_164_derived.json"
    )
    await set_up_entry(hass, BIZI_ONLY, [ROSALES, PALACIO])
    assert state_of(hass, "sensor", "bizi_164_bikes").state == STATE_UNAVAILABLE
    assert state_of(hass, "sensor", "bizi_1_bikes").attributes["capacity"] is None

    await pass_time(hass, freezer, timedelta(minutes=11), step=timedelta(minutes=1))

    found = await hass.services.async_call(
        DOMAIN,
        "find_stops",
        {"kind": "bizi", "query": "164"},
        blocking=True,
        return_response=True,
    )
    assert found is not None
    stops = found["stops"]
    assert isinstance(stops, list)
    assert [stop["code"] for stop in stops if isinstance(stop, dict)][:1] == ["164"]
    answer = await hass.services.async_call(
        DOMAIN,
        "get_bizi_station",
        {"station": "164"},
        blocking=True,
        return_response=True,
    )
    assert answer is not None
    assert answer["source"] == "gbfs"
    assert answer["electric"] == 4
    bikes = state_of(hass, "sensor", "bizi_164_bikes")
    assert bikes.state == "4"
    assert bikes.attributes["capacity"] == 19
    assert state_of(hass, "sensor", "bizi_1_bikes").attributes["capacity"] == 19


@pytest.mark.freeze_time(NOW)
async def test_station_the_city_stand_in_lacks_is_placed_once_the_operator_is_back(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The only station added missing from the city's list, its place comes in minutes.

    The operator failing once at setup, the city's list places nothing; it is asked
    again as soon as it is due, not an hour later.
    """
    serve_failing_once(aioclient_mock, GBFS_STATIONS, "gbfs/station_information.json")
    serve_city_bizi(
        aioclient_mock, fixture="bizi_city_stations_missing_164_derived.json"
    )
    await set_up_entry(hass, BIZI_ONLY, [ROSALES])
    assert "capacity" not in state_of(hass, "sensor", "bizi_164_bikes").attributes

    await pass_time(hass, freezer, timedelta(minutes=11), step=timedelta(minutes=1))

    bikes = state_of(hass, "sensor", "bizi_164_bikes")
    assert bikes.state == "4"
    assert bikes.attributes["capacity"] == 19
    assert bikes.attributes["latitude"] == 41.639471


@pytest.mark.freeze_time(NOW)
async def test_stand_in_retry_is_timed_to_when_the_city_list_expires(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A reload late in the stand-in's life doesn't push the operator's place back.

    The city's list, fetched at setup, is kept 10 minutes. Placing again at minute
    9 (after a reload) must wait for minute 10, when the list is due and the
    operator is asked, not for minute 19.
    """
    serve_failing_once(aioclient_mock, GBFS_STATIONS, "gbfs/station_information.json")
    serve_city_bizi(
        aioclient_mock, fixture="bizi_city_stations_missing_164_derived.json"
    )
    entry = await set_up_entry(hass, BIZI_ONLY, [ROSALES])
    await pass_time(hass, freezer, timedelta(minutes=9), step=timedelta(minutes=1))
    assert "capacity" not in state_of(hass, "sensor", "bizi_164_bikes").attributes

    await change_options(hass, entry, refresh={"bike_s": 180})
    await pass_time(hass, freezer, timedelta(minutes=4), step=timedelta(minutes=1))

    bikes = state_of(hass, "sensor", "bizi_164_bikes")
    assert bikes.attributes["capacity"] == 19
