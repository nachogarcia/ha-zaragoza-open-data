"""Map markers: which picture each category and air band gets, and the files behind them."""

import logging
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from custom_components.zaragoza_open_data.api.air_index import AirQualityBand
from custom_components.zaragoza_open_data.api.models import RoadWorkCategory
from custom_components.zaragoza_open_data.markers import (
    air_marker,
    async_load_digests,
    marker_for,
    marker_url,
)
from homeassistant.core import HomeAssistant
from scripts.build_markers import MARKER_SPECS, compose

MARKERS = (
    Path(__file__).parents[2] / "custom_components" / "zaragoza_open_data" / "markers"
)
SVG = "{http://www.w3.org/2000/svg}"
# The pharmacy marker: a Greek cross 58 units across, centred in the 64 square,
# its arms a third of that (19.33).
GREEK_CROSS = (
    "22.33,3.00 41.67,3.00 41.67,22.33 61.00,22.33 61.00,41.67 41.67,41.67 "
    "41.67,61.00 22.33,61.00 22.33,41.67 3.00,41.67 3.00,22.33 22.33,22.33"
)
PHARMACY_GREEN = "#2E9E44"
# The air stations' pictogram, our own: four filled dots of different sizes in a
# 24 square, placed at (12, 12) and 40 wide inside the disc.
PARTICLES = [
    ("9", "9", "4.6"),
    ("17.2", "13.4", "3.2"),
    ("9.6", "18.6", "2.4"),
    ("18", "6", "1.7"),
]
DARK_INK = "#1c1c1c"
# The ink on each air disc: dark on the bright ones, white on the others.
AIR_INK = {
    "air_good": DARK_INK,
    "air_fair": DARK_INK,
    "air_moderate": DARK_INK,
    "air_poor": "#FFFFFF",
    "air_very_poor": "#FFFFFF",
    "air_extremely_poor": "#FFFFFF",
    "air_no_data": "#FFFFFF",
}

ROAD_WORK_MARKERS = {
    RoadWorkCategory.TRAFFIC_CLOSURE: "road_closed",
    RoadWorkCategory.MAINTENANCE: "works",
    RoadWorkCategory.MAJOR_DISRUPTION: "major_disruption",
    RoadWorkCategory.PUBLIC_TRANSPORT_DISRUPTION: "transit_disruption",
    RoadWorkCategory.WATER_CUT: "water_cut",
    RoadWorkCategory.OTHER: "road_other",
}
AIR_MARKERS = {
    AirQualityBand.GOOD: "air_good",
    AirQualityBand.FAIR: "air_fair",
    AirQualityBand.MODERATE: "air_moderate",
    AirQualityBand.POOR: "air_poor",
    AirQualityBand.VERY_POOR: "air_very_poor",
    AirQualityBand.EXTREMELY_POOR: "air_extremely_poor",
}
ALL_NAMES = [
    *ROAD_WORK_MARKERS.values(),
    "pharmacy",
    "tram_stop",
    "bus_stop",
    *AIR_MARKERS.values(),
    "air_no_data",
]


@pytest.mark.parametrize(("category", "name"), ROAD_WORK_MARKERS.items())
def test_every_road_work_category_has_its_marker(
    category: RoadWorkCategory, name: str
) -> None:
    """Each kind of road work gets the picture the README's legend gives it."""
    assert marker_for(category) == name


def test_every_road_work_category_is_covered() -> None:
    """A category added later can't be left without a picture."""
    assert set(ROAD_WORK_MARKERS) == set(RoadWorkCategory)
    assert {marker_for(category) for category in RoadWorkCategory} <= set(ALL_NAMES)


@pytest.mark.parametrize(("band", "name"), AIR_MARKERS.items())
def test_every_air_band_has_its_marker(band: AirQualityBand, name: str) -> None:
    """An air station's picture follows its index band."""
    assert air_marker(band) == name


def test_air_marker_without_a_band_is_the_no_data_picture() -> None:
    """A station with no usable readings is grey."""
    assert air_marker(None) == "air_no_data"


@pytest.mark.parametrize("name", ALL_NAMES)
def test_every_marker_name_has_a_valid_64_pixel_svg(name: str) -> None:
    """Each name has a file that parses as SVG with a 64 by 64 viewBox."""
    root = ET.parse(MARKERS / f"{name}.svg").getroot()  # noqa: S314 our own files

    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.get("viewBox") == "0 0 64 64"
    assert (root.get("width"), root.get("height")) == ("64", "64")


def test_markers_folder_holds_only_named_markers() -> None:
    """No stray picture ships that nothing refers to."""
    assert sorted(path.stem for path in MARKERS.glob("*.svg")) == sorted(ALL_NAMES)


@pytest.mark.parametrize("name", ALL_NAMES)
def test_every_shipped_marker_is_what_the_build_makes(name: str) -> None:
    """The committed files are the build's output: a rebuild changes nothing."""
    assert (MARKERS / f"{name}.svg").read_text("utf-8") == compose(MARKER_SPECS[name])


def pharmacy_marker() -> ET.Element:
    """Return the shipped pharmacy marker's root element."""
    return ET.parse(MARKERS / "pharmacy.svg").getroot()  # noqa: S314 our own file


def test_pharmacy_marker_is_the_green_greek_cross_of_spanish_pharmacies() -> None:
    """The sign on every Spanish pharmacy: a green Greek cross with a white edge."""
    (cross,) = list(pharmacy_marker())

    assert cross.tag == f"{SVG}polygon"
    assert cross.get("points") == GREEK_CROSS
    assert cross.get("fill") == PHARMACY_GREEN
    assert (
        cross.get("stroke"),
        cross.get("stroke-width"),
        cross.get("stroke-linejoin"),
    ) == ("#FFFFFF", "4", "round")


def test_pharmacy_marker_draws_everything_itself() -> None:
    """No embedded picture and no link: nothing third-party, nothing to fetch."""
    for element in pharmacy_marker().iter():
        assert element.tag not in {f"{SVG}image", f"{SVG}use"}
        for attribute, value in element.attrib.items():
            assert not attribute.endswith("href")
            assert "url(" not in value


def test_pharmacy_marker_is_green_and_never_red() -> None:
    """Never a red cross: that is a protected emblem."""
    colours = {
        value
        for element in pharmacy_marker().iter()
        for attribute in ("fill", "stroke")
        if (value := element.get(attribute)) is not None
    }

    assert PHARMACY_GREEN in colours
    for colour in colours:
        red, green, blue = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
        assert not (red > green and red > blue), colour


@pytest.mark.parametrize(("name", "ink"), AIR_INK.items())
def test_air_markers_draw_four_particles_and_nothing_else(name: str, ink: str) -> None:
    """Every air pin, no data included, shows our own four dots, drawn here."""
    root = ET.parse(MARKERS / f"{name}.svg").getroot()  # noqa: S314 our own file

    disc, pictogram = list(root)
    assert disc.tag == f"{SVG}circle"
    assert pictogram.tag == f"{SVG}svg"
    assert pictogram.get("viewBox") == "0 0 24 24"
    assert [pictogram.get(side) for side in ("x", "y", "width", "height")] == [
        "12",
        "12",
        "40",
        "40",
    ]
    assert pictogram.get("fill") == ink
    assert [
        (dot.tag, dot.get("cx"), dot.get("cy"), dot.get("r")) for dot in pictogram
    ] == [(f"{SVG}circle", *dot) for dot in PARTICLES]
    for element in root.iter():
        assert element.tag not in {f"{SVG}image", f"{SVG}use", f"{SVG}path"}
        for attribute, value in element.attrib.items():
            assert not attribute.endswith("href")
            assert "url(" not in value


async def test_marker_without_a_digest_has_its_plain_url(
    hass: HomeAssistant, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A marker the files read didn't include gets its URL without a version."""
    (tmp_path / "works.svg").write_text("<svg/>", "utf-8")
    await async_load_digests(hass, tmp_path)

    assert marker_url(hass, "works").startswith(
        "/zaragoza_open_data/markers/works.svg?v="
    )
    assert marker_url(hass, "pharmacy") == "/zaragoza_open_data/markers/pharmacy.svg"
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


async def test_markers_without_digests_have_plain_urls_and_one_warning(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """With no digests read at all, every URL is plain, and the log says so once."""
    assert marker_url(hass, "works") == "/zaragoza_open_data/markers/works.svg"
    assert marker_url(hass, "pharmacy") == "/zaragoza_open_data/markers/pharmacy.svg"

    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING
    ]
    assert warnings == [
        "The map pictures' files weren't read: their URLs carry no version, "
        "so phones may show old pictures"
    ]
