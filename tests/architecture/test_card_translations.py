"""Architecture rule: the card can say every error the integration's actions raise.

Home Assistant's error message is English, so the card shows its own text for the
error's translation key: ``error.<key>`` in each of its languages.
"""

import json
from pathlib import Path
import re

import pytest

from custom_components.zaragoza_open_data.entity import attribution_for

ROOT = Path(__file__).parents[2]
INTEGRATION = (
    ROOT / "custom_components" / "zaragoza_open_data" / "translations" / "en.json"
)
CARD = ROOT / "frontend" / "src" / "translations"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _exceptions() -> dict[str, str]:
    """Return each exception's translation key and its English message."""
    translations = json.loads(INTEGRATION.read_text("utf-8"))
    return {key: value["message"] for key, value in translations["exceptions"].items()}


def _card(language: str) -> dict[str, str]:
    """Return the card's flat translations for ``language``."""
    texts: dict[str, str] = json.loads((CARD / f"{language}.json").read_text("utf-8"))
    return texts


@pytest.mark.parametrize("language", ["en", "es"])
def test_card_translates_every_exception(language: str) -> None:
    """Each exception key has an ``error.<key>`` text in the card's language."""
    exceptions = _exceptions()
    assert exceptions, "The integration declares no exceptions"
    card = _card(language)

    missing = sorted(f"error.{key}" for key in exceptions if f"error.{key}" not in card)

    assert not missing, f"{language}.json of the card lacks {', '.join(missing)}"


@pytest.mark.parametrize("language", ["en", "es"])
def test_card_errors_use_only_placeholders_the_integration_sends(language: str) -> None:
    """An error text only fills in placeholders its exception has."""
    card = _card(language)

    for key, message in _exceptions().items():
        text = card.get(f"error.{key}", "")
        unknown = set(_PLACEHOLDER.findall(text)) - set(_PLACEHOLDER.findall(message))
        assert not unknown, f"error.{key} in {language}.json uses {sorted(unknown)}"


@pytest.mark.parametrize("source", ["zaragoza_city", "avanza", "gbfs"])
def test_card_footer_names_each_source_as_the_entities_do(source: str) -> None:
    """The card's footer cites a source in the words of the entities' attribution.

    In Spanish, as the city's reuse terms suggest; English says the same.
    """
    footer = f"footer.{source}"

    assert _card("es")[footer] == attribution_for(source)
    assert _card("en")[footer].removeprefix("Data source: ") == (
        attribution_for(source) or ""
    ).removeprefix("Origen de los datos: ")
