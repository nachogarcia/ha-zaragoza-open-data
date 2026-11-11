"""Air quality stations and their latest hourly readings from the city's ``calidad-aire``.

One request serves both: ``calidad-aire/listado.json?srsname=wgs84`` lists the stations
and each carries an ``observation`` array of hourly readings with their real hour in
``publicationDate`` (checked on 2026-11-09). The plain
``calidad-aire.json`` is not used: it repeats pollutants, all stamped ``T00:00``. The
per-station ``calidad-aire/estacion/horaria.json`` (``estacion`` = ``idSparql``,
``fechaFin`` = tomorrow) also gives hours but costs one request per station.
"""

import logging

from ...models import AirQualityReport, AirReading, AirStation, JsonObject, Pollutant
from ..json import obj_list, point, req_float, req_id, req_str
from .client import CityClient
from .names import clean, madrid

_LOGGER = logging.getLogger(__name__)

PATH = "calidad-aire/listado.json"
_POLLUTANTS = {
    "CO": Pollutant.CO,
    "NO": Pollutant.NO,
    "NO2": Pollutant.NO2,
    "O3": Pollutant.O3,
    "SO2": Pollutant.SO2,
    "PM10": Pollutant.PM10,
    "PM2.5": Pollutant.PM25,
    "SH2": Pollutant.H2S,
    "Benceno": Pollutant.BENZENE,
}


class CityAirQuality:
    """``AirQualitySource`` backed by the city API."""

    def __init__(self, client: CityClient) -> None:
        """Keep the client."""
        self._client = client

    @property
    def source_name(self) -> str:
        """Provider name."""
        return self._client.source_name

    async def stations(self) -> tuple[AirStation, ...]:
        """Return every station."""
        return self._stations(await self._rows())

    async def report(self) -> AirQualityReport:
        """Return every station and the newest hour of each pollutant at each.

        Both come from one request.
        """
        rows = await self._rows()
        return AirQualityReport(self._stations(rows), self._readings(rows))

    def _stations(self, rows: list[JsonObject]) -> tuple[AirStation, ...]:
        source = self.source_name
        return tuple(
            AirStation(
                id=req_id(row, "id", source),
                name=clean(req_str(row, "title", source)),
                location=point(row, source),
            )
            for row in rows
        )

    def _readings(self, rows: list[JsonObject]) -> tuple[AirReading, ...]:
        source = self.source_name
        readings: list[AirReading] = []
        for row in rows:
            station_id = req_id(row, "id", source)
            latest: dict[Pollutant, AirReading] = {}
            for observation in obj_list(row, "observation", source):
                name = clean(req_str(observation, "magnitud", source))
                pollutant = _POLLUTANTS.get(name)
                if pollutant is None:
                    # A pollutant the city adds later has no sensor here yet.
                    _LOGGER.debug(
                        "Skipping unknown pollutant %s at station %s", name, station_id
                    )
                    continue
                reading = AirReading(
                    station_id=station_id,
                    pollutant=pollutant,
                    value=req_float(observation, "value", source),
                    measured_at=madrid(req_str(observation, "publicationDate", source)),
                )
                known = latest.get(pollutant)
                if known is None or reading.measured_at > known.measured_at:
                    latest[pollutant] = reading
            readings.extend(latest.values())
        return tuple(readings)

    async def _rows(self) -> list[JsonObject]:
        return await self._client.get_all(PATH, {"srsname": "wgs84"})
