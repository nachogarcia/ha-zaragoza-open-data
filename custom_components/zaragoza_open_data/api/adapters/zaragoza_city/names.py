"""Helpers for the city's upper-case names and naive local timestamps."""

from datetime import datetime
from zoneinfo import ZoneInfo

from ...errors import SourceUnavailableError

_SOURCE = "zaragoza_city"

_MADRID = ZoneInfo("Europe/Madrid")
# Spanish particles stay lower case inside a name ("Plaza del Pilar").
_LOWER = frozenset({"de", "del", "la", "las", "los", "el", "y", "en"})


def tidy(text: str) -> str:
    """Title-case a city name, dropping tabs, line breaks and repeated spaces."""
    words = text.split()  # splits on any whitespace, so tabs and CR/LF vanish
    return " ".join(
        word.lower() if index and word.lower() in _LOWER else word.capitalize()
        for index, word in enumerate(words)
    )


def clean(text: str) -> str:
    """Drop stray tabs, line breaks and repeated spaces; the case stays as written."""
    return " ".join(text.split())


def clean_or_none(text: str | None) -> str | None:
    """Like ``clean``, with absent or blank text reported as ``None``."""
    return (clean(text) or None) if text is not None else None


def madrid(naive_iso: str) -> datetime:
    """Parse a naive ISO timestamp the city publishes in local time into an aware one.

    A malformed value is the city changing its format, so it is reported like every
    other wrong shape: ``SourceUnavailableError``.
    """
    try:
        return datetime.fromisoformat(naive_iso).replace(tzinfo=_MADRID)
    except ValueError:
        raise SourceUnavailableError(_SOURCE) from None
