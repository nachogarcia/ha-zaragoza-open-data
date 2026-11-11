"""The picture URLs entities carry: the marker's path, versioned by its contents."""

import hashlib
from pathlib import Path

PATH = "/zaragoza_open_data/markers/"
_FOLDER = (
    Path(__file__).parents[2] / "custom_components" / "zaragoza_open_data" / "markers"
)


def picture(name: str) -> str:
    """Return the URL of marker ``name``: ``?v=`` and 8 hex of its file's SHA-256."""
    digest = hashlib.sha256((_FOLDER / f"{name}.svg").read_bytes()).hexdigest()[:8]
    return f"{PATH}{name}.svg?v={digest}"
