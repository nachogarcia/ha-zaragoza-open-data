"""Diagnostics: the settings, each source's status, each stop's latest data, no places."""

from collections.abc import Iterator

import pytest
from pytest_homeassistant.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant.typing import ClientSessionGenerator
from syrupy.assertion import SnapshotAssertion
from syrupy.filters import props

from homeassistant.core import HomeAssistant
from tests.acceptance.entry import bizi_station, bus_stop, set_up_entry, tram_stop
from tests.acceptance.providers import serve_pollen, serve_tram_list

pytestmark = pytest.mark.usefixtures("in_zaragoza", "home_in_zaragoza")

NOW = "2026-11-09 12:40:30+00:00"
REDACTED = "**REDACTED**"


def coordinates(node: object) -> Iterator[object]:
    """Yield every value stored under a ``latitude`` or ``longitude`` key."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"latitude", "longitude"}:
                yield value
            else:
                yield from coordinates(value)
    elif isinstance(node, list):
        for item in node:
            yield from coordinates(item)


@pytest.mark.freeze_time(NOW)
async def test_diagnostics_snapshot_redacts_coordinates(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client: ClientSessionGenerator,
    snapshot: SnapshotAssertion,
) -> None:
    """Options, stops, every source's last result and who answered; no coordinates.

    The pollen levels can't be reached, so their source shows its error.
    """
    serve_pollen(aioclient_mock, status=500)
    entry = await set_up_entry(
        hass,
        {"kinds": ["tram", "bus", "bizi", "pollen"], "refresh": {"bus_s": 120}},
        [
            tram_stop("2502", "Mago de Oz → Avenida de la Academia"),
            bus_stop("688", "688 · P. Reyes de Aragón N.º 24 · line 58", ["58"]),
            bizi_station("164", "164 · Rosales: Illueca"),
        ],
    )

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics == snapshot(exclude=props("subentry_id"))
    working = {
        "last_update_success": True,
        "last_exception": None,
        "cause": None,
        "cause_message": None,
    }
    assert diagnostics["coordinators"] == {
        "tram": working,
        "bus": working,
        "bizi": working,
        # Why it failed: our own error, whose message never carries data.
        "pollen": {
            "last_update_success": False,
            "last_exception": "UpdateFailed",
            "cause": "SourceUnavailableError",
            "cause_message": "Source unavailable",
        },
    }
    stops = diagnostics["stops"]
    assert isinstance(stops, dict)
    assert {key: stop["source"] for key, stop in stops.items()} == {
        "tram_2502": "zaragoza_city",
        "bus_688": "avanza",
        "bizi_164": "gbfs",
    }
    # Each stop's place, from its list, has both coordinates, both redacted.
    assert list(coordinates(diagnostics)) == [REDACTED] * 6


@pytest.mark.freeze_time(NOW)
async def test_diagnostics_show_a_stop_its_source_never_answered(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client: ClientSessionGenerator,
) -> None:
    """With the tram down since setup, its platform has no place, data or source."""
    serve_tram_list(aioclient_mock, status=500)
    entry = await set_up_entry(
        hass,
        {"kinds": ["tram"]},
        [tram_stop("2502", "Mago de Oz → Avenida de la Academia")],
    )

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics["coordinators"] == {
        "tram": {
            "last_update_success": False,
            "last_exception": "UpdateFailed",
            "cause": "SourceUnavailableError",
            "cause_message": "Source unavailable",
        }
    }
    assert diagnostics["stops"] == {
        "tram_2502": {"place": None, "latest": None, "source": None}
    }
