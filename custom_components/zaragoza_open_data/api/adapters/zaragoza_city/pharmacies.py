"""Pharmacies on duty from the city's ``farmacia`` list."""

from ...models import DutyPharmacy, JsonObject
from ..json import obj_list, opt_str, point, req_id, req_obj, req_str
from .client import CityClient
from .names import clean, clean_or_none, madrid

PATH = "farmacia.json"
# About seven pharmacies are on duty per day; 50 leaves a wide margin in one request.
_ROWS = "50"


class CityPharmacies:
    """``PharmacySource`` backed by the city API."""

    def __init__(self, client: CityClient) -> None:
        """Keep the client."""
        self._client = client

    @property
    def source_name(self) -> str:
        """Provider name."""
        return self._client.source_name

    async def on_duty(self) -> tuple[DutyPharmacy, ...]:
        """Return today's duty pharmacies."""
        page = await self._client.get(
            PATH, {"tipo": "guardia", "srsname": "wgs84", "rows": _ROWS}
        )
        rows = obj_list(page, "result", self.source_name)
        return tuple(self._parse(row) for row in rows)

    def _parse(self, row: JsonObject) -> DutyPharmacy:
        source = self.source_name
        shift = req_obj(row, "guardia", source)
        return DutyPharmacy(
            id=req_id(row, "id", source),
            name=clean(req_str(row, "title", source)),
            address=clean(req_str(row, "calle", source)),
            phone=clean_or_none(opt_str(row, "telefonos", source)),
            hours=clean(req_str(shift, "horario", source)),
            sector=clean_or_none(opt_str(shift, "sector", source)),
            location=point(row, source),
            day=madrid(req_str(shift, "fecha", source)).date(),
        )
