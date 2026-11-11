"""The city pharmacies adapter against recorded HTTP."""

import asyncio
from collections.abc import AsyncIterator
from datetime import date
import json

import pytest
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.client import (
    CityClient,
)
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.pharmacies import (
    CityPharmacies,
)
from custom_components.zaragoza_open_data.api.errors import SourceUnavailableError
from tests.fixtures import read_fixture
from tests.integration.contracts import check_pharmacy_contract

BASE = "https://www.zaragoza.es/sede/servicio/"
USER_AGENT = "ZaragozaOpenData/test (+https://example.invalid)"
PATH = "farmacia.json"


@pytest.fixture
async def pharmacies(
    aioclient_mock: AiohttpClientMocker,
) -> AsyncIterator[CityPharmacies]:
    """Adapter whose HTTP replays the recorded duty list."""
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield CityPharmacies(CityClient(session, USER_AGENT))
    await session.close()


def serve(aioclient_mock: AiohttpClientMocker, text: str | None = None) -> None:
    """Serve the recorded duty list (or ``text``)."""
    aioclient_mock.get(
        BASE + PATH,
        text=text
        if text is not None
        else read_fixture("zaragoza_city/pharmacies_on_duty.json"),
    )


async def test_pharmacies_on_duty_parsed_with_shift(
    pharmacies: CityPharmacies, aioclient_mock: AiohttpClientMocker
) -> None:
    """Seven pharmacies on 2026-11-09, each with its shift hours, sector and day."""
    serve(aioclient_mock)

    duty = await pharmacies.on_duty()

    assert pharmacies.source_name == "zaragoza_city"
    assert len(duty) == 7
    first = next(p for p in duty if p.id == "8860")
    assert first.name == "Farmacia Artal Lerín, Ana Cristina"
    assert first.address == "Pº. de Sagasta, 8"
    assert first.phone == "976226203"
    assert first.hours == "Abiertas de 9:15 h. a 9:15 h. del día siguiente"
    assert first.sector == "Sector Gran Vía"
    assert first.day == date(2026, 11, 9)
    assert first.location.latitude == pytest.approx(41.646146396697176)
    assert first.location.longitude == pytest.approx(-0.8858667199718896)


async def test_requests_the_duty_list_in_wgs84_with_user_agent(
    pharmacies: CityPharmacies, aioclient_mock: AiohttpClientMocker
) -> None:
    """One request: ``tipo=guardia``, ``srsname=wgs84``, ``rows=50``."""
    serve(aioclient_mock)

    await pharmacies.on_duty()

    assert len(aioclient_mock.mock_calls) == 1
    call = aioclient_mock.mock_calls[0]
    assert call[1].query["tipo"] == "guardia"
    assert call[1].query["srsname"] == "wgs84"
    assert call[1].query["rows"] == "50"
    assert call[3]["User-Agent"] == USER_AGENT


async def test_blank_phone_is_none(
    pharmacies: CityPharmacies, aioclient_mock: AiohttpClientMocker
) -> None:
    """A pharmacy with an empty or missing ``telefonos`` has no phone."""
    data = json.loads(read_fixture("zaragoza_city/pharmacies_on_duty.json"))
    data["result"][0]["telefonos"] = "  "
    del data["result"][1]["telefonos"]
    serve(aioclient_mock, json.dumps(data))

    duty = await pharmacies.on_duty()

    assert duty[0].phone is None
    assert duty[1].phone is None
    assert duty[2].phone is not None


async def test_missing_sector_is_none_and_text_is_trimmed(
    pharmacies: CityPharmacies, aioclient_mock: AiohttpClientMocker
) -> None:
    """Optional sector is ``None`` when absent; tabs and line breaks are removed."""
    data = json.loads(read_fixture("zaragoza_city/pharmacies_on_duty.json"))
    del data["result"][0]["guardia"]["sector"]
    data["result"][0]["title"] = "Farmacia\tX\r\n"
    serve(aioclient_mock, json.dumps(data))

    first = (await pharmacies.on_duty())[0]

    assert first.sector is None
    assert first.name == "Farmacia X"


async def test_pharmacy_without_shift_is_source_unavailable(
    pharmacies: CityPharmacies, aioclient_mock: AiohttpClientMocker
) -> None:
    """A duty list entry with no ``guardia`` is the city changing its format."""
    data = json.loads(read_fixture("zaragoza_city/pharmacies_on_duty.json"))
    del data["result"][0]["guardia"]
    serve(aioclient_mock, json.dumps(data))

    with pytest.raises(SourceUnavailableError):
        await pharmacies.on_duty()


async def test_error_body_with_http_200_is_source_unavailable(
    pharmacies: CityPharmacies, aioclient_mock: AiohttpClientMocker
) -> None:
    """The city's ``{"status": 400}`` body is an outage."""
    serve(aioclient_mock, read_fixture("zaragoza_city/bus_error_200_derived.json"))

    with pytest.raises(SourceUnavailableError):
        await pharmacies.on_duty()


async def test_pharmacy_contract(
    pharmacies: CityPharmacies, aioclient_mock: AiohttpClientMocker
) -> None:
    """The city adapter meets the pharmacy contract."""
    serve(aioclient_mock)

    await check_pharmacy_contract(pharmacies)
