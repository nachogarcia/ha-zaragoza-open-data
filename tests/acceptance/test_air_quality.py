"""Air quality: pollutant sensors, the European index, and the 8-station map layer."""

import asyncio
from datetime import timedelta
import logging

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import async_fire_time_changed
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from syrupy.assertion import SnapshotAssertion
from yarl import URL

from custom_components.zaragoza_open_data.const import DOMAIN
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util
from tests.acceptance.clock import move_to
from tests.acceptance.entry import change_options, set_up_entry
from tests.acceptance.forms import field_options
from tests.acceptance.logs import logged
from tests.acceptance.pictures import picture
from tests.acceptance.providers import AIR_STATIONS, requests_to, serve_air_stations
from tests.acceptance.states import (
    device,
    device_snapshot,
    entity_id,
    geo_events,
    state_of,
)
from tests.fixtures import read_fixture

pytestmark = pytest.mark.usefixtures("in_zaragoza", "home_in_zaragoza")

# 13:40:30 in Zaragoza; the latest readings are from 12:00.
NOW = "2026-11-09 12:40:30+00:00"
# Every reading in the recording was published for 12:00 in Zaragoza.
PUBLISHED = "2026-11-09T12:00:00+01:00"
AIR_ONLY = {"kinds": ["air_quality"]}
SOURCE = "zaragoza_open_data_air_quality"
# "Centro", the station nearest to home: no particle readings.
CENTRO = (41.651434258371395, -0.8837332377253103)


def pollutant_sensors(hass: HomeAssistant) -> dict[str, str]:
    """Return the air quality device's pollutant sensors' states, by pollutant."""
    registry = er.async_get(hass)
    sensors: dict[str, str] = {}
    for registered in er.async_entries_for_config_entry(
        registry, hass.config_entries.async_entries(DOMAIN)[0].entry_id
    ):
        pollutant = registered.unique_id.removeprefix("air_quality_")
        if registered.domain != "sensor" or pollutant in {
            registered.unique_id,
            "index",
        }:
            continue
        state = hass.states.get(registered.entity_id)
        assert state is not None
        sensors[pollutant] = state.state
    return sensors


@pytest.mark.freeze_time(NOW)
async def test_air_quality_defaults_to_nearest_station(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """With no station picked, the sensors show what the station nearest home measures."""
    serve_air_stations(aioclient_mock)
    await set_up_entry(hass, AIR_ONLY)

    # Centro measures no particles, so it has no PM sensors.
    assert pollutant_sensors(hass) == {
        "no": "47.24",
        "no2": "28.75",
        "o3": "37.68",
        "so2": "2.73",
        "co": "0.2",
    }
    no2 = state_of(hass, "sensor", "air_quality_no2")
    assert no2.attributes["unit_of_measurement"] == "μg/m³"
    assert no2.attributes["device_class"] == "nitrogen_dioxide"
    assert (no2.attributes["latitude"], no2.attributes["longitude"]) == CENTRO
    assert (
        no2.attributes["attribution"] == "Origen de los datos: Ayuntamiento de Zaragoza"
    )
    # When the city published the reading: it changes with the reading, hourly.
    assert no2.attributes["published_at"] == PUBLISHED
    no = state_of(hass, "sensor", "air_quality_no")
    assert no.state == "47.24"
    assert no.attributes["unit_of_measurement"] == "μg/m³"
    assert no.attributes["device_class"] == "nitrogen_monoxide"
    assert no.attributes["state_class"] == "measurement"
    assert no.attributes["published_at"] == PUBLISHED
    co = state_of(hass, "sensor", "air_quality_co")
    assert co.attributes["unit_of_measurement"] == "mg/m³"
    assert co.attributes["device_class"] == "carbon_monoxide"
    assert co.attributes["published_at"] == PUBLISHED


@pytest.mark.freeze_time(NOW)
async def test_picked_air_station_is_used(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A station picked in the options is used however far it is."""
    serve_air_stations(aioclient_mock)
    await set_up_entry(hass, {**AIR_ONLY, "air_station": "12"})

    assert pollutant_sensors(hass) == {
        "pm25": "8.7",
        "pm10": "16.26",
        "no": "21.05",
        "no2": "14.92",
        "o3": "43.36",
    }
    index = state_of(hass, "sensor", "air_quality_index")
    assert index.state == "fair"
    assert index.attributes["pollutant"] == "pm25"
    assert index.attributes["complete"] is True


@pytest.mark.freeze_time(NOW)
async def test_air_station_no_longer_listed_falls_back_to_nearest(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A picked station the city stopped listing gives way to the nearest, quietly."""
    serve_air_stations(aioclient_mock)
    with caplog.at_level(logging.DEBUG):
        await set_up_entry(hass, {**AIR_ONLY, "air_station": "99"})

    assert state_of(hass, "sensor", "air_quality_no2").state == "28.75"
    assert (
        "custom_components.zaragoza_open_data.coordinator",
        logging.DEBUG,
        "Air quality station 99 is no longer listed: using Centro, the nearest to home",
    ) in caplog.record_tuples
    assert [
        record
        for record in caplog.records
        if record.levelno >= logging.WARNING and record.name.startswith(DOMAIN)
    ] == []


@pytest.mark.freeze_time(NOW)
async def test_one_request_per_refresh_brings_the_stations_and_their_readings(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Each refresh, the first and a day later's included, costs one request.

    The options form lists the stations that request brought, without asking.
    """
    serve_air_stations(aioclient_mock)
    entry = await set_up_entry(hass, AIR_ONLY)
    assert requests_to(aioclient_mock, AIR_STATIONS) == 1

    await move_to(hass, freezer, "2026-11-09 13:10:29+00:00")
    assert requests_to(aioclient_mock, AIR_STATIONS) == 1
    await move_to(hass, freezer, "2026-11-09 13:10:30+00:00")
    assert requests_to(aioclient_mock, AIR_STATIONS) == 2

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    assert len(field_options(result["data_schema"], "air_station")) == 9
    assert requests_to(aioclient_mock, AIR_STATIONS) == 2

    await move_to(hass, freezer, "2026-11-10 12:40:30+00:00")
    assert requests_to(aioclient_mock, AIR_STATIONS) == 3


@pytest.mark.freeze_time(NOW)
async def test_air_station_layer_has_eight_events_with_index_pictures(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Every station is a pin coloured by its index, with its readings."""
    serve_air_stations(aioclient_mock)
    await set_up_entry(hass, AIR_ONLY)

    events = geo_events(hass, SOURCE)
    assert {
        event.name: (event.attributes["index"], event.attributes["entity_picture"])
        for event in events.values()
    } == {
        "Centro": ("moderate", picture("air_moderate")),
        "Avda. Soria": ("moderate", picture("air_moderate")),
        "Renovales": ("fair", picture("air_fair")),
        "Roger de Flor": ("moderate", picture("air_moderate")),
        "Las Fuentes": ("good", picture("air_good")),
        "El Picarral": ("moderate", picture("air_moderate")),
        "Actur": ("fair", picture("air_fair")),
        "Jaime Ferran": ("good", picture("air_good")),
    }
    centro = events["air_quality_station_10"]
    # Measured from home, in km.
    assert centro.state == "0.5"
    assert centro.attributes == {
        "source": SOURCE,
        "latitude": 41.65143,
        "longitude": -0.88373,
        "index": "moderate",
        "no": 47.24,
        "no2": 28.75,
        "o3": 37.68,
        "so2": 2.73,
        "co": 0.2,
        "published_at": PUBLISHED,
        "attribution": "Origen de los datos: Ayuntamiento de Zaragoza",
        "entity_picture": picture("air_moderate"),
        "unit_of_measurement": "km",
        "friendly_name": "Centro",
    }


@pytest.mark.freeze_time(NOW)
async def test_air_quality_index_sensor_and_picture(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The index is the worst pollutant's band; without particles it isn't complete."""
    serve_air_stations(aioclient_mock)
    await set_up_entry(hass, AIR_ONLY)

    index = state_of(hass, "sensor", "air_quality_index")
    # NO2 28.75 µg/m³ is "moderate" (25 < x ≤ 60), worse than the others' bands.
    assert index.state == "moderate"
    assert index.attributes["pollutant"] == "no2"
    assert index.attributes["complete"] is False
    # The publication time of the reading that set the band.
    assert index.attributes["published_at"] == PUBLISHED
    assert index.attributes["entity_picture"] == picture("air_moderate")
    assert (index.attributes["latitude"], index.attributes["longitude"]) == CENTRO
    assert index.attributes["options"] == [
        "good",
        "fair",
        "moderate",
        "poor",
        "very_poor",
        "extremely_poor",
    ]

    translations = await async_get_translations(hass, "es", "entity", [DOMAIN])
    states = f"component.{DOMAIN}.entity.sensor.air_quality_index.state"
    assert [
        translations[f"{states}.{band}"] for band in index.attributes["options"]
    ] == [
        "Buena",
        "Razonablemente buena",
        "Regular",
        "Desfavorable",
        "Muy desfavorable",
        "Extremadamente desfavorable",
    ]


@pytest.mark.freeze_time(NOW)
async def test_air_sensors_have_device_classes_snapshot(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
) -> None:
    """Pollutants with a device class use it; benzene has none; all in µg/m³ but CO."""
    serve_air_stations(aioclient_mock)
    await set_up_entry(hass, {**AIR_ONLY, "air_station": "2"})

    assert pollutant_sensors(hass) == {
        "benzene": "0.33",
        "no": "53.44",
        "o3": "30.14",
        "no2": "28.37",
        "so2": "2.85",
        "co": "0.16",
        "pm10": "13.99",
    }
    assert device_snapshot(hass, "air_quality") == snapshot


@pytest.mark.freeze_time(NOW)
async def test_changing_the_station_replaces_the_pollutant_sensors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Another station brings its own pollutants; those it doesn't measure go."""
    serve_air_stations(aioclient_mock)
    entry = await set_up_entry(hass, {**AIR_ONLY, "air_station": "12"})
    registry = er.async_get(hass)
    pm10 = registry.async_get_entity_id("sensor", DOMAIN, "air_quality_pm10")
    assert pm10 is not None

    await change_options(hass, entry, air_station="7")

    assert pollutant_sensors(hass) == {
        "h2s": "5.08",
        "co": "0.28",
        "pm10": "11.37",
        "so2": "4.17",
    }
    # The pollutant both measure keeps its entity and history.
    assert registry.async_get_entity_id("sensor", DOMAIN, "air_quality_pm10") == pm10


@pytest.mark.freeze_time(NOW)
async def test_one_failed_air_quality_refresh_is_a_blip_not_an_outage(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed refresh between good ones logs no error; the readings stay shown."""
    serve_air_stations(aioclient_mock)
    with caplog.at_level(logging.INFO, logger="custom_components.zaragoza_open_data"):
        await set_up_entry(hass, AIR_ONLY)
        aioclient_mock.clear_requests()
        serve_air_stations(aioclient_mock, status=500)
        await move_to(hass, freezer, "2026-11-09 13:10:30+00:00")

        assert requests_to(aioclient_mock, AIR_STATIONS) == 1
        assert state_of(hass, "sensor", "air_quality_index").state == "moderate"
        assert pollutant_sensors(hass)["no2"] == "28.75"
        stations = geo_events(hass, SOURCE)
        assert len(stations) == 8
        assert STATE_UNAVAILABLE not in {station.state for station in stations.values()}

        aioclient_mock.clear_requests()
        serve_air_stations(aioclient_mock)
        await move_to(hass, freezer, "2026-11-09 13:40:30+00:00")

        assert requests_to(aioclient_mock, AIR_STATIONS) == 1
        assert state_of(hass, "sensor", "air_quality_index").state == "moderate"

    assert logged(caplog) == []


@pytest.mark.freeze_time(NOW)
async def test_air_quality_down_for_three_refreshes_is_one_outage(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The readings stand in for two failed refreshes; the third one is an outage.

    The outage logs one error when it starts and one line when the city is back.
    """
    serve_air_stations(aioclient_mock)
    with caplog.at_level(logging.INFO, logger="custom_components.zaragoza_open_data"):
        await set_up_entry(hass, AIR_ONLY)
        aioclient_mock.clear_requests()
        serve_air_stations(aioclient_mock, status=500)
        for refresh in ("13:10:30", "13:40:30"):
            await move_to(hass, freezer, f"2026-11-09 {refresh}+00:00")
            assert state_of(hass, "sensor", "air_quality_index").state == "moderate"
        assert logged(caplog) == []

        # The last good readings, from 13:40:30, are now 90 minutes old.
        await move_to(hass, freezer, "2026-11-09 14:10:30+00:00")
        assert state_of(hass, "sensor", "air_quality_index").state == STATE_UNAVAILABLE
        assert set(pollutant_sensors(hass).values()) == {STATE_UNAVAILABLE}
        # Unavailable, the pins carry no place and leave the map.
        assert geo_events(hass, SOURCE) == {}
        await move_to(hass, freezer, "2026-11-09 14:40:30+00:00")
        assert state_of(hass, "sensor", "air_quality_index").state == STATE_UNAVAILABLE

        aioclient_mock.clear_requests()
        serve_air_stations(aioclient_mock)
        await move_to(hass, freezer, "2026-11-09 15:10:30+00:00")
        assert state_of(hass, "sensor", "air_quality_index").state == "moderate"

    assert logged(caplog) == [
        (
            "ERROR",
            "Error fetching air quality data: "
            "The city's air quality readings can't be reached",
        ),
        ("INFO", "Fetching air quality data recovered"),
    ]


@pytest.mark.freeze_time(NOW)
async def test_air_quality_unavailable_until_the_city_answers(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The city down at start: unavailable, asked every 5 minutes, then everything fills in.

    Not at the next half-hourly refresh: those resume once the city is back.
    """
    serve_air_stations(aioclient_mock, status=500)
    with caplog.at_level(logging.INFO, logger="custom_components.zaragoza_open_data"):
        # With pollen on too, whose device the late pollutants must not land on.
        await set_up_entry(hass, {"kinds": ["air_quality", "pollen"]})

        assert state_of(hass, "sensor", "air_quality_index").state == STATE_UNAVAILABLE
        assert pollutant_sensors(hass) == {}
        assert geo_events(hass, SOURCE) == {}

        # 5 minutes after the start's second try (itself 5 s after the first).
        await move_to(hass, freezer, "2026-11-09 12:45:35+00:00")
        assert state_of(hass, "sensor", "air_quality_index").state == STATE_UNAVAILABLE

        aioclient_mock.clear_requests()
        serve_air_stations(aioclient_mock)
        await move_to(hass, freezer, "2026-11-09 12:50:30+00:00")
        assert requests_to(aioclient_mock, AIR_STATIONS) == 0
        await move_to(hass, freezer, "2026-11-09 12:50:35+00:00")

        assert state_of(hass, "sensor", "air_quality_index").state == "moderate"
        assert pollutant_sensors(hass)["no2"] == "28.75"
        assert len(geo_events(hass, SOURCE)) == 8
        air = device(hass, "air_quality")
        no2 = er.async_get(hass).async_get(entity_id(hass, "sensor", "air_quality_no2"))
        assert air is not None
        assert no2 is not None
        assert no2.device_id == air.id

        # Back to every half hour.
        asked = requests_to(aioclient_mock, AIR_STATIONS)
        await move_to(hass, freezer, "2026-11-09 13:20:30+00:00")
        assert requests_to(aioclient_mock, AIR_STATIONS) == asked
        await move_to(hass, freezer, "2026-11-09 13:20:35+00:00")
        assert requests_to(aioclient_mock, AIR_STATIONS) == asked + 1

    assert logged(caplog) == [
        (
            "ERROR",
            "Error fetching air quality data: "
            "The city's air quality readings can't be reached",
        ),
        ("INFO", "Fetching air quality data recovered"),
    ]


@pytest.mark.freeze_time(NOW)
async def test_station_the_city_stops_listing_leaves_the_map(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The next day's list without a station takes its pin off the map."""
    serve_air_stations(aioclient_mock)
    await set_up_entry(hass, AIR_ONLY)
    assert "air_quality_station_7" in geo_events(hass, SOURCE)

    aioclient_mock.clear_requests()
    serve_air_stations(
        aioclient_mock, fixture="air_quality_stations_missing_7_derived.json"
    )
    await move_to(hass, freezer, "2026-11-10 12:40:30+00:00")

    events = geo_events(hass, SOURCE)
    assert len(events) == 7
    assert "air_quality_station_7" not in events
    assert (
        er.async_get(hass).async_get_entity_id(
            "geo_location", DOMAIN, "air_quality_station_7"
        )
        is None
    )


@pytest.mark.freeze_time(NOW)
async def test_empty_station_list_is_not_kept_for_a_day(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An answer listing no station counts as a failure, retried at the next refresh."""
    serve_air_stations(
        aioclient_mock, fixture="air_quality_stations_empty_derived.json"
    )
    await set_up_entry(hass, AIR_ONLY)

    assert state_of(hass, "sensor", "air_quality_index").state == STATE_UNAVAILABLE

    aioclient_mock.clear_requests()
    serve_air_stations(aioclient_mock)
    # Half an hour after the start's second try, 5 s after the first.
    await move_to(hass, freezer, "2026-11-09 13:10:35+00:00")

    assert state_of(hass, "sensor", "air_quality_index").state == "moderate"
    assert len(geo_events(hass, SOURCE)) == 8


@pytest.mark.freeze_time(NOW)
async def test_silent_analyser_keeps_its_sensor_through_a_reload(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A pollutant missing from the last two hours' readings keeps its sensor, unknown."""
    serve_air_stations(aioclient_mock)
    entry = await set_up_entry(hass, {**AIR_ONLY, "air_station": "12"})
    pm25 = entity_id(hass, "sensor", "air_quality_pm25")

    aioclient_mock.clear_requests()
    serve_air_stations(
        aioclient_mock, fixture="air_quality_stations_actur_without_pm25_derived.json"
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    # Same station, so nothing is taken for another station's: PM2.5 stays.
    assert entity_id(hass, "sensor", "air_quality_pm25") == pm25
    assert pollutant_sensors(hass) == {
        "pm25": STATE_UNKNOWN,
        "pm10": "16.26",
        "no": "21.05",
        "no2": "14.92",
        "o3": "43.36",
    }

    aioclient_mock.clear_requests()
    serve_air_stations(aioclient_mock)
    await move_to(hass, freezer, "2026-11-09 13:10:30+00:00")

    assert state_of(hass, "sensor", "air_quality_pm25").state == "8.7"


async def test_old_station_pollutant_comes_back_once_the_new_one_reports_it(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Readings arriving after setup drop the old station's sensors; reported, back."""
    serve_air_stations(aioclient_mock)
    # El Picarral measures CO, PM2.5, NO, NO2, H2S and O3.
    entry = await set_up_entry(hass, {**AIR_ONLY, "air_station": "1"})
    answered = asyncio.Event()

    async def held(method: str, url: URL, data: object) -> AiohttpClientMockResponse:
        await answered.wait()
        return AiohttpClientMockResponse(
            method,
            url,
            text=read_fixture(
                "zaragoza_city/air_quality_stations_actur_without_pm25_derived.json"
            ),
        )

    aioclient_mock.clear_requests()
    aioclient_mock.get(AIR_STATIONS, side_effect=held)
    # Real time here: a setup waiting for the held readings would never end.
    async with asyncio.timeout(10):
        await change_options(hass, entry, air_station="12")

    # Until Actur answers, El Picarral's sensors stay, unknown.
    assert set(pollutant_sensors(hass)) == {"co", "pm25", "no", "no2", "h2s", "o3"}

    answered.set()
    await hass.async_block_till_done(wait_background_tasks=True)

    # Actur's first readings lack PM2.5 too, so its sensor goes with CO and H2S.
    assert pollutant_sensors(hass) == {
        "pm10": "16.26",
        "no": "21.05",
        "no2": "14.92",
        "o3": "43.36",
    }

    aioclient_mock.clear_requests()
    serve_air_stations(aioclient_mock)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=31))
    await hass.async_block_till_done(wait_background_tasks=True)

    assert pollutant_sensors(hass)["pm25"] == "8.7"
