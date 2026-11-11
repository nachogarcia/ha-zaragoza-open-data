"""The Avanza bus adapter against recorded HTTP."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
import logging

import aiohttp
import pytest
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.zaragoza_open_data.api.adapters.avanza.bus import (
    AvanzaBusArrivals,
)
from custom_components.zaragoza_open_data.api.errors import SourceUnavailableError
from custom_components.zaragoza_open_data.api.models import StopCode
from tests.fixtures import FIXTURES, read_fixture

URL = "https://zaragoza-pasobus.avanzagrupo.com/frm_esquemaparadatime.php"
USER_AGENT = "ZaragozaOpenData/test (+https://example.invalid)"
NOW = datetime(2026, 11, 9, 12, 41, 30, tzinfo=UTC)


@pytest.fixture
async def avanza(
    aioclient_mock: AiohttpClientMocker,
) -> AsyncIterator[AvanzaBusArrivals]:
    """Adapter whose HTTP is the recorded replay, with a fixed clock."""
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield AvanzaBusArrivals(session, USER_AGENT, lambda: NOW)
    await session.close()


def serve(aioclient_mock: AiohttpClientMocker, fixture: str) -> None:
    """Serve a recorded page as its raw bytes (the adapter decodes them itself)."""
    aioclient_mock.get(URL, content=(FIXTURES / "avanza" / fixture).read_bytes())


async def test_avanza_parses_two_rows_per_line(
    avanza: AvanzaBusArrivals, aioclient_mock: AiohttpClientMocker
) -> None:
    """Each row is one bus, with its line, destination and minutes."""
    serve(aioclient_mock, "stop_1231.html")

    board = await avanza.board(StopCode("1231"))

    assert board.source == "avanza"
    assert board.stop_code == "1231"
    assert board.observed_at == NOW
    assert [(a.line, a.destination, a.expected_at - NOW) for a in board.arrivals] == [
        ("56", "VALDESPARTERA", timedelta(minutes=22)),
        ("56", "VALDESPARTERA", timedelta(minutes=48)),
        ("59", "TRANVIA-ARCOSUR", timedelta(minutes=7)),
        ("59", "TRANVIA-ARCOSUR", timedelta(minutes=27)),
    ]
    call = aioclient_mock.mock_calls[0]
    assert call[1].query["poste"] == "1231"
    assert call[3]["User-Agent"] == USER_AGENT


async def test_avanza_stop_without_buses_gives_empty_board(
    avanza: AvanzaBusArrivals, aioclient_mock: AiohttpClientMocker
) -> None:
    """A page with the table but no bus rows is an empty board."""
    serve(aioclient_mock, "stop_no_buses_derived.html")

    board = await avanza.board(StopCode("688"))

    assert board.arrivals == ()
    assert board.observed_at == NOW


async def test_avanza_page_without_table_is_source_unavailable(
    avanza: AvanzaBusArrivals, aioclient_mock: AiohttpClientMocker
) -> None:
    """A page that is not the stop page at all is a changed format."""
    serve(aioclient_mock, "stop_no_table_derived.html")

    with pytest.raises(SourceUnavailableError) as raised:
        await avanza.board(StopCode("688"))

    assert raised.value.source == "avanza"


async def test_avanza_at_stop_text_means_now(
    avanza: AvanzaBusArrivals, aioclient_mock: AiohttpClientMocker
) -> None:
    """``En la parada.`` is zero minutes; text that is no time is skipped."""
    page = read_fixture("avanza/stop_688.html")
    page = page.replace("24 minutos.", "En la parada.").replace(
        "48 minutos.", "Sin estimacion."
    )
    aioclient_mock.get(URL, content=page.encode())

    board = await avanza.board(StopCode("688"))

    assert [a.expected_at for a in board.arrivals] == [NOW]


async def test_avanza_decodes_utf8_with_bom_despite_latin1_header(
    avanza: AvanzaBusArrivals, aioclient_mock: AiohttpClientMocker
) -> None:
    """The page says ISO-8859-1 in its header but is UTF-8 with a BOM."""
    page = read_fixture("avanza/stop_688.html").replace("FUENTE JUNQUERA", "ARAGÓN")
    aioclient_mock.get(
        URL,
        content=b"\xef\xbb\xbf" + page.encode(),
        headers={"Content-Type": "text/html; charset=iso-8859-1"},
    )

    board = await avanza.board(StopCode("688"))

    assert {a.destination for a in board.arrivals} == {"ARAGÓN"}


async def test_avanza_decodes_latin1_body(
    avanza: AvanzaBusArrivals, aioclient_mock: AiohttpClientMocker
) -> None:
    """A genuine ISO-8859-1 body still decodes."""
    page = read_fixture("avanza/stop_688.html").replace("FUENTE JUNQUERA", "ARAGÓN")
    aioclient_mock.get(URL, content=page.encode("iso-8859-1", "replace"))

    board = await avanza.board(StopCode("688"))

    assert {a.destination for a in board.arrivals} == {"ARAGÓN"}


@pytest.mark.parametrize("status", [500, 404])
async def test_avanza_http_error_is_source_unavailable(
    avanza: AvanzaBusArrivals, aioclient_mock: AiohttpClientMocker, status: int
) -> None:
    """A non-200 answer is source unavailable."""
    aioclient_mock.get(URL, status=status, text="oops")

    with pytest.raises(SourceUnavailableError) as raised:
        await avanza.board(StopCode("688"))

    assert raised.value.source == "avanza"


@pytest.mark.parametrize("failure", [aiohttp.ClientError(), TimeoutError()])
async def test_avanza_transport_failure_is_source_unavailable(
    avanza: AvanzaBusArrivals,
    aioclient_mock: AiohttpClientMocker,
    failure: Exception,
) -> None:
    """A timeout or client error is source unavailable."""
    aioclient_mock.get(URL, exc=failure)

    with pytest.raises(SourceUnavailableError):
        await avanza.board(StopCode("688"))


@pytest.mark.parametrize(
    ("answer", "logged", "cause"),
    [
        ({"exc": TimeoutError()}, f"No answer from {URL} in 10 s", TimeoutError),
        ({"status": 503, "text": "oops"}, f"{URL} answered HTTP 503", type(None)),
    ],
    ids=["timeout", "http_503"],
)
async def test_avanza_failure_cause_is_logged_at_debug(
    avanza: AvanzaBusArrivals,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
    answer: dict[str, object],
    logged: str,
    cause: type[BaseException | None],
) -> None:
    """The operator failing says why at debug, and the error keeps its cause."""
    aioclient_mock.get(URL, **answer)

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(SourceUnavailableError) as raised,
    ):
        await avanza.board(StopCode("688"))

    assert [
        (record.levelname, record.getMessage())
        for record in caplog.records
        if record.name.endswith("avanza.bus")
    ] == [("DEBUG", logged)]
    assert isinstance(raised.value.__cause__, cause)


async def test_avanza_default_clock_is_aware_utc_now(
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Without an injected clock the board is observed now, timezone-aware."""
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    serve(aioclient_mock, "stop_688.html")
    before = datetime.now(UTC)

    board = await AvanzaBusArrivals(session, USER_AGENT).board(StopCode("688"))

    assert before <= board.observed_at <= datetime.now(UTC)
    await session.close()
