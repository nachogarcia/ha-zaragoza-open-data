"""The Google Maps directions link: one URL format for every entity that has one."""

from custom_components.zaragoza_open_data.api.models import GeoPoint
from custom_components.zaragoza_open_data.directions import directions_url


def test_directions_url_opens_the_route_preview_to_the_place() -> None:
    """Destination only: the traveller picks the mode and taps Start."""
    assert directions_url(GeoPoint(41.646146396697176, -0.8858667199718896)) == (
        "https://www.google.com/maps/dir/?api=1&destination=41.646146,-0.885867"
    )


def test_directions_url_has_six_decimals_and_keeps_negative_longitudes() -> None:
    """Coordinates are padded or rounded to 6 decimals, and the west sign stays."""
    url = directions_url(GeoPoint(41.624375626652835, -0.936450897480926))
    assert url.endswith("destination=41.624376,-0.936451")
    assert directions_url(GeoPoint(41.6, -0.9)).endswith(
        "destination=41.600000,-0.900000"
    )


def test_directions_url_leaves_out_travel_mode_and_instant_navigation() -> None:
    """The route preview, not a started trip, and no mode chosen for the user."""
    url = directions_url(GeoPoint(41.0, -0.9))
    assert "travelmode" not in url
    assert "dir_action" not in url
