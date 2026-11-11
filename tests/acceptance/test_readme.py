"""The READMEs' examples work as pasted, in both languages.

Every ``yaml`` block parses. Automations and scripts pass the checks Home
Assistant's editors run. Action calls name real fields and pass the action's own
checks. Response examples have the shape the actions answer with. The map card
shows the integration's layers and the example stops' real entities, with a
legend for every pin the integration ships. The card that keeps the automatic Map
to people lists only people and zones.
"""

from collections.abc import Iterator
import json
from pathlib import Path
import re

import pytest

from custom_components.zaragoza_open_data.const import DOMAIN, EVENT_NEW_ROAD_WORK
from custom_components.zaragoza_open_data.geo_location import (
    AIR_QUALITY_SOURCE,
    PHARMACIES_SOURCE,
    ROAD_WORKS_SOURCE,
)
from homeassistant.components.automation.config import (
    async_validate_config_item as validate_automation,
)
from homeassistant.components.script.config import (
    async_validate_config_item as validate_script,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util.yaml import load_yaml_dict, parse_yaml
from tests.acceptance.entry import set_up_entry

pytestmark = pytest.mark.usefixtures("in_zaragoza", "home_in_zaragoza")

REPO = Path(__file__).parents[2]
INTEGRATION = REPO / "custom_components" / DOMAIN
SNAPSHOTS = Path(__file__).parent / "snapshots" / "test_actions"
README_LANGUAGES = {"README.md": "en", "README.es.md": "es"}
READMES = pytest.mark.parametrize("readme", list(README_LANGUAGES))

# What the road work event carries (the public contract, see test_road_works.py).
EVENT_DATA = {
    "id",
    "title",
    "street",
    "category",
    "distance_km",
    "latitude",
    "longitude",
    "starts",
    "ends",
}
# The stops the map example lists: (subentry type, its picker's field, the code).
EXAMPLE_STOPS = [
    ("tram_stop", "stop", "1302"),
    ("bus_stop", "stop", "688"),
    ("bizi_station", "station", "16"),
]


def examples(readme: str) -> list[dict[str, object]]:
    """Return every ``yaml`` block of ``readme``, parsed by Home Assistant's loader."""
    blocks = re.findall(
        r"```yaml\n(.*?)```", (REPO / readme).read_text("utf-8"), re.DOTALL
    )
    parsed = [parse_yaml(block) for block in blocks]
    assert all(isinstance(block, dict) for block in parsed)
    return [block for block in parsed if isinstance(block, dict)]


def of_kind(readme: str, kind: str) -> list[dict[str, object]]:
    """Return the examples of one kind; every example is of exactly one kind."""
    return [block for block in examples(readme) if kind_of(block) == kind]


def kind_of(block: dict[str, object]) -> str:
    """Tell what a block is from its keys."""
    if "triggers" in block:
        return "automation"
    if "sequence" in block:
        return "script"
    if "action" in block:
        return "action"
    if "type" in block:
        return "card"
    if "arrivals" in block or "stops" in block or "bikes" in block:
        return "response"
    raise AssertionError(f"An example of no known kind: {block}")


def integration_actions(config: object) -> Iterator[dict[str, object]]:
    """Yield every call to one of the integration's actions inside ``config``."""
    if isinstance(config, dict):
        action = config.get("action")
        if isinstance(action, str) and action.startswith(f"{DOMAIN}."):
            yield config
        for value in config.values():
            yield from integration_actions(value)
    elif isinstance(config, list):
        for value in config:
            yield from integration_actions(value)


def fields_of(action: str) -> set[str]:
    """Return the fields ``services.yaml`` documents for ``action``."""
    services = load_yaml_dict(INTEGRATION / "services.yaml")
    return set(services[action.removeprefix(f"{DOMAIN}.")]["fields"])


def shape(value: object) -> object:
    """Return the keys of ``value`` all the way down, with lists by their first item."""
    if isinstance(value, dict):
        return {key: shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return None


@READMES
def test_every_kind_of_example_is_there(readme: str) -> None:
    """Each README has an action, a response, a script, automations and the map."""
    kinds = [kind_of(block) for block in examples(readme)]

    assert {"action", "response", "script", "automation", "card"} <= set(kinds)


@READMES
async def test_automations_and_scripts_pass_home_assistant_checks(
    hass: HomeAssistant, readme: str
) -> None:
    """Pasted into the automation or script editor, each example is accepted."""
    automations = of_kind(readme, "automation")
    scripts = of_kind(readme, "script")

    for automation in automations:
        assert await validate_automation(hass, "readme", automation) is not None
    for script in scripts:
        assert await validate_script(hass, "readme", script) is not None
    for config in [*automations, *scripts]:
        for call in integration_actions(config):
            data = call.get("data", {})
            assert isinstance(data, dict)
            assert set(data) <= fields_of(str(call["action"])), call


@READMES
async def test_action_examples_pass_the_actions_checks(
    hass: HomeAssistant, readme: str
) -> None:
    """Each action example names real fields with values the action accepts."""
    await set_up_entry(hass, {"kinds": ["tram", "bus", "bizi"]})
    registered = hass.services.async_services_for_domain(DOMAIN)
    calls = of_kind(readme, "action")

    assert calls
    for call in calls:
        name = str(call["action"]).removeprefix(f"{DOMAIN}.")
        data = call.get("data", {})
        assert isinstance(data, dict)
        assert set(data) <= fields_of(str(call["action"])), call
        schema = registered[name].schema
        assert schema is not None
        schema(data)


@READMES
def test_response_examples_have_the_actions_shape(readme: str) -> None:
    """A response example has exactly the keys the action answers with."""
    snapshots = [
        shape(json.loads(path.read_text("utf-8")))
        for path in SNAPSHOTS.glob("test_response_shapes_snapshot*.json")
    ]
    responses = of_kind(readme, "response")

    assert responses
    for response in responses:
        assert shape(response) in snapshots, response


@READMES
def test_search_card_example_uses_the_cards_settings(readme: str) -> None:
    """The search card example sets only settings the card reads."""
    config = (REPO / "frontend" / "src" / "config.ts").read_text("utf-8")
    settings = set(re.findall(r'config\["(\w+)"\]', config)) | set(
        re.findall(r'optional\(config, "(\w+)"', config)
    )
    [card] = [
        card
        for card in of_kind(readme, "card")
        if card["type"] == "custom:zaragoza-open-data-card"
    ]

    assert set(card) - {"type"} <= settings


@READMES
def test_road_work_automation_uses_the_event(readme: str) -> None:
    """The "new closure near home" example triggers on the integration's event.

    It reads only what the event carries.
    """
    automations = [
        automation
        for automation in of_kind(readme, "automation")
        if EVENT_NEW_ROAD_WORK in json.dumps(automation)
    ]

    assert len(automations) == 1
    [automation] = automations
    assert automation["triggers"] == [
        {"trigger": "event", "event_type": EVENT_NEW_ROAD_WORK}
    ]
    read = set(re.findall(r"trigger\.event\.data\.(\w+)", json.dumps(automation)))
    assert read
    assert read <= EVENT_DATA


@READMES
async def test_map_card_shows_layers_example_stops_and_a_full_legend(
    hass: HomeAssistant, readme: str
) -> None:
    """The "Zaragoza" map card works as pasted, after adding the example stops.

    It lists the three map layers and the stops' real entities (Bizi by its
    number of bikes), and its legend shows every pin the integration ships.
    """
    [dashboard] = [
        card for card in of_kind(readme, "card") if card["type"] == "vertical-stack"
    ]
    cards = dashboard["cards"]
    assert isinstance(cards, list)
    [map_card, legend] = cards
    hass.config.language = README_LANGUAGES[readme]
    entry = await set_up_entry(hass, {"kinds": ["tram", "bus", "bizi"]})
    # Added as a user does, so their titles (and the entity ids) are the flows' own.
    for subentry_type, field, code in EXAMPLE_STOPS:
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, subentry_type), context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {field: code}
        )
        if result["type"] is FlowResultType.FORM:
            # A bus stop asks which lines to show: none ticked is every line.
            assert result["step_id"] == "lines"
            result = await hass.config_entries.subentries.async_configure(
                result["flow_id"], {"lines": []}
            )
        assert result["type"] is FlowResultType.CREATE_ENTRY, result
        await hass.async_block_till_done(wait_background_tasks=True)

    assert map_card["type"] == "map"
    assert map_card["geo_location_sources"] == [
        ROAD_WORKS_SOURCE,
        PHARMACIES_SOURCE,
        AIR_QUALITY_SOURCE,
    ]
    entities = [
        entity if isinstance(entity, dict) else {"entity": entity}
        for entity in map_card["entities"]
    ]
    assert len(entities) == len(EXAMPLE_STOPS)
    for entity in entities:
        state = hass.states.get(entity["entity"])
        assert state is not None, entity
        # A map card places an entity by these.
        assert {"latitude", "longitude"} <= set(state.attributes), entity
    [bikes] = [entity for entity in entities if "label_mode" in entity]
    assert bikes["label_mode"] == "state"
    registered = er.async_get(hass).async_get(bikes["entity"])
    assert registered is not None
    assert registered.unique_id == "bizi_16_bikes"
    assert legend["type"] == "markdown"
    shown = set(
        re.findall(r"/zaragoza_open_data/markers/(\w+)\.svg", legend["content"])
    )
    shipped = {path.stem for path in (INTEGRATION / "markers").glob("*.svg")}
    assert shown == shipped


@READMES
def test_people_map_card_lists_only_people_and_zones(readme: str) -> None:
    """The card that keeps the automatic Map to people shows nothing of the city.

    The automatic Map's card has ``show_all``, which takes every entity with a
    position, the integration's included; this one names people and zones.
    """
    [card] = [card for card in of_kind(readme, "card") if card["type"] == "map"]
    entities = card["entities"]

    assert isinstance(entities, list)
    assert entities
    assert {str(entity).split(".")[0] for entity in entities} <= {"person", "zone"}
    assert not {"show_all", "geo_location_sources"} & set(card)


@READMES
def test_public_examples_keep_clear_of_a_private_home_area(readme: str) -> None:
    """No example, text or action example points at the Bizi station next to a home.

    Station 164 stays as recorded test data; the examples use a central one instead.
    """
    public = [
        (REPO / readme).read_text("utf-8"),
        (INTEGRATION / "services.yaml").read_text("utf-8"),
    ]

    for text in public:
        assert not re.search(r"\b164\b|Rosales", text)


@READMES
async def test_badge_example_shows_the_minutes_to_the_next_trams(
    hass: HomeAssistant, readme: str
) -> None:
    """The badge works as pasted, after adding the example tram platform.

    It shows the platform's minutes sensor: its state, then attributes it has.
    """
    [badge] = [card for card in of_kind(readme, "card") if card["type"] == "entity"]
    hass.config.language = README_LANGUAGES[readme]
    entry = await set_up_entry(hass, {"kinds": ["tram"]})
    # Added as a user does, so the entity id is the flow's own.
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "tram_stop"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"stop": "1302"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done(wait_background_tasks=True)

    entity = str(badge["entity"])
    registered = er.async_get(hass).async_get(entity)
    assert registered is not None
    assert registered.unique_id == "tram_1302_minutes_to_next"
    state = hass.states.get(entity)
    assert state is not None
    shown = badge["state_content"]
    assert isinstance(shown, list)
    assert shown[0] == "state"
    assert shown[1:]
    assert set(shown[1:]) <= set(state.attributes)
