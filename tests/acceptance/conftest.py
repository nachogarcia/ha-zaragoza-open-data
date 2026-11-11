"""Fixtures for the acceptance tests."""

from collections.abc import Iterator
from datetime import datetime
import logging

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import async_fire_time_changed
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
    mock_aiohttp_client,
)

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from tests.acceptance.clock import FIRST_RETRY
from tests.acceptance.providers import serve_recordings

_UNMOCKED = "No mock registered"
_COORDINATORS = "custom_components.zaragoza_open_data.coordinator"
# What the coordinators log just before they wait to ask a failing source again.
_ASKING_AGAIN = "No %s data from %s yet: asking again in %d s"


@pytest.fixture(autouse=True)
def aioclient_mock() -> Iterator[AiohttpClientMocker]:
    """Answer provider HTTP with what the test serves, else the recorded answers.

    A test serves only what it is about, a failure included; the coordinators'
    other requests get the recordings. A URL neither knows still fails loudly.
    """
    recordings = AiohttpClientMocker()
    serve_recordings(recordings)
    with mock_aiohttp_client() as mocker:
        served = mocker.match_request

        async def answer(method: str, url: object, **kwargs: object) -> object:
            try:
                return await served(method, url, **kwargs)
            except AssertionError as err:
                if not str(err).startswith(_UNMOCKED):
                    raise
            response = await recordings.match_request(method, url, **kwargs)
            # Counted with the test's own, so request counts stay true.
            mocker.mock_calls.append(recordings.mock_calls[-1])
            return response

        mocker.match_request = answer
        yield mocker


@pytest.fixture(autouse=True)
def first_retry_wait_passes(
    request: pytest.FixtureRequest, hass: HomeAssistant
) -> Iterator[None]:
    """Under frozen time, let the 5 s pass when a first refresh waits to ask again.

    A source failing at a coordinator's first refresh is asked again 5 s later,
    and setup waits for the tram's and Bizi's: frozen time would never get
    there. The coordinator logs that it will ask again just before it waits, so
    once it waits the clock moves on to that moment, as at home. A test that
    doesn't freeze time waits the 5 s for real. Should that log line change,
    the tests waiting on it time out instead of passing by chance.
    """
    if "freezer" not in request.fixturenames:
        yield
        return
    freezer: FrozenDateTimeFactory = request.getfixturevalue("freezer")

    def move_on(until: datetime) -> None:
        if dt_util.utcnow() < until:
            freezer.move_to(until)
        async_fire_time_changed(hass)

    class Waiting(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.msg == _ASKING_AGAIN:
                # Called while the coordinator runs: move on once it waits.
                hass.loop.call_soon(move_on, dt_util.utcnow() + FIRST_RETRY)

    coordinators = logging.getLogger(_COORDINATORS)
    waiting = Waiting(logging.DEBUG)
    level = coordinators.level
    coordinators.setLevel(logging.DEBUG)
    coordinators.addHandler(waiting)
    yield
    coordinators.removeHandler(waiting)
    coordinators.setLevel(level)


@pytest.fixture(autouse=True)
def no_traceback_logged(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Fail a test that logs an error with a traceback.

    An outage is logged as one plain line; a traceback means a bug, or a request
    nothing answers.
    """
    yield
    logged = [
        f"{record.name}: {record.getMessage()}"
        for when in ("setup", "call")
        for record in caplog.get_records(when)
        if record.levelno >= logging.ERROR and record.exc_info
    ]
    assert logged == []


@pytest.fixture(autouse=True)
def no_access_log(caplog: pytest.LogCaptureFixture) -> None:
    """Keep aiohttp's access log off, as Home Assistant's default log level does.

    Under frozen time it can't read the local UTC offset (freezegun's
    ``localtime`` has none) and logs that as an error with a traceback.
    """
    caplog.set_level(logging.WARNING, logger="aiohttp.access")


@pytest.fixture
async def in_zaragoza(hass: HomeAssistant) -> None:
    """Run Home Assistant on Zaragoza's clock, Europe/Madrid."""
    await hass.config.async_set_time_zone("Europe/Madrid")


# Near Plaza Aragón, in the city centre.
HOME = (41.6488, -0.8891)


@pytest.fixture
def home_in_zaragoza(hass: HomeAssistant) -> None:
    """Put home in Zaragoza; the test instance's home is in San Diego."""
    hass.config.latitude, hass.config.longitude = HOME
