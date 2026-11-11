"""Pollen: one sensor per plant with translated levels, refreshed every 6 hours."""

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker
from syrupy.assertion import SnapshotAssertion

from custom_components.zaragoza_open_data.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from tests.acceptance.clock import move_to
from tests.acceptance.entry import change_options, set_up_entry
from tests.acceptance.providers import POLLEN, requests_to, serve_pollen
from tests.acceptance.states import device, device_snapshot, state_of

pytestmark = pytest.mark.usefixtures("in_zaragoza")

# 13:40:30 in Zaragoza.
NOW = "2026-11-09 12:40:30+00:00"
POLLEN_ONLY = {"kinds": ["pollen"]}
LEVELS = ["nulo", "bajo", "moderado", "alto", "muy_alto"]


@pytest.mark.freeze_time(NOW)
async def test_pollen_refresh_interval(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Asked at start, then every 6 hours, or less often if the options say so."""
    serve_pollen(aioclient_mock)
    entry = await set_up_entry(hass, POLLEN_ONLY)
    assert requests_to(aioclient_mock, POLLEN) == 1

    await move_to(hass, freezer, "2026-11-09 18:40:00+00:00")
    assert requests_to(aioclient_mock, POLLEN) == 1
    await move_to(hass, freezer, "2026-11-09 18:40:30+00:00")
    assert requests_to(aioclient_mock, POLLEN) == 2

    await change_options(hass, entry, refresh={"pollen_h": 12})
    assert requests_to(aioclient_mock, POLLEN) == 3

    await move_to(hass, freezer, "2026-11-10 00:40:30+00:00")
    assert requests_to(aioclient_mock, POLLEN) == 3
    await move_to(hass, freezer, "2026-11-10 06:40:30+00:00")
    assert requests_to(aioclient_mock, POLLEN) == 4


@pytest.mark.freeze_time(NOW)
async def test_pollen_enum_states_translated_snapshot(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
) -> None:
    """Each plant is a sensor named by the city, its level one of five translated."""
    serve_pollen(aioclient_mock)
    await set_up_entry(hass, POLLEN_ONLY)

    cypress = state_of(hass, "sensor", "pollen_Cupressaceae")
    assert cypress.state == "bajo"
    assert cypress.name == "Pollen Cupresaceas"
    assert cypress.attributes["published_on"] == "2026-11-01"
    assert cypress.attributes["options"] == LEVELS
    assert (
        cypress.attributes["attribution"]
        == "Origen de los datos: Ayuntamiento de Zaragoza"
    )
    assert state_of(hass, "sensor", "pollen_Pinus").state == "nulo"
    plants = device(hass, "pollen")
    assert plants is not None
    assert (
        len(
            er.async_entries_for_device(
                er.async_get(hass), plants.id, include_disabled_entities=True
            )
        )
        == 14
    )

    for language, names in (
        ("en", ["None", "Low", "Moderate", "High", "Very high"]),
        ("es", ["Nulo", "Bajo", "Moderado", "Alto", "Muy alto"]),
    ):
        translations = await async_get_translations(hass, language, "entity", [DOMAIN])
        states = f"component.{DOMAIN}.entity.sensor.pollen.state"
        assert [translations[f"{states}.{level}"] for level in LEVELS] == names
    assert device_snapshot(hass, "pollen") == snapshot


@pytest.mark.freeze_time(NOW)
async def test_pollen_sensors_appear_once_the_city_answers(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The plants come from the city's list: down at start, they arrive with it.

    The city is asked again every 5 minutes, not at the next 6-hour refresh.
    """
    serve_pollen(aioclient_mock, status=500)
    await set_up_entry(hass, POLLEN_ONLY)

    assert device(hass, "pollen") is None

    aioclient_mock.clear_requests()
    serve_pollen(aioclient_mock)
    # 5 minutes after the start's second try (itself 5 s after the first).
    await move_to(hass, freezer, "2026-11-09 12:45:35+00:00")

    assert state_of(hass, "sensor", "pollen_Cupressaceae").state == "bajo"
    assert requests_to(aioclient_mock, POLLEN) == 1
