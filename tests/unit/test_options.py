"""Options and stop subentries, read back through typed objects."""

from datetime import timedelta
from types import MappingProxyType

import pytest

from custom_components.zaragoza_open_data.api.models import (
    RoadWorkCategory,
    StationCode,
    StopCode,
)
from custom_components.zaragoza_open_data.const import Kind
from custom_components.zaragoza_open_data.options import (
    MapLayerOptions,
    RefreshOptions,
    ZodOptions,
    read_bizi_station,
    read_bus_stop,
    read_stop,
    read_tram_stop,
    refresh_below_minimum,
)
from homeassistant.config_entries import ConfigSubentry

DEFAULT_REFRESH = RefreshOptions(
    tram=timedelta(seconds=60),
    bus=timedelta(seconds=60),
    bizi=timedelta(seconds=120),
    road_works=timedelta(minutes=30),
    air_quality=timedelta(minutes=30),
    pollen=timedelta(hours=6),
    pharmacies=timedelta(hours=6),
)


def subentry(subentry_type: str, data: dict[str, object]) -> ConfigSubentry:
    """A stop subentry as Home Assistant stores it."""
    return ConfigSubentry(
        data=MappingProxyType(data),
        subentry_type=subentry_type,
        title="A stop",
        unique_id=None,
    )


def test_missing_keys_give_the_defaults() -> None:
    """With nothing stored, every kind is on and every setting has its default."""
    options = ZodOptions.from_mapping({})

    assert options == ZodOptions(
        kinds=frozenset(Kind),
        road_works=MapLayerOptions(radius_km=2.0, centre_zone="zone.home"),
        pharmacies=MapLayerOptions(radius_km=0, centre_zone="zone.home"),
        road_work_categories=frozenset(RoadWorkCategory),
        air_station=None,
        refresh=DEFAULT_REFRESH,
    )


def test_options_round_trip() -> None:
    """What is stored reads back as the same options."""
    options = ZodOptions(
        kinds=frozenset({Kind.TRAM, Kind.POLLEN}),
        road_works=MapLayerOptions(radius_km=0.5, centre_zone="zone.work"),
        pharmacies=MapLayerOptions(radius_km=3.0, centre_zone="zone.home"),
        road_work_categories=frozenset({RoadWorkCategory.WATER_CUT}),
        air_station="12",
        refresh=RefreshOptions(
            tram=timedelta(seconds=90),
            bus=timedelta(seconds=120),
            bizi=timedelta(seconds=300),
            road_works=timedelta(minutes=45),
            air_quality=timedelta(minutes=60),
            pollen=timedelta(hours=12),
            pharmacies=timedelta(hours=8),
        ),
    )

    assert ZodOptions.from_mapping(options.to_mapping()) == options
    defaults = ZodOptions.from_mapping({})
    assert ZodOptions.from_mapping(defaults.to_mapping()) == defaults


def test_stored_shape_uses_plain_values_and_whole_units() -> None:
    """The entry stores lists of names, numbers and whole interval units."""
    assert ZodOptions.from_mapping({}).to_mapping() == {
        "kinds": [
            "tram",
            "bus",
            "bizi",
            "road_works",
            "pharmacies",
            "air_quality",
            "pollen",
        ],
        "road_works_radius_km": 2.0,
        "road_works_centre": "zone.home",
        "road_works_categories": [
            "traffic_closure",
            "water_cut",
            "major_disruption",
            "public_transport_disruption",
            "maintenance",
            "other",
        ],
        "pharmacies_radius_km": 0.0,
        "pharmacies_centre": "zone.home",
        "air_station": "",
        "refresh": {
            "tram_s": 60,
            "bus_s": 60,
            "bike_s": 120,
            "road_works_min": 30,
            "air_quality_min": 30,
            "pollen_h": 6,
            "pharmacies_h": 6,
        },
    }


def test_unknown_names_are_dropped_and_unreadable_values_take_the_default() -> None:
    """A value of the wrong type reads as missing; unknown names are ignored."""
    options = ZodOptions.from_mapping(
        {
            "kinds": ["tram", "teleport"],
            "road_works_categories": ["water_cut", 7],
            "road_works_radius_km": "far",
            "pharmacies_radius_km": True,
            "road_works_centre": None,
            "air_station": 12,
            "refresh": {"tram_s": "fast", "bus_s": 75, "bike_s": float("inf")},
        }
    )

    assert options.kinds == {Kind.TRAM}
    assert options.road_work_categories == {RoadWorkCategory.WATER_CUT}
    assert options.road_works == MapLayerOptions(radius_km=2.0, centre_zone="zone.home")
    assert options.pharmacies.radius_km == 0
    assert options.air_station is None
    assert options.refresh.tram == timedelta(seconds=60)
    assert options.refresh.bus == timedelta(seconds=75)
    assert options.refresh.bizi == timedelta(seconds=120)
    assert ZodOptions.from_mapping({"refresh": "often"}).refresh == DEFAULT_REFRESH


def test_stored_refresh_outside_its_range_reads_as_the_nearest_limit() -> None:
    """A stored interval below its floor reads as the floor; a huge one as the ceiling."""
    refresh = ZodOptions.from_mapping(
        {"refresh": {"tram_s": 5, "road_works_min": 1e20, "pollen_h": 1e20}}
    ).refresh

    assert refresh.tram == timedelta(seconds=60)
    assert refresh.road_works == timedelta(days=1)
    assert refresh.pollen == timedelta(days=7)


def test_refresh_faster_than_a_default_is_below_minimum() -> None:
    """Each default is also the floor: slower is allowed, faster is not."""
    assert not refresh_below_minimum({})
    assert not refresh_below_minimum({"refresh": "often"})
    assert not refresh_below_minimum({"refresh": {"tram_s": 60, "pollen_h": 24}})
    assert refresh_below_minimum({"refresh": {"tram_s": 30}})
    assert refresh_below_minimum({"refresh": {"pollen_h": 5}})


def test_stop_subentries_read_as_typed_data() -> None:
    """Each stop subentry reads as its typed data."""
    assert read_tram_stop(subentry("tram_stop", {"code": "2502"})) == {
        "code": StopCode("2502")
    }
    assert read_bus_stop(subentry("bus_stop", {"code": "688", "lines": ["58"]})) == {
        "code": StopCode("688"),
        "lines": ["58"],
    }
    assert read_bizi_station(subentry("bizi_station", {"code": "164"})) == {
        "code": StationCode("164")
    }


def test_any_stop_subentry_reads_as_its_kind_and_code() -> None:
    """Whatever its type, a stop subentry says which kind it is and its code."""
    assert read_stop(subentry("tram_stop", {"code": "2502"})) == (Kind.TRAM, "2502")
    assert read_stop(subentry("bus_stop", {"code": "688", "lines": []})) == (
        Kind.BUS,
        "688",
    )
    assert read_stop(subentry("bizi_station", {"code": "164"})) == (Kind.BIZI, "164")
    assert read_stop(subentry("ferry_stop", {"code": "1"})) is None


@pytest.mark.parametrize(
    ("reader", "data"),
    [
        (read_tram_stop, {}),
        (read_tram_stop, {"code": ""}),
        (read_bizi_station, {"code": 164}),
        (read_bus_stop, {"code": "688"}),
        (read_bus_stop, {"code": "688", "lines": "58"}),
        (read_bus_stop, {"code": "688", "lines": [58]}),
    ],
)
def test_malformed_stop_subentry_is_rejected(
    reader: object, data: dict[str, object]
) -> None:
    """A subentry without a code, or with lines that are not names, raises."""
    assert callable(reader)
    with pytest.raises(ValueError):
        reader(subentry("stop", data))
