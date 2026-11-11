"""Name tidying, Madrid time and the typed JSON readers."""

from datetime import UTC, datetime

import pytest

from custom_components.zaragoza_open_data.api.adapters.json import (
    obj_list,
    opt_int,
    opt_str,
    point,
    req_bool,
    req_float,
    req_id,
    req_int,
    req_obj,
    req_str,
)
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.names import (
    clean,
    clean_or_none,
    madrid,
    tidy,
)
from custom_components.zaragoza_open_data.api.errors import SourceUnavailableError
from custom_components.zaragoza_open_data.api.models import GeoPoint

SOURCE = "zaragoza_city"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("MAGO DE OZ", "Mago de Oz"),
        ("PLAZA DEL PILAR - MURALLAS", "Plaza del Pilar - Murallas"),
        ("AVENIDA DE LA ACADEMIA", "Avenida de la Academia"),
        ("JESÚS GRACIA\t4\t", "Jesús Gracia 4"),
        ("DE LA ROSA", "De la Rosa"),
        ("calle  del\r\nsol", "Calle del Sol"),
    ],
)
def test_tidy(raw: str, expected: str) -> None:
    """Tidy."""
    assert tidy(raw) == expected


def test_madrid_returns_aware_local_time() -> None:
    """Madrid returns aware local time."""
    parsed = madrid("2026-11-09T11:58:01")

    assert parsed == datetime(2026, 11, 9, 10, 58, 1, tzinfo=UTC)
    assert parsed.utcoffset() is not None


def test_madrid_applies_summer_time() -> None:
    """Madrid applies summer time."""
    assert madrid("2026-07-01T12:00:00") == datetime(2026, 7, 1, 10, 0, tzinfo=UTC)


def test_json_readers_return_typed_values() -> None:
    """Json readers return typed values."""
    obj = {
        "s": "x",
        "i": 3,
        "f": "0.11",
        "n": 2,
        "b": True,
        "o": {"k": 1},
        "none": None,
    }

    assert req_str(obj, "s", SOURCE) == "x"
    assert opt_str(obj, "s", SOURCE) == "x"
    assert opt_str(obj, "none", SOURCE) is None
    assert opt_str(obj, "missing", SOURCE) is None
    assert req_int(obj, "i", SOURCE) == 3
    assert opt_int(obj, "i", SOURCE) == 3
    assert opt_int(obj, "missing", SOURCE) is None
    assert req_float(obj, "f", SOURCE) == pytest.approx(0.11)
    assert req_float(obj, "n", SOURCE) == 2.0
    assert req_bool(obj, "b", SOURCE) is True
    assert req_obj(obj, "o", SOURCE) == {"k": 1}


@pytest.mark.parametrize(
    "call",
    [
        lambda: req_int({"a": "x"}, "a", SOURCE),
        lambda: req_int({"a": True}, "a", SOURCE),
        lambda: req_int({}, "a", SOURCE),
        lambda: req_str({"a": 1}, "a", SOURCE),
        lambda: opt_str({"a": 1}, "a", SOURCE),
        lambda: opt_int({"a": "1"}, "a", SOURCE),
        lambda: req_float({"a": "abc"}, "a", SOURCE),
        lambda: req_float({"a": True}, "a", SOURCE),
        lambda: req_bool({"a": 1}, "a", SOURCE),
        lambda: req_obj({"a": []}, "a", SOURCE),
        lambda: obj_list({"a": {}}, "a", SOURCE),
        lambda: obj_list({"a": [1]}, "a", SOURCE),
        lambda: point({"geometry": {"coordinates": [1.0]}}, SOURCE),
        lambda: point({"geometry": {"coordinates": ["a", "b"]}}, SOURCE),
        lambda: point({}, SOURCE),
    ],
)
def test_json_readers_reject_wrong_types(call: object) -> None:
    """Json readers reject wrong types."""
    assert callable(call)
    with pytest.raises(SourceUnavailableError) as raised:
        call()

    assert raised.value.source == SOURCE


def test_obj_list_of_missing_key_is_empty() -> None:
    """Obj list of missing key is empty."""
    assert obj_list({}, "destinos", SOURCE) == []


def test_obj_list_returns_objects() -> None:
    """Obj list returns objects."""
    assert obj_list({"destinos": [{"a": 1}, {"a": 2}]}, "destinos", SOURCE) == [
        {"a": 1},
        {"a": 2},
    ]


def test_point_swaps_geojson_lon_lat() -> None:
    """Point swaps geojson lon lat."""
    feature = {"geometry": {"type": "Point", "coordinates": [-0.9072, 41.627]}}

    assert point(feature, SOURCE) == GeoPoint(latitude=41.627, longitude=-0.9072)


def test_madrid_rejects_malformed_timestamp_as_source_unavailable() -> None:
    """Madrid rejects malformed timestamp as source unavailable."""
    with pytest.raises(SourceUnavailableError) as raised:
        madrid("soon")

    assert raised.value.source == SOURCE


def test_clean_keeps_case_and_drops_stray_whitespace() -> None:
    """Clean keeps case and drops stray whitespace."""
    assert clean("  Corte\tde\r\n  CALLE  ") == "Corte de CALLE"
    assert clean_or_none(" \t\r\n") is None
    assert clean_or_none(None) is None
    assert clean_or_none(" a ") == "a"


def test_req_id_reads_integers_and_strings_as_text() -> None:
    """Req id reads integers and strings as text."""
    assert req_id({"id": 25688}, "id", SOURCE) == "25688"
    assert req_id({"id": "25688"}, "id", SOURCE) == "25688"


@pytest.mark.parametrize("value", [None, True, 1.5, ["1"]])
def test_req_id_rejects_other_shapes(value: object) -> None:
    """Req id rejects other shapes."""
    with pytest.raises(SourceUnavailableError):
        req_id({"id": value}, "id", SOURCE)
