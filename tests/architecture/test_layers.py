"""Architecture rule: ``api/`` is plain Python and knows nothing of Home Assistant."""

import ast
from pathlib import Path

import pytest

API = Path(__file__).parents[2] / "custom_components" / "zaragoza_open_data" / "api"
PACKAGE = "custom_components"


def _violations(path: Path) -> list[str]:
    """List imports in one file that break the ``api/`` layer rule."""
    return _source_violations(
        path.read_text("utf-8"), path.name, path.relative_to(API).parent.parts
    )


def _source_violations(source: str, name: str, package: tuple[str, ...]) -> list[str]:
    """List layer-breaking imports in ``source``, a module living in ``package``."""
    problems: list[str] = []
    for node in ast.walk(ast.parse(source, filename=name)):
        if isinstance(node, ast.Import):
            problems.extend(
                f"{name}: import {alias.name}"
                for alias in node.names
                if alias.name.split(".")[0] in {"homeassistant", PACKAGE}
            )
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if (node.module or "").split(".")[0] in {"homeassistant", PACKAGE}:
                    problems.append(f"{name}: from {node.module}")
            elif node.level - 1 > len(package):
                # Each extra dot climbs one package; past ``api`` leaves the layer.
                problems.append(f"{name}: relative import leaves api/")
    return problems


def test_api_directory_exists() -> None:
    """The layer under test is present, so the checks below never pass vacuously."""
    assert (API / "models.py").is_file()


@pytest.mark.parametrize(
    "source",
    [
        "import homeassistant",
        "from homeassistant.core import HomeAssistant",
        "from custom_components.zaragoza_open_data.const import DOMAIN",
        "import custom_components.zaragoza_open_data",
        "from .. import const",
    ],
)
def test_checker_flags_violations(source: str) -> None:
    """The checker reports each kind of forbidden import."""
    assert _source_violations(source, "x.py", ()) != []


def test_checker_allows_imports_inside_api() -> None:
    """Relative imports that stay in ``api/`` and the standard library are fine."""
    source = "from .models import Stop\nfrom ..errors import X\nimport json"

    assert _source_violations(source, "x.py", ("adapters",)) == []


def test_api_imports_no_home_assistant() -> None:
    """Nothing under ``api/`` imports Home Assistant or anything outside ``api/``."""
    problems = [
        problem for path in sorted(API.rglob("*.py")) for problem in _violations(path)
    ]

    assert problems == []
