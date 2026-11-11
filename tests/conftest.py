"""Shared fixtures."""

import pytest


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    """Give each test its own configuration folder.

    The test package's default is ``tests/testing_config``, in the repository, and
    setting up ``automation`` writes Home Assistant's own blueprints into it.
    """
    return hass_tmp_config_dir


@pytest.fixture
def mock_recorder_before_hass(request: pytest.FixtureRequest) -> None:
    """In a test that records history, prepare the recorder before Home Assistant.

    The test package's ``hass`` asks for this fixture before it starts, and the
    recorder's database must come first (its fixture checks). Without it, an
    autouse fixture that needs ``hass`` would start Home Assistant too early.
    """
    if "recorder_mock" in request.fixturenames:
        request.getfixturevalue("async_test_recorder")
