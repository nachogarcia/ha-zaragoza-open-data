"""Operator-first, city-fallback policy shared by the bus and bike sources."""

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta

from .errors import SourceUnavailableError
from .models import ArrivalBoard, BikeAvailability, BikeStation, StationCode, StopCode
from .ports import BikeSource, BusArrivalsSource


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FallbackPolicy:
    """Use the primary; after it fails, use the fallback until the retry time."""

    def __init__(
        self,
        retry_primary_after: timedelta = timedelta(minutes=5),
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Set how long the primary rests after a failure and the clock to use."""
        self._retry_primary_after = retry_primary_after
        self._now = now
        self._primary_failed_at: datetime | None = None

    def _primary_is_resting(self) -> bool:
        failed_at = self._primary_failed_at
        return (
            failed_at is not None
            and self._now() < failed_at + self._retry_primary_after
        )

    async def run[R](
        self,
        primary: Callable[[], Awaitable[R]],
        fallback: Callable[[], Awaitable[R]],
    ) -> R:
        """Return the primary's result, or the fallback's while the primary rests.

        If both fail, the fallback's ``SourceUnavailableError`` propagates.
        """
        if not self._primary_is_resting():
            try:
                result = await primary()
            except SourceUnavailableError:
                self._primary_failed_at = self._now()
            else:
                self._primary_failed_at = None
                return result
        return await fallback()


def _composite_name(primary: str, fallback: str) -> str:
    return f"{primary}+{fallback}"


class FallbackBusArrivals:
    """A ``BusArrivalsSource`` made of an operator source and a city source."""

    def __init__(
        self,
        primary: BusArrivalsSource,
        fallback: BusArrivalsSource,
        policy: FallbackPolicy,
    ) -> None:
        """Wrap both sources with the shared policy."""
        self._primary = primary
        self._fallback = fallback
        self._policy = policy

    @property
    def source_name(self) -> str:
        """Both provider names; boards keep the name of whoever answered."""
        return _composite_name(self._primary.source_name, self._fallback.source_name)

    async def board(self, code: StopCode) -> ArrivalBoard:
        """Return the board from the primary, or from the fallback if it is down."""
        return await self._policy.run(
            lambda: self._primary.board(code), lambda: self._fallback.board(code)
        )


class FallbackBikeSource:
    """A ``BikeSource`` made of GBFS and the city list."""

    def __init__(
        self,
        primary: BikeSource,
        fallback: BikeSource,
        policy: FallbackPolicy,
    ) -> None:
        """Wrap both sources with the shared policy."""
        self._primary = primary
        self._fallback = fallback
        self._policy = policy

    @property
    def source_name(self) -> str:
        """Both provider names; availability keeps the name of whoever answered."""
        return _composite_name(self._primary.source_name, self._fallback.source_name)

    async def stations(self) -> tuple[BikeStation, ...]:
        """Return the stations from the primary, or from the fallback if it is down."""
        return await self._policy.run(self._primary.stations, self._fallback.stations)

    async def availability(self) -> Mapping[StationCode, BikeAvailability]:
        """Return the availability from the primary, or from the fallback."""
        return await self._policy.run(
            self._primary.availability, self._fallback.availability
        )
