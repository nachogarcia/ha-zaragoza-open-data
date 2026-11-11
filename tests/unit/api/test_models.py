"""Behaviour of the typed models and errors in ``api/``."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.zaragoza_open_data.api.errors import (
    SourceUnavailableError,
    ZaragozaOpenDataError,
)
from custom_components.zaragoza_open_data.api.models import (
    Area,
    Arrival,
    ArrivalBoard,
    GeoPoint,
    StopCode,
)

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def _arrival(line: str, minutes: int) -> Arrival:
    return Arrival(
        line=line,
        destination="Destino",
        expected_at=NOW + timedelta(minutes=minutes),
    )


def _board(*arrivals: Arrival, observed_at: datetime = NOW) -> ArrivalBoard:
    return ArrivalBoard(
        stop_code=StopCode("688"),
        arrivals=arrivals,
        observed_at=observed_at,
        source="avanza",
    )


def test_distance_between_mago_de_oz_platforms_is_small() -> None:
    """Two platforms of one stop are only a few metres apart."""
    first = GeoPoint(41.624375, -0.936450)

    assert first.distance_to(GeoPoint(41.62437, -0.93645)) < 5


def test_area_without_radius_contains_everything() -> None:
    """No radius means the whole city."""
    area = Area(centre=GeoPoint(41.65, -0.88), radius_m=None)

    assert area.contains(GeoPoint(0.0, 0.0))


def test_area_contains_point_inside_radius() -> None:
    """A point about 500 m away is inside a 1 km area and outside a 100 m one."""
    centre = GeoPoint(41.65, -0.88)
    point = GeoPoint(41.65 + 0.0045, -0.88)  # ~500 m north

    assert Area(centre=centre, radius_m=1000).contains(point)
    assert not Area(centre=centre, radius_m=100).contains(point)


def test_upcoming_sorts_by_time_and_filters_lines() -> None:
    """Upcoming arrivals come soonest first and can be limited to some lines."""
    a58_5, a31_3, a58_20 = _arrival("58", 5), _arrival("31", 3), _arrival("58", 20)
    board = _board(a58_5, a31_3, a58_20)

    assert board.upcoming(NOW) == (a31_3, a58_5, a58_20)
    assert board.upcoming(NOW, frozenset({"58"})) == (a58_5, a58_20)


def test_upcoming_drops_arrivals_gone_more_than_a_minute() -> None:
    """A vehicle due up to a minute ago may still be at the stop; earlier ones left."""
    gone, at_stop = _arrival("58", -2), _arrival("58", -1)
    coming, other_line = _arrival("58", 4), _arrival("31", 1)
    board = _board(coming, gone, at_stop, other_line)

    assert board.upcoming(NOW) == (at_stop, other_line, coming)
    assert board.upcoming(NOW, frozenset({"58"})) == (at_stop, coming)


def test_minutes_to_are_the_sources_until_a_whole_minute_passes() -> None:
    """The source's own minutes, one fewer per whole minute since it counted them.

    The source counted 4 minutes at ``NOW``; seconds later it still says 4.
    """
    arrival = _arrival("58", 4)
    board = _board(arrival)

    assert board.minutes_to(arrival, NOW) == 4
    assert board.minutes_to(arrival, NOW + timedelta(seconds=59)) == 4
    assert board.minutes_to(arrival, NOW + timedelta(minutes=1)) == 3
    assert board.minutes_to(arrival, NOW + timedelta(minutes=10)) == 0
    # A clock a little behind the source's adds nothing.
    assert board.minutes_to(arrival, NOW - timedelta(seconds=5)) == 4


def test_minutes_change_a_whole_minute_after_the_reading() -> None:
    """The minutes drop at each whole minute after the source counted, and only then."""
    board = _board(_arrival("58", 4))

    assert board.minutes_change_at(NOW) == NOW + timedelta(minutes=1)
    assert board.minutes_change_at(NOW + timedelta(seconds=30)) == NOW + timedelta(
        minutes=1
    )
    assert board.minutes_change_at(NOW + timedelta(minutes=1)) == NOW + timedelta(
        minutes=2
    )
    assert board.minutes_change_at(NOW - timedelta(seconds=5)) == NOW + timedelta(
        minutes=1
    )


def test_board_usable_until_max_age() -> None:
    """A board is usable while it is younger than max_age."""
    board = _board()
    max_age = timedelta(minutes=10)

    assert board.is_usable_at(NOW + timedelta(minutes=9, seconds=59), max_age)
    assert not board.is_usable_at(NOW + timedelta(minutes=10, seconds=1), max_age)


def test_naive_datetime_rejected() -> None:
    """Models refuse datetimes without a timezone."""
    with pytest.raises(ValueError, match="timezone"):
        Arrival(
            line="58",
            destination="Destino",
            expected_at=datetime(2026, 11, 9, 12, 0),
        )


def test_errors_keep_stable_messages() -> None:
    """Error text never contains data; the data sits in attributes."""
    unavailable = SourceUnavailableError(source="avanza")

    assert str(unavailable) == "Source unavailable"
    assert unavailable.source == "avanza"
    assert isinstance(unavailable, ZaragozaOpenDataError)
