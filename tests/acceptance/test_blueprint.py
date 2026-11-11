"""The Assist blueprint: ask when the next tram or bus comes, in Spanish or English."""

import json
from pathlib import Path
import re
import shutil
from urllib.parse import parse_qs, urlparse

import pytest
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant.typing import WebSocketGenerator

from homeassistant.components import conversation
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
from homeassistant.core import Context, HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml_dict
from tests.acceptance.entry import set_up_entry
from tests.acceptance.providers import (
    serve_avanza,
    serve_bus_stops,
    serve_city_bus,
    serve_tram_list,
)

pytestmark = pytest.mark.usefixtures("in_zaragoza", "home_in_zaragoza")

REPO = Path(__file__).parents[2]
BLUEPRINT = REPO / "blueprints/automation/zaragoza_open_data/ask_next_tram.yaml"
# The blueprint needs the version the integration needs.
MIN_VERSION = json.loads((REPO / "hacs.json").read_text("utf-8"))["homeassistant"]
# Where the READMEs' import link points, and the file GitHub serves for it.
GITHUB = (
    "https://github.com/nachogarcia/ha-zaragoza-open-data/blob/main/"
    "blueprints/automation/zaragoza_open_data/ask_next_tram.yaml"
)
RAW = (
    "https://raw.githubusercontent.com/nachogarcia/ha-zaragoza-open-data/main/"
    "blueprints/automation/zaragoza_open_data/ask_next_tram.yaml"
)
# Where Home Assistant saves a blueprint imported from that link.
IMPORTED = "nachogarcia/ask_next_tram.yaml"

# 13:40:30 in Zaragoza, 28 s after the recorded tram list was published (13:40:02).
NOW = "2026-11-09 12:40:30+00:00"
TRANSPORT = {"kinds": ["tram", "bus", "bizi"]}
# What it says when find_stops fails, whatever the reason.
CANT_LOOK_UP_BUS_ES = (
    "Ahora no puedo buscar paradas de autobús. "
    "Comprueba que el autobús está activado en las opciones de la integración."
)
CANT_LOOK_UP_BUS_EN = (
    "I can't look up bus stops right now. "
    "Check that buses are switched on in the integration's options."
)


def _blueprint() -> Blueprint:
    """Load the blueprint file as Home Assistant loads an automation blueprint."""
    return Blueprint(
        load_yaml_dict(BLUEPRINT),
        path=IMPORTED,
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )


async def test_blueprint_is_valid(hass: HomeAssistant) -> None:
    """Home Assistant accepts it: two sentence triggers, Spanish and English.

    The sentences are inputs, so people can add their own wording; the stop and
    the mode come from the spoken sentence.
    """
    blueprint = _blueprint()

    assert blueprint.metadata["homeassistant"]["min_version"] == MIN_VERSION
    assert blueprint.validate() is None
    assert set(blueprint.inputs) == {"spanish_sentences", "english_sentences"}
    automation = BlueprintInputs(
        blueprint, {"use_blueprint": {"path": IMPORTED, "input": {}}}
    ).async_substitute()
    triggers = automation["triggers"]
    assert [(trigger["trigger"], trigger["id"]) for trigger in triggers] == [
        ("conversation", "es"),
        ("conversation", "en"),
    ]
    spanish, english = (trigger["command"] for trigger in triggers)
    assert "cuándo pasa el {mode} en {stop}" in spanish
    assert "when is the next {mode} at {stop}" in english


@pytest.mark.parametrize("readme", ["README.md", "README.es.md"])
async def test_readme_link_imports_the_blueprint(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    aioclient_mock: AiohttpClientMocker,
    tmp_path: Path,
    readme: str,
) -> None:
    """The import button in each README brings this file into Home Assistant."""
    links = re.findall(
        r"https://my\.home-assistant\.io/redirect/blueprint_import/\?[^)\s]+",
        (REPO / readme).read_text("utf-8"),
    )
    assert len(links) == 1
    assert parse_qs(urlparse(links[0]).query)["blueprint_url"] == [GITHUB]
    hass.config.config_dir = str(tmp_path)
    aioclient_mock.get(RAW, text=BLUEPRINT.read_text("utf-8"))
    assert await async_setup_component(hass, "automation", {})
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "blueprint/import", "url": GITHUB})
    imported = await client.receive_json()
    assert imported["success"], imported
    assert imported["result"]["validation_errors"] is None
    await client.send_json_auto_id(
        {
            "type": "blueprint/save",
            "domain": "automation",
            "path": imported["result"]["suggested_filename"],
            "yaml": imported["result"]["raw_data"],
            "source_url": GITHUB,
        }
    )
    saved = await client.receive_json()

    assert saved["success"], saved
    assert (tmp_path / "blueprints/automation" / IMPORTED).is_file()


@pytest.fixture
async def assistant(hass: HomeAssistant, tmp_path: Path) -> None:
    """Assist with an automation made from the imported blueprint, all defaults."""
    hass.config.config_dir = str(tmp_path)
    saved = tmp_path / "blueprints/automation" / IMPORTED
    saved.parent.mkdir(parents=True)
    shutil.copyfile(BLUEPRINT, saved)
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "conversation", {})
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "id": "ask_next_tram",
                "alias": "Ask for the next tram or bus",
                "use_blueprint": {"path": IMPORTED, "input": {}},
            }
        },
    )
    state = hass.states.get("automation.ask_for_the_next_tram_or_bus")
    assert state is not None
    assert state.state == "on"


async def ask(hass: HomeAssistant, text: str, language: str) -> str:
    """Say ``text`` to Assist in ``language`` and return what it answers."""
    result = await conversation.async_converse(
        hass, text, None, Context(), language=language
    )
    speech = result.response.speech["plain"]["speech"]
    assert isinstance(speech, str)
    return speech


@pytest.mark.usefixtures("assistant")
@pytest.mark.freeze_time(NOW)
async def test_spanish_question_answers_next_trams_in_spanish(
    hass: HomeAssistant,
) -> None:
    """Asked in Spanish, it names the platform nearest home and what comes next."""
    await set_up_entry(hass, TRANSPORT)

    answer = await ask(hass, "¿Cuándo pasa el tranvía en Plaza España?", "es")

    assert answer == (
        "Plaza Espana, hacia Mago de Oz: "
        "línea L1 a Mago de Oz en 2 minutos; línea L1 a Mago de Oz en 7 minutos."
    )


@pytest.mark.usefixtures("assistant")
@pytest.mark.freeze_time(NOW)
async def test_english_question_answers_next_buses_in_english(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Asked in English for a bus stop by its number, it answers in English."""
    serve_avanza(aioclient_mock, "688")
    await set_up_entry(hass, TRANSPORT)

    answer = await ask(hass, "When is the next bus at 688?", "en")

    assert answer == (
        "P. Reyes de Aragón N.º 24: line 58 to FUENTE JUNQUERA in 24 minutes; "
        "line 58 to FUENTE JUNQUERA in 48 minutes."
    )


@pytest.mark.usefixtures("assistant")
@pytest.mark.freeze_time(NOW)
async def test_stop_found_by_name_and_its_departing_platform(
    hass: HomeAssistant,
) -> None:
    """Mago de Oz is found by name, at its departing platform.

    Not Gran Vía (nearer, heading to Mago de Oz), and not the arrival-only
    platform 2501 (nearer home than 2502, but nothing leaves from it).
    """
    await set_up_entry(hass, TRANSPORT)

    answer = await ask(hass, "cuándo pasa el tranvía en Mago de Oz", "es")

    assert answer == (
        "Mago de Oz, hacia Avenida de la Academia: línea L1 a Avenida Academia en "
        "4 minutos; línea L1 a Avenida Academia en 8 minutos."
    )


@pytest.mark.usefixtures("assistant")
@pytest.mark.freeze_time(NOW)
async def test_tram_at_the_platform_is_now(hass: HomeAssistant) -> None:
    """A tram at the platform (0 minutes) is "ahora", not "en 0 minutos"."""
    await set_up_entry(hass, TRANSPORT)

    answer = await ask(hass, "cuándo llega el tranvía a César Augusto", "es")

    assert answer == (
        "Cesar Augusto, hacia Mago de Oz: "
        "línea L1 a Mago de Oz ahora; línea L1 a Mago de Oz en 4 minutos."
    )


@pytest.mark.usefixtures("assistant")
@pytest.mark.freeze_time(NOW)
async def test_answer_names_three_arrivals_at_most(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A stop with four buses coming gets the first three, to keep the answer short."""
    serve_avanza(aioclient_mock, "1231")
    await set_up_entry(hass, TRANSPORT)

    answer = await ask(hass, "next bus at 1231", "en")

    assert answer == (
        "La Lista de Schindler: line 59 to TRANVIA-ARCOSUR in 7 minutes; "
        "line 56 to VALDESPARTERA in 22 minutes; "
        "line 59 to TRANVIA-ARCOSUR in 27 minutes."
    )


@pytest.mark.usefixtures("assistant")
@pytest.mark.freeze_time(NOW)
async def test_unknown_stop_says_no_stop_found(hass: HomeAssistant) -> None:
    """A stop no list has gets a sentence saying so, in the question's language."""
    await set_up_entry(hass, TRANSPORT)

    spanish = await ask(hass, "cuándo pasa el tranvía en la luna", "es")
    english = await ask(hass, "when is the next tram at the moon", "en")

    assert spanish == "No encuentro ninguna parada de tranvía que se llame la luna."
    assert english == "I can't find a tram stop called the moon."


@pytest.mark.usefixtures("assistant")
@pytest.mark.freeze_time(NOW)
async def test_night_says_nothing_is_coming(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """At night, with no tram listed, it says nothing is coming to that platform."""
    serve_tram_list(aioclient_mock, fixture="tram_list_night_derived.json")
    await set_up_entry(hass, TRANSPORT)

    spanish = await ask(hass, "cuándo pasa el tranvía en plaza españa", "es")
    english = await ask(hass, "when is the next tram at plaza españa", "en")

    assert spanish == "Plaza Espana, hacia Mago de Oz: ahora no viene nada."
    assert english == "Plaza Espana, towards Mago de Oz: nothing is coming right now."


@pytest.mark.usefixtures("assistant")
@pytest.mark.freeze_time(NOW)
async def test_switched_off_kind_says_so(hass: HomeAssistant) -> None:
    """Asked about the bus with bus switched off, it says where to switch it on."""
    await set_up_entry(hass, {"kinds": ["tram"]})

    spanish = await ask(hass, "cuándo pasa el autobús en 688", "es")
    english = await ask(hass, "when is the next bus at 688", "en")

    assert spanish == CANT_LOOK_UP_BUS_ES
    assert english == CANT_LOOK_UP_BUS_EN


@pytest.mark.usefixtures("assistant")
@pytest.mark.freeze_time(NOW)
async def test_stop_list_never_fetched_and_source_down_says_the_same(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """With bus on but its stop list never fetched, a city outage gets the same answer.

    The script can't tell why find_stops failed, so the sentence fits every
    cause: the kind off, the integration not running, or no list yet.
    """
    serve_bus_stops(aioclient_mock, status=500)
    await set_up_entry(hass, TRANSPORT)

    spanish = await ask(hass, "cuándo pasa el autobús en 688", "es")
    english = await ask(hass, "when is the next bus at 688", "en")

    assert spanish == CANT_LOOK_UP_BUS_ES
    assert english == CANT_LOOK_UP_BUS_EN


@pytest.mark.usefixtures("assistant")
@pytest.mark.freeze_time(NOW)
async def test_unknown_mode_says_what_it_can_answer(hass: HomeAssistant) -> None:
    """Asked about something other than a tram or a bus, it says what it knows."""
    await set_up_entry(hass, TRANSPORT)

    answer = await ask(hass, "cuándo pasa el metro en plaza españa", "es")

    assert answer == "Puedo decirte cuándo pasa el tranvía o el autobús."


@pytest.mark.usefixtures("assistant")
@pytest.mark.freeze_time(NOW)
async def test_sources_down_says_arrivals_cannot_be_reached(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When neither bus source answers, it says so instead of staying silent."""
    serve_avanza(aioclient_mock, "688", status=500)
    serve_city_bus(aioclient_mock, "688", status=400)
    await set_up_entry(hass, TRANSPORT)

    answer = await ask(hass, "cuándo pasa el autobús en 688", "es")

    assert answer == "Ahora no puedo consultar las llegadas."
