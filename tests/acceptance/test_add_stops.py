"""Adding tram, bus and Bizi stops from searchable pickers, and a bus stop's lines."""

import asyncio
from datetime import timedelta
import re

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.zaragoza_open_data.config_flow import NEAR_PLACE
from custom_components.zaragoza_open_data.const import DOMAIN, NAME
from custom_components.zaragoza_open_data.options import (
    read_bizi_station,
    read_bus_stop,
    read_tram_stop,
)
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigEntryState,
    ConfigSubentry,
    SubentryFlowResult,
)
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from tests.acceptance.entry import bus_stop, set_up_entry
from tests.acceptance.forms import (
    field_config,
    field_names,
    field_options,
    suggested_values,
)
from tests.acceptance.providers import (
    AVANZA,
    BUS_STOPS,
    TRAM_LIST,
    requests_to,
    serve_air_stations,
    serve_bike_stations,
    serve_bus_stops,
    serve_tram_list,
)
from tests.acceptance.states import device, state_of
from tests.fixtures import read_fixture

# Near Plaza Aragón, in the city centre.
HOME = (41.6488, -0.8891)
# A pin dropped on the Mago de Oz tram stop, at the southern end of the line.
MAGO_DE_OZ = {"latitude": 41.6244, "longitude": -0.9365}
NEAR_PLACE_OPTION = {"value": NEAR_PLACE, "label": "Near another place…"}


@pytest.fixture(autouse=True)
def home_in_zaragoza(hass: HomeAssistant) -> None:
    """Put home in Zaragoza; the test instance's home is in San Diego."""
    hass.config.latitude, hass.config.longitude = HOME


async def open_picker(
    hass: HomeAssistant, entry: MockConfigEntry, subentry_type: str
) -> SubentryFlowResult:
    """Start adding a stop, as the entry's "Add" button does."""
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, subentry_type), context={"source": SOURCE_USER}
    )


async def open_reconfigure(
    hass: HomeAssistant, entry: MockConfigEntry, subentry: ConfigSubentry
) -> SubentryFlowResult:
    """Start changing a saved stop, as its "Reconfigure" menu item does."""
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, subentry.subentry_type),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )


async def submit(
    hass: HomeAssistant, result: SubentryFlowResult, user_input: dict[str, object]
) -> SubentryFlowResult:
    """Submit the form ``result`` shows and let any reload finish."""
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], user_input
    )
    await hass.async_block_till_done()
    return result


async def switch_kinds(
    hass: HomeAssistant, entry: MockConfigEntry, kinds: list[str]
) -> None:
    """Tick only ``kinds`` in the options form, leave the rest, and save it."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**suggested_values(result["data_schema"]), "kinds": kinds}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


def only_subentry(entry: MockConfigEntry) -> ConfigSubentry:
    """Return the entry's one stop."""
    (subentry,) = entry.subentries.values()
    assert isinstance(subentry, ConfigSubentry)
    return subentry


async def test_tram_stop_added_from_list(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A platform picked from the list becomes a stop named by its direction."""
    serve_tram_list(aioclient_mock)
    entry = await set_up_entry(hass)
    assert device(hass, "tram_2502") is None

    result = await open_picker(hass, entry, "tram_stop")

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert {
        "value": "2502",
        "label": "Mago de Oz → Avenida de la Academia · 4.8 km",
    } in field_options(result["data_schema"], "stop")

    result = await submit(hass, result, {"stop": "2502"})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = only_subentry(entry)
    assert subentry.subentry_type == "tram_stop"
    assert subentry.unique_id == "tram_2502"
    assert subentry.title == "Mago de Oz → Avenida de la Academia"
    assert read_tram_stop(subentry) == {"code": "2502"}
    # A new stop starts the entry again, so its device and entities follow.
    assert entry.state is ConfigEntryState.LOADED
    assert device(hass, "tram_2502") is not None
    assert state_of(hass, "sensor", "tram_2502_next_arrival").state != STATE_UNAVAILABLE


async def test_options_ordered_nearest_first_with_near_place_on_top(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Every platform is offered, nearest to home first, after "Near another place…"."""
    serve_tram_list(aioclient_mock)
    entry = await set_up_entry(hass)

    result = await open_picker(hass, entry, "tram_stop")

    options = field_options(result["data_schema"], "stop")
    assert options[:5] == [
        NEAR_PLACE_OPTION,
        {"value": "1401", "label": "Gran Via → Mago de Oz · 302 m"},
        {"value": "1402", "label": "Gran Via → Avenida de la Academia · 310 m"},
        {"value": "1311", "label": "Plaza Aragon → Mago de Oz · 334 m"},
        {"value": "1312", "label": "Plaza Aragon → Avenida de la Academia · 342 m"},
    ]
    assert len(options) == 1 + 50
    # The frontend draws a searchable list only for a custom-value dropdown, and
    # keeps the nearest-first order only when told not to sort.
    config = field_config(result["data_schema"], "stop")
    assert config["custom_value"] is True
    assert config["sort"] is False
    assert config["mode"] == "dropdown"


async def test_typed_code_accepted(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A typed stop number works like picking it; labels follow the home language."""
    hass.config.language = "es"
    serve_bus_stops(aioclient_mock)
    entry = await set_up_entry(hass)

    result = await open_picker(hass, entry, "bus_stop")
    assert field_options(result["data_schema"], "stop")[0] == {
        "value": NEAR_PLACE,
        "label": "Cerca de otro lugar…",
    }
    result = await submit(hass, result, {"stop": " 688 "})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "lines"
    assert field_options(result["data_schema"], "lines") == ["58"]

    # Ticking no line keeps every line.
    result = await submit(hass, result, {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = only_subentry(entry)
    assert subentry.subentry_type == "bus_stop"
    assert subentry.unique_id == "bus_688"
    assert subentry.title == "688 · P. Reyes de Aragón N.º 24 · línea 58"
    assert read_bus_stop(subentry) == {"code": "688", "lines": []}


async def test_typed_unknown_text_shows_pick_from_list(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Text that is no stop number asks for a stop from the list, which stays shown."""
    serve_tram_list(aioclient_mock)
    entry = await set_up_entry(hass)

    result = await open_picker(hass, entry, "tram_stop")
    result = await submit(hass, result, {"stop": "pilar"})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"stop": "pick_from_list"}
    assert len(field_options(result["data_schema"], "stop")) == 1 + 50
    assert entry.subentries == {}

    result = await submit(hass, result, {"stop": "2502"})

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_near_place_reorders_list(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Picking "Near another place…" asks for a map pin, then sorts from it."""
    serve_tram_list(aioclient_mock)
    entry = await set_up_entry(hass)

    result = await open_picker(hass, entry, "tram_stop")
    result = await submit(hass, result, {"stop": NEAR_PLACE})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "place"
    assert suggested_values(result["data_schema"]) == {
        "location": {"latitude": HOME[0], "longitude": HOME[1]}
    }
    assert field_config(result["data_schema"], "location") == {"radius": False}

    result = await submit(hass, result, {"location": MAGO_DE_OZ})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert field_options(result["data_schema"], "stop")[:4] == [
        NEAR_PLACE_OPTION,
        {"value": "2502", "label": "Mago de Oz → Avenida de la Academia · 5 m"},
        {"value": "2501", "label": "Mago de Oz (arrivals) · 64 m"},
        {
            "value": "2422",
            "label": "Un Americano en Paris → Avenida de la Academia · 522 m",
        },
    ]

    result = await submit(hass, result, {"stop": "2502"})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert only_subentry(entry).unique_id == "tram_2502"


async def test_duplicate_stop_aborts_already_configured(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A stop already added is refused at once, before asking for its lines."""
    serve_bus_stops(aioclient_mock)
    entry = await set_up_entry(hass)
    result = await open_picker(hass, entry, "bus_stop")
    result = await submit(hass, result, {"stop": "688"})
    await submit(hass, result, {})

    result = await open_picker(hass, entry, "bus_stop")
    result = await submit(hass, result, {"stop": "688"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(entry.subentries) == 1


async def test_bus_stop_with_line_filter_and_reconfigure(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A bus stop keeps the lines ticked; reconfiguring changes only those."""
    serve_bus_stops(aioclient_mock)
    # The operator's page for 1274: lines 41 and N6, from the one recorded for 1231.
    page = (
        read_fixture("avanza/stop_1231.html")
        .replace('<td class="digital">56</td>', '<td class="digital">41</td>')
        .replace('<td class="digital">59</td>', '<td class="digital">N6</td>')
    )
    aioclient_mock.get(AVANZA, params={"poste": "1274"}, text=page)
    entry = await set_up_entry(hass)

    result = await open_picker(hass, entry, "bus_stop")
    assert field_options(result["data_schema"], "stop")[1:3] == [
        {"value": "1079", "label": "1079 · Hernán Cortés N.º 9 · lines 38, 41 · 51 m"},
        {
            "value": "1274",
            "label": "1274 · Hernán Cortés N.º 10 · lines N4, N6, 41 · 56 m",
        },
    ]
    result = await submit(hass, result, {"stop": "1274"})

    assert result["step_id"] == "lines"
    assert field_options(result["data_schema"], "lines") == ["N4", "N6", "41"]

    result = await submit(hass, result, {"lines": ["41", "N4"]})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = only_subentry(entry)
    title = "1274 · Hernán Cortés N.º 10 · lines N4, N6, 41"
    assert subentry.title == title
    # Stored in the stop's own order, whatever the order they were ticked in.
    assert read_bus_stop(subentry) == {"code": "1274", "lines": ["N4", "41"]}
    await hass.async_block_till_done(wait_background_tasks=True)
    assert state_of(hass, "sensor", "bus_1274_next_arrival").attributes["line"] == "41"

    result = await open_reconfigure(hass, entry, subentry)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert field_names(result["data_schema"]) == ["lines"]
    assert field_options(result["data_schema"], "lines") == ["N4", "N6", "41"]
    assert suggested_values(result["data_schema"]) == {"lines": ["N4", "41"]}

    result = await submit(hass, result, {"lines": ["N6"]})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    subentry = only_subentry(entry)
    assert read_bus_stop(subentry) == {"code": "1274", "lines": ["N6"]}
    assert subentry.title == title
    assert subentry.unique_id == "bus_1274"
    # The entry starts again with the new filter.
    assert entry.state is ConfigEntryState.LOADED
    await hass.async_block_till_done(wait_background_tasks=True)
    assert state_of(hass, "sensor", "bus_1274_next_arrival").attributes["line"] == "N6"


async def test_bus_picker_offers_only_urban_bus_stops(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Near home the picker offers bus stops only, each number once.

    The city's list also holds tram platforms ("TRA" their only line) and another
    network's stops, some sharing a number with an urban stop.
    """
    serve_bus_stops(aioclient_mock)
    entry = await set_up_entry(hass)

    result = await open_picker(hass, entry, "bus_stop")

    options = field_options(result["data_schema"], "stop")
    values = [option["value"] for option in options if isinstance(option, dict)]
    labels = [str(option["label"]) for option in options if isinstance(option, dict)]
    # "(1) Principio de Línea Líneas: 501" lies 150 m from home and
    # "(900) Terminal Líneas: 603, 605" 170 m; neither is offered.
    assert values[1:8] == ["1079", "1274", "505", "1249", "673", "3001", "682"]
    # The other network's stops near home (701, 900, 964) and the tram
    # platforms (1, 2, 11, 12, 22) have numbers no urban stop has.
    assert not {"1", "2", "11", "12", "22", "701", "900", "964"} & set(values)
    assert not [label for label in labels if re.search(r"\bTRA\b", label)]
    assert len(set(values)) == len(values) == 1 + 978


async def test_typed_bus_number_saves_that_stops_name_and_lines(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A number both networks use saves the urban stop; a tram platform's is refused.

    The city lists "(338) Esquina calle Atiliana Líneas: 501" before "(338) Coso
    N.º 126", and has bus stop 1 only as a tram platform and line 501's first stop.
    """
    serve_bus_stops(aioclient_mock)
    entry = await set_up_entry(hass)

    result = await open_picker(hass, entry, "bus_stop")
    result = await submit(hass, result, {"stop": "1"})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"stop": "pick_from_list"}

    result = await submit(hass, result, {"stop": "338"})

    assert result["step_id"] == "lines"
    assert field_options(result["data_schema"], "lines") == [
        "22",
        "35",
        "N1",
        "28",
        "21",
        "32",
    ]

    result = await submit(hass, result, {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = only_subentry(entry)
    assert subentry.title == "338 · Coso N.º 126 · lines 22, 35, N1, 28, 21, 32"
    assert read_bus_stop(subentry) == {"code": "338", "lines": []}


async def test_bus_stop_without_listed_lines_skips_the_filter(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A stop the city lists without lines has no filter to offer: every line."""
    serve_bus_stops(aioclient_mock)
    entry = await set_up_entry(hass)

    result = await open_picker(hass, entry, "bus_stop")
    result = await submit(hass, result, {"stop": "8111"})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = only_subentry(entry)
    assert subentry.title == "8111 · P. Fernando el Católico / Luis Vives"
    assert read_bus_stop(subentry) == {"code": "8111", "lines": []}


async def test_bizi_station_added(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A Bizi station picked from the list is saved under its public number."""
    serve_bike_stations(aioclient_mock)
    entry = await set_up_entry(hass)

    result = await open_picker(hass, entry, "bizi_station")
    assert field_options(result["data_schema"], "station")[:2] == [
        NEAR_PLACE_OPTION,
        {"value": "48", "label": "48 · H. Cortés: Pza. Arregui · 149 m"},
    ]
    result = await submit(hass, result, {"station": "164"})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = only_subentry(entry)
    assert subentry.subentry_type == "bizi_station"
    assert subentry.unique_id == "bizi_164"
    assert subentry.title == "164 · Rosales: Illueca"
    assert read_bizi_station(subentry) == {"code": "164"}


async def test_same_number_allowed_for_different_kinds(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Bus stop 48 and Bizi station 48 are different places: both can be added."""
    serve_bus_stops(aioclient_mock)
    serve_bike_stations(aioclient_mock)
    entry = await set_up_entry(hass)

    result = await open_picker(hass, entry, "bus_stop")
    result = await submit(hass, result, {"stop": "48"})
    result = await submit(hass, result, {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    result = await open_picker(hass, entry, "bizi_station")
    result = await submit(hass, result, {"station": "48"})
    assert result["type"] is FlowResultType.CREATE_ENTRY

    saved = {subentry.unique_id: subentry for subentry in entry.subentries.values()}
    assert sorted(saved) == ["bizi_48", "bus_48"]
    # Only the unique id carries the kind; the data keeps the public number.
    assert read_bus_stop(saved["bus_48"]) == {"code": "48", "lines": []}
    assert read_bizi_station(saved["bizi_48"]) == {"code": "48"}

    result = await open_picker(hass, entry, "bus_stop")
    result = await submit(hass, result, {"stop": "48"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(entry.subentries) == 2


async def test_every_stop_type_is_always_offered(hass: HomeAssistant) -> None:
    """The three "Add" buttons exist whatever the kinds; bus stops can be changed.

    Home Assistant works the buttons out once per entry and doesn't refresh them
    when the options change, so each flow checks its kind instead.
    """
    entry = await set_up_entry(hass, {"kinds": ["pollen"]})

    assert entry.supported_subentry_types == {
        "tram_stop": {"supports_reconfigure": False},
        "bus_stop": {"supports_reconfigure": True},
        "bizi_station": {"supports_reconfigure": False},
    }


async def test_disabled_kind_aborts_kind_disabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Adding a stop of a kind switched off in the options stops and says so."""
    serve_air_stations(aioclient_mock)
    serve_tram_list(aioclient_mock)
    serve_bus_stops(aioclient_mock)
    entry = await set_up_entry(hass)
    await switch_kinds(hass, entry, ["tram", "pollen"])

    result = await open_picker(hass, entry, "bus_stop")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "kind_disabled"
    result = await open_picker(hass, entry, "tram_stop")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    await switch_kinds(hass, entry, ["tram", "bus", "pollen"])
    result = await open_picker(hass, entry, "bus_stop")

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_bus_lines_cannot_change_while_bus_is_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A saved bus stop's lines can't be changed while bus is switched off."""
    serve_bus_stops(aioclient_mock)
    entry = await set_up_entry(hass)
    result = await open_picker(hass, entry, "bus_stop")
    result = await submit(hass, result, {"stop": "688"})
    await submit(hass, result, {})
    # The options form is to refuse switching off a kind that still has stops, so
    # the stored options are changed directly.
    hass.config_entries.async_update_entry(entry, options={"kinds": ["tram"]})
    await hass.async_block_till_done()

    result = await open_reconfigure(hass, entry, only_subentry(entry))

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "kind_disabled"


# Frozen, so the tram's second try at start (5 s on) doesn't wait for real.
@pytest.mark.freeze_time("2026-11-09 12:40:30+00:00")
async def test_source_down_shows_cannot_connect_and_retry_works(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The list unreachable: the form says so, and submitting it asks again."""
    serve_tram_list(aioclient_mock, status=500)
    entry = await set_up_entry(hass)

    result = await open_picker(hass, entry, "tram_stop")

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}
    assert field_names(result["data_schema"]) == []

    aioclient_mock.clear_requests()
    serve_tram_list(aioclient_mock)
    result = await submit(hass, result, {})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}
    assert len(field_options(result["data_schema"], "stop")) == 1 + 50

    result = await submit(hass, result, {"stop": "2502"})

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_bus_lines_cannot_change_while_the_list_is_down(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Reconfiguring needs the stop's lines: with no list yet it stops and says why."""
    serve_bus_stops(aioclient_mock, status=500)
    entry = await set_up_entry(hass, stops=[bus_stop("688", "688", ["58"])])

    result = await open_reconfigure(hass, entry, only_subentry(entry))

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"
    assert read_bus_stop(only_subentry(entry)) == {"code": "688", "lines": ["58"]}


async def test_pickers_keep_the_last_list_while_the_city_is_down(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A day on, with the city not answering, the picker offers the last list."""
    serve_bus_stops(aioclient_mock)
    entry = await set_up_entry(hass)
    await open_picker(hass, entry, "bus_stop")

    freezer.tick(timedelta(hours=24))
    aioclient_mock.clear_requests()
    serve_bus_stops(aioclient_mock, status=500)
    result = await open_picker(hass, entry, "bus_stop")

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}
    assert len(field_options(result["data_schema"], "stop")) == 1 + 978
    assert requests_to(aioclient_mock, BUS_STOPS) == 1


async def test_stops_need_the_entry_loaded(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """With the entry not running, adding or changing a stop stops at once and says why."""
    serve_bus_stops(aioclient_mock)
    entry = await set_up_entry(hass)
    result = await open_picker(hass, entry, "bus_stop")
    result = await submit(hass, result, {"stop": "688"})
    await submit(hass, result, {})
    assert await hass.config_entries.async_unload(entry.entry_id)

    # Nothing is starting, so nothing is waited for.
    async with asyncio.timeout(1):
        result = await open_picker(hass, entry, "bus_stop")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_loaded"

    async with asyncio.timeout(1):
        result = await open_reconfigure(hass, entry, only_subentry(entry))

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_loaded"


async def test_entry_waiting_to_retry_its_setup_aborts_at_once(
    hass: HomeAssistant,
) -> None:
    """An entry whose setup failed and waits to be retried isn't starting: no wait.

    A source down at setup doesn't fail this integration's setup (the tram list
    down still loads the entry), so the entry is given the state Home Assistant
    leaves after a setup that asked to be retried.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        data={},
        options={"kinds": ["tram"]},
        state=ConfigEntryState.SETUP_RETRY,
    )
    entry.add_to_hass(hass)

    async with asyncio.timeout(1):
        result = await open_picker(hass, entry, "tram_stop")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_loaded"


async def test_next_stop_can_be_added_right_after_one_is_added(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Adding a stop starts the entry again; an "Add" meanwhile waits for it.

    On a real instance the next picker, opened 0.3 s after a stop was saved, stopped.
    """
    serve_bus_stops(aioclient_mock)
    entry = await set_up_entry(hass)
    result = await open_picker(hass, entry, "bus_stop")
    result = await submit(hass, result, {"stop": "688"})

    # Saved, and nothing waited for: the entry is still starting again.
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.state is not ConfigEntryState.LOADED

    result = await open_picker(hass, entry, "bus_stop")

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert entry.state is ConfigEntryState.LOADED
    assert device(hass, "bus_688") is not None

    result = await submit(hass, result, {"stop": "1274"})
    result = await submit(hass, result, {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(entry.subentries) == 2


async def test_lines_can_be_changed_right_after_the_stop_is_added(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Reconfiguring a stop while the entry starts again waits for it too."""
    serve_bus_stops(aioclient_mock)
    entry = await set_up_entry(hass)
    result = await open_picker(hass, entry, "bus_stop")
    result = await submit(hass, result, {"stop": "1274"})
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"lines": ["41"]}
    )
    assert entry.state is not ConfigEntryState.LOADED

    result = await open_reconfigure(hass, entry, only_subentry(entry))

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert suggested_values(result["data_schema"]) == {"lines": ["41"]}


async def test_stop_flow_waits_at_most_30_s_for_the_entry_to_start(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An entry still starting 30 s on: the flow stops waiting and says why."""
    serve_tram_list(aioclient_mock)
    entry = await set_up_entry(hass, {"kinds": ["tram"]})
    result = await open_picker(hass, entry, "tram_stop")
    # The city holds the restarted entry's first tram request until told.
    answer = asyncio.Event()

    async def slow_city(
        method: str, url: URL, data: object
    ) -> AiohttpClientMockResponse:
        await answer.wait()
        return AiohttpClientMockResponse(
            method, url, text=read_fixture("zaragoza_city/tram_list.json")
        )

    aioclient_mock.clear_requests()
    aioclient_mock.get(TRAM_LIST, side_effect=slow_city)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"stop": "2502"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    # Started at once, the flow runs until it waits for the entry.
    picker = hass.async_create_task(open_picker(hass, entry, "tram_stop"))
    assert not picker.done()
    freezer.tick(timedelta(seconds=29))
    async_fire_time_changed(hass)
    await asyncio.sleep(0)

    assert not picker.done()

    freezer.tick(timedelta(seconds=1))
    async_fire_time_changed(hass)
    result = await picker

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_loaded"

    answer.set()
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_stop_lists_fetched_once_a_day(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The bus list (three requests) is asked for once a day, even across reloads.

    Adding a stop reloads the entry, so the list must outlive it.
    """
    serve_bus_stops(aioclient_mock)
    entry = await set_up_entry(hass)

    result = await open_picker(hass, entry, "bus_stop")
    assert requests_to(aioclient_mock, BUS_STOPS) == 3
    result = await submit(hass, result, {"stop": "688"})
    await submit(hass, result, {})
    # Started again: the new stop has its device.
    assert device(hass, "bus_688") is not None

    result = await open_picker(hass, entry, "bus_stop")
    assert len(field_options(result["data_schema"], "stop")) == 1 + 978
    assert requests_to(aioclient_mock, BUS_STOPS) == 3

    freezer.tick(timedelta(hours=23, minutes=59))
    await open_picker(hass, entry, "bus_stop")
    assert requests_to(aioclient_mock, BUS_STOPS) == 3

    freezer.tick(timedelta(minutes=1))
    await open_picker(hass, entry, "bus_stop")
    assert requests_to(aioclient_mock, BUS_STOPS) == 6


async def test_pickers_opened_together_share_one_fetch(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Two bus pickers opened at once cause a single fetch of the list."""
    serve_bus_stops(aioclient_mock)
    entry = await set_up_entry(hass)

    first, second = await asyncio.gather(
        open_picker(hass, entry, "bus_stop"), open_picker(hass, entry, "bus_stop")
    )

    assert first["type"] is second["type"] is FlowResultType.FORM
    assert requests_to(aioclient_mock, BUS_STOPS) == 3
