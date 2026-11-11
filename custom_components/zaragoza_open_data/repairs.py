"""Repairs: a configured stop or station gone from its source's list, and removing it."""

from collections.abc import Collection
from datetime import datetime, timedelta

from homeassistant.components.repairs import (
    ConfirmRepairFlow,
    RepairsFlow,
    RepairsFlowResult,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, StopKind
from .options import read_stop
from .runtime import Listing, ZodConfigEntry

ISSUE_STOP_VANISHED = "stop_vanished"
_ISSUE_PREFIX = f"{ISSUE_STOP_VANISHED}_"
# A stop missing from its source's list this long was renumbered or removed.
VANISHED_AFTER = timedelta(hours=24)


def _issue_id(subentry_id: str) -> str:
    """Return the id of the issue about the stop with ``subentry_id``."""
    return _ISSUE_PREFIX + subentry_id


class VanishedStops:
    """Spots the configured stops gone from their lists, raising an issue for each.

    A stop is gone once two fresh lists of its kind, fetched at least a day
    apart, both lack it. Each list counts from when it was fetched, so a check
    that finds yesterday's list again learns nothing new; a list kept after
    failed fetches doesn't count at all. What was seen lives here: a restart,
    or a reload (adding or removing any stop), starts the count again. A raised
    issue outlives restarts, and goes once a fresh list has the stop again.
    """

    def __init__(self, hass: HomeAssistant, entry: ZodConfigEntry) -> None:
        """Start with nothing seen."""
        self._hass = hass
        self._entry = entry
        # When the first fresh list lacking each stop, by subentry id, was fetched.
        self._missing_since: dict[str, datetime] = {}

    async def async_check(self) -> None:
        """Look each configured stop up in the fresh list of its kind, if any.

        One kind's list after another: the tram and bus lists share a server.
        """
        runtime = self._entry.runtime_data
        listings: dict[StopKind, Listing | None] = {}
        for subentry in self._entry.subentries.values():
            stop = read_stop(subentry)
            if stop is None:
                continue
            kind, code = stop
            if kind not in listings:
                listings[kind] = await runtime.fresh_listing(kind)
            listing = listings[kind]
            if listing is not None:
                self._compare(subentry, code, listing)

    @callback
    def _compare(self, subentry: ConfigSubentry, code: str, listing: Listing) -> None:
        """Raise the stop's issue once it has been missing a day; drop it once back."""
        stop_id = subentry.subentry_id
        if code in listing.codes:
            self._missing_since.pop(stop_id, None)
            ir.async_delete_issue(self._hass, DOMAIN, _issue_id(stop_id))
            return
        since = self._missing_since.setdefault(stop_id, listing.fetched_at)
        if listing.fetched_at - since >= VANISHED_AFTER:
            ir.async_create_issue(
                self._hass,
                DOMAIN,
                _issue_id(stop_id),
                is_fixable=True,
                # Kept across restarts: a gone stop doesn't come back by itself.
                is_persistent=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_STOP_VANISHED,
                translation_placeholders={"title": subentry.title},
                data={"subentry_id": stop_id},
            )


@callback
def async_drop_issues_of_removed_stops(
    hass: HomeAssistant, kept: Collection[str]
) -> None:
    """Delete the issues of stops no longer configured: those in ``kept`` stay.

    A stop removed by hand, or with the whole integration, takes its issue along.
    """
    for domain, issue_id in list(ir.async_get(hass).issues):
        if (
            domain == DOMAIN
            and issue_id.startswith(_ISSUE_PREFIX)
            and issue_id.removeprefix(_ISSUE_PREFIX) not in kept
        ):
            ir.async_delete_issue(hass, DOMAIN, issue_id)


class StopVanishedRepairFlow(ConfirmRepairFlow):
    """Removes the stop an issue names, with its device and sensors, once confirmed."""

    def __init__(self, subentry_id: str) -> None:
        """Remember which stop to remove."""
        super().__init__()
        self._subentry_id = subentry_id

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Ask, naming the stop; once confirmed, remove it (if still there)."""
        if user_input is not None:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if self._subentry_id in entry.subentries:
                    self.hass.config_entries.async_remove_subentry(
                        entry, self._subentry_id
                    )
        return await super().async_step_confirm(user_input)


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Return the flow that fixes ``issue_id``: removing the stop it names."""
    subentry_id = None if data is None else data.get("subentry_id")
    if not isinstance(subentry_id, str):
        raise TypeError(f"Issue {issue_id} names no stop")
    return StopVanishedRepairFlow(subentry_id)
