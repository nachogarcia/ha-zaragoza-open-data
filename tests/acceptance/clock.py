"""Letting time pass on Home Assistant's test instance, with time frozen by freezer."""

from datetime import datetime, timedelta

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant.common import async_fire_time_changed

from homeassistant.core import HomeAssistant

_STEP = timedelta(seconds=1)
# A source that fails at a coordinator's first refresh is asked once more this
# much later: Home Assistant may have just started, its network not quite up.
FIRST_RETRY = timedelta(seconds=5)


async def pass_time(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    delta: timedelta,
    step: timedelta = _STEP,
) -> None:
    """Let ``delta`` pass ``step`` at a time, firing every timer as it falls due.

    A second at a time by default, so a refresh that waits between its requests
    (the bus, with several stops) gets each of its waits. With one stop a step
    can be a whole refresh interval.
    """
    for _ in range(delta // step):
        freezer.tick(step)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def move_to(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, when: str | datetime
) -> None:
    """Jump to ``when`` and fire the timers due by then."""
    freezer.move_to(when)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
