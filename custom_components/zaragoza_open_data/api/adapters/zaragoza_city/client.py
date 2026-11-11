"""HTTP client for the city's open-data API (www.zaragoza.es/sede/servicio/)."""

from collections.abc import Mapping
import json
import logging

import aiohttp

from ...errors import SourceUnavailableError
from ...models import JsonObject
from ..json import obj_list, req_int

_LOGGER = logging.getLogger(__name__)

PAGE_ROWS = 500
_TIMEOUT_S = 10
_TIMEOUT = aiohttp.ClientTimeout(total=_TIMEOUT_S)


class CityClient:
    """Fetches JSON from the city API; every failure is ``SourceUnavailableError``.

    Each failure's cause is logged at debug: a short failure is not an outage, so
    whoever asked decides what reaches the log above that.
    """

    source_name = "zaragoza_city"

    def __init__(
        self,
        session: aiohttp.ClientSession,
        user_agent: str,
        base_url: str = "https://www.zaragoza.es/sede/servicio/",
    ) -> None:
        """Keep the shared session; it is owned (and closed) by the caller."""
        self._session = session
        self._user_agent = user_agent
        self._base_url = base_url

    async def get(self, path: str, params: Mapping[str, str]) -> JsonObject:
        """GET ``path`` and return the JSON object.

        The city answers errors as ``{"status": 400, "mensaje": ...}``, sometimes with
        HTTP 200, and maintenance as an HTML page; both count as the source being down.
        """
        url = self._base_url + path
        try:
            async with self._session.get(
                url,
                params=params,
                headers={"User-Agent": self._user_agent},
                timeout=_TIMEOUT,
            ) as response:
                status = response.status
                raw = await response.read()
        except TimeoutError as err:
            _LOGGER.debug("No answer from %s in %d s", url, _TIMEOUT_S)
            raise SourceUnavailableError(self.source_name) from err
        except aiohttp.ClientError as err:
            _LOGGER.debug("Can't reach %s: %s", url, err)
            raise SourceUnavailableError(self.source_name) from err
        if status != 200:
            _LOGGER.debug("%s answered HTTP %s", url, status)
            raise SourceUnavailableError(self.source_name)
        try:
            body = json.loads(raw)
        except ValueError as err:
            _LOGGER.debug("%s answered no JSON", url)
            raise SourceUnavailableError(self.source_name) from err
        if not isinstance(body, Mapping):
            _LOGGER.debug("%s answered JSON that is not an object", url)
            raise SourceUnavailableError(self.source_name)
        if "status" in body:
            _LOGGER.debug(
                "%s answered an error: %s %r", url, body["status"], body.get("mensaje")
            )
            raise SourceUnavailableError(self.source_name)
        return body

    async def get_all(self, path: str, params: Mapping[str, str]) -> list[JsonObject]:
        """GET every page of a list (500 rows at a time) and concatenate ``result``.

        A list that runs out before its ``totalCount`` (an empty page on the way)
        was not read whole: that is the source failing, not a shorter list, and
        raises ``SourceUnavailableError``. Stopping there also keeps a wrong
        ``totalCount`` from spinning forever.
        """
        collected: list[JsonObject] = []
        start = 0
        while True:
            page = await self.get(
                path, {**params, "rows": str(PAGE_ROWS), "start": str(start)}
            )
            start += PAGE_ROWS
            rows = obj_list(page, "result", self.source_name)
            collected.extend(rows)
            total = req_int(page, "totalCount", self.source_name)
            if len(collected) >= total:
                return collected
            if not rows:
                _LOGGER.debug(
                    "%s ended after %s of %s rows",
                    self._base_url + path,
                    len(collected),
                    total,
                )
                raise SourceUnavailableError(self.source_name)
