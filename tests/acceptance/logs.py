"""What the integration writes to Home Assistant's log."""

import logging

import pytest

_OURS = "custom_components.zaragoza_open_data"


def logged(
    caplog: pytest.LogCaptureFixture, level: int = logging.INFO
) -> list[tuple[str, str]]:
    """Return what the integration logged at ``level`` or above: (level, message)."""
    return [
        (record.levelname, record.getMessage())
        for record in caplog.records
        if record.name.startswith(_OURS) and record.levelno >= level
    ]
