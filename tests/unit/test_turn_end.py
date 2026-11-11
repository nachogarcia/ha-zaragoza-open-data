"""When a pharmacies' turn ends: 09:15 the next day in Zaragoza, across clock changes."""

from datetime import date

import pytest

from custom_components.zaragoza_open_data.coordinator import turn_end


@pytest.mark.parametrize(
    ("day", "ends"),
    [
        ("2026-11-09", "2026-11-10T09:15:00+01:00"),
        # The clocks go forward at 02:00 on 29 March and back at 03:00 on 25 October.
        ("2026-03-28", "2026-03-29T09:15:00+02:00"),
        ("2026-10-24", "2026-10-25T09:15:00+01:00"),
    ],
)
def test_turn_ends_at_nine_fifteen_madrid_time_the_next_day(
    day: str, ends: str
) -> None:
    """The turn's date gives 09:15 Zaragoza time on the day after, with its offset."""
    assert turn_end(date.fromisoformat(day)).isoformat() == ends
