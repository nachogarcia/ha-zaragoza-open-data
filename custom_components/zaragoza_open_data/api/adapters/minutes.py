"""Reading the "time to arrival" text both bus providers show."""

import re

_MINUTES = re.compile(r"(\d+)\s*minutos?\.?", re.IGNORECASE)
_AT_STOP = re.compile(r"en la parada\.?", re.IGNORECASE)


def parse_minutes(text: str) -> int | None:
    """Return minutes for "N minutos." or "En la parada." (0); None for anything else."""
    text = text.strip()
    if _AT_STOP.fullmatch(text):
        return 0
    match = _MINUTES.fullmatch(text)
    return int(match.group(1)) if match else None
