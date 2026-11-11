"""Contract suites: what every adapter of a port must satisfy.

Each function takes the port type, so mypy also proves the adapter implements it.
Integration tests run them on recorded HTTP; the live tests run them on the real
providers.
"""

from collections.abc import Mapping
from datetime import datetime

from custom_components.zaragoza_open_data.api.models import (
    AirReading,
    AirStation,
    ArrivalBoard,
    BikeAvailability,
    BikeStation,
    DutyPharmacy,
    PollenReading,
    RoadWork,
    StationCode,
    Stop,
    StopCode,
)
from custom_components.zaragoza_open_data.api.ports import (
    AirQualitySource,
    BikeSource,
    BusArrivalsSource,
    BusStopCatalog,
    PharmacySource,
    PollenSource,
    RoadWorksSource,
    TramSource,
)


def _assert_aware(value: datetime) -> None:
    assert value.tzinfo is not None
    assert value.utcoffset() is not None


def _assert_board(board: ArrivalBoard, code: StopCode, source_name: str) -> None:
    assert isinstance(board, ArrivalBoard)
    assert board.stop_code == code
    assert board.source == source_name
    _assert_aware(board.observed_at)
    for arrival in board.arrivals:
        _assert_aware(arrival.expected_at)


def _assert_stops(stops: tuple[Stop, ...]) -> None:
    assert isinstance(stops, tuple)
    assert stops
    assert all(isinstance(stop, Stop) for stop in stops)


async def check_tram_contract(source: TramSource, known_code: StopCode) -> None:
    """Tram stops are listed and every platform has a board."""
    assert source.source_name
    stops = await source.stops()
    _assert_stops(stops)
    assert known_code in {stop.code for stop in stops}
    boards = await source.boards()
    assert isinstance(boards, Mapping)
    assert known_code in boards
    for code, board in boards.items():
        _assert_board(board, code, source.source_name)


async def check_bus_catalog_contract(
    source: BusStopCatalog, known_code: StopCode
) -> None:
    """The bus stop list contains the known stop, and each number is one stop."""
    assert source.source_name
    stops = await source.stops()
    _assert_stops(stops)
    codes = [stop.code for stop in stops]
    assert known_code in codes
    assert len(set(codes)) == len(codes)


async def check_bus_arrivals_contract(
    source: BusArrivalsSource, known_code: StopCode
) -> None:
    """A known stop yields a board for that stop, from this source."""
    board = await source.board(known_code)
    _assert_board(board, known_code, source.source_name)


async def check_bike_contract(source: BikeSource, known_code: StationCode) -> None:
    """Stations are listed and the known one has availability, both from this source."""
    assert source.source_name
    stations = await source.stations()
    assert isinstance(stations, tuple)
    assert all(isinstance(station, BikeStation) for station in stations)
    assert all(station.source == source.source_name for station in stations)
    assert known_code in {station.code for station in stations}
    availability = await source.availability()
    assert isinstance(availability, Mapping)
    assert known_code in availability
    for code, entry in availability.items():
        assert isinstance(entry, BikeAvailability)
        assert entry.code == code
        assert entry.source == source.source_name
        _assert_aware(entry.reported_at)


async def check_road_works_contract(source: RoadWorksSource) -> None:
    """Road works are typed and their dates are aware."""
    assert source.source_name
    works = await source.road_works()
    assert isinstance(works, tuple)
    for work in works:
        assert isinstance(work, RoadWork)
        for moment in (work.starts, work.ends):
            if moment is not None:
                _assert_aware(moment)


async def check_pharmacy_contract(source: PharmacySource) -> None:
    """Duty pharmacies are typed."""
    assert source.source_name
    pharmacies = await source.on_duty()
    assert isinstance(pharmacies, tuple)
    assert all(isinstance(pharmacy, DutyPharmacy) for pharmacy in pharmacies)


async def check_air_quality_contract(source: AirQualitySource) -> None:
    """The report's readings refer to its stations and have aware timestamps."""
    assert source.source_name
    stations = await source.stations()
    assert isinstance(stations, tuple)
    assert all(isinstance(station, AirStation) for station in stations)
    report = await source.report()
    assert isinstance(report.stations, tuple)
    assert all(isinstance(station, AirStation) for station in report.stations)
    readings = report.readings
    assert isinstance(readings, tuple)
    known = {station.id for station in report.stations}
    for reading in readings:
        assert isinstance(reading, AirReading)
        assert reading.station_id in known
        _assert_aware(reading.measured_at)


async def check_pollen_contract(source: PollenSource) -> None:
    """Pollen readings are typed."""
    assert source.source_name
    readings = await source.readings()
    assert isinstance(readings, tuple)
    assert all(isinstance(reading, PollenReading) for reading in readings)
