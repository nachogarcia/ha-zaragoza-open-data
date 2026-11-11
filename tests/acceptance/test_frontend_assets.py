"""The card and the marker pictures are served by Home Assistant once set up."""

import hashlib
from http import HTTPStatus
import re

import pytest
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant.typing import ClientSessionGenerator

from custom_components.zaragoza_open_data.const import DOMAIN
from homeassistant.components.onboarding import STORAGE_KEY, STORAGE_VERSION
from homeassistant.components.onboarding.const import STEPS
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from tests.acceptance.entry import set_up_entry
from tests.acceptance.providers import (
    serve_air_stations,
    serve_pharmacies,
    serve_road_works,
)
from tests.acceptance.states import geo_events, state_of

CARD = "/zaragoza_open_data/zaragoza-open-data-card.js"


async def test_card_url_served_and_registered(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    hass_storage: dict[str, object],
) -> None:
    """Every dashboard loads the search card, versioned so a new card isn't cached.

    The page a browser opens imports the card, its URL naming the release and the
    file's contents; the card's file is JavaScript, cached like the other assets.
    """
    # A house that finished onboarding, so the page is the dashboard's.
    hass_storage[STORAGE_KEY] = {
        "version": STORAGE_VERSION,
        "key": STORAGE_KEY,
        "data": {"done": STEPS},
    }
    await set_up_entry(hass)
    version = (await async_get_integration(hass, DOMAIN)).version
    client = await hass_client()

    page = await (await client.get("/")).text()
    imported = re.findall(r'import\("([^"]*zaragoza-open-data-card[^"]*)"\)', page)
    assert len(imported) == 1
    response = await client.get(imported[0])
    assert response.status == HTTPStatus.OK
    assert response.content_type in ("text/javascript", "application/javascript")
    assert "max-age" in response.headers["Cache-Control"]
    card = await response.read()
    assert b"zaragoza-open-data-card" in card

    digest = hashlib.sha256(card).hexdigest()[:8]
    assert imported == [f"{CARD}?v={version}-{digest}"]


async def test_marker_pictures_are_served_as_cached_svg(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """A map card can load a pin picture from the integration's own folder."""
    await set_up_entry(hass)
    client = await hass_client()

    response = await client.get("/zaragoza_open_data/markers/pharmacy.svg")

    assert response.status == HTTPStatus.OK
    assert response.content_type == "image/svg+xml"
    assert "max-age" in response.headers["Cache-Control"]
    assert b"<svg" in await response.read()


async def test_unknown_marker_is_not_found(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """Only shipped pictures are served."""
    await set_up_entry(hass)
    client = await hass_client()

    response = await client.get("/zaragoza_open_data/markers/nothing.svg")

    assert response.status == HTTPStatus.NOT_FOUND


@pytest.mark.freeze_time("2026-11-09 12:40:30+00:00")
@pytest.mark.usefixtures("in_zaragoza", "home_in_zaragoza")
async def test_map_pins_name_their_picture_by_contents(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A pin's picture URL carries the hash of the file served at it.

    The pictures are cached for a month: a marker that changes must reach phones
    that already have the old one, which only a new URL does.
    """
    serve_road_works(aioclient_mock)
    serve_pharmacies(aioclient_mock)
    serve_air_stations(aioclient_mock)
    await set_up_entry(hass, {"kinds": ["road_works", "pharmacies", "air_quality"]})
    client = await hass_client()

    pins = {
        "road work": next(
            iter(geo_events(hass, "zaragoza_open_data_road_works").values())
        ),
        "pharmacy": next(
            iter(geo_events(hass, "zaragoza_open_data_pharmacies").values())
        ),
        "air station": next(
            iter(geo_events(hass, "zaragoza_open_data_air_quality").values())
        ),
        "air index": state_of(hass, "sensor", "air_quality_index"),
    }
    for pin, state in pins.items():
        url = str(state.attributes["entity_picture"])
        match = re.fullmatch(
            r"(/zaragoza_open_data/markers/\w+\.svg)\?v=([0-9a-f]{8})", url
        )
        assert match, f"{pin}: {url}"
        response = await client.get(url)
        assert response.status == HTTPStatus.OK, pin
        served = await response.read()
        assert hashlib.sha256(served).hexdigest()[:8] == match[2], pin
        # Still the same file, cached, when asked for without the version.
        assert (await client.get(match[1])).status == HTTPStatus.OK
