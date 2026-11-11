"""Bus arrivals from the operator's own page (Avanza), parsed from its HTML."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
import logging

import aiohttp

from ...errors import SourceUnavailableError
from ...models import Arrival, ArrivalBoard, StopCode
from ..minutes import parse_minutes

_LOGGER = logging.getLogger(__name__)

URL = "https://zaragoza-pasobus.avanzagrupo.com/frm_esquemaparadatime.php"
SOURCE = "avanza"
_TIMEOUT_S = 10
_TIMEOUT = aiohttp.ClientTimeout(total=_TIMEOUT_S)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _Rows(HTMLParser):
    """Collects the text of every table row's cells (nested tables included)."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.has_table = False
        self._open_rows: list[list[str]] = []
        self._open_cells: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.has_table = True
        elif tag == "tr":
            self._open_rows.append([])
        elif tag == "td" and self._open_rows:
            self._open_cells.append([])

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._open_cells and self._open_rows:
            cell = "".join(self._open_cells.pop()).strip()
            self._open_rows[-1].append(" ".join(cell.split()))
        elif tag == "tr" and self._open_rows:
            self.rows.append(self._open_rows.pop())

    def handle_data(self, data: str) -> None:
        # The wheelchair icon's <title> lands in its cell's text: "Accesible con ...".
        if self._open_cells:
            self._open_cells[-1].append(data)


def _decode(raw: bytes) -> str:
    # The header claims ISO-8859-1 but the body is UTF-8 with a BOM; trust the bytes.
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("iso-8859-1")


class AvanzaBusArrivals:
    """``BusArrivalsSource`` backed by the operator's page."""

    source_name = SOURCE

    def __init__(
        self,
        session: aiohttp.ClientSession,
        user_agent: str,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Keep the shared session (owned by the caller) and the clock."""
        self._session = session
        self._user_agent = user_agent
        self._now = now

    async def board(self, code: StopCode) -> ArrivalBoard:
        """Return the board of one stop.

        Each failure's cause is logged at debug: a short failure is not an outage.
        """
        try:
            async with self._session.get(
                URL,
                params={"poste": code},
                headers={"User-Agent": self._user_agent},
                timeout=_TIMEOUT,
            ) as response:
                status = response.status
                raw = await response.read()
        except TimeoutError as err:
            _LOGGER.debug("No answer from %s in %d s", URL, _TIMEOUT_S)
            raise SourceUnavailableError(SOURCE) from err
        except aiohttp.ClientError as err:
            _LOGGER.debug("Can't reach %s: %s", URL, err)
            raise SourceUnavailableError(SOURCE) from err
        if status != 200:
            _LOGGER.debug("%s answered HTTP %s", URL, status)
            raise SourceUnavailableError(SOURCE)
        observed_at = self._now()
        parser = _Rows()
        parser.feed(_decode(raw))
        parser.close()
        if not parser.has_table:
            _LOGGER.debug("%s answered a page without the arrivals table", URL)
            raise SourceUnavailableError(SOURCE)
        arrivals: list[Arrival] = []
        for cells in parser.rows:
            # LINEA, DESTINO, MIN, then ACCES (not read): the header and the page's
            # other rows fail the minutes test and are skipped.
            if len(cells) < 3:
                continue
            minutes = parse_minutes(cells[2])
            if minutes is None:
                continue
            arrivals.append(
                Arrival(
                    line=cells[0],
                    destination=cells[1],
                    expected_at=observed_at + timedelta(minutes=minutes),
                )
            )
        return ArrivalBoard(
            stop_code=code,
            arrivals=tuple(arrivals),
            observed_at=observed_at,
            source=SOURCE,
        )
