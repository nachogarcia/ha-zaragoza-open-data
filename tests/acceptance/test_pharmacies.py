"""Pharmacies on duty: the map layer, the nearest one, and the 09:20 refresh."""

import logging

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.zaragoza_open_data.const import DOMAIN
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from tests.acceptance.clock import move_to
from tests.acceptance.entry import change_options, set_up_entry
from tests.acceptance.logs import logged
from tests.acceptance.pictures import picture
from tests.acceptance.providers import PHARMACIES, requests_to, serve_pharmacies
from tests.acceptance.states import device, geo_events, state_of

pytestmark = pytest.mark.usefixtures("in_zaragoza", "home_in_zaragoza")

# 13:40:30 in Zaragoza.
NOW = "2026-11-09 12:40:30+00:00"
# 08:00 in Zaragoza, before the shifts change at 09:15.
MORNING = "2026-11-09 07:00:00+00:00"
PHARMACIES_ONLY = {"kinds": ["pharmacies"]}
SOURCE = "zaragoza_open_data_pharmacies"
ARTAL_DIRECTIONS = (
    "https://www.google.com/maps/dir/?api=1&destination=41.646146,-0.885867"
)
SHIFT = "Abiertas de 9:15 h. a 9:15 h. del día siguiente"
# The turn of 2026-11-09 ends at 09:15 the next day, Zaragoza time.
OPEN_UNTIL = "2026-11-10T09:15:00+01:00"


@pytest.mark.freeze_time(NOW)
async def test_pharmacy_events_and_nearest_sensor(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Every pharmacy on duty is on the map; a sensor names the nearest one."""
    serve_pharmacies(aioclient_mock)
    entry = await set_up_entry(hass, PHARMACIES_ONLY)

    # The whole city by default: about seven are on duty at once.
    events = geo_events(hass, SOURCE)
    assert len(events) == 7
    artal = events["pharmacies_8860"]
    assert artal.name == "Farmacia Artal Lerín, Ana Cristina"
    assert artal.state == "0.4"
    assert artal.attributes == {
        "source": SOURCE,
        "latitude": 41.64615,
        "longitude": -0.88587,
        "address": "Pº. de Sagasta, 8",
        "phone": "976226203",
        "hours": SHIFT,
        "sector": "Sector Gran Vía",
        # The duty's own date, from the city's list: it changes once a day.
        "on_duty": "2026-11-09",
        "open_until": OPEN_UNTIL,
        "directions": ARTAL_DIRECTIONS,
        "attribution": "Origen de los datos: Ayuntamiento de Zaragoza",
        "entity_picture": picture("pharmacy"),
        "unit_of_measurement": "km",
        "friendly_name": "Farmacia Artal Lerín, Ana Cristina",
    }
    assert events["pharmacies_8810"].state == "3.5"

    nearest = state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy")
    assert nearest.state == "Farmacia Artal Lerín, Ana Cristina"
    assert nearest.attributes["address"] == "Pº. de Sagasta, 8"
    assert nearest.attributes["phone"] == "976226203"
    assert nearest.attributes["hours"] == SHIFT
    assert nearest.attributes["distance_km"] == 0.4
    assert nearest.attributes["on_duty"] == "2026-11-09"
    assert nearest.attributes["open_until"] == OPEN_UNTIL
    assert nearest.attributes["directions"] == ARTAL_DIRECTIONS
    assert (
        nearest.attributes["attribution"]
        == "Origen de los datos: Ayuntamiento de Zaragoza"
    )
    on_duty = device(hass, "pharmacies")
    assert on_duty is not None
    assert on_duty.name == "Pharmacies on duty"

    await change_options(hass, entry, pharmacies_radius_km=2)

    assert sorted(geo_events(hass, SOURCE)) == [
        "pharmacies_8860",
        "pharmacies_8909",
        "pharmacies_8932",
    ]


@pytest.mark.freeze_time(MORNING)
async def test_pharmacies_refresh_after_shift_change_at_0920(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Asked at start, at 09:20 when the new shift is published, and every 6 hours."""
    serve_pharmacies(aioclient_mock)
    await set_up_entry(hass, PHARMACIES_ONLY)
    assert requests_to(aioclient_mock, PHARMACIES) == 1

    await move_to(hass, freezer, "2026-11-09 08:19:30+00:00")
    assert requests_to(aioclient_mock, PHARMACIES) == 1
    await move_to(hass, freezer, "2026-11-09 08:20:00+00:00")
    assert requests_to(aioclient_mock, PHARMACIES) == 2

    # Then every 6 hours from there: 15:20, 21:20, 03:20, and 09:20 again, once.
    await move_to(hass, freezer, "2026-11-09 14:19:30+00:00")
    assert requests_to(aioclient_mock, PHARMACIES) == 2
    await move_to(hass, freezer, "2026-11-09 14:20:00+00:00")
    assert requests_to(aioclient_mock, PHARMACIES) == 3
    await move_to(hass, freezer, "2026-11-09 20:20:00+00:00")
    await move_to(hass, freezer, "2026-11-10 02:20:00+00:00")
    await move_to(hass, freezer, "2026-11-10 08:19:30+00:00")
    assert requests_to(aioclient_mock, PHARMACIES) == 5
    await move_to(hass, freezer, "2026-11-10 08:20:00+00:00")
    assert requests_to(aioclient_mock, PHARMACIES) == 6


@pytest.mark.freeze_time(MORNING)
async def test_slower_refresh_still_gets_the_new_shift_at_0920(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Set to once a week, the list is still asked each day at 09:20."""
    serve_pharmacies(aioclient_mock)
    await set_up_entry(hass, {**PHARMACIES_ONLY, "refresh": {"pharmacies_h": 168}})

    await move_to(hass, freezer, "2026-11-09 08:20:00+00:00")
    await move_to(hass, freezer, "2026-11-10 08:19:30+00:00")
    assert requests_to(aioclient_mock, PHARMACIES) == 2
    await move_to(hass, freezer, "2026-11-10 08:20:00+00:00")
    assert requests_to(aioclient_mock, PHARMACIES) == 3


@pytest.mark.freeze_time(MORNING)
async def test_shift_change_refresh_stops_with_the_entry(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Once the entry is unloaded, 09:20 asks nobody."""
    serve_pharmacies(aioclient_mock)
    entry = await set_up_entry(hass, PHARMACIES_ONLY)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    await move_to(hass, freezer, "2026-11-09 08:20:00+00:00")

    assert requests_to(aioclient_mock, PHARMACIES) == 1


@pytest.mark.freeze_time(MORNING)
async def test_new_shift_replaces_the_pharmacies_at_0920(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A pharmacy whose shift ended leaves the map, and the nearest one changes."""
    serve_pharmacies(aioclient_mock)
    await set_up_entry(hass, PHARMACIES_ONLY)
    assert "pharmacies_8860" in geo_events(hass, SOURCE)

    aioclient_mock.clear_requests()
    serve_pharmacies(
        aioclient_mock, fixture="pharmacies_on_duty_next_shift_derived.json"
    )
    await move_to(hass, freezer, "2026-11-09 08:20:00+00:00")

    events = geo_events(hass, SOURCE)
    assert len(events) == 6
    assert "pharmacies_8860" not in events
    assert (
        er.async_get(hass).async_get_entity_id(
            "geo_location", DOMAIN, "pharmacies_8860"
        )
        is None
    )
    nearest = state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy")
    assert nearest.state == "Farmacia Sanchez Villanueva, Monica"
    assert nearest.attributes["distance_km"] == 1.5
    # The link follows the nearest pharmacy when it changes.
    assert nearest.attributes["directions"] == (
        "https://www.google.com/maps/dir/?api=1&destination=41.643771,-0.905998"
    )


@pytest.mark.freeze_time(NOW)
async def test_no_pharmacy_within_the_distance(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """With none on duty within the distance, the nearest is unknown."""
    serve_pharmacies(aioclient_mock)
    await set_up_entry(hass, {**PHARMACIES_ONLY, "pharmacies_radius_km": 0.2})

    assert geo_events(hass, SOURCE) == {}
    nearest = state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy")
    assert nearest.state == STATE_UNKNOWN
    assert "address" not in nearest.attributes
    assert "directions" not in nearest.attributes


@pytest.mark.freeze_time(NOW)
async def test_pharmacies_unavailable_while_the_city_is_down(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The city down at start: the nearest pharmacy is unavailable, the map empty.

    The city is asked again 5 minutes later, not at the next 6-hour refresh;
    once it answers, the 6-hour refreshes resume.
    """
    serve_pharmacies(aioclient_mock, status=500)
    with caplog.at_level(logging.INFO, logger="custom_components.zaragoza_open_data"):
        await set_up_entry(hass, PHARMACIES_ONLY)

        nearest = state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy")
        assert nearest.state == STATE_UNAVAILABLE
        assert geo_events(hass, SOURCE) == {}

        aioclient_mock.clear_requests()
        serve_pharmacies(aioclient_mock)
        # 5 minutes after the start's second try (itself 5 s after the first).
        await move_to(hass, freezer, "2026-11-09 12:45:30+00:00")
        assert requests_to(aioclient_mock, PHARMACIES) == 0
        await move_to(hass, freezer, "2026-11-09 12:45:35+00:00")

        assert requests_to(aioclient_mock, PHARMACIES) == 1
        nearest = state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy")
        assert nearest.state == "Farmacia Artal Lerín, Ana Cristina"
        assert len(geo_events(hass, SOURCE)) == 7

        # Back to every 6 hours.
        await move_to(hass, freezer, "2026-11-09 18:45:30+00:00")
        assert requests_to(aioclient_mock, PHARMACIES) == 1
        await move_to(hass, freezer, "2026-11-09 18:45:35+00:00")
        assert requests_to(aioclient_mock, PHARMACIES) == 2

    assert logged(caplog) == [
        (
            "ERROR",
            "Error fetching pharmacies data: "
            "The city's list of pharmacies on duty can't be reached",
        ),
        ("INFO", "Fetching pharmacies data recovered"),
    ]


@pytest.mark.freeze_time(NOW)
async def test_failed_refreshes_keep_the_turn_on_duty_until_it_ends(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Through the night the day's pharmacies stay shown; at 09:20 they don't.

    Turns run from 09:15 to 09:15: once the next turn has started, the old
    list is no longer who is on duty, so a failed 09:20 refresh is an outage.
    """
    serve_pharmacies(aioclient_mock)
    with caplog.at_level(logging.INFO, logger="custom_components.zaragoza_open_data"):
        await set_up_entry(hass, PHARMACIES_ONLY)
        aioclient_mock.clear_requests()
        serve_pharmacies(aioclient_mock, status=500)
        # 19:40, 01:40 and 07:40 in Zaragoza: still the turn that began at 09:15.
        for refresh in (
            "2026-11-09 18:40:30+00:00",
            "2026-11-10 00:40:30+00:00",
            "2026-11-10 06:40:30+00:00",
        ):
            await move_to(hass, freezer, refresh)
            nearest = state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy")
            assert nearest.state == "Farmacia Artal Lerín, Ana Cristina"
            assert len(geo_events(hass, SOURCE)) == 7
        assert requests_to(aioclient_mock, PHARMACIES) == 3
        assert logged(caplog) == []

        # 09:20 in Zaragoza: a new turn.
        await move_to(hass, freezer, "2026-11-10 08:20:00+00:00")

        assert requests_to(aioclient_mock, PHARMACIES) == 4
        nearest = state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy")
        assert nearest.state == STATE_UNAVAILABLE
        # Unavailable, the pins carry no place and leave the map.
        assert geo_events(hass, SOURCE) == {}

    assert logged(caplog) == [
        (
            "ERROR",
            "Error fetching pharmacies data: "
            "The city's list of pharmacies on duty can't be reached",
        )
    ]


@pytest.mark.freeze_time(MORNING)
async def test_pharmacies_down_past_the_turn_are_asked_every_5_minutes(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed 09:20 refresh is asked again 5 minutes later, not at the next 6 h one.

    Without the new turn's list there is nobody to show, so the city is asked
    every 5 minutes until it answers; then the 6-hour refreshes resume.
    """
    # At 08:00 the city still lists the turn of 2026-11-08.
    serve_pharmacies(
        aioclient_mock, fixture="pharmacies_on_duty_previous_turn_derived.json"
    )
    with caplog.at_level(logging.INFO, logger="custom_components.zaragoza_open_data"):
        await set_up_entry(hass, PHARMACIES_ONLY)
        aioclient_mock.clear_requests()
        serve_pharmacies(aioclient_mock, status=500)

        await move_to(hass, freezer, "2026-11-09 08:20:00+00:00")
        nearest = state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy")
        assert nearest.state == STATE_UNAVAILABLE
        await move_to(hass, freezer, "2026-11-09 08:24:30+00:00")
        assert requests_to(aioclient_mock, PHARMACIES) == 1
        await move_to(hass, freezer, "2026-11-09 08:25:00+00:00")
        assert requests_to(aioclient_mock, PHARMACIES) == 2
        nearest = state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy")
        assert nearest.state == STATE_UNAVAILABLE

        aioclient_mock.clear_requests()
        serve_pharmacies(aioclient_mock)
        await move_to(hass, freezer, "2026-11-09 08:30:00+00:00")
        assert requests_to(aioclient_mock, PHARMACIES) == 1
        nearest = state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy")
        assert nearest.state == "Farmacia Artal Lerín, Ana Cristina"
        assert len(geo_events(hass, SOURCE)) == 7

        # Back to every 6 hours.
        await move_to(hass, freezer, "2026-11-09 14:29:30+00:00")
        assert requests_to(aioclient_mock, PHARMACIES) == 1
        await move_to(hass, freezer, "2026-11-09 14:30:00+00:00")
        assert requests_to(aioclient_mock, PHARMACIES) == 2

    assert logged(caplog) == [
        (
            "ERROR",
            "Error fetching pharmacies data: "
            "The city's list of pharmacies on duty can't be reached",
        ),
        ("INFO", "Fetching pharmacies data recovered"),
    ]


# 09:17 in Zaragoza: the turn changed at 09:15, the city lists the new one by 09:20.
RESTART_AT_0917 = "2026-11-09 08:17:00+00:00"


@pytest.mark.freeze_time(RESTART_AT_0917)
async def test_list_of_the_turn_that_ended_is_no_standing_for_the_new_one(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Started at 09:17, the city still lists yesterday's turn: nobody is shown.

    The list's own date says it is of the turn that ended at 09:15. A failed 09:20
    refresh is then an outage, not a blip; the city is asked again 5 minutes later.
    """
    serve_pharmacies(
        aioclient_mock, fixture="pharmacies_on_duty_previous_turn_derived.json"
    )
    with caplog.at_level(logging.INFO, logger="custom_components.zaragoza_open_data"):
        await set_up_entry(hass, PHARMACIES_ONLY)
        assert geo_events(hass, SOURCE) == {}
        aioclient_mock.clear_requests()
        serve_pharmacies(aioclient_mock, status=500)

        await move_to(hass, freezer, "2026-11-09 08:20:00+00:00")

        assert requests_to(aioclient_mock, PHARMACIES) == 1
        nearest = state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy")
        assert nearest.state == STATE_UNAVAILABLE
        assert geo_events(hass, SOURCE) == {}

        aioclient_mock.clear_requests()
        serve_pharmacies(
            aioclient_mock, fixture="pharmacies_on_duty_next_shift_derived.json"
        )
        await move_to(hass, freezer, "2026-11-09 08:25:00+00:00")

        assert requests_to(aioclient_mock, PHARMACIES) == 1
        assert len(geo_events(hass, SOURCE)) == 6

    assert logged(caplog) == [
        ("INFO", "Waiting for the city's on-duty list for 2026-11-09"),
        (
            "ERROR",
            "Error fetching pharmacies data: "
            "The city's list of pharmacies on duty can't be reached",
        ),
        ("INFO", "Fetching pharmacies data recovered"),
    ]


@pytest.mark.freeze_time("2026-11-09 08:19:30+00:00")
async def test_refresh_just_before_0920_still_gets_the_shift_change(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Started at 09:19:30, the list is still asked at 09:20, not a day later."""
    serve_pharmacies(aioclient_mock)
    await set_up_entry(hass, PHARMACIES_ONLY)
    assert requests_to(aioclient_mock, PHARMACIES) == 1

    await move_to(hass, freezer, "2026-11-09 08:20:00+00:00")

    assert requests_to(aioclient_mock, PHARMACIES) == 2


@pytest.mark.freeze_time(NOW)
async def test_pharmacy_listed_twice_is_one_pin(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A pharmacy the city lists twice gets one pin, and nothing is logged about it."""
    serve_pharmacies(aioclient_mock, fixture="pharmacies_on_duty_repeated_derived.json")

    await set_up_entry(hass, PHARMACIES_ONLY)

    assert len(geo_events(hass, SOURCE)) == 7
    assert [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING
        and "pharmacies_8860" in record.getMessage()
    ] == []


async def in_los_angeles(hass: HomeAssistant) -> None:
    """Set Home Assistant to a time zone that is never Zaragoza's."""
    await hass.config.async_set_time_zone("America/Los_Angeles")


@pytest.mark.freeze_time(NOW)
async def test_open_until_is_madrid_nine_fifteen_in_the_house_time_zone(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The turn of 2026-11-09 ends at 09:15 in Zaragoza: 00:15 for a house in California."""
    await in_los_angeles(hass)
    serve_pharmacies(aioclient_mock)
    await set_up_entry(hass, PHARMACIES_ONLY)

    nearest = state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy")
    assert nearest.attributes["on_duty"] == "2026-11-09"
    assert nearest.attributes["open_until"] == "2026-11-10T00:15:00-08:00"


@pytest.mark.freeze_time(NOW)
async def test_turn_day_follows_zaragoza_not_the_house_time_zone(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A list fetched after 09:20 in Zaragoza stands in all day, whatever the house clock.

    At 14:40 in California it is still the turn that began that morning in Zaragoza.
    """
    await in_los_angeles(hass)
    serve_pharmacies(aioclient_mock)
    await set_up_entry(hass, PHARMACIES_ONLY)
    aioclient_mock.clear_requests()
    serve_pharmacies(aioclient_mock, status=500)

    await move_to(hass, freezer, "2026-11-09 18:40:30+00:00")

    assert requests_to(aioclient_mock, PHARMACIES) == 1
    nearest = state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy")
    assert nearest.state == "Farmacia Artal Lerín, Ana Cristina"
    assert len(geo_events(hass, SOURCE)) == 7


@pytest.mark.freeze_time(MORNING)
async def test_shift_change_refresh_is_at_0920_in_zaragoza_whatever_the_house_zone(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A house in California is still asked at 09:20 in Zaragoza: 00:20 there."""
    await in_los_angeles(hass)
    serve_pharmacies(aioclient_mock)
    await set_up_entry(hass, PHARMACIES_ONLY)
    assert requests_to(aioclient_mock, PHARMACIES) == 1

    await move_to(hass, freezer, "2026-11-09 08:19:30+00:00")
    assert requests_to(aioclient_mock, PHARMACIES) == 1
    await move_to(hass, freezer, "2026-11-09 08:20:00+00:00")
    assert requests_to(aioclient_mock, PHARMACIES) == 2


# 09:58 in Zaragoza on 2026-11-10, the morning the city published the new turn late.
LATE_MORNING = "2026-11-10 08:58:00+00:00"
WAITING = (
    "INFO",
    "Waiting for the city's on-duty list for 2026-11-10",
)


@pytest.mark.freeze_time(LATE_MORNING)
async def test_turn_the_city_has_not_published_yet_is_waited_for_quietly(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """After 09:15 a list of the turn before isn't shown; the city is asked every 5 minutes.

    Nothing is on duty on the map and the nearest sensor has no pharmacy. No error
    is logged: one line says what is awaited. The new turn shows as soon as it comes.
    """
    serve_pharmacies(aioclient_mock)  # still the turn of 2026-11-09
    with caplog.at_level(logging.INFO, logger="custom_components.zaragoza_open_data"):
        await set_up_entry(hass, PHARMACIES_ONLY)

        assert geo_events(hass, SOURCE) == {}
        nearest = state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy")
        assert nearest.state == STATE_UNKNOWN
        assert requests_to(aioclient_mock, PHARMACIES) == 1

        # Still not there at 10:03: asked again, quietly.
        await move_to(hass, freezer, "2026-11-10 09:02:59+00:00")
        assert requests_to(aioclient_mock, PHARMACIES) == 1
        await move_to(hass, freezer, "2026-11-10 09:03:00+00:00")
        assert requests_to(aioclient_mock, PHARMACIES) == 2
        assert geo_events(hass, SOURCE) == {}

        aioclient_mock.clear_requests()
        serve_pharmacies(
            aioclient_mock, fixture="pharmacies_on_duty_next_turn_derived.json"
        )
        await move_to(hass, freezer, "2026-11-10 09:08:00+00:00")

        assert requests_to(aioclient_mock, PHARMACIES) == 1
        assert len(geo_events(hass, SOURCE)) == 6
        nearest = state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy")
        assert nearest.attributes["on_duty"] == "2026-11-10"
        assert nearest.attributes["open_until"] == "2026-11-11T09:15:00+01:00"

        # Back to the normal schedule: the next ask is the 6-hour one, not 5 minutes.
        aioclient_mock.clear_requests()
        serve_pharmacies(
            aioclient_mock, fixture="pharmacies_on_duty_next_turn_derived.json"
        )
        await move_to(hass, freezer, "2026-11-10 15:07:59+00:00")
        assert requests_to(aioclient_mock, PHARMACIES) == 0
        await move_to(hass, freezer, "2026-11-10 15:08:00+00:00")
        assert requests_to(aioclient_mock, PHARMACIES) == 1

    assert logged(caplog, logging.INFO) == [WAITING]


@pytest.mark.parametrize(
    "started",
    [
        "2026-11-09 07:00:00+00:00",  # 08:00: the turn before is still on, and listed
        "2026-11-09 08:16:00+00:00",  # 09:16
        "2026-11-09 08:20:00+00:00",  # 09:20
        "2026-11-09 22:00:00+00:00",  # 23:00
        "2026-11-10 01:00:00+00:00",  # 02:00 the day after
    ],
)
async def test_list_of_the_current_turn_is_accepted_at_any_time(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    started: str,
) -> None:
    """The list says which turn it is: a list of the turn on duty shows whenever fetched."""
    freezer.move_to(started)
    serve_pharmacies(aioclient_mock)  # the turn of 2026-11-09

    await set_up_entry(hass, PHARMACIES_ONLY)

    assert len(geo_events(hass, SOURCE)) == 7
    assert (
        state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy").state
        != STATE_UNKNOWN
    )


@pytest.mark.freeze_time("2026-11-09 22:00:00+00:00")
async def test_list_fetched_at_23_00_still_stands_in_at_02_00_the_day_after(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The turn runs to 09:15: a failed refresh overnight keeps the list of the turn."""
    serve_pharmacies(aioclient_mock)
    await set_up_entry(hass, PHARMACIES_ONLY)
    aioclient_mock.clear_requests()
    serve_pharmacies(aioclient_mock, status=500)

    await move_to(hass, freezer, "2026-11-10 04:00:30+00:00")  # 05:00 at the 6 h poll

    assert requests_to(aioclient_mock, PHARMACIES) == 1
    assert len(geo_events(hass, SOURCE)) == 7


@pytest.mark.parametrize(
    "entity",
    [
        "sensor.pharmacies_on_duty_nearest",
        "geo_location.farmacia_artal_lerin_ana_cristina",
    ],
)
@pytest.mark.freeze_time(NOW)
async def test_update_entity_on_a_pin_or_the_nearest_sensor_asks_the_city_once(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    entity: str,
) -> None:
    """A manual update on any pharmacy entity fetches the list again, once."""
    serve_pharmacies(aioclient_mock)
    await set_up_entry(hass, PHARMACIES_ONLY)
    assert requests_to(aioclient_mock, PHARMACIES) == 1
    aioclient_mock.clear_requests()
    serve_pharmacies(
        aioclient_mock, fixture="pharmacies_on_duty_next_shift_derived.json"
    )
    await move_to(hass, freezer, "2026-11-09 12:50:30+00:00")
    assert await async_setup_component(hass, "homeassistant", {})

    await hass.services.async_call(
        "homeassistant", "update_entity", {"entity_id": entity}, blocking=True
    )

    assert requests_to(aioclient_mock, PHARMACIES) == 1
    nearest = state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy")
    assert nearest.state == "Farmacia Sanchez Villanueva, Monica"
    assert len(geo_events(hass, SOURCE)) == 6


@pytest.mark.freeze_time(LATE_MORNING)
async def test_update_entity_gets_the_turn_the_city_has_just_published(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """At 10:00, the new turn is there: a manual update shows it without a reload."""
    serve_pharmacies(aioclient_mock)
    await set_up_entry(hass, PHARMACIES_ONLY)
    assert geo_events(hass, SOURCE) == {}
    aioclient_mock.clear_requests()
    serve_pharmacies(
        aioclient_mock, fixture="pharmacies_on_duty_next_turn_derived.json"
    )
    await move_to(hass, freezer, "2026-11-10 09:00:00+00:00")
    assert await async_setup_component(hass, "homeassistant", {})

    await hass.services.async_call(
        "homeassistant",
        "update_entity",
        {"entity_id": "sensor.pharmacies_on_duty_nearest"},
        blocking=True,
    )

    assert requests_to(aioclient_mock, PHARMACIES) == 1
    assert len(geo_events(hass, SOURCE)) == 6
    nearest = state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy")
    assert nearest.attributes["open_until"] == "2026-11-11T09:15:00+01:00"


# 09:21 in Zaragoza: the next 09:20 is a day away, so only the wait rule can ask sooner.
AFTER_THE_CHANGE = "2026-11-10 08:21:00+00:00"


@pytest.mark.freeze_time(AFTER_THE_CHANGE)
async def test_empty_list_after_the_change_is_waited_for_every_5_minutes(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An empty list tells no turn: it is asked again in 5 minutes, with one info line."""
    aioclient_mock.get(
        PHARMACIES, json={"totalCount": 0, "start": 0, "rows": 50, "result": []}
    )
    with caplog.at_level(logging.INFO, logger="custom_components.zaragoza_open_data"):
        await set_up_entry(hass, PHARMACIES_ONLY)
        assert geo_events(hass, SOURCE) == {}
        assert requests_to(aioclient_mock, PHARMACIES) == 1

        await move_to(hass, freezer, "2026-11-10 08:25:59+00:00")
        assert requests_to(aioclient_mock, PHARMACIES) == 1
        await move_to(hass, freezer, "2026-11-10 08:26:00+00:00")
        assert requests_to(aioclient_mock, PHARMACIES) == 2

        aioclient_mock.clear_requests()
        serve_pharmacies(
            aioclient_mock, fixture="pharmacies_on_duty_next_turn_derived.json"
        )
        await move_to(hass, freezer, "2026-11-10 08:31:00+00:00")
        assert len(geo_events(hass, SOURCE)) == 6

    assert logged(caplog, logging.INFO) == [WAITING]


@pytest.mark.freeze_time("2026-11-10 08:14:00+00:00")
async def test_pharmacies_of_the_ended_turn_leave_at_0915_before_the_new_list(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Once the turn's `open_until` has passed, its pharmacies aren't shown as on duty.

    At 09:15 in Zaragoza they go, without a request; the new list comes at 09:20.
    """
    serve_pharmacies(aioclient_mock)  # the turn of 2026-11-09, until 09:15 today
    with caplog.at_level(logging.INFO, logger="custom_components.zaragoza_open_data"):
        await set_up_entry(hass, PHARMACIES_ONLY)
        assert len(geo_events(hass, SOURCE)) == 7

        await move_to(hass, freezer, "2026-11-10 08:14:59+00:00")
        assert len(geo_events(hass, SOURCE)) == 7
        await move_to(hass, freezer, "2026-11-10 08:15:00+00:00")

        assert geo_events(hass, SOURCE) == {}
        nearest = state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy")
        assert nearest.state == STATE_UNKNOWN
        assert requests_to(aioclient_mock, PHARMACIES) == 1

        aioclient_mock.clear_requests()
        serve_pharmacies(
            aioclient_mock, fixture="pharmacies_on_duty_next_turn_derived.json"
        )
        await move_to(hass, freezer, "2026-11-10 08:20:00+00:00")
        assert requests_to(aioclient_mock, PHARMACIES) == 1
        assert len(geo_events(hass, SOURCE)) == 6

    assert logged(caplog) == []
