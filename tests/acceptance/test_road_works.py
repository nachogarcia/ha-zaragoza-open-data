"""Road works map layer: radius, categories, appear/disappear, pictures, count, names."""

import asyncio

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import async_capture_events
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.zaragoza_open_data.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from homeassistant.setup import async_setup_component
from tests.acceptance.clock import move_to
from tests.acceptance.entry import change_options, set_up_entry
from tests.acceptance.pictures import picture
from tests.acceptance.providers import (
    ROAD_WORKS,
    ROAD_WORKS_TODAY,
    requests_to,
    serve_road_works,
)
from tests.acceptance.states import device, geo_events, state_of
from tests.fixtures import read_fixture

pytestmark = pytest.mark.usefixtures("in_zaragoza", "home_in_zaragoza")

# 13:40:30 in Zaragoza.
NOW = "2026-11-09 12:40:30+00:00"
ROAD_WORKS_ONLY = {"kinds": ["road_works"]}
SOURCE = "zaragoza_open_data_road_works"
# "DR. BLANCO CORDERO": a traffic closure 1.8 km from home, the incidents list's first.
BLANCO_CORDERO = "road_works_25688"


@pytest.mark.freeze_time(NOW)
async def test_road_works_filtered_by_radius_and_category(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Only works of the ticked categories within the distance of home are shown."""
    serve_road_works(aioclient_mock)
    await set_up_entry(
        hass,
        {
            "kinds": ["road_works"],
            "road_works_radius_km": 1.0,
            "road_works_categories": ["traffic_closure", "water_cut"],
        },
    )

    events = geo_events(hass, SOURCE)
    # From both lists (31580 is a water cut on today's maintenance list), all within
    # 1 km: 18 works are, but the other 11 are major disruptions or maintenance.
    assert sorted(events) == [
        "road_works_28004",
        "road_works_29395",
        "road_works_31093",
        "road_works_31364",
        "road_works_31425",
        "road_works_31580",
        "road_works_31592",
    ]
    # The state is the distance from home, in km.
    assert events["road_works_28004"].state == "0.5"
    assert events["road_works_28004"].attributes["unit_of_measurement"] == "km"
    assert events["road_works_29395"].state == "1.0"
    nearby = state_of(hass, "sensor", "road_works_nearby")
    assert nearby.state == "7"
    assert (
        nearby.attributes["attribution"]
        == "Origen de los datos: Ayuntamiento de Zaragoza"
    )
    # Both lists, once each.
    assert requests_to(aioclient_mock, ROAD_WORKS) == 1
    assert requests_to(aioclient_mock, ROAD_WORKS_TODAY) == 1


@pytest.mark.freeze_time(NOW)
async def test_whole_city_with_no_distance(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A distance of 0 shows every located work in the city; 2 km is the default."""
    serve_road_works(aioclient_mock)
    entry = await set_up_entry(hass, ROAD_WORKS_ONLY)

    assert state_of(hass, "sensor", "road_works_nearby").state == "53"
    assert len(geo_events(hass, SOURCE)) == 53

    await change_options(hass, entry, road_works_radius_km=0)

    # 70 incidents and 25 of today's 28 maintenance jobs: 3 have no location.
    assert state_of(hass, "sensor", "road_works_nearby").state == "95"
    assert len(geo_events(hass, SOURCE)) == 95


@pytest.mark.freeze_time(NOW)
async def test_road_works_events_appear_and_disappear(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A work the city starts listing appears on the map; one it drops leaves it."""
    serve_road_works(
        aioclient_mock, incidents="road_works_incidencia_ended_derived.json"
    )
    await set_up_entry(hass, ROAD_WORKS_ONLY)

    assert BLANCO_CORDERO not in geo_events(hass, SOURCE)
    assert state_of(hass, "sensor", "road_works_nearby").state == "52"

    aioclient_mock.clear_requests()
    serve_road_works(aioclient_mock)
    await move_to(hass, freezer, "2026-11-09 13:10:30+00:00")

    event = geo_events(hass, SOURCE)[BLANCO_CORDERO]
    assert event.name == "DR. BLANCO CORDERO"
    assert event.state == "1.8"
    assert event.attributes["latitude"] == 41.65224
    assert event.attributes["longitude"] == -0.86801
    assert event.attributes["street"] == "BLANCO CORDERO (DR.), 11"
    assert event.attributes["reason"] == (
        "Para la reforma de las calles y de las viviendas es necesario el corte de "
        "las calles"
    )
    assert event.attributes["stretch"].startswith("Dr. Blanco Cordero se corta")
    assert event.attributes["detour"].startswith("Se mantiene cortada Blanco Cordero")
    # In Zaragoza's time, like every time the integration shows.
    assert event.attributes["starts"] == "2025-07-09T00:00:00+02:00"
    assert event.attributes["ends"] == "2027-02-26T00:00:00+01:00"
    assert event.attributes["category"] == "traffic_closure"
    assert (
        event.attributes["attribution"]
        == "Origen de los datos: Ayuntamiento de Zaragoza"
    )
    assert state_of(hass, "sensor", "road_works_nearby").state == "53"
    registry = er.async_get(hass)
    ended = registry.async_get_entity_id("geo_location", DOMAIN, BLANCO_CORDERO)
    assert ended is not None

    aioclient_mock.clear_requests()
    serve_road_works(
        aioclient_mock, incidents="road_works_incidencia_ended_derived.json"
    )
    await move_to(hass, freezer, "2026-11-09 13:40:30+00:00")

    assert BLANCO_CORDERO not in geo_events(hass, SOURCE)
    assert hass.states.get(ended) is None
    # Gone from the registry too: works come and go, and none is left behind.
    assert registry.async_get_entity_id("geo_location", DOMAIN, BLANCO_CORDERO) is None
    assert state_of(hass, "sensor", "road_works_nearby").state == "52"

    # Listed again (the city's lists do flicker): back on the map, same entity.
    aioclient_mock.clear_requests()
    serve_road_works(aioclient_mock)
    await move_to(hass, freezer, "2026-11-09 14:10:30+00:00")

    assert geo_events(hass, SOURCE)[BLANCO_CORDERO].state == "1.8"
    assert registry.async_get_entity_id("geo_location", DOMAIN, BLANCO_CORDERO) == ended


@pytest.mark.freeze_time(NOW)
async def test_new_closure_fires_the_geolocation_trigger(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An automation "new road work near Work" runs when one appears there."""
    serve_road_works(
        aioclient_mock, incidents="road_works_incidencia_ended_derived.json"
    )
    await set_up_entry(hass, ROAD_WORKS_ONLY)
    # 500 m around Dr. Blanco Cordero, where five other works already are.
    assert await async_setup_component(
        hass,
        "zone",
        {
            "zone": [
                {
                    "name": "Work",
                    "latitude": 41.6522,
                    "longitude": -0.868,
                    "radius": 500,
                }
            ]
        },
    )
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "triggers": {
                    "trigger": "geo_location",
                    "source": SOURCE,
                    "zone": "zone.work",
                    "event": "enter",
                },
                "actions": {
                    "event": "road_work_near_work",
                    "event_data": {"work": "{{ trigger.to_state.name }}"},
                },
            }
        },
    )
    fired = async_capture_events(hass, "road_work_near_work")

    aioclient_mock.clear_requests()
    serve_road_works(aioclient_mock)
    await move_to(hass, freezer, "2026-11-09 13:10:30+00:00")

    assert [event.data for event in fired] == [{"work": "DR. BLANCO CORDERO"}]


async def test_pins_keep_their_settings_across_a_reload(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A pin renamed by the user is still renamed after a reload, while the city answers."""
    serve_road_works(aioclient_mock)
    entry = await set_up_entry(hass, ROAD_WORKS_ONLY)
    registry = er.async_get(hass)
    pin = registry.async_get_entity_id("geo_location", DOMAIN, BLANCO_CORDERO)
    assert pin is not None
    registry.async_update_entity(pin, name="Corte de casa")
    answered = asyncio.Event()

    async def held(method: str, url: URL, data: object) -> AiohttpClientMockResponse:
        await answered.wait()
        return AiohttpClientMockResponse(
            method, url, text=read_fixture("zaragoza_city/road_works_incidencia.json")
        )

    aioclient_mock.clear_requests()
    aioclient_mock.get(ROAD_WORKS, side_effect=held)
    # Real time here: a reload waiting for the held answer would never end.
    async with asyncio.timeout(10):
        assert await hass.config_entries.async_reload(entry.entry_id)

    # The list isn't in yet: no pin is taken for gone.
    renamed = registry.async_get(pin)
    assert renamed is not None
    assert renamed.name == "Corte de casa"

    answered.set()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert geo_events(hass, SOURCE)[BLANCO_CORDERO].name == "Corte de casa"


@pytest.mark.freeze_time(NOW)
async def test_road_works_refresh_every_30_minutes(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Both lists are asked at start and every 30 minutes after."""
    serve_road_works(aioclient_mock)
    await set_up_entry(hass, ROAD_WORKS_ONLY)

    await move_to(hass, freezer, "2026-11-09 13:10:29+00:00")
    assert requests_to(aioclient_mock, ROAD_WORKS) == 1
    await move_to(hass, freezer, "2026-11-09 13:10:30+00:00")
    assert requests_to(aioclient_mock, ROAD_WORKS) == 2
    assert requests_to(aioclient_mock, ROAD_WORKS_TODAY) == 2


@pytest.mark.freeze_time(NOW)
async def test_road_works_unavailable_while_the_city_is_down(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The city down past three refreshes: the count and pins are unavailable until it answers.

    The two failed refreshes before keep the last lists shown.
    """
    serve_road_works(aioclient_mock)
    entry = await set_up_entry(hass, ROAD_WORKS_ONLY)

    aioclient_mock.clear_requests()
    serve_road_works(aioclient_mock, status=500)
    for refresh in ("13:10:30", "13:40:30"):
        await move_to(hass, freezer, f"2026-11-09 {refresh}+00:00")
        assert state_of(hass, "sensor", "road_works_nearby").state == "53"
        assert geo_events(hass, SOURCE)[BLANCO_CORDERO].state == "1.8"
    await move_to(hass, freezer, "2026-11-09 14:10:30+00:00")

    assert state_of(hass, "sensor", "road_works_nearby").state == "unavailable"
    # Unavailable, the pins carry no place and leave the map until the city answers.
    assert geo_events(hass, SOURCE) == {}
    pins = [
        registered.entity_id
        for registered in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
        if registered.domain == "geo_location"
    ]
    assert len(pins) == 53
    states = [hass.states.get(pin) for pin in pins]
    assert {None if state is None else state.state for state in states} == {
        "unavailable"
    }

    aioclient_mock.clear_requests()
    serve_road_works(aioclient_mock)
    await move_to(hass, freezer, "2026-11-09 14:40:30+00:00")

    assert state_of(hass, "sensor", "road_works_nearby").state == "53"
    assert geo_events(hass, SOURCE)[BLANCO_CORDERO].state == "1.8"


@pytest.mark.freeze_time(NOW)
async def test_road_work_pictures_follow_category(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Each pin shows its category's sign; a category the city adds shows "other"."""
    serve_road_works(
        aioclient_mock, incidents="road_works_incidencia_unknown_category_derived.json"
    )
    await set_up_entry(hass, ROAD_WORKS_ONLY)

    events = geo_events(hass, SOURCE)
    pictures = {
        unique_id: (
            events[unique_id].attributes["category"],
            events[unique_id].attributes["entity_picture"],
        )
        for unique_id in (
            BLANCO_CORDERO,
            "road_works_28004",
            "road_works_31148",
            "road_works_31542",
            "road_works_31580",
            "road_works_31534",
        )
    }
    assert pictures == {
        # "Obras Menores", which the integration doesn't know.
        BLANCO_CORDERO: ("other", picture("road_other")),
        "road_works_28004": ("traffic_closure", picture("road_closed")),
        "road_works_31148": ("major_disruption", picture("major_disruption")),
        "road_works_31542": ("maintenance", picture("works")),
        "road_works_31580": ("water_cut", picture("water_cut")),
        "road_works_31534": (
            "public_transport_disruption",
            picture("transit_disruption"),
        ),
    }


@pytest.mark.parametrize(
    ("language", "names", "closure", "until"),
    [
        (
            "en",
            ["Street", "Reason", "Stretch", "Detour", "From", "Until", "Category"],
            "Traffic closure",
            "Open until",
        ),
        (
            "es",
            ["Calle", "Motivo", "Tramo", "Desvío", "Desde", "Hasta", "Categoría"],
            "Corte de tráfico",
            "Abierta hasta",
        ),
    ],
)
@pytest.mark.freeze_time(NOW)
async def test_attribute_names_translated(
    hass: HomeAssistant, language: str, names: list[str], closure: str, until: str
) -> None:
    """A pin's details read in the user's language, the category included."""
    await set_up_entry(hass)
    registry = er.async_get(hass)

    def translation_key(source: str) -> str | None:
        state = next(iter(geo_events(hass, f"zaragoza_open_data_{source}").values()))
        registered = registry.async_get(state.entity_id)
        assert registered is not None
        return registered.translation_key

    # The frontend finds an entity's translations through its registry entry.
    assert {
        source: translation_key(source)
        for source in ("road_works", "pharmacies", "air_quality")
    } == {
        "road_works": "road_work",
        "pharmacies": "pharmacy",
        "air_quality": "air_station",
    }

    translations = await async_get_translations(hass, language, "entity", [DOMAIN])

    prefix = f"component.{DOMAIN}.entity.geo_location"
    attributes = ("street", "reason", "stretch", "detour", "starts", "ends", "category")
    assert [
        translations[f"{prefix}.road_work.state_attributes.{attribute}.name"]
        for attribute in attributes
    ] == names
    assert (
        translations[
            f"{prefix}.road_work.state_attributes.category.state.traffic_closure"
        ]
        == closure
    )
    for attribute in ("address", "phone", "hours", "sector"):
        assert f"{prefix}.pharmacy.state_attributes.{attribute}.name" in translations
    open_until = "state_attributes.open_until.name"
    assert translations[f"{prefix}.pharmacy.{open_until}"] == until
    sensor = f"component.{DOMAIN}.entity.sensor.nearest_duty_pharmacy.{open_until}"
    assert translations[sensor] == until
    for attribute in ("index", "no", "no2", "o3", "so2", "pm10", "pm25", "co", "h2s"):
        assert f"{prefix}.air_station.state_attributes.{attribute}.name" in translations
    assert f"{prefix}.air_station.state_attributes.index.state.moderate" in translations
    assert (
        translations[f"{prefix}.air_station.state_attributes.no.name"] == "NO (μg/m³)"
    )


@pytest.mark.freeze_time(NOW)
async def test_geo_location_source_names(hass: HomeAssistant) -> None:
    """Each layer has its own source, which a map card lists to show it."""
    await set_up_entry(hass)

    sources = {
        state.attributes["source"] for state in hass.states.async_all("geo_location")
    }
    assert sources == {
        "zaragoza_open_data_road_works",
        "zaragoza_open_data_pharmacies",
        "zaragoza_open_data_air_quality",
    }
    assert len(geo_events(hass, "zaragoza_open_data_road_works")) == 53
    assert len(geo_events(hass, "zaragoza_open_data_pharmacies")) == 7
    assert len(geo_events(hass, "zaragoza_open_data_air_quality")) == 8


NEW_ROAD_WORK = "zaragoza_open_data_new_road_work"
ENDED = "road_works_incidencia_ended_derived.json"


@pytest.mark.freeze_time(NOW)
async def test_no_new_road_work_events_on_the_first_setup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """On the entry's first start every work is new to it, so none is announced."""
    fired = async_capture_events(hass, NEW_ROAD_WORK)
    serve_road_works(aioclient_mock)

    await set_up_entry(hass, ROAD_WORKS_ONLY)

    assert len(geo_events(hass, SOURCE)) == 53
    assert fired == []


@pytest.mark.freeze_time(NOW)
async def test_new_road_work_event_only_on_first_appearance(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A new work is announced once: not after a reload, an outage or a day away."""
    fired = async_capture_events(hass, NEW_ROAD_WORK)
    serve_road_works(aioclient_mock, incidents=ENDED)
    entry = await set_up_entry(hass, ROAD_WORKS_ONLY)

    aioclient_mock.clear_requests()
    serve_road_works(aioclient_mock)
    await move_to(hass, freezer, "2026-11-09 13:10:30+00:00")

    assert [event.data for event in fired] == [
        {
            "id": "25688",
            "title": "DR. BLANCO CORDERO",
            "street": "BLANCO CORDERO (DR.), 11",
            "category": "traffic_closure",
            "distance_km": 1.8,
            "latitude": 41.65223943112013,
            "longitude": -0.8680137472773933,
            "starts": "2025-07-09T00:00:00+02:00",
            "ends": "2027-02-26T00:00:00+01:00",
        }
    ]

    # Known works after a reload (as after a restart) aren't new.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    # Nor after the city is down for a while.
    aioclient_mock.clear_requests()
    serve_road_works(aioclient_mock, status=500)
    await move_to(hass, freezer, "2026-11-09 13:40:30+00:00")
    aioclient_mock.clear_requests()
    serve_road_works(aioclient_mock)
    await move_to(hass, freezer, "2026-11-09 14:10:30+00:00")
    # Nor when the city drops one for a day and lists it again.
    aioclient_mock.clear_requests()
    serve_road_works(aioclient_mock, incidents=ENDED)
    await move_to(hass, freezer, "2026-11-10 12:40:30+00:00")
    aioclient_mock.clear_requests()
    serve_road_works(aioclient_mock)
    await move_to(hass, freezer, "2026-11-10 13:10:30+00:00")

    assert len(fired) == 1
    assert BLANCO_CORDERO in geo_events(hass, SOURCE)


@pytest.mark.freeze_time(NOW)
async def test_new_road_work_outside_the_layer_is_not_announced(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Only works the layer shows are announced; widening it announces none."""
    fired = async_capture_events(hass, NEW_ROAD_WORK)
    serve_road_works(aioclient_mock, incidents=ENDED)
    entry = await set_up_entry(hass, {**ROAD_WORKS_ONLY, "road_works_radius_km": 1.0})

    aioclient_mock.clear_requests()
    serve_road_works(aioclient_mock)
    # Dr. Blanco Cordero, 1.8 km away, starts outside the 1 km.
    await move_to(hass, freezer, "2026-11-09 13:10:30+00:00")
    await change_options(hass, entry, road_works_radius_km=0)

    assert len(geo_events(hass, SOURCE)) == 95
    assert fired == []


@pytest.mark.freeze_time(NOW)
async def test_road_works_announced_afresh_after_the_entry_is_removed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Removing the integration forgets the works seen: set up again, it starts over."""
    fired = async_capture_events(hass, NEW_ROAD_WORK)
    serve_road_works(aioclient_mock, incidents=ENDED)
    entry = await set_up_entry(hass, ROAD_WORKS_ONLY)
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert device(hass, "road_works") is None

    aioclient_mock.clear_requests()
    serve_road_works(aioclient_mock)
    await set_up_entry(hass, ROAD_WORKS_ONLY)

    # A first setup again: Dr. Blanco Cordero is not announced.
    assert BLANCO_CORDERO in geo_events(hass, SOURCE)
    assert fired == []


@pytest.mark.freeze_time(NOW)
async def test_road_work_back_after_a_month_is_announced_again(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A work off the lists for over 30 days is forgotten, as is a month-old memory."""
    fired = async_capture_events(hass, NEW_ROAD_WORK)
    serve_road_works(aioclient_mock)
    await set_up_entry(hass, ROAD_WORKS_ONLY)
    aioclient_mock.clear_requests()
    serve_road_works(aioclient_mock, incidents=ENDED)
    await move_to(hass, freezer, "2026-11-10 12:40:30+00:00")

    # 31 days without a refresh (Home Assistant off, or road works switched
    # off): everything remembered is too old, so nothing is announced.
    await move_to(hass, freezer, "2026-12-11 12:40:30+00:00")
    assert fired == []

    aioclient_mock.clear_requests()
    serve_road_works(aioclient_mock)
    await move_to(hass, freezer, "2026-12-11 13:10:30+00:00")

    assert [event.data["id"] for event in fired] == ["25688"]


@pytest.mark.freeze_time(NOW)
async def test_damaged_road_works_memory_starts_afresh(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, object],
) -> None:
    """A memory edited by hand into nonsense is ignored, quietly."""
    hass_storage["zaragoza_open_data.road_works"] = {
        "version": 1,
        "key": "zaragoza_open_data.road_works",
        "data": {"seen": {"25688": "yesterday", "28004": 5}},
    }
    fired = async_capture_events(hass, NEW_ROAD_WORK)
    serve_road_works(aioclient_mock, incidents=ENDED)
    await set_up_entry(hass, ROAD_WORKS_ONLY)

    aioclient_mock.clear_requests()
    serve_road_works(aioclient_mock)
    await move_to(hass, freezer, "2026-11-09 13:10:30+00:00")

    # Nothing readable was remembered: the first list was taken as known.
    assert [event.data["id"] for event in fired] == ["25688"]


@pytest.mark.freeze_time(NOW)
async def test_road_work_that_appeared_during_a_restart_is_announced(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """What the entry saw is kept across a restart: a work new since then is new."""
    fired = async_capture_events(hass, NEW_ROAD_WORK)
    serve_road_works(aioclient_mock, incidents=ENDED)
    entry = await set_up_entry(hass, ROAD_WORKS_ONLY)

    aioclient_mock.clear_requests()
    serve_road_works(aioclient_mock)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert [event.data["id"] for event in fired] == ["25688"]
