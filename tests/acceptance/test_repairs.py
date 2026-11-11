"""Repairs: a stop gone from its source's list for over a day, and removing it."""

from datetime import timedelta
from http import HTTPStatus
import json

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import (
    CLIENT_ID,
    MockConfigEntry,
    MockUser,
    async_fire_time_changed,
)
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant.typing import ClientSessionGenerator, TestClient

from custom_components.zaragoza_open_data.const import DOMAIN
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from tests.acceptance.entry import bizi_station, bus_stop, set_up_entry, tram_stop
from tests.acceptance.forms import field_options
from tests.acceptance.providers import (
    BUS_STOPS,
    GBFS_STATIONS,
    TRAM_LIST,
    serve_bike_stations,
    serve_bike_status,
    serve_bus_stops,
    serve_city_bizi,
    serve_tram_list,
)
from tests.acceptance.states import device
from tests.fixtures import read_fixture

pytestmark = pytest.mark.usefixtures("in_zaragoza")

NOW = "2026-11-09 12:40:30+00:00"
TRAM_ONLY = {"kinds": ["tram"]}
TITLE = "Mago de Oz → Avenida de la Academia"
MAGO_DE_OZ = tram_stop("2502", TITLE)
# Platform 2502 renumbered 2603.
RENUMBERED = "tram_list_unknown_digit_derived.json"
# How the city answers for a list with nothing in it.
EMPTY_CITY_LIST = json.dumps({"totalCount": 0, "start": 0, "rows": 500, "result": []})
# The first check runs 5 minutes after setup; each next one a day and 5 minutes
# later, a little over the day a list is kept, so it finds the list fetched anew.
FIRST_CHECK = timedelta(minutes=5)
NEXT_CHECK = timedelta(hours=24, minutes=5)


def empty_gbfs_list() -> str:
    """Return the operator's recorded station list with every station taken out."""
    answer = json.loads(read_fixture("gbfs/station_information.json"))
    answer["data"]["stations"] = []
    return json.dumps(answer)


async def later(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta
) -> None:
    """Jump ``delta`` ahead and wait for whatever fell due, the checks included."""
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


def subentry_id(entry: MockConfigEntry) -> str:
    """Return the id of the entry's one stop."""
    (only,) = entry.subentries
    assert isinstance(only, str)
    return only


def vanished(hass: HomeAssistant, stop_id: str) -> ir.IssueEntry | None:
    """Return the open issue saying the stop ``stop_id`` is gone, if any."""
    return ir.async_get(hass).async_get_issue(DOMAIN, f"stop_vanished_{stop_id}")


async def log_in_now(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, admin: MockUser
) -> TestClient:
    """Return a client for ``admin``, logged in now.

    The test's own login is from before the days these tests let pass, and an
    access token lasts half an hour.
    """
    refresh_token = await hass.auth.async_create_refresh_token(admin, CLIENT_ID)
    return await hass_client(hass.auth.async_create_access_token(refresh_token))


async def set_up_vanished_stop(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> tuple[MockConfigEntry, str]:
    """Set up Mago de Oz, renumbered from the start, and let a day of checks pass.

    Return the entry and the stop's subentry id; the issue is open.
    """
    serve_tram_list(aioclient_mock, fixture=RENUMBERED)
    entry = await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ])
    stop_id = subentry_id(entry)
    await later(hass, freezer, FIRST_CHECK)
    await later(hass, freezer, NEXT_CHECK)
    assert vanished(hass, stop_id) is not None
    return entry, stop_id


@pytest.mark.freeze_time(NOW)
async def test_vanished_stop_raises_issue_only_after_24_h(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Missing from the lists of two checks a day apart, a stop gets a fixable issue."""
    serve_tram_list(aioclient_mock, fixture=RENUMBERED)
    entry = await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ])
    stop_id = subentry_id(entry)

    await later(hass, freezer, FIRST_CHECK)
    assert vanished(hass, stop_id) is None

    # The day's list is due a day after the first; the check comes 5 minutes on.
    await later(hass, freezer, NEXT_CHECK - timedelta(minutes=1))
    assert vanished(hass, stop_id) is None

    await later(hass, freezer, timedelta(minutes=1))
    issue = vanished(hass, stop_id)
    assert issue is not None
    assert issue.is_fixable
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == "stop_vanished"
    assert issue.translation_placeholders == {"title": TITLE}
    assert issue.data == {"subentry_id": stop_id}


@pytest.mark.freeze_time(NOW)
async def test_list_kept_after_a_failed_fetch_is_no_evidence(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A day's check while the city is down counts for nothing; the next one does.

    The list still served then is the old one, which says nothing about today.
    """
    serve_tram_list(aioclient_mock, fixture=RENUMBERED)
    entry = await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ])
    stop_id = subentry_id(entry)
    await later(hass, freezer, FIRST_CHECK)

    aioclient_mock.clear_requests()
    serve_tram_list(aioclient_mock, status=500)
    await later(hass, freezer, NEXT_CHECK)
    assert vanished(hass, stop_id) is None

    aioclient_mock.clear_requests()
    serve_tram_list(aioclient_mock, fixture=RENUMBERED)
    await later(hass, freezer, NEXT_CHECK)
    assert vanished(hass, stop_id) is not None


@pytest.mark.freeze_time(NOW)
async def test_bizi_list_from_the_city_fallback_is_no_evidence(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Only the operator lists every station: the city's subset can't tell one is gone.

    With the operator down for two days, the city's list lacks station 164 at
    every check: no issue. Once the operator's own list lacks it a day apart: issue.
    """
    serve_bike_stations(aioclient_mock, status=500)
    serve_bike_status(aioclient_mock, status=500)
    serve_city_bizi(
        aioclient_mock, fixture="bizi_city_stations_missing_164_derived.json"
    )
    entry = await set_up_entry(
        hass, {"kinds": ["bizi"]}, [bizi_station("164", "164 · Rosales: Illueca")]
    )
    stop_id = subentry_id(entry)
    await later(hass, freezer, FIRST_CHECK)
    await later(hass, freezer, NEXT_CHECK)
    await later(hass, freezer, NEXT_CHECK)
    assert vanished(hass, stop_id) is None

    aioclient_mock.clear_requests()
    serve_bike_stations(
        aioclient_mock, fixture="station_information_missing_164_derived.json"
    )
    serve_bike_status(aioclient_mock)
    await later(hass, freezer, NEXT_CHECK)
    assert vanished(hass, stop_id) is None

    await later(hass, freezer, NEXT_CHECK)
    assert vanished(hass, stop_id) is not None


@pytest.mark.freeze_time(NOW)
async def test_empty_lists_are_no_evidence(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A list with nothing in it is a bad answer, not news: no stop is taken for gone.

    The tram, bus and Bizi lists all come back empty, at checks a day apart.
    """
    aioclient_mock.get(TRAM_LIST, text=EMPTY_CITY_LIST)
    aioclient_mock.get(BUS_STOPS, text=EMPTY_CITY_LIST)
    aioclient_mock.get(GBFS_STATIONS, text=empty_gbfs_list())
    await set_up_entry(
        hass,
        {"kinds": ["tram", "bus", "bizi"]},
        [
            MAGO_DE_OZ,
            bus_stop("688", "688 · P. Reyes de Aragón N.º 24 · line 58", ["58"]),
            bizi_station("164", "164 · Rosales: Illueca"),
        ],
    )
    await later(hass, freezer, FIRST_CHECK)
    await later(hass, freezer, NEXT_CHECK)
    await later(hass, freezer, NEXT_CHECK)

    issues = ir.async_get(hass).issues
    assert [issue_id for domain, issue_id in issues if domain == DOMAIN] == []


@pytest.mark.freeze_time(NOW)
async def test_bus_list_read_short_is_no_evidence(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A bus list missing a page failed: the last whole one stays, no stop is gone.

    Stop 1231 is on the list's second page, which comes back empty two days running.
    """
    entry = await set_up_entry(
        hass,
        {"kinds": ["bus"]},
        [bus_stop("1231", "1231 · La Lista de Schindler · lines 56, 59, N4")],
    )
    stop_id = subentry_id(entry)
    await later(hass, freezer, FIRST_CHECK)

    aioclient_mock.clear_requests()
    serve_bus_stops(aioclient_mock, empty_page=2)
    await later(hass, freezer, NEXT_CHECK)
    await later(hass, freezer, NEXT_CHECK)
    assert vanished(hass, stop_id) is None

    picker = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "bus_stop"), context={"source": SOURCE_USER}
    )
    assert len(field_options(picker["data_schema"], "stop")) == 1 + 978


@pytest.mark.freeze_time(NOW)
async def test_stop_back_in_between_starts_the_count_again(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Missing, listed again a day later, then missing: not a day gone yet."""
    serve_tram_list(aioclient_mock, fixture=RENUMBERED)
    entry = await set_up_entry(hass, TRAM_ONLY, [MAGO_DE_OZ])
    stop_id = subentry_id(entry)
    await later(hass, freezer, FIRST_CHECK)

    aioclient_mock.clear_requests()
    serve_tram_list(aioclient_mock)
    await later(hass, freezer, NEXT_CHECK)

    aioclient_mock.clear_requests()
    serve_tram_list(aioclient_mock, fixture=RENUMBERED)
    await later(hass, freezer, NEXT_CHECK)
    assert vanished(hass, stop_id) is None

    await later(hass, freezer, NEXT_CHECK)
    assert vanished(hass, stop_id) is not None


@pytest.mark.freeze_time(NOW)
async def test_issue_cleared_when_stop_returns(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Once a day's list has the stop again, its issue goes."""
    _entry, stop_id = await set_up_vanished_stop(hass, aioclient_mock, freezer)

    aioclient_mock.clear_requests()
    serve_tram_list(aioclient_mock)
    await later(hass, freezer, NEXT_CHECK)

    assert vanished(hass, stop_id) is None


@pytest.mark.freeze_time(NOW)
async def test_issue_survives_a_restart_until_the_stop_is_listed_again(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The issue is still there after a restart, and goes once the stop is back."""
    entry, stop_id = await set_up_vanished_stop(hass, aioclient_mock, freezer)
    # The registry saves a few seconds after a change.
    await later(hass, freezer, timedelta(seconds=11))

    # What Home Assistant loads from storage when it starts again.
    after_restart = ir.IssueRegistry(hass)
    await after_restart.async_load()
    restored = after_restart.async_get_issue(DOMAIN, f"stop_vanished_{stop_id}")
    assert restored is not None
    assert restored.active
    assert restored.is_fixable
    assert restored.translation_placeholders == {"title": TITLE}
    assert restored.data == {"subentry_id": stop_id}

    # Set up again, the integration keeps it while the stop is still missing.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await later(hass, freezer, FIRST_CHECK)
    assert vanished(hass, stop_id) is not None

    aioclient_mock.clear_requests()
    serve_tram_list(aioclient_mock)
    await later(hass, freezer, NEXT_CHECK)
    assert vanished(hass, stop_id) is None


@pytest.mark.freeze_time(NOW)
async def test_repair_flow_removes_the_stop(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    hass_client: ClientSessionGenerator,
    hass_admin_user: MockUser,
) -> None:
    """Confirming the repair removes the stop, its device and the issue."""
    entry, stop_id = await set_up_vanished_stop(hass, aioclient_mock, freezer)
    assert device(hass, "tram_2502") is not None
    assert await async_setup_component(hass, "repairs", {})
    client = await log_in_now(hass, hass_client, hass_admin_user)

    response = await client.post(
        "/api/repairs/issues/fix",
        json={"handler": DOMAIN, "issue_id": f"stop_vanished_{stop_id}"},
    )
    assert response.status == HTTPStatus.OK
    shown = await response.json()
    assert shown["type"] == "form"
    assert shown["step_id"] == "confirm"
    assert shown["description_placeholders"] == {"title": TITLE}

    response = await client.post(f"/api/repairs/issues/fix/{shown['flow_id']}")
    assert response.status == HTTPStatus.OK
    assert (await response.json())["type"] == "create_entry"
    await hass.async_block_till_done()

    assert entry.subentries == {}
    assert device(hass, "tram_2502") is None
    assert vanished(hass, stop_id) is None


@pytest.mark.freeze_time(NOW)
async def test_issue_dropped_when_stop_removed_by_hand(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A stop deleted from the integration's page takes its issue with it."""
    entry, stop_id = await set_up_vanished_stop(hass, aioclient_mock, freezer)

    assert hass.config_entries.async_remove_subentry(entry, stop_id)
    await hass.async_block_till_done()

    assert vanished(hass, stop_id) is None


@pytest.mark.freeze_time(NOW)
async def test_issue_dropped_when_the_integration_is_removed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Deleting the integration leaves no issue about its stops behind."""
    entry, stop_id = await set_up_vanished_stop(hass, aioclient_mock, freezer)

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert vanished(hass, stop_id) is None
