"""Draw the integration's icon: a tram above a bicycle on a teal tile.

Original artwork, generic shapes only (no city logo). Writes ``brand/icon.png``
(256 px) and ``brand/icon@2x.png`` (512 px) into the integration:
``uv run python scripts/build_brand.py``. Pillow comes with Home Assistant in the
development environment.
"""

from pathlib import Path

from PIL import Image, ImageDraw

BRAND = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "zaragoza_open_data"
    / "brand"
)
# Shapes are laid out on a 512-unit grid, drawn at four times the output size and
# scaled down, which smooths every edge.
GRID = 512
SUPERSAMPLE = 4
TILE = (14, 124, 134, 255)
WHITE = (255, 255, 255, 255)

type Point = tuple[float, float]


class Pen:
    """Draws on the grid, scaled to the canvas."""

    def __init__(self, image: Image.Image) -> None:
        """Draw on ``image``, whose side maps to the whole grid."""
        self._draw = ImageDraw.Draw(image)
        self._scale = image.width / GRID

    def _at(self, point: Point) -> tuple[float, float]:
        return (point[0] * self._scale, point[1] * self._scale)

    def _box(self, left: float, top: float, right: float, bottom: float) -> list[float]:
        return [value * self._scale for value in (left, top, right, bottom)]

    def tile(self, radius: float) -> None:
        """Fill the canvas with a rounded square."""
        self._draw.rounded_rectangle(
            self._box(0, 0, GRID - 1, GRID - 1), radius * self._scale, fill=TILE
        )

    def block(
        self,
        box: tuple[float, float, float, float],
        radius: float,
        colour: tuple[int, ...],
    ) -> None:
        """Fill a rounded rectangle."""
        self._draw.rounded_rectangle(self._box(*box), radius * self._scale, fill=colour)

    def dot(self, centre: Point, radius: float) -> None:
        """Fill a white circle."""
        x, y = centre
        self._draw.ellipse(
            self._box(x - radius, y - radius, x + radius, y + radius), fill=WHITE
        )

    def ring(self, centre: Point, radius: float, width: float) -> None:
        """Draw a white circle outline."""
        x, y = centre
        self._draw.ellipse(
            self._box(x - radius, y - radius, x + radius, y + radius),
            outline=WHITE,
            width=round(width * self._scale),
        )

    def stroke(self, points: list[Point], width: float) -> None:
        """Draw a white line through ``points`` with round ends and joints."""
        self._draw.line(
            [self._at(point) for point in points],
            fill=WHITE,
            width=round(width * self._scale),
            joint="curve",
        )
        for point in points:
            self.dot(point, width / 2)


def draw_icon(size: int) -> Image.Image:
    """Return the icon at ``size`` pixels square."""
    canvas = Image.new("RGBA", (size * SUPERSAMPLE, size * SUPERSAMPLE), (0, 0, 0, 0))
    pen = Pen(canvas)
    pen.tile(radius=104)
    # Tram: pantograph, body with four windows, wheels on the rail.
    pen.stroke([(214, 104), (256, 64), (298, 104)], width=12)
    pen.stroke([(226, 64), (286, 64)], width=12)
    pen.block((84, 100, 428, 250), radius=40, colour=WHITE)
    for left in (112, 188, 264, 340):
        pen.block((left, 128, left + 60, 188), radius=12, colour=TILE)
    pen.dot((150, 254), radius=20)
    pen.dot((362, 254), radius=20)
    pen.stroke([(64, 276), (448, 276)], width=12)
    # Bicycle: wheels, frame, saddle and handlebar.
    rear, crank, front = (168.0, 392.0), (252.0, 392.0), (344.0, 392.0)
    seat, head = (230.0, 324.0), (322.0, 324.0)
    pen.ring(rear, radius=56, width=14)
    pen.ring(front, radius=56, width=14)
    pen.stroke([rear, crank, seat, rear], width=14)
    pen.stroke([seat, head, crank], width=14)
    pen.stroke([head, front], width=14)
    pen.stroke([(208, 314), (252, 314)], width=14)
    pen.stroke([head, (314, 300), (342, 300)], width=14)
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    """Write both icon sizes."""
    BRAND.mkdir(exist_ok=True)
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        draw_icon(size).save(BRAND / name, optimize=True)
        print(f"Wrote {BRAND / name}")


if __name__ == "__main__":
    main()
