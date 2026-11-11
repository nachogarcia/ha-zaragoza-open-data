"""Architecture rule: every language ships the same translation keys."""

import json
from pathlib import Path

TRANSLATIONS = (
    Path(__file__).parents[2]
    / "custom_components"
    / "zaragoza_open_data"
    / "translations"
)


def _flatten(node: object, prefix: str = "") -> set[str]:
    """Return the dotted paths of every leaf in a nested JSON value."""
    if isinstance(node, dict):
        keys: set[str] = set()
        for key, value in node.items():
            keys |= _flatten(value, f"{prefix}.{key}" if prefix else key)
        return keys
    return {prefix}


def test_languages_have_identical_keys() -> None:
    """English and Spanish translations expose exactly the same keys."""
    english = _flatten(json.loads((TRANSLATIONS / "en.json").read_text("utf-8")))
    spanish = _flatten(json.loads((TRANSLATIONS / "es.json").read_text("utf-8")))

    assert english, "en.json must not be empty"
    assert english == spanish


CARD_TRANSLATIONS = Path(__file__).parents[2] / "frontend" / "src" / "translations"
NAME = json.loads((TRANSLATIONS.parent / "manifest.json").read_text("utf-8"))["name"]


def _texts(node: object) -> list[str]:
    """Return every text in a nested JSON value."""
    if isinstance(node, dict):
        return [text for value in node.values() for text in _texts(value)]
    return [node] if isinstance(node, str) else []


def test_the_name_is_the_same_in_every_language() -> None:
    """The integration and its card are "Zaragoza Open Data", a name, in each language.

    Texts that name it use that name, never a translation of it.
    """
    for language in ("en", "es"):
        integration = json.loads((TRANSLATIONS / f"{language}.json").read_text("utf-8"))
        card = json.loads((CARD_TRANSLATIONS / f"{language}.json").read_text("utf-8"))

        assert integration["title"] == NAME == "Zaragoza Open Data"
        assert card["card.name"] == NAME
        translated = [
            text
            for text in _texts(integration) + _texts(card)
            if "Datos Abiertos" in text or "Open data" in text
        ]
        assert translated == [], language
