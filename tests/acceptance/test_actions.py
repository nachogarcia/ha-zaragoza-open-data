"""The find_stops, get_arrivals and get_bizi_station actions: answers, errors, shapes."""

import asyncio
from datetime import timedelta
import json
import logging
from pathlib import Path

from freezegun.api import FrozenDateTimeFactory
import probatio
import pytest
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from pytest_homeassistant.typing import WebSocketGenerator
from syrupy.assertion import SnapshotAssertion
from syrupy.extensions.json import JSONSnapshotExtension
from syrupy.location import PyTestLocation
from yarl import URL

from custom_components.zaragoza_open_data.const import DOMAIN
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util.json import JsonObjectType
from tests.acceptance.clock import move_to, pass_time
from tests.acceptance.entry import bizi_station, bus_stop, set_up_entry, tram_stop
from tests.acceptance.logs import logged
from tests.acceptance.providers import (
    AVANZA,
    BUS_STOPS,
    CITY_BIZI,
    CITY_BUS,
    GBFS_STATUS,
    TRAM_LIST,
    requests_to,
    serve_avanza,
    serve_bike_status,
    serve_bus_stops,
    serve_city_bus,
    serve_tram_list,
)
from tests.acceptance.states import state_of
from tests.fixtures import read_fixture

pytestmark = pytest.mark.usefixtures("in_zaragoza", "home_in_zaragoza")

# 13:40:30 in Zaragoza, 28 s after the recorded tram list was published (13:40:02).
NOW = "2026-11-09 12:40:30+00:00"
TRAM_ONLY = {"kinds": ["tram"]}
BUS_ONLY = {"kinds": ["bus"]}
BIZI_ONLY = {"kinds": ["bizi"]}
TRANSPORT = {"kinds": ["tram", "bus", "bizi"]}
MAGO_DE_OZ = tram_stop("2502", "Mago de Oz → Avenida de la Academia")
ROSALES = bizi_station("164", "164 · Rosales: Illueca")
REYES_DE_ARAGON = bus_stop("688", "688 · P. Reyes de Aragón N.º 24 · line 58")
# Where bus stop 688 is, by the city's stop list.
AT_688 = {"latitude": 41.62702649728611, "longitude": -0.9072975810322448}


class ResponseSnapshotExtension(JSONSnapshotExtension):
    """Plain JSON files, which ``make card-fixtures`` hands to the card's tests.

    Kept in ``snapshots/test_actions/``, next to the other snapshots.
    """

    @classmethod
    def dirname(cls, *, test_location: PyTestLocation) -> str:
        """Return the folder of this test file's response snapshots."""
        return str(
            Path(test_location.filepath).parent / "snapshots" / test_location.basename
        )


@pytest.fixture
def response_snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Snapshot action responses as the JSON the card receives."""
    return snapshot.use_extension(ResponseSnapshotExtension)


async def call(hass: HomeAssistant, action: str, **data: object) -> JsonObjectType:
    """Call one of the integration's actions as a script does, and return its answer."""
    response = await hass.services.async_call(
        DOMAIN, action, data, blocking=True, return_response=True
    )
    assert response is not None
    return response


def items(response: JsonObjectType, key: str) -> list[JsonObjectType]:
    """Return the list of objects a response holds under ``key``."""
    value = response[key]
    assert isinstance(value, list)
    found = [item for item in value if isinstance(item, dict)]
    assert len(found) == len(value)
    return found


@pytest.mark.freeze_time(NOW)
async def test_find_stops_by_text(hass: HomeAssistant) -> None:
    """Text finds a stop by name, accents and case aside; each with its distance."""
    await set_up_entry(hass, TRAM_ONLY)

    response = await call(hass, "find_stops", kind="tram", query="pilar")

    assert response == {
        "stops": [
            {
                "code": "1101",
                "name": "Plaza del Pilar - Murallas",
                "direction": "Mago de Oz",
                "lines": ["L1"],
                "distance_m": 1104,
                "latitude": 41.65727632462157,
                "longitude": -0.8821748834915281,
            },
            {
                "code": "1102",
                "name": "Plaza del Pilar - Murallas",
                "direction": "Avenida de la Academia",
                "lines": ["L1"],
                "distance_m": 1104,
                "latitude": 41.657231175221874,
                "longitude": -0.8820733181164175,
            },
        ]
    }


@pytest.mark.freeze_time(NOW)
async def test_find_stops_near_point_sorted(hass: HomeAssistant) -> None:
    """From a point, the nearest stops come first, as many as asked for."""
    await set_up_entry(hass, BUS_ONLY)

    response = await call(hass, "find_stops", kind="bus", limit=3, **AT_688)

    stops = items(response, "stops")
    assert [(stop["code"], stop["distance_m"]) for stop in stops] == [
        ("688", 0),
        ("670", 53),
        ("843", 118),
    ]
    assert stops[0]["lines"] == ["58"]
    assert stops[0]["direction"] is None


@pytest.mark.freeze_time(NOW)
async def test_find_bus_stops_finds_only_urban_bus_stops(hass: HomeAssistant) -> None:
    """Bus stops are the urban network's: no tram platform, no other network's stop.

    The city's list holds both, and some numbers in both networks.
    """
    await set_up_entry(hass, BUS_ONLY)

    nearest = items(await call(hass, "find_stops", kind="bus", limit=7), "stops")
    by_number = items(await call(hass, "find_stops", kind="bus", query="338"), "stops")
    plaza_aragon = items(
        await call(hass, "find_stops", kind="bus", query="plaza aragon", limit=50),
        "stops",
    )

    # "(1) Principio de Línea Líneas: 501" lies 150 m from home, and
    # "(900) Terminal Líneas: 603, 605" 170 m: neither is offered.
    assert [(stop["code"], stop["distance_m"]) for stop in nearest] == [
        ("1079", 51),
        ("1274", 56),
        ("505", 91),
        ("1249", 145),
        ("673", 149),
        ("3001", 152),
        ("682", 173),
    ]
    # Not "(338) Esquina calle Atiliana Líneas: 501", listed first by the city.
    assert (by_number[0]["code"], by_number[0]["name"], by_number[0]["lines"]) == (
        "338",
        "Coso N.º 126",
        ["22", "35", "N1", "28", "21", "32"],
    )
    # "(11) Plaza Aragón Líneas: TRA" and 12 are tram platforms.
    assert plaza_aragon
    assert all(stop["code"] not in {"11", "12"} for stop in plaza_aragon)
    lines = [stop["lines"] for stop in plaza_aragon]
    assert all(isinstance(listed, list) and "TRA" not in listed for listed in lines)


@pytest.mark.freeze_time(NOW)
async def test_find_stops_from_home_by_default(hass: HomeAssistant) -> None:
    """Without a point, distances are from home; eight results unless asked otherwise."""
    await set_up_entry(hass, BIZI_ONLY)

    response = await call(hass, "find_stops", kind="bizi")

    stops = items(response, "stops")
    assert len(stops) == 8
    assert [(stop["code"], stop["distance_m"]) for stop in stops[:3]] == [
        ("48", 149),
        ("105", 170),
        ("26", 192),
    ]
    assert stops[0]["direction"] is None
    assert stops[0]["lines"] == []


@pytest.mark.freeze_time(NOW)
async def test_find_stops_puts_name_matches_before_direction_matches(
    hass: HomeAssistant,
) -> None:
    """A stop named like the text comes first, though platforms heading there are nearer.

    Every platform towards Mago de Oz has it as its direction, and from home
    (the centre) dozens of them are nearer than the stop itself, at the line's end.
    """
    await set_up_entry(hass, TRAM_ONLY)

    response = await call(hass, "find_stops", kind="tram", query="mago de oz")

    stops = items(response, "stops")
    assert [(stop["code"], stop["name"]) for stop in stops[:2]] == [
        ("2501", "Mago de Oz"),
        ("2502", "Mago de Oz"),
    ]
    # Then the platforms that only head there, nearest first.
    assert [stop["code"] for stop in stops[2:4]] == ["1401", "1311"]
    assert all(stop["direction"] == "Mago de Oz" for stop in stops[2:])


@pytest.mark.freeze_time(NOW)
async def test_find_stops_rejects_latitude_without_longitude(
    hass: HomeAssistant,
) -> None:
    """A point needs both coordinates; one alone is refused before any search."""
    await set_up_entry(hass, BUS_ONLY)

    with pytest.raises(probatio.Invalid):
        await call(hass, "find_stops", kind="bus", latitude=41.65)
    with pytest.raises(probatio.Invalid):
        await call(hass, "find_stops", kind="bus", longitude=-0.88)


@pytest.mark.freeze_time(NOW)
@pytest.mark.parametrize("limit", [0, 51])
async def test_find_stops_limit_is_from_1_to_50(
    hass: HomeAssistant, limit: int
) -> None:
    """A limit outside 1 to 50 is refused before any search; 1 and 50 are answered."""
    await set_up_entry(hass, BUS_ONLY)

    with pytest.raises(probatio.Invalid):
        await call(hass, "find_stops", kind="bus", limit=limit)
    assert len(items(await call(hass, "find_stops", kind="bus", limit=1), "stops")) == 1
    assert (
        len(items(await call(hass, "find_stops", kind="bus", limit=50), "stops")) == 50
    )


async def minutes_shown(
    hass: HomeAssistant, mode: str, stop: str
) -> tuple[str, object, list[object], list[object]]:
    """Return what the stop's minutes sensor and ``get_arrivals`` say, in minutes.

    The sensor's state and ``following``, its ``arrivals``' minutes, the action's.
    """
    sensor = state_of(hass, "sensor", f"{mode}_{stop}_minutes_to_next")
    listed = sensor.attributes["arrivals"]
    assert isinstance(listed, list)
    response = await call(hass, "get_arrivals", mode=mode, stop=stop)
    return (
        sensor.state,
        sensor.attributes["following"],
        [arrival["minutes"] for arrival in listed],
        [arrival["minutes"] for arrival in items(response, "arrivals")],
    )


# 30 s after the recorded tram list's reading (13:40:02 in Zaragoza).
@pytest.mark.freeze_time("2026-11-09 12:40:32+00:00")
async def test_tram_minutes_agree_in_the_sensor_and_get_arrivals(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The badge and the card count alike: the city's minutes, less whole minutes since.

    The city read "4 minutos" and "8 minutos" for platform 2502 at 13:40:02.
    """
    await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ])

    assert await minutes_shown(hass, "tram", "2502") == ("4", 8, [4, 8], [4, 8])

    # 61 s after the reading; the next refresh is at 13:41:10.
    await move_to(hass, freezer, "2026-11-09 12:41:03+00:00")

    assert await minutes_shown(hass, "tram", "2502") == ("3", 7, [3, 7], [3, 7])


@pytest.mark.freeze_time(NOW)
async def test_bus_minutes_agree_in_the_sensor_and_get_arrivals(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The same for a bus: the operator read 24 and 48 at 13:40:30, then went quiet.

    Neither source answers afterwards, so the reading stands for both.
    """
    serve_avanza(aioclient_mock, "688")
    await set_up_entry(hass, BUS_ONLY, [REYES_DE_ARAGON])
    aioclient_mock.clear_requests()
    serve_avanza(aioclient_mock, "688", status=500)
    serve_city_bus(aioclient_mock, "688", status=400)

    await move_to(hass, freezer, "2026-11-09 12:41:00+00:00")

    assert await minutes_shown(hass, "bus", "688") == ("24", 48, [24, 48], [24, 48])

    # The refresh a minute after the reading, then a second later.
    await move_to(hass, freezer, "2026-11-09 12:41:30+00:00")
    await move_to(hass, freezer, "2026-11-09 12:41:31+00:00")

    assert await minutes_shown(hass, "bus", "688") == ("23", 47, [23, 47], [23, 47])


@pytest.mark.freeze_time(NOW)
async def test_get_arrivals_tram_uses_coordinator_data_without_request(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Any platform answers from the tram list already fetched, with the city's minutes.

    The city read 3 and 7 minutes at 13:40:02; it is 28 s later.
    """
    await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ])
    aioclient_mock.clear_requests()

    response = await call(hass, "get_arrivals", mode="tram", stop="1101")

    assert response == {
        "stop": {
            "code": "1101",
            "name": "Plaza del Pilar - Murallas",
            "direction": "Mago de Oz",
        },
        "arrivals": [
            {
                "line": "L1",
                "destination": "Mago de Oz",
                "minutes": 3,
                "time": "2026-11-09T13:43:02+01:00",
            },
            {
                "line": "L1",
                "destination": "Mago de Oz",
                "minutes": 7,
                "time": "2026-11-09T13:47:02+01:00",
            },
        ],
        "source": "zaragoza_city",
        "updated": "2026-11-09T13:40:02+01:00",
    }
    assert requests_to(aioclient_mock, TRAM_LIST) == 0


@pytest.mark.freeze_time(NOW)
async def test_get_arrivals_bus_on_demand(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Any bus stop, configured or not, is asked for when someone wants it."""
    serve_avanza(aioclient_mock, "688")
    await set_up_entry(hass, BUS_ONLY)
    assert requests_to(aioclient_mock, AVANZA) == 0

    response = await call(hass, "get_arrivals", mode="bus", stop="688")

    assert response == {
        "stop": {"code": "688", "name": "P. Reyes de Aragón N.º 24", "direction": None},
        "arrivals": [
            {
                "line": "58",
                "destination": "FUENTE JUNQUERA",
                "minutes": 24,
                "time": "2026-11-09T14:04:30+01:00",
            },
            {
                "line": "58",
                "destination": "FUENTE JUNQUERA",
                "minutes": 48,
                "time": "2026-11-09T14:28:30+01:00",
            },
        ],
        "source": "avanza",
        "updated": "2026-11-09T13:40:30+01:00",
    }
    assert requests_to(aioclient_mock, AVANZA) == 1


@pytest.mark.freeze_time(NOW)
async def test_get_arrivals_bus_reuses_answer_under_30_s(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A stop answered under 30 s ago isn't asked again, so open phones don't add up.

    A new request waits its turn: a second after the last bus request.
    """
    serve_avanza(aioclient_mock, "688")
    serve_avanza(aioclient_mock, "1231")
    await set_up_entry(hass, BUS_ONLY, [REYES_DE_ARAGON])
    assert requests_to(aioclient_mock, AVANZA) == 1

    # Stop 688 was just refreshed: its board is reused.
    response = await call(hass, "get_arrivals", mode="bus", stop="688")
    assert response["stop"] == {
        "code": "688",
        "name": "P. Reyes de Aragón N.º 24",
        "direction": None,
    }
    assert requests_to(aioclient_mock, AVANZA) == 1

    asked = hass.async_create_task(call(hass, "get_arrivals", mode="bus", stop="1231"))
    await asyncio.sleep(0)
    assert requests_to(aioclient_mock, AVANZA) == 1
    await pass_time(hass, freezer, timedelta(seconds=1))
    assert [arrival["line"] for arrival in items(await asked, "arrivals")] == [
        "59",
        "56",
        "59",
        "56",
    ]
    assert requests_to(aioclient_mock, AVANZA) == 2

    freezer.tick(timedelta(seconds=10))
    await call(hass, "get_arrivals", mode="bus", stop="1231")
    assert requests_to(aioclient_mock, AVANZA) == 2

    freezer.tick(timedelta(seconds=20))
    await call(hass, "get_arrivals", mode="bus", stop="1231")
    assert requests_to(aioclient_mock, AVANZA) == 3


@pytest.mark.freeze_time(NOW)
async def test_get_arrivals_bus_fresh_board_updates_the_stop_entities(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A configured stop asked for shows the new answer at once, not at its refresh."""
    serve_avanza(aioclient_mock, "688")
    await set_up_entry(hass, BUS_ONLY, [REYES_DE_ARAGON])
    next_bus = state_of(hass, "sensor", "bus_688_next_arrival")
    assert next_bus.state == "2026-11-09T13:04:30+00:00"

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        AVANZA,
        params={"poste": "688"},
        text=read_fixture("avanza/stop_no_buses_derived.html"),
    )
    # Short of the stop's next refresh, a minute after setup.
    freezer.tick(timedelta(seconds=40))
    response = await call(hass, "get_arrivals", mode="bus", stop="688")

    assert response["arrivals"] == []
    assert requests_to(aioclient_mock, AVANZA) == 1
    assert state_of(hass, "sensor", "bus_688_next_arrival").state == STATE_UNKNOWN


@pytest.mark.freeze_time(NOW)
@pytest.mark.parametrize(("interval_s", "retry_s"), [(60, 60), (600, 300)])
async def test_get_arrivals_bus_recovers_entities_without_moving_the_next_poll(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
    interval_s: int,
    retry_s: int,
) -> None:
    """An action's fresh answer ends an outage and keeps the existing poll due."""
    serve_avanza(aioclient_mock, "688", status=500)
    serve_city_bus(aioclient_mock, "688", status=400)
    with caplog.at_level(logging.INFO, logger="custom_components.zaragoza_open_data"):
        await set_up_entry(
            hass,
            {"kinds": ["bus"], "refresh": {"bus_s": interval_s}},
            [REYES_DE_ARAGON],
        )
        assert (
            state_of(hass, "sensor", "bus_688_next_arrival").state == STATE_UNAVAILABLE
        )
        await pass_time(hass, freezer, timedelta(seconds=40))
        aioclient_mock.clear_requests()
        serve_avanza(aioclient_mock, "688", status=500)
        serve_city_bus(aioclient_mock, "688")

        response = await call(hass, "get_arrivals", mode="bus", stop="688")

        assert response["arrivals"]
        assert (
            state_of(hass, "sensor", "bus_688_next_arrival").state != STATE_UNAVAILABLE
        )
        assert (
            state_of(hass, "sensor", "bus_688_following_arrival").state
            != STATE_UNAVAILABLE
        )
        assert requests_to(aioclient_mock, CITY_BUS.format("688")) == 1

        await pass_time(hass, freezer, timedelta(seconds=retry_s - 41))
        assert requests_to(aioclient_mock, CITY_BUS.format("688")) == 1
        await pass_time(hass, freezer, timedelta(seconds=1))
        assert requests_to(aioclient_mock, CITY_BUS.format("688")) == 2

    assert logged(caplog) == [
        (
            "ERROR",
            "Error fetching bus data: No bus stop has arrivals from the last "
            "10 minutes: neither the operator nor the city answers",
        ),
        ("INFO", "Fetching bus data recovered"),
    ]


@pytest.mark.freeze_time(NOW)
async def test_get_arrivals_bus_answers_from_the_kept_board_while_sources_fail(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """With neither source answering, a stop's board under 10 minutes old stands in."""
    serve_avanza(aioclient_mock, "688")
    await set_up_entry(hass, BUS_ONLY)
    await call(hass, "get_arrivals", mode="bus", stop="688")

    aioclient_mock.clear_requests()
    serve_avanza(aioclient_mock, "688", status=500)
    serve_city_bus(aioclient_mock, "688", status=400)
    freezer.tick(timedelta(minutes=5))
    response = await call(hass, "get_arrivals", mode="bus", stop="688")

    # Still the operator's board, five minutes on.
    assert response["source"] == "avanza"
    assert response["updated"] == "2026-11-09T13:40:30+01:00"
    assert [arrival["minutes"] for arrival in items(response, "arrivals")] == [19, 43]
    # Both sources were asked first.
    assert requests_to(aioclient_mock, AVANZA) == 1
    assert requests_to(aioclient_mock, CITY_BUS.format("688")) == 1

    freezer.tick(timedelta(minutes=5))
    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "get_arrivals", mode="bus", stop="688")
    assert raised.value.translation_key == "source_unavailable"


@pytest.mark.freeze_time(NOW)
async def test_get_bizi_station(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A station's bikes by type, free docks, and whether it rents and returns."""
    await set_up_entry(hass, BIZI_ONLY)

    response = await call(hass, "get_bizi_station", station="164")

    assert response == {
        "station": {"code": "164", "name": "Rosales: Illueca"},
        "bikes": 4,
        "electric": 4,
        "mechanical": 0,
        "docks": 15,
        "renting": True,
        "returning": True,
        "source": "gbfs",
        "updated": "2026-11-09T13:40:04+01:00",
    }
    assert requests_to(aioclient_mock, CITY_BIZI) == 0


@pytest.mark.freeze_time(NOW)
async def test_get_bizi_station_refreshes_data_older_than_its_interval(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """With no station added, nothing keeps Bizi fresh: the action asks first."""

    async def status(method: str, url: URL, data: object) -> AiohttpClientMockResponse:
        # A request sent alongside this one would start while this one waits here.
        await asyncio.sleep(0)
        return AiohttpClientMockResponse(
            method, url, text=read_fixture("gbfs/station_status.json")
        )

    aioclient_mock.get(GBFS_STATUS, side_effect=status)
    await set_up_entry(hass, BIZI_ONLY)
    assert requests_to(aioclient_mock, GBFS_STATUS) == 1
    await pass_time(hass, freezer, timedelta(minutes=3), step=timedelta(minutes=1))
    # Nobody shows Bizi counts, so nobody asked for them.
    assert requests_to(aioclient_mock, GBFS_STATUS) == 1

    # Two phones asking at once share one refresh.
    await asyncio.gather(
        call(hass, "get_bizi_station", station="164"),
        call(hass, "get_bizi_station", station="1"),
    )
    assert requests_to(aioclient_mock, GBFS_STATUS) == 2

    freezer.tick(timedelta(seconds=30))
    await call(hass, "get_bizi_station", station="164")
    assert requests_to(aioclient_mock, GBFS_STATUS) == 2


@pytest.mark.freeze_time(NOW)
@pytest.mark.parametrize("listed", [True, False], ids=["without_counts", "not_listed"])
async def test_get_bizi_station_without_counts_from_the_answering_source(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    listed: bool,
) -> None:
    """The city, standing in, lists a known station without counts, or not at all.

    The error says the answering source has no counts for it, not that it is down.
    """
    await set_up_entry(hass, BIZI_ONLY)
    serve_bike_status(aioclient_mock, status=500)
    city = json.loads(read_fixture("zaragoza_city/bizi_city_stations.json"))
    rosales = next(row for row in city["result"] if row["title"].startswith("164"))
    if listed:
        rosales["estado"] = "MAINTENANCE"
        del rosales["bicisDisponibles"]
        del rosales["anclajesDisponibles"]
    else:
        city["result"].remove(rosales)
    aioclient_mock.get(CITY_BIZI, text=json.dumps(city))
    freezer.tick(timedelta(minutes=3))

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "get_bizi_station", station="164")

    assert not isinstance(raised.value, ServiceValidationError)
    assert raised.value.translation_key == "station_without_counts"
    assert raised.value.translation_placeholders == {"code": "164"}
    assert str(raised.value) == (
        "The source answering now has no bike or dock counts for station 164"
    )
    # The other stations are answered from the city.
    assert (await call(hass, "get_bizi_station", station="1"))["source"] == (
        "zaragoza_city"
    )


@pytest.mark.freeze_time(NOW)
async def test_unknown_stop_error_is_translated(hass: HomeAssistant) -> None:
    """A code no list has is refused with a translated message naming it."""
    await set_up_entry(hass, {"kinds": ["tram", "bizi"]})

    with pytest.raises(ServiceValidationError) as raised:
        await call(hass, "get_arrivals", mode="tram", stop="9999")
    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == "unknown_stop"
    assert raised.value.translation_placeholders == {"code": "9999"}
    assert str(raised.value) == "No stop or station has the code 9999"

    with pytest.raises(ServiceValidationError) as raised:
        await call(hass, "get_bizi_station", station="9999")
    assert raised.value.translation_key == "unknown_stop"


@pytest.mark.freeze_time(NOW)
async def test_unknown_stop_once_the_city_stops_listing_it(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A platform the day's stop list has but the latest tram list lacks is unknown."""
    await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ])
    # Platform 2502 renumbered 2603.
    serve_tram_list(aioclient_mock, fixture="tram_list_unknown_digit_derived.json")
    await move_to(hass, freezer, "2026-11-09 12:41:10+00:00")

    with pytest.raises(ServiceValidationError) as raised:
        await call(hass, "get_arrivals", mode="tram", stop="2502")
    assert raised.value.translation_key == "unknown_stop"


@pytest.mark.freeze_time(NOW)
@pytest.mark.parametrize(
    ("kinds", "action", "data"),
    [
        (["bizi"], "find_stops", {"kind": "tram"}),
        (["bizi"], "get_arrivals", {"mode": "tram", "stop": "2502"}),
        (["tram"], "get_arrivals", {"mode": "bus", "stop": "688"}),
        (["tram"], "get_bizi_station", {"station": "164"}),
    ],
)
async def test_kind_disabled_error(
    hass: HomeAssistant, kinds: list[str], action: str, data: dict[str, object]
) -> None:
    """A kind switched off in the options answers no action."""
    await set_up_entry(hass, {"kinds": kinds})

    with pytest.raises(ServiceValidationError) as raised:
        await call(hass, action, **data)
    assert raised.value.translation_key == "kind_disabled"
    assert str(raised.value) == (
        "That kind of stop is switched off in the integration's options"
    )


@pytest.mark.freeze_time(NOW)
async def test_source_down_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A source that doesn't answer gives a translated error, not a validation one.

    The day's stop lists still answer: the tram and Bizi data themselves fail.
    """
    await set_up_entry(hass, TRANSPORT, [MAGO_DE_OZ, ROSALES])
    serve_tram_list(aioclient_mock, status=500)
    serve_bike_status(aioclient_mock, status=500)
    aioclient_mock.get(CITY_BIZI, status=500)
    serve_avanza(aioclient_mock, "688", status=500)
    serve_city_bus(aioclient_mock, "688", status=400)
    # Past the 3 minutes the tram's last list stands in, and Bizi's 6 (3 refreshes).
    await pass_time(hass, freezer, timedelta(minutes=7), step=timedelta(seconds=10))

    for action, data in (
        ("get_arrivals", {"mode": "tram", "stop": "2502"}),
        ("get_arrivals", {"mode": "bus", "stop": "688"}),
        ("get_bizi_station", {"station": "164"}),
    ):
        with pytest.raises(HomeAssistantError) as raised:
            await call(hass, action, **data)
        assert not isinstance(raised.value, ServiceValidationError)
        assert raised.value.translation_key == "source_unavailable"
        assert str(raised.value) == (
            "The source of this data can't be reached right now"
        )


@pytest.mark.freeze_time(NOW)
async def test_find_stops_without_any_stop_list_is_source_down(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A kind whose stop list never came says its source is down."""
    serve_bus_stops(aioclient_mock, status=500)
    await set_up_entry(hass, BUS_ONLY)

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "find_stops", kind="bus", query="688")
    assert raised.value.translation_key == "source_unavailable"


@pytest.mark.freeze_time(NOW)
async def test_stop_list_kept_while_its_daily_refetch_fails(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A day on, with the city not sending the stop list, the last one answers.

    The city is asked again every 10 minutes, not at every call.
    """
    await set_up_entry(hass, BUS_ONLY)
    nearest = await call(hass, "find_stops", kind="bus", limit=1, **AT_688)
    assert requests_to(aioclient_mock, BUS_STOPS) == 3

    aioclient_mock.clear_requests()
    serve_bus_stops(aioclient_mock, status=500)
    freezer.tick(timedelta(days=1))

    assert await call(hass, "find_stops", kind="bus", limit=1, **AT_688) == nearest
    response = await call(hass, "get_arrivals", mode="bus", stop="688")
    assert response["stop"] == {
        "code": "688",
        "name": "P. Reyes de Aragón N.º 24",
        "direction": None,
    }
    assert requests_to(aioclient_mock, BUS_STOPS) == 1

    freezer.tick(timedelta(minutes=9, seconds=59))
    await call(hass, "find_stops", kind="bus", query="688")
    assert requests_to(aioclient_mock, BUS_STOPS) == 1

    freezer.tick(timedelta(seconds=1))
    await call(hass, "find_stops", kind="bus", query="688")
    assert requests_to(aioclient_mock, BUS_STOPS) == 2


@pytest.mark.freeze_time(NOW)
async def test_stop_list_replaced_once_the_city_answers_again(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """After a failed daily fetch, the next one that works brings the new list."""
    await set_up_entry(hass, TRAM_ONLY)

    def nearest_codes(response: JsonObjectType) -> list[object]:
        return [stop["code"] for stop in items(response, "stops")]

    near_mago_de_oz = {"latitude": 41.624375626652835, "longitude": -0.936450897480926}
    found = await call(hass, "find_stops", kind="tram", limit=2, **near_mago_de_oz)
    assert nearest_codes(found) == ["2502", "2501"]

    aioclient_mock.clear_requests()
    serve_tram_list(aioclient_mock, status=500)
    freezer.tick(timedelta(days=1))
    found = await call(hass, "find_stops", kind="tram", limit=2, **near_mago_de_oz)
    assert nearest_codes(found) == ["2502", "2501"]

    aioclient_mock.clear_requests()
    # Platform 2502 renumbered 2603.
    serve_tram_list(aioclient_mock, fixture="tram_list_unknown_digit_derived.json")
    freezer.tick(timedelta(minutes=10))
    found = await call(hass, "find_stops", kind="tram", limit=2, **near_mago_de_oz)
    assert nearest_codes(found) == ["2603", "2501"]
    assert requests_to(aioclient_mock, TRAM_LIST) == 1

    # Good for a day again.
    freezer.tick(timedelta(hours=23))
    await call(hass, "find_stops", kind="tram", limit=2, **near_mago_de_oz)
    assert requests_to(aioclient_mock, TRAM_LIST) == 1


@pytest.mark.freeze_time(NOW)
async def test_actions_need_the_entry_loaded(hass: HomeAssistant) -> None:
    """While the integration isn't running, the actions say so."""
    entry = await set_up_entry(hass, TRAM_ONLY)
    assert await hass.config_entries.async_unload(entry.entry_id)

    with pytest.raises(ServiceValidationError) as raised:
        await call(hass, "find_stops", kind="tram", query="pilar")
    assert raised.value.translation_key == "not_loaded"


@pytest.mark.freeze_time(NOW)
async def test_response_shapes_snapshot(
    hass: HomeAssistant, response_snapshot: SnapshotAssertion
) -> None:
    """The answers' shapes are a public contract, which the card's tests read too."""
    await set_up_entry(hass, TRANSPORT)

    assert await call(
        hass, "find_stops", kind="tram", query="pilar"
    ) == response_snapshot(name="find_tram_stops")
    assert await call(
        hass, "find_stops", kind="bus", limit=3, **AT_688
    ) == response_snapshot(name="find_bus_stops")
    assert await call(hass, "find_stops", kind="bizi", limit=3) == response_snapshot(
        name="find_bizi_stations"
    )
    assert await call(
        hass, "get_arrivals", mode="tram", stop="2502"
    ) == response_snapshot(name="tram_arrivals")
    assert await call(
        hass, "get_arrivals", mode="bus", stop="1231"
    ) == response_snapshot(name="bus_arrivals")
    assert await call(hass, "get_bizi_station", station="164") == response_snapshot(
        name="bizi_station"
    )


@pytest.mark.freeze_time(NOW)
async def test_error_shapes_snapshot(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    response_snapshot: SnapshotAssertion,
) -> None:
    """The errors as the card receives them, over the websocket: its tests read them too.

    One with placeholders, one without (Home Assistant sends those as null).
    """
    serve_tram_list(aioclient_mock, status=500)
    await set_up_entry(hass, {"kinds": ["tram", "bizi"]})
    # The websocket client starts the web server, so it comes after every setup.
    client = await hass_ws_client(hass)

    async def error_of(action: str, **data: object) -> object:
        await client.send_json_auto_id(
            {
                "type": "call_service",
                "domain": DOMAIN,
                "service": action,
                "service_data": data,
                "return_response": True,
            }
        )
        answer = await client.receive_json()
        assert answer["success"] is False
        return answer["error"]

    assert await error_of("get_bizi_station", station="9999") == response_snapshot(
        name="error_unknown_stop"
    )
    assert await error_of(
        "get_arrivals", mode="tram", stop="2502"
    ) == response_snapshot(name="error_source_unavailable")
