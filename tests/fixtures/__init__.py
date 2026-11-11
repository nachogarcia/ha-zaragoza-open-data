"""Recorded provider responses, see README.md in this folder."""

from pathlib import Path

FIXTURES = Path(__file__).parent


def read_fixture(name: str) -> str:
    """Return the text of ``tests/fixtures/<name>`` (e.g. ``zaragoza_city/tram_list.json``)."""
    return (FIXTURES / name).read_text(encoding="utf-8")
