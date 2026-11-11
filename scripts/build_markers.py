"""Compose the map pin pictures from the vendored open icons, and draw our own two.

Writes one 64 by 64 SVG per marker into ``custom_components/zaragoza_open_data/markers/``:
``uv run python -m scripts.build_markers``. The outputs are committed, so the
integration ships them as they are. Road signs go in as they are; the pharmacy
marker is a Greek cross and the air markers four dots, both drawn here from their
geometry; every other marker is a pictogram on a filled disc, white or dark,
whichever reads better on the disc's colour. Where each icon comes from is in ``icon_sources/SOURCES.md``.
"""

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from custom_components.zaragoza_open_data.api.air_index import (
    BAND_COLOURS,
    NO_DATA_COLOUR,
)

SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG)
ET.register_namespace("xlink", XLINK)

SOURCES = Path(__file__).resolve().parent / "icon_sources"
MARKERS = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "zaragoza_open_data"
    / "markers"
)

SIZE = 64
RING = 2  # the white edge keeps a disc visible on a dark map
PICTOGRAM = 40  # the pictogram's side inside the disc
WHITE = "#FFFFFF"
DARK = "#1F2933"
PARTICLE_INK = "#1c1c1c"  # the dots' dark ink: it reads better than DARK on pale discs
# Air particles: four filled dots of different sizes in a 24 square (cx, cy, r),
# our own drawing, plain geometry.
PARTICLES = (
    (9, 9, 4.6),
    (17.2, 13.4, 3.2),
    (9.6, 18.6, 2.4),
    (18, 6, 1.7),
)
PARTICLES_BOX = 24
CROSS = 58  # the cross's width: its 4-wide edge stays inside the 64 square
CROSS_EDGE = 4


@dataclass(frozen=True, slots=True)
class Sign:
    """A road sign drawn as it is, scaled into the 64 pixel square."""

    source: str


@dataclass(frozen=True, slots=True)
class Disc:
    """A pictogram on a filled disc, white or dark by the disc's brightness."""

    source: str
    colour: str


@dataclass(frozen=True, slots=True)
class Cross:
    """A Greek cross with a white edge, drawn from geometry: no source file."""

    colour: str


@dataclass(frozen=True, slots=True)
class Dots:
    """The four particles on a filled disc, white or dark by the disc's brightness."""

    colour: str


type Marker = Sign | Disc | Cross | Dots

MARKER_SPECS: dict[str, Marker] = {
    "road_closed": Sign("commons-r100.svg"),
    "works": Sign("commons-p18.svg"),
    "major_disruption": Disc("maki-caution.svg", "#F28C28"),
    "transit_disruption": Disc("maki-bus.svg", "#7B3FA0"),
    "water_cut": Disc("temaki-water_shutoff.svg", "#1E88E5"),
    "road_other": Disc("maki-caution.svg", "#6F6F6F"),
    # The green cross every Spanish pharmacy shows; never red, a protected emblem.
    "pharmacy": Cross("#2E9E44"),
    "tram_stop": Disc("temaki-tram.svg", "#37474F"),
    "bus_stop": Disc("maki-bus.svg", "#37474F"),
    **{f"air_{band}": Dots(colour) for band, colour in BAND_COLOURS.items()},
    "air_no_data": Dots(NO_DATA_COLOUR),
}


def _brightness(colour: str) -> float:
    """Return the perceived brightness of ``#RRGGBB``, 0 (black) to 1 (white)."""
    red, green, blue = (int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.299 * red + 0.587 * green + 0.114 * blue


def _nested(
    source: str, x: float, y: float, side: float, ink: str | None
) -> ET.Element:
    """Return the icon file as an ``svg`` element placed in a ``side`` square at x, y."""
    root = ET.parse(SOURCES / source).getroot()  # noqa: S314 our own vendored files
    assert root is not None
    view_box = root.get("viewBox")
    if view_box is None:
        # Some files give only their size; that is then the whole drawing.
        view_box = f"0 0 {root.get('width')} {root.get('height')}"
    root.attrib.clear()
    root.set("viewBox", view_box)
    root.set("x", f"{x:g}")
    root.set("y", f"{y:g}")
    root.set("width", f"{side:g}")
    root.set("height", f"{side:g}")
    if ink is not None:
        root.set("fill", ink)
    return root


def _cross_points() -> str:
    """Return the outline of a Greek cross ``CROSS`` wide, centred, arms a third wide."""
    low = (SIZE - CROSS) / 2
    high = low + CROSS
    inner, outer = low + CROSS / 3, high - CROSS / 3
    corners = (
        (inner, low),
        (outer, low),
        (outer, inner),
        (high, inner),
        (high, outer),
        (outer, outer),
        (outer, high),
        (inner, high),
        (inner, outer),
        (low, outer),
        (low, inner),
        (inner, inner),
    )
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in corners)


def _add_disc(canvas: ET.Element, colour: str) -> None:
    """Draw the filled disc with its white edge."""
    centre = SIZE / 2
    ET.SubElement(
        canvas,
        f"{{{SVG}}}circle",
        {
            "cx": f"{centre:g}",
            "cy": f"{centre:g}",
            "r": f"{centre - RING / 2:g}",
            "fill": colour,
            "stroke": WHITE,
            "stroke-width": str(RING),
        },
    )


def _particles(disc_colour: str, offset: float) -> ET.Element:
    """Return the four dots as an ``svg`` element placed in the disc's pictogram square."""
    ink = PARTICLE_INK if _brightness(disc_colour) > 0.6 else WHITE
    box = f"{PARTICLES_BOX}"
    dots = ET.Element(
        f"{{{SVG}}}svg",
        {
            "viewBox": f"0 0 {box} {box}",
            "fill": ink,
            "x": f"{offset:g}",
            "y": f"{offset:g}",
            "width": f"{PICTOGRAM:g}",
            "height": f"{PICTOGRAM:g}",
        },
    )
    for cx, cy, radius in PARTICLES:
        ET.SubElement(
            dots,
            f"{{{SVG}}}circle",
            {"cx": f"{cx:g}", "cy": f"{cy:g}", "r": f"{radius:g}"},
        )
    return dots


def compose(marker: Marker) -> str:
    """Return the 64 by 64 SVG text of ``marker``."""
    canvas = ET.Element(
        f"{{{SVG}}}svg",
        {
            "viewBox": f"0 0 {SIZE} {SIZE}",
            "width": str(SIZE),
            "height": str(SIZE),
        },
    )
    if isinstance(marker, Sign):
        margin = 2
        canvas.append(_nested(marker.source, margin, margin, SIZE - 2 * margin, None))
    elif isinstance(marker, Cross):
        ET.SubElement(
            canvas,
            f"{{{SVG}}}polygon",
            {
                "points": _cross_points(),
                "fill": marker.colour,
                "stroke": WHITE,
                "stroke-width": str(CROSS_EDGE),
                "stroke-linejoin": "round",
            },
        )
    else:
        _add_disc(canvas, marker.colour)
        offset = (SIZE - PICTOGRAM) / 2
        if isinstance(marker, Dots):
            canvas.append(_particles(marker.colour, offset))
        else:
            ink = DARK if _brightness(marker.colour) > 0.6 else WHITE
            canvas.append(_nested(marker.source, offset, offset, PICTOGRAM, ink))
    return ET.tostring(canvas, encoding="unicode") + "\n"


def build(target: Path = MARKERS) -> list[Path]:
    """Write every marker into ``target`` and return the files."""
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, marker in MARKER_SPECS.items():
        path = target / f"{name}.svg"
        path.write_text(compose(marker), "utf-8")
        written.append(path)
    return written


def main() -> None:
    """Build the markers and say what was written."""
    for path in build():
        print(path.relative_to(MARKERS.parent.parent.parent))


if __name__ == "__main__":
    main()
