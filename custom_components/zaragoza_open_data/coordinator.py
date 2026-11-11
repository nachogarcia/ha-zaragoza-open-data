"""One coordinator per kind of data: when each source is asked, and what is kept."""

from abc import abstractmethod
import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import logging
import math
from typing import overload
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api.errors import SourceUnavailableError
from .api.models import (
    AirReading,
    AirStation,
    Area,
    ArrivalBoard,
    BikeAvailability,
    DutyPharmacy,
    GeoPoint,
    PollenReading,
    RoadWork,
    StationCode,
    StopCode,
)
from .api.ports import (
    AirQualitySource,
    BikeSource,
    BusArrivalsSource,
    PharmacySource,
    PollenSource,
    RoadWorksSource,
    TramSource,
)
from .const import DOMAIN, EVENT_NEW_ROAD_WORK, SUBENTRY_BUS_STOP
from .memory import ROAD_WORKS_KEY, memory, texts_in
from .options import MapLayerOptions, ZodOptions, read_bus_stop

_LOGGER = logging.getLogger(__name__)

# A source that fails for a moment isn't down: the last good data stands in for
# this many of its kind's refreshes after the fetch that brought it (3 minutes for
# the tram by default), and only then do its entities go unavailable (one error in
# the log, and "recovered" when it is back).
_KEPT_REFRESHES = 3
# A refresh can start a second or so early or late; this keeps the one due just as
# the data reaches its limit from being let through or not by chance.
_KEEP_TOLERANCE = timedelta(seconds=5)
# A source that fails at a coordinator's first refresh is asked once more this
# much later: Home Assistant may have just started, its network not quite up.
FIRST_RETRY = timedelta(seconds=5)
# A source refreshed less often than this that is down (past its blip, or with
# nothing to show) is asked again this much later, until it answers: else its
# entities could stay unavailable until a refresh hours away. Its own interval
# resumes after the first success.
_OUTAGE_RETRY = timedelta(minutes=5)

# A bus stop's last arrivals stay shown this long when nobody answers for it.
# They are absolute times, so they stay right; after this they are too old to trust.
BUS_MAX_AGE = timedelta(minutes=10)
# The city's bus endpoint failed for minutes after a burst of parallel requests, so
# bus requests go one at a time with at least this much rest between them.
BUS_GAP = timedelta(seconds=1)
# An action asking for a stop answered this recently gets the same answer.
BUS_REUSE = timedelta(seconds=30)

# The city republishes the tram list once a minute, a second or two after :00;
# asking at :10 gets each new list once.
_TRAM_SECOND = 10
# A refresh can start up to a second early or late; this keeps it from being taken
# for the slot before or after.
_TRAM_SLOT_TOLERANCE = timedelta(seconds=30)


# The pharmacies on duty change at 09:15; by 09:20 the city lists the new ones.
# All of that is Zaragoza's clock, whatever time zone Home Assistant is set to.
_TURN_START = timedelta(hours=9, minutes=15)
_MADRID = ZoneInfo("Europe/Madrid")
_SHIFT_CHANGE_HOUR = 9
_SHIFT_CHANGE_MINUTE = 20
# A refresh can fire up to a second early; this keeps the 09:20 refresh from
# aiming at the same 09:20 again, and nothing else.
_SHIFT_CHANGE_TOLERANCE = timedelta(seconds=5)
# A road work off the city's lists this long is forgotten: should it come back,
# it is announced as new again. This also keeps the store small.
_ROAD_WORKS_MEMORY = timedelta(days=30)


def _tram_period(interval: timedelta) -> timedelta:
    """Return the time between tram refreshes: ``interval`` up to whole minutes.

    The list changes once a minute, so asking at a finer step gains nothing.
    """
    return timedelta(minutes=max(1, math.ceil(interval / timedelta(minutes=1))))


def _until_tram_slot(now: datetime, interval: timedelta) -> timedelta:
    """Return the wait from ``now`` to the next refresh, at ten past a minute.

    The next slot is the first :10 at least one tram period after ``now``, give
    or take the tolerance.
    """
    earliest = now + _tram_period(interval) - _TRAM_SLOT_TOLERANCE
    slot = earliest.replace(second=_TRAM_SECOND, microsecond=0)
    if slot < earliest:
        slot += timedelta(minutes=1)
    return slot - now


class _SourceCoordinator[T](DataUpdateCoordinator[T]):
    """A coordinator of one kind of data that rides out its source's short failures.

    A refresh whose source fails keeps the last good data while
    ``_keeps_last_good`` says it still stands, logged at debug: the entities stay
    available with their values. Past that the refresh fails, which Home
    Assistant logs once, and once more when the source is back. With no data
    yet, the first refresh asks once more ``FIRST_RETRY`` later before failing.
    A kind refreshed less often than ``_OUTAGE_RETRY`` is asked again that much
    after a failed refresh, until it answers.
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        name: str,
        interval: timedelta,
        unavailable: str,
        keep_for: timedelta | None,
        update_interval: timedelta | None = None,
    ) -> None:
        """Refresh every ``update_interval`` (``interval`` if None) while listened to.

        ``interval`` is the one the options set. ``unavailable`` is the failure's
        translation key. ``keep_for`` is how long the last good data stands in,
        from the fetch that brought it; None for a kind whose
        ``_keeps_last_good`` decides otherwise.
        """
        self._interval = interval
        self._unavailable = unavailable
        self._keep_for = keep_for
        # When the last good data came, and whether a refresh was ever tried.
        self._last_good: datetime | None = None
        self._tried = False
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=name,
            update_interval=interval if update_interval is None else update_interval,
        )

    @abstractmethod
    async def _async_fetch(self) -> T:
        """Ask the source for new data; raise ``SourceUnavailableError`` if it fails."""

    def _keeps_last_good(self, now: datetime) -> bool:
        """Say whether the last good data still stands in for a failed refresh."""
        return (
            self._keep_for is not None
            and self._last_good is not None
            and now - self._last_good < self._keep_for - _KEEP_TOLERANCE
        )

    async def _async_update_data(self) -> T:
        """Fetch new data; through a short failure, keep the last good data.

        Data is as old as the moment it was asked for: a slow answer is no newer.
        """
        first, self._tried = not self._tried, True
        started = dt_util.utcnow()
        try:
            data = await self._async_fetch()
        except SourceUnavailableError as err:
            if self.data is not None and self._keeps_last_good(dt_util.utcnow()):
                _LOGGER.debug(
                    "No %s data from %s: showing the last for now",
                    self.name,
                    err.source,
                )
                return self.data
            if not first:
                raise self._failed() from err
            _LOGGER.debug(
                "No %s data from %s yet: asking again in %d s",
                self.name,
                err.source,
                FIRST_RETRY.total_seconds(),
            )
            await asyncio.sleep(FIRST_RETRY.total_seconds())
            started = dt_util.utcnow()
            try:
                data = await self._async_fetch()
            except SourceUnavailableError as again:
                raise self._failed() from again
        self._last_good = started
        return data

    def _failed(self) -> UpdateFailed:
        """Return the failure Home Assistant logs, in the user's language.

        For a kind refreshed less often than ``_OUTAGE_RETRY`` it carries that as
        ``retry_after``: Home Assistant asks again that much later, once, instead
        of at the next refresh. Each failed retry carries it again.
        """
        retry_after = (
            _OUTAGE_RETRY.total_seconds() if self._interval > _OUTAGE_RETRY else None
        )
        return UpdateFailed(
            translation_domain=DOMAIN,
            translation_key=self._unavailable,
            retry_after=retry_after,
        )


class _AskedCoordinator[T](_SourceCoordinator[T]):
    """A coordinator the actions read too: refreshed first when its data is old.

    A coordinator polls only while some entity listens, so with no stop of its
    kind added its data dates from setup. The actions ask at most once per
    refresh interval, whether the last refresh worked or not: a source that is
    down isn't asked more often than polling would.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        name: str,
        interval: timedelta,
        unavailable: str,
        keep_for: timedelta,
        update_interval: timedelta | None = None,
    ) -> None:
        """Refresh every ``update_interval`` (``interval`` if None) while listened to.

        ``interval`` is the one the options set: how old the data may get.
        """
        self._refreshed_at: datetime | None = None
        self._asking = asyncio.Lock()
        super().__init__(
            hass,
            entry,
            name=name,
            interval=interval,
            unavailable=unavailable,
            keep_for=keep_for,
            update_interval=update_interval,
        )

    @callback
    def _async_refresh_finished(self) -> None:
        """Note when the last refresh ended, whether it worked or not."""
        self._refreshed_at = dt_util.utcnow()

    async def async_fresh_data(self) -> T | None:
        """Return data refreshed within the interval; None while the source is down.

        Through a short failure of the source that is the last good data, as the
        entities show. Actions asking at once share one refresh.
        """
        async with self._asking:
            if (
                self._refreshed_at is None
                or dt_util.utcnow() - self._refreshed_at >= self._interval
            ):
                await self.async_refresh()
        return self.data if self.last_update_success else None


class TramCoordinator(_AskedCoordinator[dict[StopCode, ArrivalBoard]]):
    """Every tram platform's board, from one request, at ten past the minute."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, source: TramSource
    ) -> None:
        """Ask ``source`` as often as the options allow, aligned to the city's list."""
        self._source = source
        interval = ZodOptions.from_mapping(entry.options).refresh.tram
        super().__init__(
            hass,
            entry,
            name="tram",
            interval=interval,
            update_interval=_until_tram_slot(dt_util.utcnow(), interval),
            unavailable="tram_unavailable",
            keep_for=_KEPT_REFRESHES * _tram_period(interval),
        )

    async def _async_update_data(self) -> dict[StopCode, ArrivalBoard]:
        """Refresh the boards; then point the next refresh at its slot."""
        try:
            return await super()._async_update_data()
        finally:
            # Worked out again each time, so the time a request takes never drifts
            # the refreshes off :10.
            self.update_interval = _until_tram_slot(dt_util.utcnow(), self._interval)

    async def _async_fetch(self) -> dict[StopCode, ArrivalBoard]:
        """Fetch every board."""
        return dict(await self._source.boards())

    def board(self, code: StopCode) -> ArrivalBoard | None:
        """Return the platform's board, or None if the city no longer lists it."""
        return None if self.data is None else self.data.get(code)

    def notices(self) -> tuple[str, ...]:
        """Return the distinct notices of every platform, in the city's order."""
        boards = self.data or {}
        return tuple(
            dict.fromkeys(
                notice for board in boards.values() for notice in board.notices
            )
        )


class BusCoordinator(_SourceCoordinator[dict[StopCode, ArrivalBoard]]):
    """The configured bus stops' boards, asked one stop at a time.

    Each stop keeps its last good board; the refresh fails only when no stop has
    one younger than ``BUS_MAX_AGE``.
    """

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, source: BusArrivalsSource
    ) -> None:
        """Ask ``source`` for the entry's bus stops as often as the options allow."""
        self._source = source
        self._codes = tuple(
            read_bus_stop(subentry)["code"]
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_BUS_STOP
        )
        self._boards: dict[StopCode, ArrivalBoard] = {}
        # Every stop's last good board, from the refresh or an action, with when
        # it came: an action gets it again for ``BUS_REUSE``, and while nobody
        # answers it stands in for ``BUS_MAX_AGE``.
        self._recent: dict[StopCode, tuple[datetime, ArrivalBoard]] = {}
        # Held for each request and the rest before it: one bus request at a time.
        self._lock = asyncio.Lock()
        self._last_request_end: float | None = None
        super().__init__(
            hass,
            entry,
            name="bus",
            interval=ZodOptions.from_mapping(entry.options).refresh.bus,
            unavailable="bus_unavailable",
            keep_for=None,
        )

    async def _async_fetch(self) -> dict[StopCode, ArrivalBoard]:
        """Ask for each stop in turn; fail only when none of them is answered.

        A stop that isn't answered keeps its last good board (see ``board``).
        """
        failed: list[SourceUnavailableError] = []
        for code in self._codes:
            async with self._lock:
                try:
                    await self._request(code)
                except SourceUnavailableError as err:
                    _LOGGER.debug("No board for bus stop %s from %s", code, err.source)
                    failed.append(err)
        if failed and len(failed) == len(self._codes):
            raise failed[-1]
        return dict(self._boards)

    def _keeps_last_good(self, now: datetime) -> bool:
        """Say whether some stop's last board is still under ``BUS_MAX_AGE`` old.

        Each stop's board counts from its own reading: arrivals are absolute
        times, so they stay right that long.
        """
        return any(
            board.is_usable_at(now, BUS_MAX_AGE) for board in self._boards.values()
        )

    async def board_for(self, code: StopCode) -> ArrivalBoard:
        """Return any stop's board for an action, reusing one under 30 s old.

        While neither source answers, the stop's last board under 10 minutes old
        stands in. A new board for a configured stop shows on its entities at
        once; the stop's refreshes keep their time.

        Raises ``SourceUnavailableError`` when neither source answers and there
        is no such board.
        """
        async with self._lock:
            kept = self._recent.get(code)
            if kept is not None and dt_util.utcnow() - kept[0] < BUS_REUSE:
                return kept[1]
            try:
                board = await self._request(code)
            except SourceUnavailableError as err:
                if kept is None or not kept[1].is_usable_at(
                    dt_util.utcnow(), BUS_MAX_AGE
                ):
                    raise
                _LOGGER.debug(
                    "No board for bus stop %s from %s: answering with the last one",
                    code,
                    err.source,
                )
                return kept[1]
        if code in self._codes:
            if not self.last_update_success:
                self.last_update_success = True
                _LOGGER.info("Fetching %s data recovered", self.name)
            # The scheduled poll keeps its time: async_set_updated_data would
            # cancel it and start a whole new interval after this action.
            self.data = dict(self._boards)
            self.async_update_listeners()
        return board

    def board(self, code: StopCode) -> ArrivalBoard | None:
        """Return the stop's last good board while it is still usable, else None."""
        board = None if self.data is None else self.data.get(code)
        if board is None or not board.is_usable_at(dt_util.utcnow(), BUS_MAX_AGE):
            return None
        return board

    async def _request(self, code: StopCode) -> ArrivalBoard:
        """Ask for one stop, resting first if the last request ended under 1 s ago.

        The caller holds the lock.
        """
        loop = self.hass.loop
        if self._last_request_end is not None:
            rest = self._last_request_end + BUS_GAP.total_seconds() - loop.time()
            if rest > 0:
                await asyncio.sleep(rest)
        try:
            board = await self._source.board(code)
        finally:
            self._last_request_end = loop.time()
        now = dt_util.utcnow()
        self._recent = {
            known: answer
            for known, answer in self._recent.items()
            if answer[1].is_usable_at(now, BUS_MAX_AGE)
        }
        self._recent[code] = (now, board)
        if code in self._codes:
            self._boards[code] = board
        return board


class BikeCoordinator(_AskedCoordinator[dict[StationCode, BikeAvailability]]):
    """Every Bizi station's bikes and docks, from the operator or the city."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, source: BikeSource
    ) -> None:
        """Ask ``source`` as often as the options allow."""
        self._source = source
        interval = ZodOptions.from_mapping(entry.options).refresh.bizi
        super().__init__(
            hass,
            entry,
            name="Bizi",
            interval=interval,
            unavailable="bizi_unavailable",
            keep_for=_KEPT_REFRESHES * interval,
        )

    async def _async_fetch(self) -> dict[StationCode, BikeAvailability]:
        """Fetch every station's availability."""
        return dict(await self._source.availability())


def _until_shift_change(now: datetime, interval: timedelta) -> timedelta:
    """Return the wait to the next pharmacies refresh: ``interval``, or less to 09:20.

    One timer serves both, so a refresh due at 09:20 anyway isn't made twice.
    """
    local = now.astimezone(_MADRID)
    change = local.replace(
        hour=_SHIFT_CHANGE_HOUR, minute=_SHIFT_CHANGE_MINUTE, second=0, microsecond=0
    )
    if change < local + _SHIFT_CHANGE_TOLERANCE:
        # Wall-clock arithmetic: 09:20 tomorrow, whatever the clocks do tonight.
        change += timedelta(days=1)
    # In UTC, so a daylight-saving change in between counts.
    return min(interval, dt_util.as_utc(change) - now)


@overload
def local_text(moment: datetime) -> str: ...


@overload
def local_text(moment: None) -> None: ...


def local_text(moment: datetime | None) -> str | None:
    """Return a time as text in Home Assistant's time zone, like every time it shows."""
    return None if moment is None else dt_util.as_local(moment).isoformat()


def home_of(hass: HomeAssistant) -> GeoPoint:
    """Return where home is."""
    return GeoPoint(hass.config.latitude, hass.config.longitude)


def centre_of(hass: HomeAssistant, zone_entity_id: str) -> GeoPoint:
    """Return where a zone is; home when the zone no longer exists.

    The zone is looked up at each refresh, so a zone deleted later moves the
    layer to home instead of breaking it.
    """
    state = hass.states.get(zone_entity_id)
    if state is not None:
        latitude = state.attributes.get(ATTR_LATITUDE)
        longitude = state.attributes.get(ATTR_LONGITUDE)
        if isinstance(latitude, int | float) and isinstance(longitude, int | float):
            return GeoPoint(float(latitude), float(longitude))
    _LOGGER.debug("Zone %s not found: measuring from home", zone_entity_id)
    return home_of(hass)


def _area(hass: HomeAssistant, layer: MapLayerOptions) -> Area:
    """Return the circle a map layer shows; a radius of 0 means the whole city."""
    radius_m = layer.radius_km * 1000 if layer.radius_km > 0 else None
    return Area(centre_of(hass, layer.centre_zone), radius_m)


class RoadWorksCoordinator(_SourceCoordinator[tuple[RoadWork, ...]]):
    """The road works of the ticked categories within the layer's distance."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, source: RoadWorksSource
    ) -> None:
        """Ask ``source`` as often as the options allow."""
        options = ZodOptions.from_mapping(entry.options)
        self._source = source
        self._layer = options.road_works
        self._categories = options.road_work_categories
        # Where distances are measured from, as of the last refresh.
        self.centre = centre_of(hass, self._layer.centre_zone)
        self._memory = memory(hass, ROAD_WORKS_KEY)
        # Each work seen lately and the day it was last listed; read at the
        # first refresh.
        self._seen: dict[str, date] | None = None
        super().__init__(
            hass,
            entry,
            name="road works",
            interval=options.refresh.road_works,
            unavailable="road_works_unavailable",
            keep_for=_KEPT_REFRESHES * options.refresh.road_works,
        )

    @property
    def source_name(self) -> str:
        """Return who publishes the road works."""
        return self._source.source_name

    async def _async_fetch(self) -> tuple[RoadWork, ...]:
        """Fetch both lists and keep the works the layer shows."""
        works = await self._source.road_works()
        area = _area(self.hass, self._layer)
        self.centre = area.centre
        shown = tuple(
            work
            for work in works
            if work.category in self._categories and area.contains(work.location)
        )
        await self._announce_new(works, shown)
        return shown

    async def _announce_new(
        self, works: tuple[RoadWork, ...], shown: tuple[RoadWork, ...]
    ) -> None:
        """Fire an event for each work shown that was never seen; remember them all.

        Every work in the city's lists counts as seen, so widening the layer
        announces nothing. While nothing is remembered (the entry's first start,
        or a month without a list) every work would be new: none is announced.
        """
        today = dt_util.now().date()
        if self._seen is None:
            self._seen = {}
            for work_id, day in texts_in(
                await self._memory.async_load(), "seen"
            ).items():
                try:
                    self._seen[work_id] = date.fromisoformat(day)
                except ValueError:
                    continue
        remembered = {
            work_id: day
            for work_id, day in self._seen.items()
            if today - day <= _ROAD_WORKS_MEMORY
        }
        new = {work.id for work in works} - remembered.keys() if remembered else set()
        seen = {**remembered, **dict.fromkeys((work.id for work in works), today)}
        if seen != self._seen:
            self._seen = seen
            await self._memory.async_save(
                {"seen": {work_id: day.isoformat() for work_id, day in seen.items()}}
            )
        for work in shown:
            if work.id in new:
                self.hass.bus.async_fire(
                    EVENT_NEW_ROAD_WORK,
                    {
                        "id": work.id,
                        "title": work.title,
                        "street": work.street,
                        "category": work.category.value,
                        "distance_km": round(
                            self.centre.distance_to(work.location) / 1000, 1
                        ),
                        "latitude": work.location.latitude,
                        "longitude": work.location.longitude,
                        "starts": local_text(work.starts),
                        "ends": local_text(work.ends),
                    },
                )

    def work(self, work_id: str) -> RoadWork | None:
        """Return the work with ``work_id``, if the layer still shows it."""
        return next((work for work in self.data or () if work.id == work_id), None)


def _turn_of(moment: datetime) -> date:
    """Return the day of the pharmacies' turn on duty at ``moment``.

    A turn runs from 09:15 to 09:15 the next day, on Zaragoza's clock.
    """
    return (moment.astimezone(_MADRID) - _TURN_START).date()


def turn_end(day: date) -> datetime:
    """Return when the pharmacies' turn of ``day`` ends: 09:15 the next day, in Zaragoza.

    The city gives the turn's date; the free text of its schedule isn't parsed.
    """
    # Wall-clock arithmetic on a zone-aware midnight: 09:15 whatever the clocks did.
    midnight = datetime.combine(day + timedelta(days=1), time(), tzinfo=_MADRID)
    return midnight + _TURN_START


class PharmaciesCoordinator(_SourceCoordinator[tuple[DutyPharmacy, ...]]):
    """Today's pharmacies on duty within the layer's distance.

    Asked as often as the options allow, and at 09:20, once the day's new
    pharmacies are published. The list says which turn it is (its newest duty
    date); one of a turn that has ended is not shown as on duty. It means the
    city hasn't published the new turn yet: nothing is on duty on the map until
    it does, asked again every 5 minutes, with one line in the log.
    """

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, source: PharmacySource
    ) -> None:
        """Ask ``source`` as often as the options allow, and at each shift change."""
        options = ZodOptions.from_mapping(entry.options)
        self._source = source
        self._layer = options.pharmacies
        # Where distances are measured from, as of the last refresh.
        self.centre = centre_of(hass, self._layer.centre_zone)
        interval = options.refresh.pharmacies
        # The turn of the last list fetched, whether that list was of a turn
        # that had ended, and the turn the log last said it was waiting for.
        self._listed_turn: date | None = None
        self._turn_over = False
        self._waiting_for: date | None = None
        # Takes the list's pharmacies off at 09:15, when its turn ends.
        self._turn_end_timer: CALLBACK_TYPE | None = None
        super().__init__(
            hass,
            entry,
            name="pharmacies",
            interval=interval,
            update_interval=_until_shift_change(dt_util.utcnow(), interval),
            unavailable="pharmacies_unavailable",
            keep_for=None,
        )

    @property
    def source_name(self) -> str:
        """Return who publishes the pharmacies on duty."""
        return self._source.source_name

    async def _async_update_data(self) -> tuple[DutyPharmacy, ...]:
        """Refresh the pharmacies; then aim the next refresh at 09:20 if sooner.

        While the new turn isn't published, the next one is 5 minutes away.
        """
        try:
            return await super()._async_update_data()
        finally:
            wait = _until_shift_change(dt_util.utcnow(), self._interval)
            self.update_interval = min(wait, _OUTAGE_RETRY) if self._turn_over else wait

    def _keeps_last_good(self, now: datetime) -> bool:
        """Say whether the last good list is still of the turn on duty now.

        Past 09:15 the next turn's pharmacies are on duty: the old list is wrong.
        """
        listed = self._listed_turn
        return not self._turn_over and listed is not None and listed >= _turn_of(now)

    async def _async_fetch(self) -> tuple[DutyPharmacy, ...]:
        """Fetch the pharmacies on duty and keep those the layer shows.

        A list of a turn that has ended, or an empty one that tells no turn,
        shows none: see the class.
        """
        pharmacies = await self._source.on_duty()
        # The newest date is the list's turn. Rows older than it would still be
        # shown, but the city never mixes dates in one list.
        listed = max((pharmacy.day for pharmacy in pharmacies), default=None)
        current = _turn_of(dt_util.utcnow())
        self._listed_turn = listed
        self._turn_over = listed is None or listed < current
        self._cancel_turn_end()
        if self._turn_over:
            if self._waiting_for != current:
                self._waiting_for = current
                _LOGGER.info("Waiting for the city's on-duty list for %s", current)
            return ()
        self._waiting_for = None
        if listed is not None:
            self._turn_end_timer = async_track_point_in_utc_time(
                self.hass, self._turn_ended, turn_end(listed)
            )
        area = _area(self.hass, self._layer)
        self.centre = area.centre
        return tuple(
            pharmacy for pharmacy in pharmacies if area.contains(pharmacy.location)
        )

    @callback
    def _turn_ended(self, _now: datetime) -> None:
        """Take the ended turn's pharmacies off at 09:15, before the new list comes."""
        self._turn_end_timer = None
        self._turn_over = True
        # Not ``async_set_updated_data``: that would move the 09:20 refresh.
        self.data = ()
        self.async_update_listeners()

    def _cancel_turn_end(self) -> None:
        if self._turn_end_timer is not None:
            self._turn_end_timer()
            self._turn_end_timer = None

    async def async_shutdown(self) -> None:
        """Stop the 09:15 timer with the coordinator."""
        self._cancel_turn_end()
        await super().async_shutdown()

    def pharmacy(self, pharmacy_id: str) -> DutyPharmacy | None:
        """Return the pharmacy with ``pharmacy_id``, if the layer still shows it."""
        return next(
            (pharmacy for pharmacy in self.data or () if pharmacy.id == pharmacy_id),
            None,
        )

    def nearest(self) -> DutyPharmacy | None:
        """Return the pharmacy on duty nearest the layer's centre, if any."""
        return min(
            self.data or (),
            key=lambda pharmacy: self.centre.distance_to(pharmacy.location),
            default=None,
        )


@dataclass(frozen=True, slots=True)
class AirQualityData:
    """Every station and its latest readings, and the station the sensors use."""

    stations: tuple[AirStation, ...]
    readings: tuple[AirReading, ...]
    chosen: AirStation

    def readings_at(self, station_id: str) -> tuple[AirReading, ...]:
        """Return the latest reading of each pollutant at ``station_id``."""
        return tuple(
            reading for reading in self.readings if reading.station_id == station_id
        )

    def station(self, station_id: str) -> AirStation | None:
        """Return the station with ``station_id``, if the city still lists it."""
        return next(
            (station for station in self.stations if station.id == station_id), None
        )


class AirQualityCoordinator(_SourceCoordinator[AirQualityData]):
    """Every station's readings, and the station the sensors use.

    One request per refresh brings the stations and their readings.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        source: AirQualitySource,
        listed: Callable[[tuple[AirStation, ...]], None],
    ) -> None:
        """Read the stations and readings from ``source``.

        Each refresh's stations go to ``listed``, never an empty list: an
        answer without stations is a failed refresh.
        """
        options = ZodOptions.from_mapping(entry.options)
        self._source = source
        self._listed = listed
        self._configured = options.air_station
        # Distances to the stations are measured from home.
        self.centre = home_of(hass)
        super().__init__(
            hass,
            entry,
            name="air quality",
            interval=options.refresh.air_quality,
            unavailable="air_quality_unavailable",
            keep_for=_KEPT_REFRESHES * options.refresh.air_quality,
        )

    @property
    def source_name(self) -> str:
        """Return who publishes the readings."""
        return self._source.source_name

    async def _async_fetch(self) -> AirQualityData:
        """Fetch the stations and their readings; pick the station."""
        report = await self._source.report()
        stations = report.stations
        if not stations:
            raise SourceUnavailableError(self._source.source_name)
        self._listed(stations)
        readings = report.readings
        self.centre = home_of(self.hass)
        nearest = min(
            stations, key=lambda station: self.centre.distance_to(station.location)
        )
        chosen = nearest
        if self._configured is not None:
            configured = next(
                (station for station in stations if station.id == self._configured),
                None,
            )
            if configured is None:
                _LOGGER.debug(
                    "Air quality station %s is no longer listed: using %s, "
                    "the nearest to home",
                    self._configured,
                    nearest.name,
                )
            else:
                chosen = configured
        return AirQualityData(stations=stations, readings=readings, chosen=chosen)


class PollenCoordinator(_SourceCoordinator[tuple[PollenReading, ...]]):
    """Each plant's pollen level, as the city last published it."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, source: PollenSource
    ) -> None:
        """Ask ``source`` as often as the options allow."""
        self._source = source
        interval = ZodOptions.from_mapping(entry.options).refresh.pollen
        super().__init__(
            hass,
            entry,
            name="pollen",
            interval=interval,
            unavailable="pollen_unavailable",
            keep_for=_KEPT_REFRESHES * interval,
        )

    @property
    def source_name(self) -> str:
        """Return who publishes the pollen levels."""
        return self._source.source_name

    async def _async_fetch(self) -> tuple[PollenReading, ...]:
        """Fetch every plant's level."""
        return await self._source.readings()

    def reading(self, plant_id: str) -> PollenReading | None:
        """Return the plant's reading, if the city still lists the plant."""
        return next(
            (reading for reading in self.data or () if reading.plant_id == plant_id),
            None,
        )


# The coordinators of the city information that has no stops: their entities
# live on one service device per kind.
type CityCoordinator = (
    RoadWorksCoordinator
    | PharmaciesCoordinator
    | AirQualityCoordinator
    | PollenCoordinator
)
