"""Ranking, typed-code resolution and picker labels for stops and Bizi stations."""

from custom_components.zaragoza_open_data.api.models import (
    BikeStation,
    GeoPoint,
    Mode,
    StationCode,
    Stop,
    StopCode,
)
from custom_components.zaragoza_open_data.search import fold, label, rank, resolve_typed

ORIGIN = GeoPoint(41.65, -0.88)
# About 111 m per 0.001 degrees of latitude.
NEAR = GeoPoint(41.651, -0.88)
MIDDLE = GeoPoint(41.655, -0.88)
FAR = GeoPoint(41.67, -0.88)


def bus(code: str, name: str, location: GeoPoint, lines: tuple[str, ...] = ()) -> Stop:
    """Build a bus stop."""
    return Stop(Mode.BUS, StopCode(code), name, location, None, lines)


PILAR = bus("688", "Plaza del Pilar - Murallas", MIDDLE, ("58",))
REYES = bus("101", "P. Reyes de Aragón N.º 24", NEAR, ("58", "51"))
OTHER = bus("1688", "Calle Alfonso", FAR, ("35",))


def codes(ranked: list[tuple[Stop, float]]) -> list[str]:
    """List the codes in ranked order."""
    return [item.code for item, _ in ranked]


def test_fold_removes_accents_and_case() -> None:
    """Folding removes accents and case."""
    assert fold("Plaza del Pilar") == fold("PLAZA DEL PILAR") == "plaza del pilar"
    assert fold("Reyes de Aragón") == "reyes de aragon"
    assert "pilar" in fold("Plaza del Pilar")


def test_query_matches_all_terms_anywhere() -> None:
    """Every query word must appear somewhere in the search terms."""
    ranked = rank([PILAR, REYES, OTHER], ORIGIN, "pilar mur")

    assert codes(ranked) == ["688"]


def test_query_ignores_accents_and_matches_line_and_street() -> None:
    """A query ignores accents and matches lines and streets."""
    assert codes(rank([PILAR, REYES, OTHER], ORIGIN, "aragon")) == ["101"]
    assert codes(rank([PILAR, REYES, OTHER], ORIGIN, "51")) == ["101"]


def test_query_with_a_term_that_matches_nothing_finds_nothing() -> None:
    """One query word that matches nothing leaves no results."""
    assert rank([PILAR, REYES], ORIGIN, "pilar zzz") == []


def test_exact_code_first() -> None:
    """An exact code match comes first, ahead of nearer text matches."""
    nearer_text_match = bus("1", "Parada 688 norte", NEAR)

    ranked = rank([nearer_text_match, OTHER, PILAR], ORIGIN, "688")

    assert codes(ranked) == ["688", "1", "1688"]


def tram(code: str, name: str, location: GeoPoint, direction: str | None) -> Stop:
    """Build a tram platform; ``direction`` None is an arrival-only platform."""
    return Stop(Mode.TRAM, StopCode(code), name, location, direction, ("L1",))


def test_name_or_code_matches_come_before_direction_or_line_matches() -> None:
    """Text found in a name or code ranks ahead of text found only elsewhere.

    Within each group the nearest come first, and words may be split between
    the name and the code.
    """
    heading_there_near = tram("1401", "Gran Via", NEAR, "Mago de Oz")
    heading_there_far = tram("1311", "Plaza Aragon", MIDDLE, "Mago de Oz")
    departing = tram(
        "2502", "Mago de Oz", GeoPoint(41.671, -0.88), "Avenida de la Academia"
    )
    arrivals = tram("2501", "Mago de Oz", FAR, None)
    platforms = [heading_there_far, departing, heading_there_near, arrivals]

    assert codes(rank(platforms, ORIGIN, "Mago de Oz")) == [
        "2501",
        "2502",
        "1401",
        "1311",
    ]
    assert codes(rank(platforms, ORIGIN, "oz 2502")) == ["2502"]
    # A line is not a name: L1 is on every platform, so distance decides.
    assert codes(rank(platforms, ORIGIN, "l1")) == ["1401", "1311", "2501", "2502"]


def test_sorted_by_distance_without_query() -> None:
    """Without a query, items come nearest first with their distances."""
    ranked = rank([OTHER, PILAR, REYES], ORIGIN)

    assert codes(ranked) == ["101", "688", "1688"]
    distances = [distance for _, distance in ranked]
    assert distances == sorted(distances)
    assert 100 < distances[0] < 125


def test_blank_query_is_the_same_as_none() -> None:
    """A blank query ranks like no query at all."""
    assert codes(rank([OTHER, REYES], ORIGIN, "   ")) == ["101", "1688"]


def test_limit_keeps_the_nearest() -> None:
    """A limit keeps the nearest items."""
    assert codes(rank([OTHER, PILAR, REYES], ORIGIN, limit=2)) == ["101", "688"]


def test_bike_stations_are_found_by_address() -> None:
    """Bike stations are found by address and by number."""
    rosales = BikeStation(
        StationCode("164"), "Rosales: Illueca", NEAR, 20, "Calle Rosales 4", "gbfs"
    )
    other = BikeStation(StationCode("7"), "Plaza Aragón", FAR, None, None, "gbfs")

    assert [s.code for s, _ in rank([other, rosales], ORIGIN, "rosales 4")] == ["164"]
    assert [s.code for s, _ in rank([other, rosales], ORIGIN, "164")] == ["164"]


def test_resolve_typed_exact_code_only() -> None:
    """Typed text resolves only to an exact code, surrounding spaces ignored."""
    items = [PILAR, REYES, OTHER]

    assert resolve_typed(items, " 688 ") == PILAR
    assert resolve_typed(items, "68") is None
    assert resolve_typed(items, "pilar") is None
    assert resolve_typed(items, "") is None


def test_labels_in_both_languages() -> None:
    """Labels read naturally in Spanish and in English."""
    tram = Stop(
        Mode.TRAM,
        StopCode("2502"),
        "Mago de Oz",
        NEAR,
        "Avenida de la Academia",
        (),
    )
    arrivals_only = Stop(Mode.TRAM, StopCode("2501"), "Mago de Oz", NEAR, None, ())
    one_line = bus("688", "P. Reyes de Aragón N.º 24", NEAR, ("58",))
    bike = BikeStation(StationCode("164"), "Rosales: Illueca", NEAR, 20, None, "gbfs")

    assert label(tram, 120, "es") == "Mago de Oz → Avenida de la Academia · 120 m"
    assert label(arrivals_only, 120, "es") == "Mago de Oz (llegadas) · 120 m"
    assert label(arrivals_only, 120, "en") == "Mago de Oz (arrivals) · 120 m"
    assert (
        label(one_line, 300, "es-ES")
        == "688 · P. Reyes de Aragón N.º 24 · línea 58 · 300 m"
    )
    assert (
        label(one_line, 300, "en-GB")
        == "688 · P. Reyes de Aragón N.º 24 · line 58 · 300 m"
    )
    assert (
        label(REYES, 300, "es")
        == "101 · P. Reyes de Aragón N.º 24 · líneas 58, 51 · 300 m"
    )
    assert (
        label(REYES, 300, "en")
        == "101 · P. Reyes de Aragón N.º 24 · lines 58, 51 · 300 m"
    )
    assert label(bike, 450, "es") == "164 · Rosales: Illueca · 450 m"


def test_label_without_lines_omits_them() -> None:
    """A stop without listed lines has no lines part in its label."""
    assert (
        label(bus("5", "Calle Alfonso", NEAR), 80, "en") == "5 · Calle Alfonso · 80 m"
    )


def test_label_without_distance_names_a_saved_stop() -> None:
    """With no distance, a label is the saved stop's title: everything but metres."""
    tram = Stop(
        Mode.TRAM, StopCode("2502"), "Mago de Oz", NEAR, "Avenida de la Academia", ()
    )
    bike = BikeStation(
        StationCode("164"), "Rosales: Illueca", NEAR, None, None, "zaragoza_city"
    )

    assert label(tram, None, "es") == "Mago de Oz → Avenida de la Academia"
    assert label(REYES, None, "es") == "101 · P. Reyes de Aragón N.º 24 · líneas 58, 51"
    assert label(bike, None, "en") == "164 · Rosales: Illueca"


def test_label_distance_formatting_per_language() -> None:
    """Distances show metres below 1 km and the language's decimal mark above."""
    bike = BikeStation(
        StationCode("164"), "Rosales: Illueca", NEAR, None, None, "zaragoza_city"
    )

    assert label(bike, 1234, "es") == "164 · Rosales: Illueca · 1,2 km"
    assert label(bike, 1234, "en") == "164 · Rosales: Illueca · 1.2 km"
    assert label(bike, 999.4, "en") == "164 · Rosales: Illueca · 999 m"
    assert label(bike, 1000, "en") == "164 · Rosales: Illueca · 1.0 km"
