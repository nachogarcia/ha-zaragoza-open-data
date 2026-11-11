# Icon sources

Every file here is vendored unchanged from its official source, and each is CC0 or in the public
domain. `scripts/build_markers.py` composes the map pin pictures from them. Licences were checked
on 2026-11-09.

## The air quality particles: our own drawing, no source file

The air quality markers show four filled dots of different sizes, drawn by `scripts/build_markers.py`
from plain geometry (circles at (9, 9) r 4.6, (17.2, 13.4) r 3.2, (9.6, 18.6) r 2.4 and (18, 6)
r 1.7 in a 24 square, placed 40 wide in the disc). It is our own drawing, not a trace of any icon,
and has no source file. The ink is white or `#1c1c1c`, whichever reads better on the band's colour.

## The pharmacy cross: drawn, no source file

The pharmacy marker is a green Greek cross with a white edge, the sign on every Spanish
pharmacy. `scripts/build_markers.py` draws it from its geometry (58 units across in the 64 square,
arms a third of that, fill `#2E9E44`): a plain geometric shape, not third-party artwork. It is
green on purpose: the red cross is a protected emblem, and white on green reads as the ISO
first-aid sign. Maki's `pharmacy` pictogram was used before and is no longer vendored.

## Maki (Mapbox), CC0 1.0

Licence: <https://github.com/mapbox/maki/blob/main/LICENSE.txt> ("CC0 1.0 Universal").

| File | URL |
| --- | --- |
| `maki-bus.svg` | <https://raw.githubusercontent.com/mapbox/maki/main/icons/bus.svg> |
| `maki-caution.svg` | <https://raw.githubusercontent.com/mapbox/maki/main/icons/caution.svg> |

Not vendored: Maki `rail-light` (Temaki's `tram` reads better for tram stops) and `danger` (it is
a skull and crossbones, wrong for a disruption).

## Temaki (Rapid editor), CC0 1.0

Licence: <https://github.com/rapideditor/temaki/blob/main/LICENSE.md> ("CC0 1.0 Universal").

| File | URL |
| --- | --- |
| `temaki-tram.svg` | <https://raw.githubusercontent.com/rapideditor/temaki/main/icons/tram.svg> |
| `temaki-water_shutoff.svg` | <https://raw.githubusercontent.com/rapideditor/temaki/main/icons/water_shutoff.svg> |

Temaki's `windsock` was used for air quality and is no longer vendored: people read it as wind,
and the stations measure none.

## Wikimedia Commons, public domain

Licence as reported by the Commons API (`prop=imageinfo&iiprop=extmetadata`, `LicenseShortName`).

| File | Page | Licence |
| --- | --- | --- |
| `commons-r100.svg` (R-100 "Circulación prohibida") | <https://commons.wikimedia.org/wiki/File:Spain_traffic_signal_r100.svg> | Public domain (`{{PD-self}}`: released by its author) |
| `commons-p18.svg` (P-18 "Obras", current 2023 design) | <https://commons.wikimedia.org/wiki/File:Spain_traffic_signal_P-18_(2023).svg> | Public domain (`{{PD-SpanishGov}}`: drawn from the Ministry's sign catalogue, BOE-A-2025-12199) |

Downloaded from `https://upload.wikimedia.org/wikipedia/commons/9/91/Spain_traffic_signal_r100.svg`
and `https://upload.wikimedia.org/wikipedia/commons/b/b1/Spain_traffic_signal_P-18_%282023%29.svg`.

The older P-18 file ("Spain traffic signal p18.svg", 1992-2003 design) and the 2003-2023 one
are not used. R-100 is the same sign in the current catalogue.
