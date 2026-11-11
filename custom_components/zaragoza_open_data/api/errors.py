"""Errors raised by ``api/``; messages are fixed, data lives in attributes."""


class ZaragozaOpenDataError(Exception):
    """Base class of every error this integration raises on purpose."""


class SourceUnavailableError(ZaragozaOpenDataError):
    """A provider is down, answered with an error body, or sent an unexpected shape."""

    def __init__(self, source: str) -> None:
        """Remember which provider failed; the message never carries data."""
        super().__init__("Source unavailable")
        self.source = source
