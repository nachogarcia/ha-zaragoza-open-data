"""Options: kinds, map distances and centres, categories, air station, refresh floors."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant.typing import WebSocketGenerator

from custom_components.zaragoza_open_data.api.models import RoadWorkCategory
from custom_components.zaragoza_open_data.const import Kind
from custom_components.zaragoza_open_data.options import (
    MapLayerOptions,
    RefreshOptions,
    ZodOptions,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from homeassistant.setup import async_setup_component
from tests.acceptance.clock import move_to
from tests.acceptance.entry import change_options, set_up_entry, tram_stop
from tests.acceptance.forms import field_options, suggested_values
from tests.acceptance.providers import (
    AIR_STATIONS,
    PHARMACIES,
    POLLEN,
    ROAD_WORKS,
    TRAM_LIST,
    requests_to,
    serve_air_stations,
    serve_road_works,
    serve_tram_list,
)
from tests.acceptance.states import device, geo_events, state_of

DEFAULT_REFRESH = {
    "tram_s": 60,
    "bus_s": 60,
    "bike_s": 120,
    "road_works_min": 30,
    "air_quality_min": 30,
    "pollen_h": 6,
    "pharmacies_h": 6,
}
# The options form as it first appears for an entry with the default options.
DEFAULT_FORM = {
    "kinds": [
        "tram",
        "bus",
        "bizi",
        "road_works",
        "pharmacies",
        "air_quality",
        "pollen",
    ],
    "road_works_radius_km": 2.0,
    "road_works_centre": "zone.home",
    "road_works_categories": [
        "traffic_closure",
        "water_cut",
        "major_disruption",
        "public_transport_disruption",
        "maintenance",
        "other",
    ],
    "pharmacies_radius_km": 0.0,
    "pharmacies_centre": "zone.home",
    "air_station": "nearest",
    "refresh": DEFAULT_REFRESH,
}


async def test_options_form_shows_current_options_and_the_air_stations(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The form starts from the options in force; stations are listed by name."""
    serve_air_stations(aioclient_mock)
    entry = await set_up_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert suggested_values(result["data_schema"]) == DEFAULT_FORM
    assert field_options(result["data_schema"], "air_station") == [
        {"value": "nearest", "label": "nearest"},
        {"value": "12", "label": "Actur"},
        {"value": "11", "label": "Avda. Soria"},
        {"value": "10", "label": "Centro"},
        {"value": "1", "label": "El Picarral"},
        {"value": "7", "label": "Jaime Ferran"},
        {"value": "9", "label": "Las Fuentes"},
        {"value": "8", "label": "Renovales"},
        {"value": "2", "label": "Roger de Flor"},
    ]


async def test_options_do_not_fetch_disabled_air_quality(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Opening and saving options respects an air-quality opt-out."""
    entry = await set_up_entry(hass, {"kinds": ["bizi"], "air_station": "12"})
    aioclient_mock.clear_requests()

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert field_options(result["data_schema"], "air_station") == [
        {"value": "nearest", "label": "nearest"},
        {"value": "12", "label": "12"},
    ]
    assert suggested_values(result["data_schema"])["air_station"] == "12"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], suggested_values(result["data_schema"])
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["air_station"] == "12"
    assert requests_to(aioclient_mock, AIR_STATIONS) == 0


async def test_enabling_air_quality_offers_stations_in_the_next_options_form(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Once enabled, air quality's station list can be used to choose a station."""
    entry = await set_up_entry(hass, {"kinds": ["bizi"]})

    await change_options(hass, entry, kinds=["bizi", "air_quality"])
    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    choices = field_options(result["data_schema"], "air_station")
    assert {"value": "12", "label": "Actur"} in choices
    assert len(choices) == 9
    assert requests_to(aioclient_mock, AIR_STATIONS) > 0


async def test_options_reject_refresh_below_floor(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A source can be asked less often than its default, never more often."""
    serve_air_stations(aioclient_mock)
    entry = await set_up_entry(hass)
    before = dict(entry.options)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**DEFAULT_FORM, "refresh": {**DEFAULT_REFRESH, "tram_s": 30}},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "refresh_below_minimum"}
    # The form keeps what the user typed so it can be corrected.
    assert suggested_values(result["data_schema"])["refresh"] == {
        **DEFAULT_REFRESH,
        "tram_s": 30,
    }
    assert dict(entry.options) == before


async def test_options_update_reloads_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Saved options are stored and the entry starts again using them."""
    serve_air_stations(aioclient_mock)
    entry = await set_up_entry(hass)
    assert device(hass, "air_quality") is not None

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "kinds": ["tram", "bus", "pollen"],
            "road_works_radius_km": 0.5,
            "road_works_centre": "zone.work",
            "road_works_categories": ["water_cut", "traffic_closure"],
            "pharmacies_radius_km": 3,
            "pharmacies_centre": "zone.home",
            "air_station": "12",
            "refresh": {**DEFAULT_REFRESH, "tram_s": 120, "pollen_h": 12},
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {
        "kinds": ["tram", "bus", "pollen"],
        "road_works_radius_km": 0.5,
        "road_works_centre": "zone.work",
        "road_works_categories": ["traffic_closure", "water_cut"],
        "pharmacies_radius_km": 3.0,
        "pharmacies_centre": "zone.home",
        "air_station": "12",
        "refresh": {**DEFAULT_REFRESH, "tram_s": 120, "pollen_h": 12},
    }
    assert entry.state is ConfigEntryState.LOADED
    # Started again: the kinds left out took their devices, pollen kept its own.
    assert device(hass, "air_quality") is None
    assert device(hass, "pollen") is not None
    assert entry.runtime_data.options == ZodOptions(
        kinds=frozenset({Kind.TRAM, Kind.BUS, Kind.POLLEN}),
        road_works=MapLayerOptions(radius_km=0.5, centre_zone="zone.work"),
        pharmacies=MapLayerOptions(radius_km=3.0, centre_zone="zone.home"),
        road_work_categories=frozenset(
            {RoadWorkCategory.WATER_CUT, RoadWorkCategory.TRAFFIC_CLOSURE}
        ),
        air_station="12",
        refresh=RefreshOptions(
            tram=timedelta(seconds=120),
            bus=timedelta(seconds=60),
            bizi=timedelta(seconds=120),
            road_works=timedelta(minutes=30),
            air_quality=timedelta(minutes=30),
            pollen=timedelta(hours=12),
            pharmacies=timedelta(hours=6),
        ),
    )


async def test_nearest_air_station_is_stored_as_empty(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Saving the form unchanged keeps the defaults, the nearest station included."""
    serve_air_stations(aioclient_mock)
    entry = await set_up_entry(hass, {"air_station": "12"})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert suggested_values(result["data_schema"])["air_station"] == "12"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], DEFAULT_FORM
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == ZodOptions.from_mapping({}).to_mapping()
    assert entry.options["air_station"] == ""
    assert entry.runtime_data.options.air_station is None


# Frozen, so the air quality's second try at start (5 s on) doesn't wait for real.
@pytest.mark.freeze_time("2026-11-09 12:40:30+00:00")
async def test_options_work_while_the_air_station_list_is_down(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The city down: the form still opens with the chosen station, and saves."""
    serve_air_stations(aioclient_mock, status=500)
    entry = await set_up_entry(hass, {"air_station": "12"})
    form = {**DEFAULT_FORM, "air_station": "12"}
    before = requests_to(aioclient_mock, AIR_STATIONS)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert field_options(result["data_schema"], "air_station") == [
        {"value": "nearest", "label": "nearest"},
        {"value": "12", "label": "12"},
    ]
    assert suggested_values(result["data_schema"]) == form

    slower = {**DEFAULT_REFRESH, "tram_s": 30, "pollen_h": 12}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**form, "refresh": slower}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "refresh_below_minimum"}
    assert suggested_values(result["data_schema"]) == {**form, "refresh": slower}
    # The list is asked for once per form, not again when it is shown again.
    assert requests_to(aioclient_mock, AIR_STATIONS) == before + 1

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**form, "refresh": {**slower, "tram_s": 90}}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["air_station"] == "12"
    assert entry.options["refresh"] == {**slower, "tram_s": 90}


async def test_configured_air_station_missing_from_the_list_is_still_offered(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A station the city stopped listing stays selectable until the user changes it."""
    serve_air_stations(aioclient_mock)
    entry = await set_up_entry(hass, {"air_station": "99"})

    result = await hass.config_entries.options.async_init(entry.entry_id)

    offered = field_options(result["data_schema"], "air_station")
    assert len(offered) == 10
    assert offered[-1] == {"value": "99", "label": "99"}


@pytest.mark.freeze_time("2026-11-09 12:40:30+00:00")
@pytest.mark.parametrize(
    ("fixture", "offered"),
    [("air_quality_stations.json", 9), ("air_quality_stations_empty_derived.json", 1)],
    ids=["listed", "empty"],
)
async def test_options_ask_for_the_stations_the_sensors_have_not_brought(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, fixture: str, offered: int
) -> None:
    """The air sensors down since setup: the form asks the city for the stations.

    An answer with no station offers only "nearest", and the form still opens.
    """
    serve_air_stations(aioclient_mock, status=500)
    entry = await set_up_entry(hass, {"kinds": ["air_quality"]})
    aioclient_mock.clear_requests()
    serve_air_stations(aioclient_mock, fixture=fixture)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert len(field_options(result["data_schema"], "air_station")) == offered
    assert requests_to(aioclient_mock, AIR_STATIONS) == 1


async def test_options_reject_huge_refresh_values(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Intervals have a ceiling, so a huge number is refused by the form itself."""
    serve_air_stations(aioclient_mock)
    entry = await set_up_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            {**DEFAULT_FORM, "refresh": {**DEFAULT_REFRESH, "tram_s": 1e20}},
        )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**DEFAULT_FORM, "refresh": {**DEFAULT_REFRESH, "tram_s": 86_400}},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_stored_refresh_below_floor_runs_at_the_floor(
    hass: HomeAssistant,
) -> None:
    """An interval stored below its floor (edited by hand) is used as the floor."""
    entry = await set_up_entry(hass, {"refresh": {"tram_s": 5, "pollen_h": 1}})

    assert entry.runtime_data.options.refresh.tram == timedelta(seconds=60)
    assert entry.runtime_data.options.refresh.pollen == timedelta(hours=6)


# 13:40:30 in Zaragoza.
NOW = "2026-11-09 12:40:30+00:00"
ROAD_WORKS_SOURCE = "zaragoza_open_data_road_works"
# The city's service devices, one per kind of city information.
CITY_DEVICES = ("road_works", "pharmacies", "air_quality", "pollen")


@pytest.mark.freeze_time(NOW)
@pytest.mark.usefixtures("in_zaragoza", "home_in_zaragoza")
async def test_deleted_centre_zone_falls_back_to_home(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A layer follows its zone at each refresh; once the zone is deleted, home."""
    assert await async_setup_component(hass, "zone", {})
    serve_road_works(aioclient_mock)
    await set_up_entry(
        hass,
        {
            "kinds": ["road_works", "pharmacies"],
            "road_works_radius_km": 0.5,
            "road_works_centre": "zone.work",
            # A zone deleted before the entry started.
            "pharmacies_centre": "zone.gone",
        },
    )

    # No Work zone yet: measured from home, 168 m from the works on María Agustín.
    events = geo_events(hass, ROAD_WORKS_SOURCE)
    assert sorted(events) == ["road_works_31148"]
    assert events["road_works_31148"].state == "0.2"
    nearest = state_of(hass, "sensor", "pharmacies_nearest_duty_pharmacy")
    assert nearest.attributes["distance_km"] == 0.4

    # Work, 1.8 km east of home, by the works on Dr. Blanco Cordero. (The
    # websocket client starts the web server, so it comes after every setup.)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "zone/create",
            "name": "Work",
            "latitude": 41.6522,
            "longitude": -0.8680,
            "radius": 100,
        }
    )
    created = await client.receive_json()
    assert created["success"]
    await move_to(hass, freezer, "2026-11-09 13:10:30+00:00")

    events = geo_events(hass, ROAD_WORKS_SOURCE)
    assert sorted(events) == [
        "road_works_25688",
        "road_works_31003",
        "road_works_31507",
        "road_works_31556",
        "road_works_31590",
        "road_works_31591",
    ]
    assert events["road_works_25688"].state == "0.0"

    await client.send_json_auto_id(
        {"type": "zone/delete", "zone_id": created["result"]["id"]}
    )
    assert (await client.receive_json())["success"]
    await move_to(hass, freezer, "2026-11-09 13:40:30+00:00")

    events = geo_events(hass, ROAD_WORKS_SOURCE)
    assert sorted(events) == ["road_works_31148"]
    assert events["road_works_31148"].state == "0.2"
    assert state_of(hass, "sensor", "road_works_nearby").state == "1"


@pytest.mark.freeze_time(NOW)
@pytest.mark.usefixtures("in_zaragoza", "home_in_zaragoza")
async def test_disabling_a_kind_removes_its_entities_and_devices(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Kinds switched off take their devices, entities and map pins, and stop asking."""
    entry = await set_up_entry(hass)
    for identifier in CITY_DEVICES:
        assert device(hass, identifier) is not None
    assert hass.states.async_all("geo_location") != []

    await change_options(hass, entry, kinds=["bus", "bizi"])

    for identifier in CITY_DEVICES:
        assert device(hass, identifier) is None
    assert hass.states.async_all("geo_location") == []
    # Bus and Bizi have no stops yet, so nothing is left: not even tram notices.
    registry = er.async_get(hass)
    assert er.async_entries_for_config_entry(registry, entry.entry_id) == []
    assert [state.entity_id for state in hass.states.async_all("sensor")] == []

    aioclient_mock.clear_requests()
    await move_to(hass, freezer, "2026-11-10 12:40:30+00:00")
    for url in (TRAM_LIST, ROAD_WORKS, PHARMACIES, AIR_STATIONS, POLLEN):
        assert requests_to(aioclient_mock, url) == 0

    await change_options(hass, entry, kinds=["bus", "bizi", "pollen"])

    assert device(hass, "pollen") is not None
    assert state_of(hass, "sensor", "pollen_Cupressaceae").state == "bajo"


@pytest.mark.freeze_time(NOW)
async def test_transport_kind_with_stops_cannot_be_disabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The form asks to remove a kind's stops before switching it off."""
    serve_tram_list(aioclient_mock)
    entry = await set_up_entry(
        hass,
        {"kinds": ["tram", "pollen"]},
        [tram_stop("2502", "Mago de Oz → Avenida de la Academia")],
    )
    before = dict(entry.options)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**suggested_values(result["data_schema"]), "kinds": ["pollen"]},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"kinds": "remove_stops_first"}
    # The form keeps what the user ticked so it can be corrected.
    assert suggested_values(result["data_schema"])["kinds"] == ["pollen"]
    assert dict(entry.options) == before

    # A kind without stops can still be switched off.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**suggested_values(result["data_schema"]), "kinds": ["tram"]},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["kinds"] == ["tram"]
    assert state_of(hass, "sensor", "tram_2502_next_arrival").state != "unavailable"


@pytest.mark.freeze_time(NOW)
async def test_options_need_a_kind_ticked(hass: HomeAssistant) -> None:
    """Unticking every kind is refused in the user's language; the options stay."""
    entry = await set_up_entry(hass, {"kinds": ["pollen"]})
    before = dict(entry.options)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**suggested_values(result["data_schema"]), "kinds": []}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"kinds": "no_kinds"}
    assert dict(entry.options) == before
    key = "component.zaragoza_open_data.options.error.no_kinds"
    english = await async_get_translations(
        hass, "en", "options", ["zaragoza_open_data"]
    )
    spanish = await async_get_translations(
        hass, "es", "options", ["zaragoza_open_data"]
    )
    assert english[key] == "Tick at least one kind of data."
    assert spanish[key] == "Marca al menos un tipo de datos."
