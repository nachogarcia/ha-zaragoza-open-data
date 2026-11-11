"""The city road works adapter against recorded HTTP."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
import json
import logging

import pytest
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMocker

from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.client import (
    CityClient,
)
from custom_components.zaragoza_open_data.api.adapters.zaragoza_city.road_works import (
    CityRoadWorks,
)
from custom_components.zaragoza_open_data.api.errors import SourceUnavailableError
from custom_components.zaragoza_open_data.api.models import RoadWorkCategory
from tests.fixtures import read_fixture
from tests.integration.contracts import check_road_works_contract

BASE = "https://www.zaragoza.es/sede/servicio/"
USER_AGENT = "ZaragozaOpenData/test (+https://example.invalid)"
INCIDENTS = "via-publica/incidencia.json"
MAINTENANCE = "via-publica/incidencia/conservacion-hoy.json"


@pytest.fixture
async def road_works(
    aioclient_mock: AiohttpClientMocker,
) -> AsyncIterator[CityRoadWorks]:
    """Adapter whose HTTP replays the recorded lists."""
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield CityRoadWorks(CityClient(session, USER_AGENT))
    await session.close()


def serve(
    aioclient_mock: AiohttpClientMocker,
    incidents: str = "road_works_incidencia.json",
    maintenance: str = "road_works_conservacion_hoy.json",
) -> None:
    """Serve the two recorded lists."""
    aioclient_mock.get(
        BASE + INCIDENTS, text=read_fixture(f"zaragoza_city/{incidents}")
    )
    aioclient_mock.get(
        BASE + MAINTENANCE, text=read_fixture(f"zaragoza_city/{maintenance}")
    )


async def test_merges_both_lists_without_duplicates(
    road_works: CityRoadWorks, aioclient_mock: AiohttpClientMocker
) -> None:
    """70 incidents and 28 maintenance jobs share no ids; 3 jobs have no location."""
    serve(aioclient_mock)

    works = await road_works.road_works()

    assert road_works.source_name == "zaragoza_city"
    ids = [work.id for work in works]
    assert len(works) == 95
    assert len(set(ids)) == 95
    assert "25688" in ids
    assert "31590" in ids


async def test_work_without_a_location_is_skipped(
    road_works: CityRoadWorks,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Three recorded maintenance jobs have no ``geometry``: left out, rest parsed."""
    serve(aioclient_mock)

    with caplog.at_level(logging.DEBUG):
        ids = {work.id for work in await road_works.road_works()}

    assert ids.isdisjoint({"31527", "31525", "31511"})
    skipped = [r for r in caplog.records if "31527" in r.getMessage()]
    assert skipped
    assert {r.levelno for r in skipped} == {logging.DEBUG}


async def test_id_in_both_lists_keeps_the_first_occurrence(
    road_works: CityRoadWorks, aioclient_mock: AiohttpClientMocker
) -> None:
    """The incident list wins over the maintenance list for a repeated id."""
    serve(
        aioclient_mock, maintenance="road_works_conservacion_hoy_overlap_derived.json"
    )

    works = await road_works.road_works()

    assert len(works) == 94
    repeated = [work for work in works if work.id == "25688"]
    assert [work.title for work in repeated] == ["DR. BLANCO CORDERO"]
    assert repeated[0].category is RoadWorkCategory.TRAFFIC_CLOSURE


async def test_requests_both_lists_in_wgs84_with_user_agent(
    road_works: CityRoadWorks, aioclient_mock: AiohttpClientMocker
) -> None:
    """Both lists are fetched with ``srsname=wgs84`` and no ``fl`` (it can drop fields)."""
    serve(aioclient_mock)

    await road_works.road_works()

    calls = aioclient_mock.mock_calls
    assert [call[1].path for call in calls] == [
        "/sede/servicio/" + INCIDENTS,
        "/sede/servicio/" + MAINTENANCE,
    ]
    for call in calls:
        assert call[1].query["srsname"] == "wgs84"
        assert "fl" not in call[1].query
        assert call[3]["User-Agent"] == USER_AGENT


async def test_maps_every_known_category_and_unknown_to_other(
    road_works: CityRoadWorks, aioclient_mock: AiohttpClientMocker
) -> None:
    """Each ``tipo.title`` maps to its category; an unseen one is ``OTHER``."""
    serve(aioclient_mock)
    by_id = {work.id: work for work in await road_works.road_works()}

    categories = {work.category for work in by_id.values()}
    assert categories == {
        RoadWorkCategory.TRAFFIC_CLOSURE,
        RoadWorkCategory.WATER_CUT,
        RoadWorkCategory.MAJOR_DISRUPTION,
        RoadWorkCategory.PUBLIC_TRANSPORT_DISRUPTION,
        RoadWorkCategory.MAINTENANCE,
    }
    assert by_id["25688"].category is RoadWorkCategory.TRAFFIC_CLOSURE
    assert by_id["31590"].category is RoadWorkCategory.MAJOR_DISRUPTION

    aioclient_mock.clear_requests()
    serve(
        aioclient_mock, incidents="road_works_incidencia_unknown_category_derived.json"
    )
    unknown = {work.id: work for work in await road_works.road_works()}
    assert unknown["25688"].category is RoadWorkCategory.OTHER


async def test_maps_water_and_transport_titles(
    road_works: CityRoadWorks, aioclient_mock: AiohttpClientMocker
) -> None:
    """Water cuts and public transport disruptions have their own categories."""
    data = json.loads(read_fixture("zaragoza_city/road_works_incidencia.json"))
    data["result"][0]["tipo"]["title"] = "Cortes de Agua"
    data["result"][1]["tipo"]["title"] = "Afecciones al Transporte Público"
    aioclient_mock.get(BASE + INCIDENTS, text=json.dumps(data))
    aioclient_mock.get(
        BASE + MAINTENANCE, text=json.dumps({"totalCount": 0, "result": []})
    )

    works = await road_works.road_works()

    assert works[0].category is RoadWorkCategory.WATER_CUT
    assert works[1].category is RoadWorkCategory.PUBLIC_TRANSPORT_DISRUPTION


async def test_maintenance_item_without_end_date(
    road_works: CityRoadWorks, aioclient_mock: AiohttpClientMocker
) -> None:
    """A maintenance job has a start but no ``fin``; times are Madrid local."""
    serve(aioclient_mock)
    by_id = {work.id: work for work in await road_works.road_works()}

    job = by_id["31590"]
    assert job.ends is None
    # 2026-11-06T00:00 Madrid (UTC+1).
    assert job.starts == datetime(2026, 11, 5, 23, 0, tzinfo=UTC)
    assert job.location.latitude == pytest.approx(41.65211268384353)
    assert job.location.longitude == pytest.approx(-0.8671248549182887)
    assert job.stretch is None
    assert job.detour is None
    closure = by_id["25688"]
    # fin 2027-02-26T00:00 Madrid (UTC+1).
    assert closure.ends == datetime(2027, 2, 25, 23, 0, tzinfo=UTC)
    assert closure.stretch is not None
    assert closure.stretch.startswith("Dr. Blanco Cordero se corta")
    assert closure.detour is not None
    assert closure.detour.startswith("Se mantiene cortada")


async def test_text_fields_are_trimmed(
    road_works: CityRoadWorks, aioclient_mock: AiohttpClientMocker
) -> None:
    """Stray tabs, CR/LF and repeated spaces go; the case is left as written."""
    serve(aioclient_mock)
    by_id = {work.id: work for work in await road_works.road_works()}

    job = by_id["31590"]
    assert job.title == (
        "ENTORNO GRUPO ALOY SALAS: C/ TABOADA, ROQUE J ALCUBIERRE, J. ANCHETA, J. VICENS"
    )
    assert job.street == "TABOADA EDUARDO JES., 10"
    assert job.reason == "Renovación tubería abastecimiento(Fase 2)"
    for work in by_id.values():
        for text in (work.title, work.street, work.reason, work.stretch, work.detour):
            assert text is None or (text == " ".join(text.split()) and text != "")


async def test_blank_optional_text_is_none(
    road_works: CityRoadWorks, aioclient_mock: AiohttpClientMocker
) -> None:
    """An empty or whitespace-only text is absent, not an empty string."""
    data = json.loads(read_fixture("zaragoza_city/road_works_incidencia.json"))
    data["result"][0]["motivo"] = " \t\r\n "
    data["result"][0]["tramo"] = ""
    aioclient_mock.get(BASE + INCIDENTS, text=json.dumps(data))
    aioclient_mock.get(
        BASE + MAINTENANCE, text=json.dumps({"totalCount": 0, "result": []})
    )

    first = (await road_works.road_works())[0]

    assert first.reason is None
    assert first.stretch is None


async def test_id_arriving_as_text_is_kept_as_text(
    road_works: CityRoadWorks, aioclient_mock: AiohttpClientMocker
) -> None:
    """An id is a string whether the city sends an integer or a string."""
    data = json.loads(read_fixture("zaragoza_city/road_works_incidencia.json"))
    data["result"][0]["id"] = "25688"
    aioclient_mock.get(BASE + INCIDENTS, text=json.dumps(data))
    aioclient_mock.get(
        BASE + MAINTENANCE, text=json.dumps({"totalCount": 0, "result": []})
    )

    works = await road_works.road_works()

    assert works[0].id == "25688"


async def test_work_with_a_malformed_location_is_source_unavailable(
    road_works: CityRoadWorks, aioclient_mock: AiohttpClientMocker
) -> None:
    """A ``geometry`` that is present but not a point is the city changing format."""
    data = json.loads(read_fixture("zaragoza_city/road_works_incidencia.json"))
    data["result"][0]["geometry"] = {"type": "Point", "coordinates": "here"}
    aioclient_mock.get(BASE + INCIDENTS, text=json.dumps(data))
    aioclient_mock.get(
        BASE + MAINTENANCE, text=json.dumps({"totalCount": 0, "result": []})
    )

    with pytest.raises(SourceUnavailableError):
        await road_works.road_works()


async def test_error_body_with_http_200_is_source_unavailable(
    road_works: CityRoadWorks, aioclient_mock: AiohttpClientMocker
) -> None:
    """The city's ``{"status": 400}`` body is an outage."""
    aioclient_mock.get(
        BASE + INCIDENTS, text=read_fixture("zaragoza_city/bus_error_200_derived.json")
    )

    with pytest.raises(SourceUnavailableError) as raised:
        await road_works.road_works()

    assert raised.value.source == "zaragoza_city"


async def test_item_with_wrong_shape_is_source_unavailable(
    road_works: CityRoadWorks, aioclient_mock: AiohttpClientMocker
) -> None:
    """A malformed ``inicio`` means the city changed its format."""
    data = json.loads(read_fixture("zaragoza_city/road_works_incidencia.json"))
    data["result"][0]["inicio"] = "soon"
    aioclient_mock.get(BASE + INCIDENTS, text=json.dumps(data))
    aioclient_mock.get(
        BASE + MAINTENANCE, text=json.dumps({"totalCount": 0, "result": []})
    )

    with pytest.raises(SourceUnavailableError):
        await road_works.road_works()


async def test_road_works_contract(
    road_works: CityRoadWorks, aioclient_mock: AiohttpClientMocker
) -> None:
    """The city adapter meets the road works contract."""
    serve(aioclient_mock)

    await check_road_works_contract(road_works)
