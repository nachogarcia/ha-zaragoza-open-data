"""Typed readers for raw provider JSON.

Adapters never index raw JSON directly: a missing key or a wrong type is the provider
changing its shape, which is reported as ``SourceUnavailableError``.
"""

from collections.abc import Mapping

from ..errors import SourceUnavailableError
from ..models import GeoPoint, JsonObject


def req_str(obj: JsonObject, key: str, source: str) -> str:
    """Return a required string."""
    value = obj.get(key)
    if not isinstance(value, str):
        raise SourceUnavailableError(source)
    return value


def opt_str(obj: JsonObject, key: str, source: str) -> str | None:
    """Return a string, or None when the key is absent or null."""
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SourceUnavailableError(source)
    return value


def req_id(obj: JsonObject, key: str, source: str) -> str:
    """Return an identifier that arrives as an integer or a string, as a string."""
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise SourceUnavailableError(source)
    return str(value)


def req_int(obj: JsonObject, key: str, source: str) -> int:
    """Return a required integer (a boolean is not one)."""
    value = obj.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise SourceUnavailableError(source)
    return value


def opt_int(obj: JsonObject, key: str, source: str) -> int | None:
    """Return an integer, or None when the key is absent or null."""
    if obj.get(key) is None:
        return None
    return req_int(obj, key, source)


def req_float(obj: JsonObject, key: str, source: str) -> float:
    """Return a required number; numeric strings such as ``"0.11"`` are accepted."""
    value = obj.get(key)
    if isinstance(value, bool):
        raise SourceUnavailableError(source)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            raise SourceUnavailableError(source) from None
    raise SourceUnavailableError(source)


def req_bool(obj: JsonObject, key: str, source: str) -> bool:
    """Return a required boolean."""
    value = obj.get(key)
    if not isinstance(value, bool):
        raise SourceUnavailableError(source)
    return value


def req_obj(obj: JsonObject, key: str, source: str) -> JsonObject:
    """Return a required nested object."""
    value = obj.get(key)
    if not isinstance(value, Mapping):
        raise SourceUnavailableError(source)
    return value


def obj_list(obj: JsonObject, key: str, source: str) -> list[JsonObject]:
    """Return a list of objects; a missing key is an empty list (e.g. ``destinos``)."""
    value = obj.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise SourceUnavailableError(source)
    items: list[JsonObject] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise SourceUnavailableError(source)
        items.append(item)
    return items


def point(obj: JsonObject, source: str) -> GeoPoint:
    """Read GeoJSON ``geometry.coordinates`` (``[lon, lat]``) as a ``GeoPoint``."""
    coordinates = req_obj(obj, "geometry", source).get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise SourceUnavailableError(source)
    longitude, latitude = coordinates[0], coordinates[1]
    if not _is_number(longitude) or not _is_number(latitude):
        raise SourceUnavailableError(source)
    return GeoPoint(latitude=float(latitude), longitude=float(longitude))


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)
