"""Names shared by several kinds of entity, as Home Assistant shows them."""

import pytest

from custom_components.zaragoza_open_data.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations


@pytest.mark.parametrize(
    ("language", "name"), [("en", "Directions"), ("es", "Cómo llegar")]
)
async def test_directions_attribute_has_a_name_on_every_entity_that_carries_it(
    hass: HomeAssistant, language: str, name: str
) -> None:
    """Pins, the nearest pharmacy, stops and stations show "Directions" by name."""
    translations = await async_get_translations(hass, language, "entity", [DOMAIN])

    for platform, key in (
        ("geo_location", "pharmacy"),
        ("sensor", "nearest_duty_pharmacy"),
        ("sensor", "next_arrival"),
        ("sensor", "bikes"),
    ):
        prefix = f"component.{DOMAIN}.entity.{platform}.{key}.state_attributes"
        assert translations[f"{prefix}.directions.name"] == name
