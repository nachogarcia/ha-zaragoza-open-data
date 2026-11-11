"""What the actions answer: a public contract for scripts, Assist and the search card.

Every answer is built here and nowhere else. The card's ``types.ts`` declares the
same shapes, and the acceptance snapshots of these answers are its test fixtures,
so a change on either side fails a test.
"""

from collections.abc import Sequence
from datetime import datetime

from homeassistant.core import ServiceResponse
from homeassistant.util.json import JsonObjectType

from .api.models import ArrivalBoard, BikeAvailability, BikeStation, Stop
from .coordinator import local_text


def _found(item: Stop | BikeStation, distance_m: float) -> JsonObjectType:
    """Describe one search result; a Bizi station has no direction and no lines."""
    stop = item if isinstance(item, Stop) else None
    return {
        "code": item.code,
        "name": item.name,
        "direction": None if stop is None else stop.direction,
        "lines": [] if stop is None else list(stop.lines),
        "distance_m": round(distance_m),
        "latitude": item.location.latitude,
        "longitude": item.location.longitude,
    }


def find_stops_response(
    results: Sequence[tuple[Stop | BikeStation, float]],
) -> ServiceResponse:
    """Answer ``find_stops``: the stops or stations in ranked order, with distances."""
    return {"stops": [_found(item, distance) for item, distance in results]}


def arrivals_response(
    stop: Stop, board: ArrivalBoard, now: datetime
) -> ServiceResponse:
    """Answer ``get_arrivals``: who comes, in how many minutes at ``now``, and when.

    The minutes are counted as the stop's minutes sensor counts them: the source's
    own, less each whole minute since it counted. A board can be minutes old (a
    bus stop's is kept while nobody answers), so vehicles already gone are left out.
    """
    return {
        "stop": {"code": stop.code, "name": stop.name, "direction": stop.direction},
        "arrivals": [
            {
                "line": arrival.line,
                "destination": arrival.destination,
                "minutes": board.minutes_to(arrival, now),
                "time": local_text(arrival.expected_at),
            }
            for arrival in board.upcoming(now)
        ],
        "source": board.source,
        "updated": local_text(board.observed_at),
    }


def bizi_response(
    station: BikeStation, availability: BikeAvailability
) -> ServiceResponse:
    """Answer ``get_bizi_station``: bikes by type, free docks, renting and returning.

    The bike types are None while the city's list stands in: it doesn't split them.
    """
    return {
        "station": {"code": station.code, "name": station.name},
        "bikes": availability.bikes,
        "electric": availability.electric,
        "mechanical": availability.mechanical,
        "docks": availability.docks,
        "renting": availability.renting,
        "returning": availability.returning,
        "source": availability.source,
        "updated": local_text(availability.reported_at),
    }
