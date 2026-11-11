"""Record real responses from every data source as test fixtures.

Run outside pytest (it blocks sockets): ``uv run python -m scripts.capture_fixtures``.
Requests go strictly one at a time, at least a second apart, with the integration's
User-Agent, so the city's servers are not stressed. Derived fixtures (``*_derived.*``)
are made by editing captured files.
"""

import asyncio
from collections.abc import Mapping
import json
from pathlib import Path
import re

import aiohttp

from custom_components.zaragoza_open_data.const import USER_AGENT

CITY = "https://www.zaragoza.es/sede/servicio/"
AVANZA = "https://zaragoza-pasobus.avanzagrupo.com/frm_esquemaparadatime.php"
GBFS = "https://zaragoza.publicbikesystem.net/customer/gbfs/v2/en/"
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
TIMEOUT = aiohttp.ClientTimeout(total=10)
AVANZA_DERIVED_DIR = FIXTURES / "avanza"
PAUSE_S = 1.0
BUS_RETRY_WAIT_S = 60
BUS_ATTEMPTS = 3
PAGE_ROWS = 500
BUS_ERROR_BODY = (
    '{"status":400,"mensaje":"; nested exception is: \\n\\tjava.net.'
    'SocketTimeoutException: Read timed out"}'
)

TRANSPORT = "urbanismo-infraestructuras/transporte-urbano/"
ROAD_FIELDS = (
    "id,title,calle,motivo,tramo,observaciones,inicio,fin,tipo,geometry,"
    "grupoTrabajo,seTrabaja"
)
CITY_FIXTURES: tuple[tuple[str, str, Mapping[str, str]], ...] = (
    (
        "tram_list.json",
        TRANSPORT + "parada-tranvia.json",
        # No ``fl``: on this list it silently drops ``destinos`` and ``mensajes``
        # (measured 2026-11-09), the two fields that matter.
        {"srsname": "wgs84", "rows": str(PAGE_ROWS)},
    ),
    (
        "road_works_incidencia.json",
        "via-publica/incidencia.json",
        {"fl": ROAD_FIELDS, "srsname": "wgs84", "rows": str(PAGE_ROWS)},
    ),
    (
        "road_works_conservacion_hoy.json",
        "via-publica/incidencia/conservacion-hoy.json",
        {"fl": ROAD_FIELDS, "srsname": "wgs84", "rows": str(PAGE_ROWS)},
    ),
    (
        "pharmacies_on_duty.json",
        "farmacia.json",
        {"tipo": "guardia", "srsname": "wgs84", "rows": str(PAGE_ROWS)},
    ),
    (
        "air_quality_stations.json",
        "calidad-aire/listado.json",
        {"srsname": "wgs84", "rows": str(PAGE_ROWS)},
    ),
    (
        "pollen.json",
        "informacion-polen.json",
        {"rows": str(PAGE_ROWS)},
    ),
    (
        "bizi_city_stations.json",
        "urbanismo-infraestructuras/estacion-bicicleta.json",
        {"srsname": "wgs84", "rows": str(PAGE_ROWS)},
    ),
)


class Recorder:
    """Fetches one URL at a time, pausing between requests, and saves the body."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Keep the shared session."""
        self._session = session

    async def fetch(
        self, url: str, params: Mapping[str, str]
    ) -> tuple[int, bytes] | None:
        """Return status and body, or None when the request itself failed."""
        try:
            async with self._session.get(url, params=params) as response:
                body = await response.read()
                status = response.status
        except (aiohttp.ClientError, TimeoutError) as err:
            print(f"  request failed: {err!r}")
            return None
        finally:
            await asyncio.sleep(PAUSE_S)
        return status, body

    async def save(
        self, directory: str, name: str, url: str, params: Mapping[str, str]
    ) -> bytes | None:
        """Save a successful (HTTP 200) response under ``tests/fixtures``."""
        print(f"GET {url} {dict(params)}")
        result = await self.fetch(url, params)
        if result is None or result[0] != 200:
            print(f"  FAILED {name}: {'no response' if result is None else result[0]}")
            return None
        folder = FIXTURES / directory
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(result[1])
        print(f"  saved {directory}/{name} ({len(result[1])} bytes)")
        return result[1]


def _write_json(directory: str, name: str, data: object) -> None:
    path = FIXTURES / directory / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    print(f"  derived {directory}/{name}")


def _derive_tram(raw: bytes) -> None:
    """Make the night board (no arrivals) and a board with a real-looking notice."""
    night = json.loads(raw)
    for stop in night["result"]:
        stop.pop("destinos", None)
    _write_json("zaragoza_city", "tram_list_night_derived.json", night)

    notice = json.loads(raw)
    notice["result"][0]["mensajes"] = [
        *notice["result"][0].get("mensajes", []),
        "Por obras, el servicio entre Parque Goya y Valdespartera se presta en "
        "autobús hasta nuevo aviso.",
    ]
    _write_json("zaragoza_city", "tram_list_notice_derived.json", notice)


async def _capture_bus_list(recorder: Recorder) -> None:
    """Page through the ~1,271 bus stops, 500 at a time."""
    start = 0
    page = 1
    total: int | None = None
    while total is None or start < total:
        body = await recorder.save(
            "zaragoza_city",
            f"bus_stops_page_{page}.json",
            CITY + TRANSPORT + "poste-autobus.json",
            {
                "fl": "id,title,geometry",
                "srsname": "wgs84",
                "rows": str(PAGE_ROWS),
                "start": str(start),
            },
        )
        if body is None:
            return
        total = int(json.loads(body)["totalCount"])
        start += PAGE_ROWS
        page += 1


async def _capture_bus_realtime(recorder: Recorder) -> None:
    """Try the flaky real-time endpoint; error variants are derived either way."""
    url = CITY + TRANSPORT + "poste-autobus/tuzsa-688.json"
    for attempt in range(1, BUS_ATTEMPTS + 1):
        body = await recorder.save(
            "zaragoza_city", "bus_realtime_688.json", url, {"srsname": "wgs84"}
        )
        if body is not None:
            break
        if attempt < BUS_ATTEMPTS:
            print(f"  waiting {BUS_RETRY_WAIT_S} s before retrying")
            await asyncio.sleep(BUS_RETRY_WAIT_S)
    else:
        print("  bus real-time not captured: falling back to the derived error only")
    path = FIXTURES / "zaragoza_city" / "bus_error_200_derived.json"
    path.write_text(BUS_ERROR_BODY + "\n")
    print("  derived zaragoza_city/bus_error_200_derived.json")


def derive_bus() -> None:
    """Make the bus variants the real providers only show occasionally."""
    city = json.loads(
        (FIXTURES / "zaragoza_city" / "bus_realtime_688.json").read_text()
    )
    city["destinos"] = [
        {
            "linea": "58",
            "destino": "FUENTE JUNQUERA,",
            "primero": "Sin estimacion.",
            "segundo": "En la parada.",
        }
    ]
    _write_json("zaragoza_city", "bus_realtime_688_unknown_time_derived.json", city)

    page = (FIXTURES / "avanza" / "stop_688.html").read_bytes().decode("utf-8-sig")
    first = page.index('<tr><td class="digital">')
    last = page.index("</table>", first)
    avanza = AVANZA_DERIVED_DIR / "stop_no_buses_derived.html"
    avanza.write_text(page[:first] + page[last:], encoding="utf-8")
    print("  derived avanza/stop_no_buses_derived.html")
    no_table = (
        page[: page.index("<table")] + "<p>Poste no encontrado</p></body></html>\n"
    )
    (AVANZA_DERIVED_DIR / "stop_no_table_derived.html").write_text(
        no_table, encoding="utf-8"
    )
    print("  derived avanza/stop_no_table_derived.html")


def derive_bike() -> None:
    """Make Bizi station lists where station 164 lost its prefix, or is missing."""
    gbfs_path = FIXTURES / "gbfs" / "station_information.json"
    gbfs = json.loads(gbfs_path.read_text())
    for station in gbfs["data"]["stations"]:
        if station["name"].startswith("164-"):
            station["name"] = station["name"].removeprefix("164-").strip()
    _write_json("gbfs", "station_information_no_prefix_derived.json", gbfs)

    # The operator no longer lists 164, as when a station is removed.
    gone = json.loads(gbfs_path.read_text())
    gone["data"]["stations"] = [
        station
        for station in gone["data"]["stations"]
        if not station["name"].startswith("164-")
    ]
    _write_json("gbfs", "station_information_missing_164_derived.json", gone)

    city_path = FIXTURES / "zaragoza_city" / "bizi_city_stations.json"
    city = json.loads(city_path.read_text())
    for row in city["result"]:
        if row["title"].startswith("164-"):
            row["title"] = row["title"].removeprefix("164-").strip()
    _write_json("zaragoza_city", "bizi_city_stations_no_prefix_derived.json", city)

    # The city lists a varying subset of the stations; here it lacks 164.
    missing = json.loads(city_path.read_text())
    missing["result"] = [
        row for row in missing["result"] if not row["title"].startswith("164-")
    ]
    missing["totalCount"] = len(missing["result"])
    _write_json("zaragoza_city", "bizi_city_stations_missing_164_derived.json", missing)


def derive_road_works() -> None:
    """Make an unknown category, an ended incident, and a repeated id."""
    incidents_path = FIXTURES / "zaragoza_city" / "road_works_incidencia.json"
    incidents = json.loads(incidents_path.read_text())
    incidents["result"][0]["tipo"]["title"] = "Obras Menores"
    _write_json(
        "zaragoza_city",
        "road_works_incidencia_unknown_category_derived.json",
        incidents,
    )

    # The first incident has ended: the city no longer lists it.
    ended = json.loads(incidents_path.read_text())
    ended["result"] = ended["result"][1:]
    ended["totalCount"] = len(ended["result"])
    _write_json("zaragoza_city", "road_works_incidencia_ended_derived.json", ended)

    first_id = json.loads(incidents_path.read_text())["result"][0]["id"]
    maintenance_path = FIXTURES / "zaragoza_city" / "road_works_conservacion_hoy.json"
    maintenance = json.loads(maintenance_path.read_text())
    maintenance["result"][0]["id"] = first_id
    maintenance["result"][0]["title"] = "REPEATED INCIDENT, MAINTENANCE COPY"
    _write_json(
        "zaragoza_city", "road_works_conservacion_hoy_overlap_derived.json", maintenance
    )


def _set_duty_date(row: dict[str, object], day: str) -> None:
    """Move a pharmacy row to the turn of ``day``: its ``fecha`` and its ``type`` suffix."""
    guardia = row["guardia"]
    types = row["type"]
    assert isinstance(guardia, dict)
    assert isinstance(types, list)
    guardia["fecha"] = f"{day}T00:00:00"
    row["type"] = [
        re.sub(r"FarmaciaGuardia/\d{4}-\d{2}-\d{2}$", f"FarmaciaGuardia/{day}", kind)
        for kind in types
    ]


def derive_city_information() -> None:
    """Make pharmacy and air station lists with one change each (see the README)."""
    city = FIXTURES / "zaragoza_city"
    pharmacies = json.loads((city / "pharmacies_on_duty.json").read_text())
    # The first pharmacy listed twice.
    repeated = {
        **pharmacies,
        "result": [*pharmacies["result"], pharmacies["result"][0]],
    }
    repeated["totalCount"] = len(repeated["result"])
    _write_json("zaragoza_city", "pharmacies_on_duty_repeated_derived.json", repeated)
    # The first pharmacy's shift ended at 09:15; the others carry on.
    pharmacies["result"] = pharmacies["result"][1:]
    pharmacies["totalCount"] = len(pharmacies["result"])
    _write_json(
        "zaragoza_city", "pharmacies_on_duty_next_shift_derived.json", pharmacies
    )
    # The next day's turn, as the city publishes it after 09:15: the same list
    # with every ``guardia.fecha`` one day on.
    for row in pharmacies["result"]:
        _set_duty_date(row, "2026-11-10")
    _write_json(
        "zaragoza_city", "pharmacies_on_duty_next_turn_derived.json", pharmacies
    )
    # The turn before, as the city still lists it until it publishes the new one.
    previous = json.loads((city / "pharmacies_on_duty.json").read_text())
    for row in previous["result"]:
        _set_duty_date(row, "2026-11-08")
    _write_json(
        "zaragoza_city", "pharmacies_on_duty_previous_turn_derived.json", previous
    )

    stations = json.loads((city / "air_quality_stations.json").read_text())
    # Actur's PM2.5 analyser sent nothing in the last two hours.
    for row in stations["result"]:
        if row["id"] == 12:
            row["observation"] = [
                item for item in row["observation"] if item["magnitud"] != "PM2.5"
            ]
    _write_json(
        "zaragoza_city",
        "air_quality_stations_actur_without_pm25_derived.json",
        stations,
    )

    stations = json.loads((city / "air_quality_stations.json").read_text())
    # The city stops listing station 7, Jaime Ferran.
    stations["result"] = [row for row in stations["result"] if row["id"] != 7]
    stations["totalCount"] = len(stations["result"])
    _write_json(
        "zaragoza_city", "air_quality_stations_missing_7_derived.json", stations
    )

    # An answer listing no station at all.
    stations["result"] = []
    stations["totalCount"] = 0
    _write_json("zaragoza_city", "air_quality_stations_empty_derived.json", stations)


async def main() -> None:
    """Capture everything, one request at a time."""
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers, timeout=TIMEOUT) as session:
        recorder = Recorder(session)
        tram_raw: bytes | None = None
        for name, path, params in CITY_FIXTURES:
            body = await recorder.save("zaragoza_city", name, CITY + path, params)
            if name == "tram_list.json":
                tram_raw = body
        if tram_raw is not None:
            _derive_tram(tram_raw)
        await _capture_bus_list(recorder)
        for stop in ("688", "1231"):
            await recorder.save("avanza", f"stop_{stop}.html", AVANZA, {"poste": stop})
        for name in ("station_information", "station_status"):
            await recorder.save("gbfs", f"{name}.json", f"{GBFS}{name}.json", {})
        await _capture_bus_realtime(recorder)
        derive_bus()
        derive_bike()
        derive_road_works()
        derive_city_information()


if __name__ == "__main__":
    asyncio.run(main())
