"""Tram stops: arrivals, the minutes sensor, night, notices, refresh timing, history."""

from datetime import datetime, timedelta
from functools import partial
import logging

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.components.recorder.common import async_wait_recording_done
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from syrupy.assertion import SnapshotAssertion
from yarl import URL

from custom_components.zaragoza_open_data.const import DOMAIN
from homeassistant.components.recorder import history
from homeassistant.components.recorder.core import Recorder
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.recorder import get_instance
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util
from tests.acceptance.clock import move_to
from tests.acceptance.entry import set_up_entry, tram_stop
from tests.acceptance.forms import suggested_values
from tests.acceptance.logs import logged
from tests.acceptance.pictures import picture
from tests.acceptance.providers import (
    TRAM_LIST,
    requests_to,
    serve_air_stations,
    serve_failing_once,
    serve_tram_list,
)
from tests.acceptance.states import device, device_snapshot, entity_id, state_of
from tests.fixtures import read_fixture

pytestmark = pytest.mark.usefixtures("in_zaragoza")

# 13:40:30 in Zaragoza, 28 s after the recorded list was published (13:40:02).
NOW = "2026-11-09 12:40:30+00:00"
TRAM_ONLY = {"kinds": ["tram"]}
MAGO_DE_OZ = tram_stop("2502", "Mago de Oz → Avenida de la Academia")
# Mago de Oz's arrival platform: trams end their trip there, none depart.
MAGO_DE_OZ_ARRIVALS = tram_stop("2501", "Mago de Oz (arrivals)")
# Warnings from the test instance itself, never about the data: the note every
# custom integration gets, missing zlib accelerators, and asyncio's slow-step
# warning when frozen time jumps ahead.
TEST_ENVIRONMENT = frozenset({"homeassistant.loader", "aiohttp_fast_zlib", "asyncio"})
# The notice the derived list adds to platform 101's messages.
NOTICE = (
    "Por obras, el servicio entre Parque Goya y Valdespartera se presta en autobús "
    "hasta nuevo aviso."
)


@pytest.mark.freeze_time(NOW)
async def test_tram_stop_entities_snapshot(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
) -> None:
    """Each platform is a device under the hub with its next and following tram."""
    serve_tram_list(aioclient_mock)
    entry = await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ, MAGO_DE_OZ_ARRIVALS])

    next_tram = state_of(hass, "sensor", "tram_2502_next_arrival")
    assert next_tram.state == "2026-11-09T12:44:02+00:00"
    assert next_tram.attributes["line"] == "L1"
    assert (
        next_tram.attributes["attribution"]
        == "Origen de los datos: Ayuntamiento de Zaragoza"
    )
    assert next_tram.attributes["arrivals"] == [
        {
            "line": "L1",
            "destination": "Avenida Academia",
            "time": "2026-11-09T13:44:02+01:00",
        },
        {
            "line": "L1",
            "destination": "Avenida Academia",
            "time": "2026-11-09T13:48:02+01:00",
        },
    ]
    assert next_tram.attributes["no_service"] is False
    # The platform's sensor a map card lists shows a tram stop pin.
    assert next_tram.attributes["entity_picture"] == picture("tram_stop")
    following = state_of(hass, "sensor", "tram_2502_following_arrival")
    assert following.state == "2026-11-09T12:48:02+00:00"
    assert "entity_picture" not in following.attributes
    # Nothing departs from an arrival platform: no time, and no warning either.
    assert state_of(hass, "sensor", "tram_2501_next_arrival").state == STATE_UNKNOWN

    hub = device(hass, entry.entry_id)
    platform = device(hass, "tram_2502")
    assert hub is not None
    assert platform is not None
    assert hub.name == "Zaragoza Open Data"
    assert platform.via_device_id == hub.id
    assert device_snapshot(hass, "tram_2502") == snapshot
    assert device_snapshot(hass, "tram_2501") == snapshot


@pytest.mark.freeze_time(NOW)
async def test_night_tram_sensors_unknown_and_no_warnings(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """At night no platform lists a tram: sensors unknown, and the log stays quiet."""
    serve_tram_list(aioclient_mock, fixture="tram_list_night_derived.json")

    with caplog.at_level(logging.DEBUG):
        await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ])
        await move_to(hass, freezer, "2026-11-09 12:41:10+00:00")

    assert requests_to(aioclient_mock, TRAM_LIST) == 2
    next_tram = state_of(hass, "sensor", "tram_2502_next_arrival")
    assert next_tram.state == STATE_UNKNOWN
    assert next_tram.attributes["no_service"] is True
    assert next_tram.attributes["arrivals"] == []
    assert (
        state_of(hass, "sensor", "tram_2502_following_arrival").state == STATE_UNKNOWN
    )
    minutes = state_of(hass, "sensor", "tram_2502_minutes_to_next")
    assert minutes.state == STATE_UNKNOWN
    assert minutes.attributes["following"] is None
    assert minutes.attributes["arrivals"] == []
    noisy = [
        (record.name, record.getMessage())
        for record in caplog.records
        if record.levelno >= logging.WARNING and record.name not in TEST_ENVIRONMENT
    ]
    assert noisy == []


@pytest.mark.freeze_time(NOW)
async def test_minutes_sensor_shows_the_citys_minutes_from_the_start(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    entity_registry: er.EntityRegistry,
) -> None:
    """The minutes sensor is on from the first setup and says what the city says.

    The city counted 4 and 8 minutes at 13:40:02; it is 13:40:30, 28 s on, and
    the sensor still says 4, as the city's own list does.
    """
    serve_tram_list(aioclient_mock)
    await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ])

    registered = entity_registry.async_get(
        entity_id(hass, "sensor", "tram_2502_minutes_to_next")
    )
    assert registered is not None
    assert registered.disabled_by is None
    # Shown as whole minutes ("4 min"), not with a duration's two decimals.
    assert registered.options["sensor"]["suggested_display_precision"] == 0
    minutes = state_of(hass, "sensor", "tram_2502_minutes_to_next")
    assert minutes.state == "4"
    assert minutes.attributes["unit_of_measurement"] == "min"
    assert minutes.attributes["following"] == 8
    assert minutes.attributes["arrivals"] == [
        {
            "line": "L1",
            "destination": "Avenida Academia",
            "minutes": 4,
            "time": "2026-11-09T13:44:02+01:00",
        },
        {
            "line": "L1",
            "destination": "Avenida Academia",
            "minutes": 8,
            "time": "2026-11-09T13:48:02+01:00",
        },
    ]


@pytest.mark.freeze_time(NOW)
async def test_minutes_stop_counting_while_the_tram_is_unavailable(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """With the tram list down past 3 minutes, the minutes sensor isn't written each minute.

    It counts again once the city answers, between refreshes too.
    """
    serve_tram_list(aioclient_mock)
    await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ])
    aioclient_mock.clear_requests()
    serve_tram_list(aioclient_mock, status=500)
    for refresh in ("12:41:10", "12:42:10", "12:43:10", "12:44:10"):
        await move_to(hass, freezer, f"2026-11-09 {refresh}+00:00")
    unavailable = state_of(hass, "sensor", "tram_2502_minutes_to_next")
    assert unavailable.state == STATE_UNAVAILABLE
    # Home Assistant updates a state's last report in place: keep the time itself.
    reported = unavailable.last_reported

    # Past the next minute's count (13:45:02) and the next failed refresh.
    for moment in ("12:44:30", "12:45:30"):
        await move_to(hass, freezer, f"2026-11-09 {moment}+00:00")

    later = state_of(hass, "sensor", "tram_2502_minutes_to_next")
    assert later.state == STATE_UNAVAILABLE
    assert later.last_reported == reported

    aioclient_mock.clear_requests()
    serve_tram_list(aioclient_mock)
    await move_to(hass, freezer, "2026-11-09 12:46:10+00:00")
    # The recorded list again: the 13:44 tram has gone, the 13:48 is 8 - 6 minutes away.
    assert state_of(hass, "sensor", "tram_2502_minutes_to_next").state == "2"

    # Counted again at 13:47:02, before the 13:47:10 refresh.
    await move_to(hass, freezer, "2026-11-09 12:47:05+00:00")
    assert state_of(hass, "sensor", "tram_2502_minutes_to_next").state == "1"


@pytest.mark.freeze_time(NOW)
async def test_one_failed_tram_refresh_is_a_blip_not_an_outage(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One failed refresh between good ones logs no error and keeps the board shown.

    The sensors stay available with their values, the minutes keep counting
    down, and the debug log says why the city failed.
    """
    serve_tram_list(aioclient_mock)
    with caplog.at_level(logging.DEBUG, logger="custom_components.zaragoza_open_data"):
        await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ])
        aioclient_mock.clear_requests()
        serve_tram_list(aioclient_mock, status=500)
        await move_to(hass, freezer, "2026-11-09 12:41:10+00:00")

        next_tram = state_of(hass, "sensor", "tram_2502_next_arrival")
        assert next_tram.state == "2026-11-09T12:44:02+00:00"
        assert next_tram.attributes["line"] == "L1"
        following = state_of(hass, "sensor", "tram_2502_following_arrival")
        assert following.state == "2026-11-09T12:48:02+00:00"
        assert state_of(hass, "sensor", "tram_notices").state == "0"
        # 13:41:10: a minute after the city counted 4.
        assert state_of(hass, "sensor", "tram_2502_minutes_to_next").state == "3"

        # Still counting down on the kept board, before the next refresh.
        await move_to(hass, freezer, "2026-11-09 12:42:05+00:00")
        assert state_of(hass, "sensor", "tram_2502_minutes_to_next").state == "2"

        aioclient_mock.clear_requests()
        serve_tram_list(aioclient_mock)
        await move_to(hass, freezer, "2026-11-09 12:42:10+00:00")
        assert state_of(hass, "sensor", "tram_2502_minutes_to_next").state == "2"

    assert logged(caplog) == []
    debug = logged(caplog, logging.DEBUG)
    assert (
        "DEBUG",
        f"{TRAM_LIST} answered HTTP 500",
    ) in debug
    assert (
        "DEBUG",
        "No tram data from zaragoza_city: showing the last for now",
    ) in debug


@pytest.mark.freeze_time(NOW)
async def test_tram_down_for_four_minutes_is_one_outage(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The last board is shown for 3 minutes; after that the stop is unavailable.

    The outage logs one error when it starts and one line when the city is back.
    """
    serve_tram_list(aioclient_mock)
    with caplog.at_level(logging.INFO, logger="custom_components.zaragoza_open_data"):
        await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ])
        aioclient_mock.clear_requests()
        serve_tram_list(aioclient_mock, status=500)
        for refresh in ("12:41:10", "12:42:10", "12:43:10"):
            await move_to(hass, freezer, f"2026-11-09 {refresh}+00:00")
            next_tram = state_of(hass, "sensor", "tram_2502_next_arrival")
            assert next_tram.state == "2026-11-09T12:44:02+00:00"
        assert logged(caplog) == []

        # The last good list, from 13:40:30, is now over 3 minutes old.
        await move_to(hass, freezer, "2026-11-09 12:44:10+00:00")
        for unique_id in (
            "tram_2502_next_arrival",
            "tram_2502_following_arrival",
            "tram_2502_minutes_to_next",
            "tram_notices",
        ):
            assert state_of(hass, "sensor", unique_id).state == STATE_UNAVAILABLE
        await move_to(hass, freezer, "2026-11-09 12:45:10+00:00")
        assert (
            state_of(hass, "sensor", "tram_2502_next_arrival").state
            == STATE_UNAVAILABLE
        )

        aioclient_mock.clear_requests()
        serve_tram_list(aioclient_mock)
        await move_to(hass, freezer, "2026-11-09 12:46:10+00:00")
        # The recorded list again: the 13:44 tram has gone.
        next_tram = state_of(hass, "sensor", "tram_2502_next_arrival")
        assert next_tram.state == "2026-11-09T12:48:02+00:00"

    assert logged(caplog) == [
        (
            "ERROR",
            "Error fetching tram data: The city's tram arrivals can't be reached",
        ),
        ("INFO", "Fetching tram data recovered"),
    ]


@pytest.mark.freeze_time(NOW)
async def test_slower_tram_keeps_its_last_list_for_three_of_its_refreshes(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Set to 120 s, the last list stands in for two failed refreshes, 4 minutes.

    The limit is three of the tram's own refreshes, so a slower tram still rides
    out a blip; the third failure, 6 minutes on, is the outage.
    """
    serve_tram_list(aioclient_mock)
    with caplog.at_level(logging.INFO, logger="custom_components.zaragoza_open_data"):
        await set_up_entry(
            hass, {"kinds": ["tram"], "refresh": {"tram_s": 120}}, [MAGO_DE_OZ]
        )
        # A good refresh at its slot, then the city fails at the next ones.
        await move_to(hass, freezer, "2026-11-09 12:42:10+00:00")
        aioclient_mock.clear_requests()
        serve_tram_list(aioclient_mock, status=500)

        await move_to(hass, freezer, "2026-11-09 12:44:10+00:00")
        next_tram = state_of(hass, "sensor", "tram_2502_next_arrival")
        assert next_tram.state == "2026-11-09T12:44:02+00:00"
        await move_to(hass, freezer, "2026-11-09 12:46:10+00:00")
        # The 13:44 tram has gone from the kept list; the 13:48 is next.
        next_tram = state_of(hass, "sensor", "tram_2502_next_arrival")
        assert next_tram.state == "2026-11-09T12:48:02+00:00"
        assert requests_to(aioclient_mock, TRAM_LIST) == 2
        assert logged(caplog) == []

        await move_to(hass, freezer, "2026-11-09 12:48:10+00:00")
        next_tram = state_of(hass, "sensor", "tram_2502_next_arrival")
        assert next_tram.state == STATE_UNAVAILABLE

    assert logged(caplog) == [
        (
            "ERROR",
            "Error fetching tram data: The city's tram arrivals can't be reached",
        )
    ]


@pytest.mark.freeze_time(NOW)
async def test_slow_answer_counts_from_when_it_was_asked(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A list that took 8 s to come is as old as the moment it was asked for.

    So the third failed refresh after it, 3 minutes after that moment, is the
    outage, as it would be after a quick answer.
    """
    serve_tram_list(aioclient_mock)
    with caplog.at_level(logging.INFO, logger="custom_components.zaragoza_open_data"):
        await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ])

        async def slowly(
            method: str, url: URL, data: object
        ) -> AiohttpClientMockResponse:
            freezer.tick(timedelta(seconds=8))
            return AiohttpClientMockResponse(
                method, url, text=read_fixture("zaragoza_city/tram_list.json")
            )

        aioclient_mock.clear_requests()
        aioclient_mock.get(TRAM_LIST, side_effect=slowly)
        await move_to(hass, freezer, "2026-11-09 12:41:10+00:00")
        assert dt_util.utcnow() == datetime.fromisoformat("2026-11-09 12:41:18+00:00")

        aioclient_mock.clear_requests()
        serve_tram_list(aioclient_mock, status=500)
        for refresh in ("12:42:10", "12:43:10"):
            await move_to(hass, freezer, f"2026-11-09 {refresh}+00:00")
            next_tram = state_of(hass, "sensor", "tram_2502_next_arrival")
            assert next_tram.state != STATE_UNAVAILABLE
        assert logged(caplog) == []

        await move_to(hass, freezer, "2026-11-09 12:44:10+00:00")
        next_tram = state_of(hass, "sensor", "tram_2502_next_arrival")
        assert next_tram.state == STATE_UNAVAILABLE

    assert logged(caplog) == [
        (
            "ERROR",
            "Error fetching tram data: The city's tram arrivals can't be reached",
        )
    ]


@pytest.mark.freeze_time(NOW)
async def test_tram_failing_once_at_start_is_asked_again_5_s_later(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Right after Home Assistant starts, one failure is asked again 5 s later.

    The city answers then: no error is logged and the sensors start with values.
    """
    serve_failing_once(aioclient_mock, TRAM_LIST, "zaragoza_city/tram_list.json")

    with caplog.at_level(logging.DEBUG, logger="custom_components.zaragoza_open_data"):
        await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ])

    assert requests_to(aioclient_mock, TRAM_LIST) == 2
    assert dt_util.utcnow() == datetime.fromisoformat(NOW) + timedelta(seconds=5)
    next_tram = state_of(hass, "sensor", "tram_2502_next_arrival")
    assert next_tram.state == "2026-11-09T12:44:02+00:00"
    assert state_of(hass, "sensor", "tram_2502_minutes_to_next").state == "4"
    assert state_of(hass, "sensor", "tram_notices").state == "0"
    assert logged(caplog) == []
    assert (
        "DEBUG",
        "No tram data from zaragoza_city yet: asking again in 5 s",
    ) in logged(caplog, logging.DEBUG)


@pytest.mark.parametrize(
    ("language", "names"),
    [
        ("en", ["Following (min)", "Arrivals"]),
        ("es", ["Siguiente (min)", "Llegadas"]),
    ],
)
async def test_minutes_attributes_have_names_in_each_language(
    hass: HomeAssistant, language: str, names: list[str]
) -> None:
    """The frontend shows the minutes sensor's attributes by translated names."""
    translations = await async_get_translations(hass, language, "entity", [DOMAIN])

    prefix = f"component.{DOMAIN}.entity.sensor.minutes_to_next.state_attributes"
    assert [
        translations[f"{prefix}.{attribute}.name"]
        for attribute in ("following", "arrivals")
    ] == names


@pytest.mark.freeze_time(NOW)
async def test_history_keeps_the_minutes_without_following_or_arrivals(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """History keeps the minutes sensor's number, not its other attributes."""
    serve_tram_list(aioclient_mock)
    await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ])
    minutes = entity_id(hass, "sensor", "tram_2502_minutes_to_next")
    assert state_of(hass, "sensor", "tram_2502_minutes_to_next").attributes["arrivals"]

    await async_wait_recording_done(hass)
    recorded = await get_instance(hass).async_add_executor_job(
        partial(
            history.get_significant_states,
            hass,
            datetime.fromisoformat(NOW) - timedelta(minutes=1),
            entity_ids=[minutes],
            significant_changes_only=False,
        )
    )

    (state,) = recorded[minutes]
    assert isinstance(state, State)
    assert state.state == "4"
    assert "following" not in state.attributes
    assert "arrivals" not in state.attributes


@pytest.mark.freeze_time(NOW)
async def test_tram_refresh_lands_ten_seconds_after_the_minute(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Asked once at start, then at ten past each minute: the city updates at :00."""
    serve_tram_list(aioclient_mock)
    await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ])
    assert requests_to(aioclient_mock, TRAM_LIST) == 1

    await move_to(hass, freezer, "2026-11-09 12:41:05+00:00")
    assert requests_to(aioclient_mock, TRAM_LIST) == 1
    await move_to(hass, freezer, "2026-11-09 12:41:10+00:00")
    assert requests_to(aioclient_mock, TRAM_LIST) == 2

    await move_to(hass, freezer, "2026-11-09 12:42:05+00:00")
    assert requests_to(aioclient_mock, TRAM_LIST) == 2
    await move_to(hass, freezer, "2026-11-09 12:42:10+00:00")
    assert requests_to(aioclient_mock, TRAM_LIST) == 3


@pytest.mark.freeze_time(NOW)
async def test_refresh_interval_comes_from_options(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """With the tram set to 120 s, the list is asked every other minute, still at :10."""
    serve_tram_list(aioclient_mock)
    await set_up_entry(
        hass, {"kinds": ["tram"], "refresh": {"tram_s": 120}}, [MAGO_DE_OZ]
    )
    assert requests_to(aioclient_mock, TRAM_LIST) == 1

    await move_to(hass, freezer, "2026-11-09 12:41:10+00:00")
    assert requests_to(aioclient_mock, TRAM_LIST) == 1
    await move_to(hass, freezer, "2026-11-09 12:42:10+00:00")
    assert requests_to(aioclient_mock, TRAM_LIST) == 2
    await move_to(hass, freezer, "2026-11-09 12:43:10+00:00")
    assert requests_to(aioclient_mock, TRAM_LIST) == 2
    await move_to(hass, freezer, "2026-11-09 12:44:10+00:00")
    assert requests_to(aioclient_mock, TRAM_LIST) == 3


@pytest.mark.freeze_time(NOW)
async def test_tram_notices_count(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The hub counts the tram's real notices; the two standing lines don't count."""
    serve_tram_list(aioclient_mock, fixture="tram_list_notice_derived.json")
    entry = await set_up_entry(hass, TRAM_ONLY)

    notices = state_of(hass, "sensor", "tram_notices")
    assert notices.state == "1"
    assert notices.attributes["notices"] == [NOTICE]
    hub = device(hass, entry.entry_id)
    registered = er.async_get(hass).async_get(entity_id(hass, "sensor", "tram_notices"))
    assert hub is not None
    assert registered is not None
    assert registered.device_id == hub.id

    aioclient_mock.clear_requests()
    serve_tram_list(aioclient_mock)
    await move_to(hass, freezer, "2026-11-09 12:41:10+00:00")

    notices = state_of(hass, "sensor", "tram_notices")
    assert notices.state == "0"
    assert notices.attributes["notices"] == []


@pytest.mark.freeze_time(NOW)
async def test_history_keeps_arrival_times_without_the_arrivals_list(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """History keeps the arrival time and line, not every tram, and no row a minute."""
    serve_tram_list(aioclient_mock)
    await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ])
    await move_to(hass, freezer, "2026-11-09 12:41:10+00:00")
    next_tram = entity_id(hass, "sensor", "tram_2502_next_arrival")
    # The live state still carries the list.
    assert state_of(hass, "sensor", "tram_2502_next_arrival").attributes["arrivals"]

    await async_wait_recording_done(hass)
    recorded = await get_instance(hass).async_add_executor_job(
        partial(
            history.get_significant_states,
            hass,
            datetime.fromisoformat(NOW) - timedelta(minutes=1),
            entity_ids=[next_tram],
            significant_changes_only=False,
        )
    )

    # Two refreshes with the same board: one row, not one a minute.
    (state,) = recorded[next_tram]
    assert isinstance(state, State)
    assert state.state == "2026-11-09T12:44:02+00:00"
    assert state.attributes["line"] == "L1"
    assert "arrivals" not in state.attributes


@pytest.mark.freeze_time(NOW)
async def test_removing_subentry_removes_device(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Removing a stop takes its device and entities away; the other stop stays."""
    serve_tram_list(aioclient_mock)
    entry = await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ, MAGO_DE_OZ_ARRIVALS])
    removed = entity_id(hass, "sensor", "tram_2502_next_arrival")
    subentry_id = next(
        subentry.subentry_id
        for subentry in entry.subentries.values()
        if subentry.unique_id == "tram_2502"
    )

    assert hass.config_entries.async_remove_subentry(entry, subentry_id)
    await hass.async_block_till_done()

    assert device(hass, "tram_2502") is None
    assert (
        er.async_get(hass).async_get_entity_id(
            "sensor", "zaragoza_open_data", "tram_2502_next_arrival"
        )
        is None
    )
    assert hass.states.get(removed) is None
    assert device(hass, "tram_2501") is not None
    assert state_of(hass, "sensor", "tram_2501_next_arrival").state == STATE_UNKNOWN


@pytest.mark.freeze_time(NOW)
async def test_tram_down_at_start_sensors_unavailable_until_the_city_answers(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The entry starts anyway; its tram sensors fill in once the city answers."""
    serve_tram_list(aioclient_mock, status=500)
    await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ])

    assert state_of(hass, "sensor", "tram_2502_next_arrival").state == STATE_UNAVAILABLE
    assert state_of(hass, "sensor", "tram_notices").state == STATE_UNAVAILABLE
    # Asked once more 5 s later; the failing city isn't asked for the platform's place.
    assert requests_to(aioclient_mock, TRAM_LIST) == 2

    aioclient_mock.clear_requests()
    serve_tram_list(aioclient_mock)
    await move_to(hass, freezer, "2026-11-09 12:41:10+00:00")

    next_tram = state_of(hass, "sensor", "tram_2502_next_arrival")
    assert next_tram.state == "2026-11-09T12:44:02+00:00"
    assert state_of(hass, "sensor", "tram_notices").state == "0"
    # Placed from the list the refresh fetched, without a reload or a request.
    assert next_tram.attributes["latitude"] == 41.624375626652835
    assert requests_to(aioclient_mock, TRAM_LIST) == 1


@pytest.mark.freeze_time(NOW)
async def test_switching_tram_off_removes_the_notices_sensor(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """With the tram off in the options, the hub no longer lists tram notices."""
    serve_tram_list(aioclient_mock)
    serve_air_stations(aioclient_mock)
    entry = await set_up_entry(hass, {"kinds": ["tram", "pollen"]})
    notices = entity_id(hass, "sensor", "tram_notices")

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**suggested_values(result["data_schema"]), "kinds": ["pollen"]},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert (
        er.async_get(hass).async_get_entity_id(
            "sensor", "zaragoza_open_data", "tram_notices"
        )
        is None
    )
    assert hass.states.get(notices) is None


@pytest.mark.freeze_time(NOW)
async def test_tram_stop_sensor_carries_the_platform_coordinates(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The next-arrival sensor says where the platform is, for a map card."""
    serve_tram_list(aioclient_mock)
    await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ])

    next_tram = state_of(hass, "sensor", "tram_2502_next_arrival")
    assert next_tram.attributes["latitude"] == 41.624375626652835
    assert next_tram.attributes["longitude"] == -0.936450897480926
    assert next_tram.attributes["directions"] == (
        "https://www.google.com/maps/dir/?api=1&destination=41.624376,-0.936451"
    )
    # Taken from the list the refresh had just fetched: nobody is asked again.
    assert requests_to(aioclient_mock, TRAM_LIST) == 1
