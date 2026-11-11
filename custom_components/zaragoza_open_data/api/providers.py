"""The one place that decides which adapter serves which port, and in what order."""

from dataclasses import dataclass

import aiohttp

from .adapters.avanza.bus import AvanzaBusArrivals
from .adapters.gbfs.bike import GbfsBike
from .adapters.zaragoza_city.air_quality import CityAirQuality
from .adapters.zaragoza_city.bike import CityBike
from .adapters.zaragoza_city.bus import CityBusArrivals, CityBusStops
from .adapters.zaragoza_city.client import CityClient
from .adapters.zaragoza_city.pharmacies import CityPharmacies
from .adapters.zaragoza_city.pollen import CityPollen
from .adapters.zaragoza_city.road_works import CityRoadWorks
from .adapters.zaragoza_city.tram import CityTram
from .fallback import FallbackBikeSource, FallbackBusArrivals, FallbackPolicy
from .ports import (
    AirQualitySource,
    BikeSource,
    BusArrivalsSource,
    BusStopCatalog,
    PharmacySource,
    PollenSource,
    RoadWorksSource,
    TramSource,
)

# The operator's feed lists every Bizi station; the city's list, its fallback, a
# varying subset of them (132, 276 and 84 at different times on 2026-11-09).
BIKE_OPERATOR = GbfsBike.source_name


@dataclass(frozen=True)
class Providers:
    """Every port, wired to its sources."""

    tram: TramSource
    bus_stops: BusStopCatalog
    bus_arrivals: BusArrivalsSource
    bike: BikeSource
    road_works: RoadWorksSource
    pharmacies: PharmacySource
    air_quality: AirQualitySource
    pollen: PollenSource


def build_providers(session: aiohttp.ClientSession, user_agent: str) -> Providers:
    """Wire the adapters: bus is Avanza then city, bikes GBFS then city, rest city."""
    city = CityClient(session, user_agent)
    return Providers(
        tram=CityTram(city),
        bus_stops=CityBusStops(city),
        bus_arrivals=FallbackBusArrivals(
            AvanzaBusArrivals(session, user_agent),
            CityBusArrivals(city),
            FallbackPolicy(),
        ),
        bike=FallbackBikeSource(
            GbfsBike(session, user_agent), CityBike(city), FallbackPolicy()
        ),
        road_works=CityRoadWorks(city),
        pharmacies=CityPharmacies(city),
        air_quality=CityAirQuality(city),
        pollen=CityPollen(city),
    )
