"""Setting the integration up: the checklist, one instance, unreachable sources, unload."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta

import pytest
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.zaragoza_open_data.const import DOMAIN, Kind
from custom_components.zaragoza_open_data.options import ZodOptions
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.translation import async_get_translations
from tests.acceptance.entry import set_up_entry
from tests.acceptance.providers import (
    AIR_STATIONS,
    BUS_STOPS,
    GBFS_STATIONS,
    GBFS_STATUS,
    PHARMACIES,
    POLLEN,
    ROAD_WORKS,
    ROAD_WORKS_TODAY,
    TRAM_LIST,
    requests_to,
    serve_bike_stations,
    serve_bike_status,
    serve_tram_list,
)
from tests.acceptance.states import geo_events, state_of
from tests.fixtures import read_fixture

# The city's endpoints the first refreshes ask, the recorded answer and a label.
CITY_ANSWERS = (
    (TRAM_LIST, "tram_list.json", "tram"),
    (ROAD_WORKS, "road_works_incidencia.json", "road works"),
    (ROAD_WORKS_TODAY, "road_works_conservacion_hoy.json", "road works today"),
    (PHARMACIES, "pharmacies_on_duty.json", "pharmacies"),
    (AIR_STATIONS, "air_quality_stations.json", "air quality"),
    (POLLEN, "pollen.json", "pollen"),
)
type Responder = Callable[[str, URL, object], Awaitable[AiohttpClientMockResponse]]

ALL_KINDS = [
    "tram",
    "bus",
    "bizi",
    "road_works",
    "pharmacies",
    "air_quality",
    "pollen",
]


async def test_user_step_creates_entry_with_all_kinds_ticked(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Accepting the one setup screen as shown brings in every kind of data."""
    serve_tram_list(aioclient_mock)
    serve_bike_stations(aioclient_mock)
    serve_bike_status(aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Zaragoza Open Data"
    assert result["data"] == {}
    assert result["options"]["kinds"] == ALL_KINDS
    assert result["options"] == ZodOptions.from_mapping({}).to_mapping()
    assert result["result"].state is ConfigEntryState.LOADED
    # The city and the Bizi operator were both checked before creating the entry;
    # then the entry asked each once more to fill in its sensors.
    assert requests_to(aioclient_mock, TRAM_LIST) == 2
    assert requests_to(aioclient_mock, GBFS_STATIONS) == 2
    assert requests_to(aioclient_mock, GBFS_STATUS) == 1


async def test_bike_operator_checked_only_when_bizi_is_ticked(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Without Bizi, setup asks only the city."""
    serve_tram_list(aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"kinds": ["tram", "pollen"]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"]["kinds"] == ["tram", "pollen"]
    # Checked once, then asked once more by the entry's tram sensors.
    assert requests_to(aioclient_mock, TRAM_LIST) == 2
    assert requests_to(aioclient_mock, GBFS_STATIONS) == 0


@pytest.mark.parametrize(
    ("kinds", "expected_urls"),
    [
        (["tram"], {TRAM_LIST}),
        (["bus"], {BUS_STOPS}),
        (["bizi"], {GBFS_STATIONS, GBFS_STATUS}),
        (["road_works"], {ROAD_WORKS, ROAD_WORKS_TODAY}),
        (["pharmacies"], {PHARMACIES}),
        (["air_quality"], {AIR_STATIONS}),
        (["pollen"], {POLLEN}),
    ],
)
async def test_setup_only_requests_enabled_kinds(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    kinds: list[str],
    expected_urls: set[str],
) -> None:
    """Unchecked kinds are never fetched, including the initial reachability check."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"kinds": kinds}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"]["kinds"] == kinds
    assert {
        str(url.with_query(None))
        for _method, url, _data, _headers in aioclient_mock.mock_calls
    } == expected_urls


async def test_bizi_only_setup_works_while_city_is_down(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Bizi's operator answering is enough when every city kind is switched off."""
    serve_tram_list(aioclient_mock, status=500)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"kinds": ["bizi"]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].state is ConfigEntryState.LOADED
    assert requests_to(aioclient_mock, TRAM_LIST) == 0
    assert requests_to(aioclient_mock, GBFS_STATIONS) == 2


async def test_single_instance(hass: HomeAssistant) -> None:
    """A second setup is refused: everything lives in one entry."""
    MockConfigEntry(domain=DOMAIN, data={}).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_cannot_connect_shows_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The city down: the form says so, nothing is created, and retrying works."""
    serve_tram_list(aioclient_mock, status=500)
    serve_bike_stations(aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"kinds": ["tram", "bizi"]}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert hass.config_entries.async_entries(DOMAIN) == []

    aioclient_mock.clear_requests()
    serve_tram_list(aioclient_mock)
    serve_bike_stations(aioclient_mock)
    serve_bike_status(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"kinds": ["tram", "bizi"]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"]["kinds"] == ["tram", "bizi"]


async def test_setup_needs_a_kind_ticked(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Nothing ticked: the form asks for a kind, in the user's language; nobody is asked."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"kinds": []}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"kinds": "no_kinds"}
    assert hass.config_entries.async_entries(DOMAIN) == []
    assert aioclient_mock.call_count == 0
    key = f"component.{DOMAIN}.config.error.no_kinds"
    english = await async_get_translations(hass, "en", "config", [DOMAIN])
    spanish = await async_get_translations(hass, "es", "config", [DOMAIN])
    assert english[key] == "Tick at least one kind of data."
    assert spanish[key] == "Marca al menos un tipo de datos."


async def test_setup_and_unload(hass: HomeAssistant) -> None:
    """The entry loads with its options in force and unloads cleanly."""
    entry = await set_up_entry(hass, {"kinds": ["bus"], "refresh": {"bus_s": 90}})

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.options.kinds == {Kind.BUS}
    assert entry.runtime_data.options.refresh.bus == timedelta(seconds=90)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    unloaded = hass.config_entries.async_get_entry(entry.entry_id)
    assert unloaded is not None
    assert unloaded.state is ConfigEntryState.NOT_LOADED


def record_city_requests(
    aioclient_mock: AiohttpClientMocker,
    timeline: list[tuple[str, str]],
    hold: dict[str, asyncio.Event] | None = None,
) -> None:
    """Answer the city's endpoints as recorded, noting when each request starts and ends.

    A request sent while another is in flight starts before that one ends. A
    request whose label is in ``hold`` waits for its event before answering.
    """

    def answer(fixture: str, label: str) -> Responder:
        async def respond(
            method: str, url: URL, data: object
        ) -> AiohttpClientMockResponse:
            timeline.append(("start", label))
            if hold is not None and label in hold:
                await hold[label].wait()
            # A request sent alongside this one would start while this one waits.
            await asyncio.sleep(0)
            timeline.append(("end", label))
            return AiohttpClientMockResponse(
                method, url, text=read_fixture(f"zaragoza_city/{fixture}")
            )

        return respond

    for url, fixture, label in CITY_ANSWERS:
        aioclient_mock.get(url, side_effect=answer(fixture, label))


# The recorded pharmacies are the turn of 2026-11-09: asked on that day, they are on duty.
@pytest.mark.freeze_time("2026-11-09 12:40:30+00:00")
@pytest.mark.usefixtures("in_zaragoza", "home_in_zaragoza")
async def test_city_first_refreshes_ask_the_city_one_at_a_time(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """At setup the city gets one request at a time: the tram's, then the others."""
    timeline: list[tuple[str, str]] = []
    record_city_requests(aioclient_mock, timeline)

    await set_up_entry(hass)

    def asked(label: str) -> list[tuple[str, str]]:
        return [("start", label), ("end", label)]

    assert timeline == [
        *asked("tram"),
        *asked("road works"),
        *asked("road works today"),
        *asked("pharmacies"),
        # The stations and their readings, in one answer.
        *asked("air quality"),
        *asked("pollen"),
    ]
    # Once they have answered, every layer and sensor is there.
    assert len(geo_events(hass, "zaragoza_open_data_road_works")) == 53
    assert len(geo_events(hass, "zaragoza_open_data_pharmacies")) == 7
    assert len(geo_events(hass, "zaragoza_open_data_air_quality")) == 8
    assert state_of(hass, "sensor", "air_quality_no2").state == "28.75"
    assert state_of(hass, "sensor", "pollen_Cupressaceae").state == "bajo"


@pytest.mark.usefixtures("in_zaragoza", "home_in_zaragoza")
async def test_setup_does_not_wait_for_the_city_information(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The entry is running, its tram sensors filled, while the city is still asked."""
    timeline: list[tuple[str, str]] = []
    road_works_answered = asyncio.Event()
    record_city_requests(
        aioclient_mock, timeline, hold={"road works": road_works_answered}
    )

    # Real time here: a setup waiting for the held answer would never end.
    async with asyncio.timeout(10):
        entry = await set_up_entry(hass, settle=False)

    assert entry.state is ConfigEntryState.LOADED
    assert timeline == [("start", "tram"), ("end", "tram"), ("start", "road works")]
    assert state_of(hass, "sensor", "tram_notices").state == "0"
    # Nothing to show yet, and no made-up zero either.
    assert state_of(hass, "sensor", "road_works_nearby").state == STATE_UNKNOWN
    assert state_of(hass, "sensor", "air_quality_index").state == STATE_UNKNOWN
    assert geo_events(hass, "zaragoza_open_data_road_works") == {}

    road_works_answered.set()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert state_of(hass, "sensor", "road_works_nearby").state == "53"
    assert len(geo_events(hass, "zaragoza_open_data_road_works")) == 53
    assert state_of(hass, "sensor", "air_quality_index").state == "moderate"
