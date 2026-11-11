"""A config entry for acceptance tests, set up the way Home Assistant does it."""

from collections.abc import Mapping, Sequence

from pytest_homeassistant.common import MockConfigEntry

from custom_components.zaragoza_open_data.const import DOMAIN, NAME
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from tests.acceptance.forms import suggested_values

# The hub device is identified by the entry id, and the device snapshots show it:
# a fixed id keeps them the same from run to run.
ENTRY_ID = "test_entry"


async def set_up_entry(
    hass: HomeAssistant,
    options: Mapping[str, object] | None = None,
    stops: Sequence[ConfigSubentryData] = (),
    *,
    settle: bool = True,
) -> MockConfigEntry:
    """Add an entry with ``options`` (defaults when None) and ``stops``; set it up.

    With ``settle``, also wait for the work setup leaves running (the bus's first
    refresh, looking stops up), so states are final. A test with several bus
    stops under frozen time passes ``settle=False`` and lets time pass itself:
    that refresh rests a second between stops, and frozen time never ends a rest.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        title=NAME,
        data={},
        options=dict(options or {}),
        subentries_data=list(stops),
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=settle)
    return entry


async def change_options(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    *,
    refresh: Mapping[str, object] | None = None,
    **changes: object,
) -> None:
    """Save the options form with ``changes`` over what it shows, as a user would.

    ``refresh`` changes only the intervals it names.
    """
    result = await hass.config_entries.options.async_init(entry.entry_id)
    shown = suggested_values(result["data_schema"])
    intervals = shown["refresh"]
    assert isinstance(intervals, Mapping)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**shown, **changes, "refresh": {**intervals, **(refresh or {})}},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


def tram_stop(code: str, title: str) -> ConfigSubentryData:
    """A tram platform as the add-stop flow saves it."""
    return ConfigSubentryData(
        data={"code": code},
        subentry_type="tram_stop",
        title=title,
        unique_id=f"tram_{code}",
    )


def bus_stop(code: str, title: str, lines: Sequence[str] = ()) -> ConfigSubentryData:
    """A bus stop as the add-stop flow saves it; no lines means every line."""
    return ConfigSubentryData(
        data={"code": code, "lines": list(lines)},
        subentry_type="bus_stop",
        title=title,
        unique_id=f"bus_{code}",
    )


def bizi_station(code: str, title: str) -> ConfigSubentryData:
    """A Bizi station as the add-stop flow saves it."""
    return ConfigSubentryData(
        data={"code": code},
        subentry_type="bizi_station",
        title=title,
        unique_id=f"bizi_{code}",
    )
