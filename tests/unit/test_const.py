"""Constants: the User-Agent follows the manifest version."""

import json
from pathlib import Path

from custom_components.zaragoza_open_data.const import DOMAIN, USER_AGENT

MANIFEST = (
    Path(__file__).parents[2]
    / "custom_components"
    / "zaragoza_open_data"
    / "manifest.json"
)


def test_user_agent_names_integration_manifest_version_and_repository() -> None:
    """Requests identify the integration, its version and its repository only."""
    version = json.loads(MANIFEST.read_text("utf-8"))["version"]

    expected = (
        f"ZaragozaOpenData/{version} "
        "(+https://github.com/nachogarcia/ha-zaragoza-open-data)"
    )

    assert expected == USER_AGENT
    assert "@" not in USER_AGENT


def test_domain_matches_manifest() -> None:
    """The domain constant is the manifest's domain."""
    assert json.loads(MANIFEST.read_text("utf-8"))["domain"] == DOMAIN
