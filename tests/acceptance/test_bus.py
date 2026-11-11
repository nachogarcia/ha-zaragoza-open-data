"""Bus stops: arrivals, operator → city fallback, the 10-minute rule, one at a time."""

import asyncio
from datetime import datetime, timedelta
from itertools import pairwise
import logging

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from syrupy.assertion import SnapshotAssertion
from yarl import URL

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from tests.acceptance.clock import pass_time
from tests.acceptance.entry import bus_stop, set_up_entry
from tests.acceptance.pictures import picture
from tests.acceptance.providers import (
    AVANZA,
    BUS_STOPS,
    CITY_BUS,
    requests_to,
    serve_avanza,
    serve_bus_stops,
    serve_city_bus,
)
from tests.acceptance.states import device_snapshot, state_of
from tests.fixtures import read_fixture

pytestmark = pytest.mark.usefixtures("in_zaragoza")

NOW = "2026-11-09 12:40:30+00:00"
BUS_ONLY = {"kinds": ["bus"]}
REYES_DE_ARAGON = bus_stop("688", "688 · P. Reyes de Aragón N.º 24 · line 58")
SCHINDLER = bus_stop("1231", "1231 · La Lista de Schindler · lines 56, 59, N4")


@pytest.mark.freeze_time(NOW)
async def test_bus_stop_entities_snapshot_with_line_filter(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
) -> None:
    """A stop showing only line 56 skips the 59 due sooner; the operator answered."""
    serve_avanza(aioclient_mock, "1231")
    await set_up_entry(
        hass,
        BUS_ONLY,
        [bus_stop("1231", "1231 · La Lista de Schindler · line 56", ["56"])],
    )

    next_bus = state_of(hass, "sensor", "bus_1231_next_arrival")
    # 13:40:30 + 22 minutes: the 59 in 7 minutes is filtered out.
    assert next_bus.state == "2026-11-09T13:02:30+00:00"
    assert next_bus.attributes["line"] == "56"
    assert next_bus.attributes["source"] == "avanza"
    assert {arrival["line"] for arrival in next_bus.attributes["arrivals"]} == {"56"}
    # The stop's sensor a map card lists shows a bus stop pin.
    assert next_bus.attributes["entity_picture"] == picture("bus_stop")
    following = state_of(hass, "sensor", "bus_1231_following_arrival")
    assert following.state == "2026-11-09T13:28:30+00:00"
    assert device_snapshot(hass, "bus_1231") == snapshot


@pytest.mark.freeze_time(NOW)
async def test_bus_minutes_are_the_operators_minutes(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Each stop's minutes sensor shows the operator's MIN column.

    Stops are asked a second apart, so the first stop's answer is a second old
    when the sensors are written: it still shows 24, as the operator does.
    """
    serve_avanza(aioclient_mock, "688")
    serve_avanza(aioclient_mock, "1231")
    await set_up_entry(hass, BUS_ONLY, [REYES_DE_ARAGON, SCHINDLER], settle=False)
    await pass_time(hass, freezer, timedelta(seconds=1))
    await hass.async_block_till_done(wait_background_tasks=True)

    reyes = state_of(hass, "sensor", "bus_688_minutes_to_next")
    assert reyes.state == "24"
    assert reyes.attributes["following"] == 48
    schindler = state_of(hass, "sensor", "bus_1231_minutes_to_next")
    assert schindler.state == "7"
    assert schindler.attributes["following"] == 22
    assert [
        (arrival["line"], arrival["minutes"])
        for arrival in schindler.attributes["arrivals"]
    ] == [("59", 7), ("56", 22), ("59", 27), ("56", 48)]


@pytest.mark.freeze_time(NOW)
async def test_bus_at_the_stop_is_zero_minutes(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A bus "En la parada." is 0 minutes; the one after it is the following one."""
    page = read_fixture("avanza/stop_688.html").replace("24 minutos.", "En la parada.")
    aioclient_mock.get(AVANZA, params={"poste": "688"}, text=page)
    await set_up_entry(hass, BUS_ONLY, [REYES_DE_ARAGON])

    minutes = state_of(hass, "sensor", "bus_688_minutes_to_next")
    assert minutes.state == "0"
    assert minutes.attributes["following"] == 48
    assert minutes.attributes["arrivals"][0]["minutes"] == 0


@pytest.mark.freeze_time(NOW)
async def test_bus_fetches_configured_stops_one_at_a_time(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Stops are asked one after another, never together, at least a second apart."""
    timeline: list[tuple[str, str, datetime]] = []

    async def operator(
        method: str, url: URL, data: object
    ) -> AiohttpClientMockResponse:
        stop = url.query["poste"]
        timeline.append(("start", stop, dt_util.utcnow()))
        # A request sent alongside this one would start while this one waits here.
        await asyncio.sleep(0)
        timeline.append(("end", stop, dt_util.utcnow()))
        page = "1231" if stop == "1231" else "688"
        return AiohttpClientMockResponse(
            method, url, text=read_fixture(f"avanza/stop_{page}.html")
        )

    aioclient_mock.get(AVANZA, side_effect=operator)
    await set_up_entry(
        hass,
        BUS_ONLY,
        [REYES_DE_ARAGON, SCHINDLER, bus_stop("3010", "3010 · Somewhere · line 58")],
        settle=False,
    )
    await pass_time(hass, freezer, timedelta(seconds=3))
    # The last stop has no rest after it: let its request finish.
    await hass.async_block_till_done(wait_background_tasks=True)

    assert [(event, stop) for event, stop, _ in timeline] == [
        ("start", "688"),
        ("end", "688"),
        ("start", "1231"),
        ("end", "1231"),
        ("start", "3010"),
        ("end", "3010"),
    ]
    starts = [when for event, _, when in timeline if event == "start"]
    assert all(
        later - earlier >= timedelta(seconds=1) for earlier, later in pairwise(starts)
    )
    assert state_of(hass, "sensor", "bus_3010_next_arrival").state != STATE_UNAVAILABLE


@pytest.mark.freeze_time(NOW)
async def test_bus_keeps_last_good_board_for_ten_minutes_then_fails(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """With both sources down, the last arrivals stay shown for 10 minutes, then go."""
    serve_avanza(aioclient_mock, "688")
    await set_up_entry(hass, BUS_ONLY, [REYES_DE_ARAGON])
    shown = state_of(hass, "sensor", "bus_688_next_arrival").state
    assert shown == "2026-11-09T13:04:30+00:00"

    aioclient_mock.clear_requests()
    serve_avanza(aioclient_mock, "688", status=500)
    serve_city_bus(aioclient_mock, "688", status=400)
    await pass_time(hass, freezer, timedelta(minutes=9, seconds=59))

    assert requests_to(aioclient_mock, CITY_BUS.format("688")) == 9
    assert state_of(hass, "sensor", "bus_688_next_arrival").state == shown

    await pass_time(hass, freezer, timedelta(seconds=1))

    assert state_of(hass, "sensor", "bus_688_next_arrival").state == STATE_UNAVAILABLE
    assert (
        state_of(hass, "sensor", "bus_688_following_arrival").state == STATE_UNAVAILABLE
    )


@pytest.mark.freeze_time(NOW)
async def test_stale_stop_unavailable_while_other_stops_keep_values(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A stop nobody answers for goes unavailable after 10 minutes; the rest carry on."""
    serve_avanza(aioclient_mock, "688")
    serve_avanza(aioclient_mock, "1231")
    await set_up_entry(hass, BUS_ONLY, [REYES_DE_ARAGON, SCHINDLER], settle=False)
    await pass_time(hass, freezer, timedelta(seconds=1))
    assert state_of(hass, "sensor", "bus_1231_next_arrival").state != STATE_UNAVAILABLE

    aioclient_mock.clear_requests()
    serve_avanza(aioclient_mock, "688")
    serve_avanza(aioclient_mock, "1231", status=500)
    serve_city_bus(aioclient_mock, "688")
    serve_city_bus(aioclient_mock, "1231", status=400)
    # Each refresh takes a second longer than a minute (the gap between the two
    # stops), so the refresh that finds 1231's board too old comes after 10 minutes.
    await pass_time(hass, freezer, timedelta(minutes=11))

    assert state_of(hass, "sensor", "bus_1231_next_arrival").state == STATE_UNAVAILABLE
    assert state_of(hass, "sensor", "bus_688_next_arrival").state != STATE_UNAVAILABLE


@pytest.mark.freeze_time(NOW)
async def test_operator_down_city_answers_and_operator_retried_after_five_minutes(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The city stands in for the operator, which is asked again after 5 minutes."""
    serve_avanza(aioclient_mock, "688", status=500)
    serve_city_bus(aioclient_mock, "688")
    await set_up_entry(hass, BUS_ONLY, [REYES_DE_ARAGON])

    next_bus = state_of(hass, "sensor", "bus_688_next_arrival")
    # The city's board was published at 13:41:19; the 58 was 24 minutes away.
    assert next_bus.state == "2026-11-09T13:05:19+00:00"
    assert next_bus.attributes["source"] == "zaragoza_city"
    assert (
        next_bus.attributes["attribution"]
        == "Origen de los datos: Ayuntamiento de Zaragoza"
    )
    assert requests_to(aioclient_mock, AVANZA) == 1

    aioclient_mock.clear_requests()
    serve_avanza(aioclient_mock, "688")
    serve_city_bus(aioclient_mock, "688")
    await pass_time(hass, freezer, timedelta(minutes=4, seconds=59))

    assert requests_to(aioclient_mock, AVANZA) == 0
    assert requests_to(aioclient_mock, CITY_BUS.format("688")) == 4

    await pass_time(hass, freezer, timedelta(seconds=1))

    assert requests_to(aioclient_mock, AVANZA) == 1
    next_bus = state_of(hass, "sensor", "bus_688_next_arrival")
    assert next_bus.attributes["source"] == "avanza"
    assert next_bus.state == "2026-11-09T13:09:30+00:00"


@pytest.mark.freeze_time(NOW)
async def test_source_failure_logs_once_and_recovery_logs_once(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Three failed refreshes log one error; coming back logs one line."""
    serve_avanza(aioclient_mock, "688", status=500)
    serve_city_bus(aioclient_mock, "688", status=400)

    with caplog.at_level(logging.INFO, logger="custom_components.zaragoza_open_data"):
        await set_up_entry(hass, BUS_ONLY, [REYES_DE_ARAGON])
        await pass_time(hass, freezer, timedelta(minutes=2))
        # At start and once more 5 s later, then a minute apart.
        assert requests_to(aioclient_mock, CITY_BUS.format("688")) == 4
        assert (
            state_of(hass, "sensor", "bus_688_next_arrival").state == STATE_UNAVAILABLE
        )

        aioclient_mock.clear_requests()
        serve_avanza(aioclient_mock, "688", status=500)
        serve_city_bus(aioclient_mock, "688")
        await pass_time(hass, freezer, timedelta(minutes=1))
        assert (
            state_of(hass, "sensor", "bus_688_next_arrival").state != STATE_UNAVAILABLE
        )

    ours = [
        record
        for record in caplog.records
        if record.name.startswith("custom_components.zaragoza_open_data")
    ]
    assert [record.levelno for record in ours if record.levelno >= logging.ERROR] == [
        logging.ERROR
    ]
    assert len([record for record in ours if record.levelno == logging.INFO]) == 1


@pytest.mark.freeze_time(NOW)
async def test_bus_stop_sensor_carries_the_stop_coordinates(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The next-arrival sensor says where the stop is; the list is asked once a day."""
    serve_bus_stops(aioclient_mock)
    serve_avanza(aioclient_mock, "688")
    entry = await set_up_entry(hass, BUS_ONLY, [REYES_DE_ARAGON])

    next_bus = state_of(hass, "sensor", "bus_688_next_arrival")
    assert next_bus.attributes["latitude"] == 41.62702649728611
    assert next_bus.attributes["longitude"] == -0.9072975810322448
    assert next_bus.attributes["directions"] == (
        "https://www.google.com/maps/dir/?api=1&destination=41.627026,-0.907298"
    )
    assert requests_to(aioclient_mock, BUS_STOPS) == 3

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert state_of(hass, "sensor", "bus_688_next_arrival").attributes["latitude"]
    assert requests_to(aioclient_mock, BUS_STOPS) == 3


@pytest.mark.freeze_time(NOW)
async def test_bus_coordinates_appear_once_the_stop_list_answers(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Without the stop list the arrivals still show; the list is asked again hourly."""
    serve_bus_stops(aioclient_mock, status=500)
    serve_avanza(aioclient_mock, "688")
    await set_up_entry(hass, BUS_ONLY, [REYES_DE_ARAGON])

    next_bus = state_of(hass, "sensor", "bus_688_next_arrival")
    assert next_bus.state == "2026-11-09T13:04:30+00:00"
    assert "latitude" not in next_bus.attributes
    # No coordinates, so no link: never an empty or broken one.
    assert "directions" not in next_bus.attributes
    assert requests_to(aioclient_mock, BUS_STOPS) == 1

    aioclient_mock.clear_requests()
    serve_bus_stops(aioclient_mock)
    serve_avanza(aioclient_mock, "688")
    await pass_time(hass, freezer, timedelta(minutes=59), step=timedelta(minutes=1))

    assert "latitude" not in state_of(hass, "sensor", "bus_688_next_arrival").attributes
    assert requests_to(aioclient_mock, BUS_STOPS) == 0

    await pass_time(hass, freezer, timedelta(minutes=1), step=timedelta(minutes=1))

    next_bus = state_of(hass, "sensor", "bus_688_next_arrival")
    assert next_bus.attributes["latitude"] == 41.62702649728611
    assert requests_to(aioclient_mock, BUS_STOPS) == 3

    await pass_time(hass, freezer, timedelta(minutes=5), step=timedelta(minutes=1))

    assert requests_to(aioclient_mock, BUS_STOPS) == 3


@pytest.mark.freeze_time(NOW)
async def test_kept_board_shows_only_buses_still_to_come(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """While the last board is kept, a bus that has gone is no longer the next one.

    One due a minute ago still counts: it may be at the stop.
    """
    serve_avanza(aioclient_mock, "1231")
    await set_up_entry(hass, BUS_ONLY, [SCHINDLER])
    # The 59 in 7 minutes, then the 56 in 22.
    assert (
        state_of(hass, "sensor", "bus_1231_next_arrival").state
        == "2026-11-09T12:47:30+00:00"
    )

    aioclient_mock.clear_requests()
    serve_avanza(aioclient_mock, "1231", status=500)
    serve_city_bus(aioclient_mock, "1231", status=400)
    await pass_time(hass, freezer, timedelta(minutes=8), step=timedelta(minutes=1))

    # 13:48:30: the 59 was due a minute ago.
    assert (
        state_of(hass, "sensor", "bus_1231_next_arrival").state
        == "2026-11-09T12:47:30+00:00"
    )

    await pass_time(hass, freezer, timedelta(minutes=1), step=timedelta(minutes=1))

    next_bus = state_of(hass, "sensor", "bus_1231_next_arrival")
    assert next_bus.state == "2026-11-09T13:02:30+00:00"
    assert next_bus.attributes["line"] == "56"
    assert [arrival["line"] for arrival in next_bus.attributes["arrivals"]] == [
        "56",
        "59",
        "56",
    ]
    following = state_of(hass, "sensor", "bus_1231_following_arrival")
    assert following.state == "2026-11-09T13:07:30+00:00"
    assert following.attributes["line"] == "59"
