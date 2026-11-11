"""The "Directions" link: Google Maps' route preview to a place.

Without ``travelmode`` (the traveller picks walking or driving) and without
``dir_action`` (a preview, not a trip started on its own). On phones with the
Google Maps app it opens there.
"""

from .api.models import GeoPoint

ATTR_DIRECTIONS = "directions"


def directions_url(location: GeoPoint) -> str:
    """Return the link to the route to ``location``, to 6 decimals (about 10 cm)."""
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&destination={location.latitude:.6f},{location.longitude:.6f}"
    )
