"""Architecture rule: picture URLs are built in one place, so each names its contents."""

from pathlib import Path

import pytest

PACKAGE = Path(__file__).parents[2] / "custom_components" / "zaragoza_open_data"
# Where the pins' pictures are served from, and the entity code that shows them.
ENTITY_MODULES = ["sensor.py", "geo_location.py", "binary_sensor.py", "entity.py"]


@pytest.mark.parametrize("module", ENTITY_MODULES)
def test_entities_do_not_build_marker_urls_themselves(module: str) -> None:
    """A marker URL without its version would be cached for a month."""
    source = (PACKAGE / module).read_text("utf-8")

    assert "MARKER_URL" not in source
    assert "MARKERS_PATH" not in source
    assert "/markers/" not in source
    assert ".svg" not in source
