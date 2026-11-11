"""The GBFS bike adapter against recorded HTTP."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
import json
import logging

import aiohttp
import pytest
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.zaragoza_open_data.api.adapters.gbfs.bike import GbfsBike
from custom_components.zaragoza_open_data.api.errors import SourceUnavailableError
from custom_components.zaragoza_open_data.api.models import StationCode
from tests.fixtures import read_fixture

BASE = "https://zaragoza.publicbikesystem.net/customer/gbfs/v2/en/"
INFORMATION = BASE + "station_information.json"
STATUS = BASE + "station_status.json"
USER_AGENT = "ZaragozaOpenData/test (+https://example.invalid)"
RECORDED = datetime(2026, 11, 9, 12, 41, tzinfo=UTC)


class Clock:
    """A settable clock handed to the adapter."""

    def __init__(self) -> None:
        """Start at the moment the fixtures were recorded."""
        self.value = RECORDED

    def __call__(self) -> datetime:
        """Return the current fake time."""
        return self.value


@pytest.fixture
def clock() -> Clock:
    """Clock."""
    return Clock()


@pytest.fixture
async def gbfs(
    aioclient_mock: AiohttpClientMocker, clock: Clock
) -> AsyncIterator[GbfsBike]:
    """Adapter whose HTTP replays the recorded feeds."""
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield GbfsBike(session, USER_AGENT, now=clock)
    await session.close()


def serve(
    aioclient_mock: AiohttpClientMocker,
    information: str = "station_information.json",
    status: str = "station_status.json",
) -> None:
    """Serve recorded GBFS feeds."""
    aioclient_mock.get(INFORMATION, text=read_fixture(f"gbfs/{information}"))
    aioclient_mock.get(STATUS, text=read_fixture(f"gbfs/{status}"))


def requested(aioclient_mock: AiohttpClientMocker, url: str) -> int:
    """Count the requests the adapter sent to ``url``."""
    return sum(1 for call in aioclient_mock.mock_calls if str(call[1]) == url)


async def test_gbfs_parses_276_stations(
    gbfs: GbfsBike, aioclient_mock: AiohttpClientMocker
) -> None:
    """Every recorded station is listed with its number as code and the rest as name."""
    serve(aioclient_mock)

    stations = await gbfs.stations()
    availability = await gbfs.availability()

    assert gbfs.source_name == "gbfs"
    assert len(stations) == 276
    assert len(availability) == 276
    first = next(s for s in stations if s.code == "1")
    assert first.name == "Palacio Congresos"
    assert first.capacity == 19
    assert first.address == "Avda. Ranillas - Edificio 5"
    assert first.location.latitude == pytest.approx(41.669943)
    assert first.location.longitude == pytest.approx(-0.903698)
    # A real name with a space before the hyphen.
    assert next(s for s in stations if s.code == "160").name == "Jardines Montemolín"
    call = aioclient_mock.mock_calls[0]
    assert call[3]["User-Agent"] == USER_AGENT


async def test_gbfs_splits_electric_and_mechanical(
    gbfs: GbfsBike, aioclient_mock: AiohttpClientMocker
) -> None:
    """EFIT and BOOST are electric, ICONIC is mechanical; flags and time come along."""
    status = json.loads(read_fixture("gbfs/station_status.json"))
    station = next(s for s in status["data"]["stations"] if s["station_id"] == "134")
    station["vehicle_types_available"] = [
        {"vehicle_type_id": "BOOST", "count": 1},
        {"vehicle_type_id": "ICONIC", "count": 3},
        {"vehicle_type_id": "EFIT", "count": 4},
    ]
    station["num_bikes_available"] = 8
    station["is_renting"] = False
    station["is_returning"] = True
    station["last_reported"] = 1794228004
    aioclient_mock.get(INFORMATION, text=read_fixture("gbfs/station_information.json"))
    aioclient_mock.get(STATUS, text=json.dumps(status))

    entry = (await gbfs.availability())[StationCode("164")]

    assert (entry.bikes, entry.electric, entry.mechanical) == (8, 5, 3)
    assert entry.docks == 15
    assert (entry.renting, entry.returning) == (False, True)
    assert entry.reported_at == datetime(2026, 11, 9, 12, 40, 4, tzinfo=UTC)
    assert entry.source == "gbfs"


async def test_gbfs_caches_station_information_for_a_day(
    gbfs: GbfsBike, aioclient_mock: AiohttpClientMocker, clock: Clock
) -> None:
    """The slow-changing station list is fetched once a day, the status every time."""
    serve(aioclient_mock)

    await gbfs.availability()
    await gbfs.availability()
    await gbfs.stations()

    assert requested(aioclient_mock, INFORMATION) == 1
    assert requested(aioclient_mock, STATUS) == 2

    clock.value += timedelta(hours=24, seconds=1)
    await gbfs.availability()

    assert requested(aioclient_mock, INFORMATION) == 2
    assert requested(aioclient_mock, STATUS) == 3


async def test_station_without_number_prefix_is_skipped(
    gbfs: GbfsBike,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A station whose name has no ``N-`` prefix is left out; the rest is parsed."""
    serve(aioclient_mock, information="station_information_no_prefix_derived.json")

    with caplog.at_level(logging.DEBUG):
        stations = await gbfs.stations()
        availability = await gbfs.availability()

    assert len(stations) == 275
    assert "164" not in {s.code for s in stations}
    assert len(availability) == 275
    assert StationCode("164") not in availability
    skipped = [r for r in caplog.records if "Rosales: Illueca" in r.getMessage()]
    assert [r.levelno for r in skipped] == [logging.DEBUG]


async def test_status_for_unknown_station_is_skipped(
    gbfs: GbfsBike, aioclient_mock: AiohttpClientMocker
) -> None:
    """A station in the status feed but not in the cached list cannot be numbered."""
    information = json.loads(read_fixture("gbfs/station_information.json"))
    information["data"]["stations"] = [
        s for s in information["data"]["stations"] if s["station_id"] != "134"
    ]
    aioclient_mock.get(INFORMATION, text=json.dumps(information))
    aioclient_mock.get(STATUS, text=read_fixture("gbfs/station_status.json"))

    availability = await gbfs.availability()

    assert len(availability) == 275
    assert StationCode("164") not in availability


@pytest.mark.parametrize("failing", [INFORMATION, STATUS])
async def test_gbfs_http_error_is_source_unavailable(
    gbfs: GbfsBike, aioclient_mock: AiohttpClientMocker, failing: str
) -> None:
    """An HTTP error from either feed is ``SourceUnavailableError('gbfs')``."""
    # The mocker answers with the first matching route, so register the failure first.
    aioclient_mock.get(failing, status=503)
    serve(aioclient_mock)

    with pytest.raises(SourceUnavailableError) as raised:
        await gbfs.availability()

    assert raised.value.source == "gbfs"


async def test_gbfs_html_body_is_source_unavailable(
    gbfs: GbfsBike, aioclient_mock: AiohttpClientMocker
) -> None:
    """A maintenance page answered with HTTP 200 is not parsed."""
    aioclient_mock.get(INFORMATION, text="<html>maintenance</html>")
    aioclient_mock.get(STATUS, text=read_fixture("gbfs/station_status.json"))

    with pytest.raises(SourceUnavailableError):
        await gbfs.stations()


async def test_gbfs_unexpected_shape_is_source_unavailable(
    gbfs: GbfsBike, aioclient_mock: AiohttpClientMocker
) -> None:
    """A status feed without the ``data.stations`` list is the provider changing."""
    aioclient_mock.get(INFORMATION, text=read_fixture("gbfs/station_information.json"))
    aioclient_mock.get(STATUS, text=json.dumps({"data": {"stations": "none"}}))

    with pytest.raises(SourceUnavailableError):
        await gbfs.availability()


async def test_gbfs_timeout_is_source_unavailable(
    gbfs: GbfsBike, aioclient_mock: AiohttpClientMocker
) -> None:
    """A timed-out request is reported like any other outage."""
    aioclient_mock.get(INFORMATION, exc=TimeoutError())

    with pytest.raises(SourceUnavailableError):
        await gbfs.stations()


@pytest.mark.parametrize(
    ("answer", "logged", "cause"),
    [
        (
            {"exc": TimeoutError()},
            f"No answer from {INFORMATION} in 10 s",
            TimeoutError,
        ),
        ({"status": 503}, f"{INFORMATION} answered HTTP 503", type(None)),
        (
            {"exc": aiohttp.ClientConnectionError("Connection reset by peer")},
            f"Can't reach {INFORMATION}: Connection reset by peer",
            aiohttp.ClientConnectionError,
        ),
    ],
    ids=["timeout", "http_503", "connection_error"],
)
async def test_gbfs_failure_cause_is_logged_at_debug(
    gbfs: GbfsBike,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
    answer: dict[str, object],
    logged: str,
    cause: type[BaseException | None],
) -> None:
    """The operator's feed failing says why at debug, and the error keeps its cause."""
    aioclient_mock.get(INFORMATION, **answer)

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(SourceUnavailableError) as raised,
    ):
        await gbfs.stations()

    assert [
        (record.levelname, record.getMessage())
        for record in caplog.records
        if record.name.endswith("gbfs.bike")
    ] == [("DEBUG", logged)]
    assert isinstance(raised.value.__cause__, cause)


async def test_gbfs_json_that_is_not_an_object_is_source_unavailable(
    gbfs: GbfsBike, aioclient_mock: AiohttpClientMocker
) -> None:
    """A JSON array instead of the feed object is the provider changing."""
    aioclient_mock.get(INFORMATION, text="[]")

    with pytest.raises(SourceUnavailableError):
        await gbfs.stations()


async def test_gbfs_impossible_report_time_is_source_unavailable(
    gbfs: GbfsBike, aioclient_mock: AiohttpClientMocker
) -> None:
    """A ``last_reported`` that is no real instant is a format failure."""
    status = json.loads(read_fixture("gbfs/station_status.json"))
    status["data"]["stations"][0]["last_reported"] = 10**18
    aioclient_mock.get(INFORMATION, text=read_fixture("gbfs/station_information.json"))
    aioclient_mock.get(STATUS, text=json.dumps(status))

    with pytest.raises(SourceUnavailableError):
        await gbfs.availability()


async def test_gbfs_station_without_type_counts_has_no_split(
    gbfs: GbfsBike, aioclient_mock: AiohttpClientMocker
) -> None:
    """When the feed omits ``vehicle_types_available`` the split is unknown, not zero."""
    status = json.loads(read_fixture("gbfs/station_status.json"))
    del status["data"]["stations"][0]["vehicle_types_available"]
    aioclient_mock.get(INFORMATION, text=read_fixture("gbfs/station_information.json"))
    aioclient_mock.get(STATUS, text=json.dumps(status))

    entries = list((await gbfs.availability()).values())

    assert (entries[0].electric, entries[0].mechanical) == (None, None)
    assert entries[1].electric is not None
