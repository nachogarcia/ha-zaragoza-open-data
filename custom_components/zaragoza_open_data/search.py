"""Ranking and labels for the stop and station pickers and the find_stops action."""

from collections.abc import Iterable
from typing import Protocol
import unicodedata

from .api.models import BikeStation, GeoPoint, Mode, Stop

_METRES_PER_KM = 1000


class Findable(Protocol):
    """Anything the pickers can search: a stop or a Bizi station."""

    @property
    def code(self) -> str:
        """Public code, the identity users type."""
        ...

    @property
    def name(self) -> str:
        """Display name."""
        ...

    @property
    def location(self) -> GeoPoint:
        """Where it is."""
        ...

    def search_terms(self) -> tuple[str, ...]:
        """Texts a user may type to find it."""
        ...


def fold(text: str) -> str:
    """Lower-case ``text`` and strip accents, so "Aragón" matches "aragon"."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.casefold()


def rank[T: Findable](
    items: Iterable[T],
    origin: GeoPoint,
    query: str | None = None,
    limit: int | None = None,
) -> list[tuple[T, float]]:
    """Return ``(item, metres from origin)``, nearest first within three groups.

    With a query, an item stays only if every query word is part of some search
    term. The exact code comes first, then items whose code or name hold every
    word, then those found only through another term: every platform heading to
    Mago de Oz has it as its direction, and is nearer than the stop for most.
    """
    words = fold(query).split() if query else []
    typed = fold(query).strip() if query else ""
    scored: list[tuple[bool, bool, float, T]] = []
    for item in items:
        named = False
        if words:
            terms = [fold(term) for term in item.search_terms()]
            if not all(any(word in term for term in terms) for word in words):
                continue
            identity = (fold(item.code), fold(item.name))
            named = all(any(word in term for term in identity) for word in words)
        distance = origin.distance_to(item.location)
        exact = bool(typed) and fold(item.code) == typed
        scored.append((exact, named, distance, item))
    # Python sorts False before True, so negate the flags.
    scored.sort(key=lambda entry: (not entry[0], not entry[1], entry[2]))
    ranked = [(item, distance) for _, _, distance, item in scored]
    return ranked if limit is None else ranked[:limit]


def resolve_typed[T: Findable](items: Iterable[T], text: str) -> T | None:
    """Return the item whose code is exactly ``text`` (surrounding spaces ignored)."""
    code = text.strip()
    if not code:
        return None
    return next((item for item in items if item.code == code), None)


def _distance_text(distance_m: float, spanish: bool) -> str:
    if round(distance_m) < _METRES_PER_KM:
        return f"{round(distance_m)} m"
    text = f"{distance_m / _METRES_PER_KM:.1f}"
    return f"{text.replace('.', ',') if spanish else text} km"


def label(item: Stop | BikeStation, distance_m: float | None, language: str) -> str:
    """Format a picker entry; Spanish for any ``es*`` language, else English.

    Without a distance it is the title of a saved stop or station.
    """
    spanish = language.lower().startswith("es")
    parts = _describe(item, spanish)
    if distance_m is not None:
        parts.append(_distance_text(distance_m, spanish))
    return " · ".join(parts)


def _describe(item: Stop | BikeStation, spanish: bool) -> list[str]:
    """Return what identifies ``item`` to a person, before any distance."""
    if isinstance(item, BikeStation):
        return [item.code, item.name]
    if item.mode is Mode.TRAM:
        if item.direction is None:
            suffix = "llegadas" if spanish else "arrivals"
            return [f"{item.name} ({suffix})"]
        return [f"{item.name} → {item.direction}"]
    parts = [item.code, item.name]
    if item.lines:
        if spanish:
            noun = "líneas" if len(item.lines) > 1 else "línea"
        else:
            noun = "lines" if len(item.lines) > 1 else "line"
        parts.append(f"{noun} {', '.join(item.lines)}")
    return parts
