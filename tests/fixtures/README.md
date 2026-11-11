# Recorded fixtures

Real responses from the providers, saved by `uv run python -m scripts.capture_fixtures`
(one request at a time, 1 s apart, 10 s timeout, the integration's User-Agent). Captured on
2026-11-09 around 13:40 Europe/Madrid. Files are stored exactly as received.

## Captured (real)

| File | Request |
| --- | --- |
| `zaragoza_city/tram_list.json` | `parada-tranvia.json?srsname=wgs84&rows=500` (no `fl`, see below) |
| `zaragoza_city/bus_stops_page_{1,2,3}.json` | `poste-autobus.json?fl=id,title,geometry&srsname=wgs84&rows=500&start=0,500,1000` (1,271 stops) |
| `zaragoza_city/bus_realtime_688.json` | `poste-autobus/tuzsa-688.json?srsname=wgs84` (succeeded at first attempt) |
| `zaragoza_city/road_works_incidencia.json`, `road_works_conservacion_hoy.json` | `via-publica/incidencia.json`, `…/incidencia/conservacion-hoy.json` with `fl`, `srsname=wgs84`, `rows=500` |
| `zaragoza_city/pharmacies_on_duty.json` | `farmacia.json?tipo=guardia&srsname=wgs84` |
| `zaragoza_city/air_quality_stations.json` | `calidad-aire/listado.json` with `srsname=wgs84` (stations and their hourly `observation`s) |
| `zaragoza_city/pollen.json` | `informacion-polen.json` |
| `zaragoza_city/bizi_city_stations.json` | `estacion-bicicleta.json?srsname=wgs84&rows=500` |
| `avanza/stop_688.html`, `stop_1231.html` | `frm_esquemaparadatime.php?poste=688` / `1231` |
| `gbfs/station_information.json`, `station_status.json` | GBFS v2 `en/` feeds |

## Derived (edited from captured files; the script regenerates them)

| File | How |
| --- | --- |
| `zaragoza_city/tram_list_night_derived.json` | `tram_list.json` with every `destinos` removed |
| `zaragoza_city/tram_list_notice_derived.json` | `tram_list.json` with a real-looking notice appended to the first stop's `mensajes` |
| `zaragoza_city/tram_list_unknown_digit_derived.json` | `tram_list.json` with platform `2502` renamed to id `"2603"` (a last digit the direction rule does not know) |
| `zaragoza_city/tram_list_bad_timestamp_derived.json` | `tram_list.json` with `2502`'s `lastUpdated` replaced by `"soon"` |
| `zaragoza_city/bus_error_200_derived.json` | the error body observed on 2026-11-09 (`{"status":400,"mensaje":"…Read timed out"}`); tests serve it with HTTP 200 and with HTTP 400 |
| `zaragoza_city/bus_realtime_688_unknown_time_derived.json` | `bus_realtime_688.json` with `primero` = `"Sin estimacion."` (neither `"N minutos."` nor `"En la parada."`) and `segundo` = `"En la parada."` |
| `avanza/stop_no_buses_derived.html` | `stop_688.html` with the bus rows removed (table kept, as for a stop with no buses) |
| `avanza/stop_no_table_derived.html` | `stop_688.html` cut before the table (a page that is not the stop page) |
| `gbfs/station_information_no_prefix_derived.json` | `station_information.json` with station 164's name stripped of its `"164-"` prefix (`"Rosales: Illueca"`) |
| `gbfs/station_information_missing_164_derived.json` | `station_information.json` without station 164, as when the operator removes a station |
| `zaragoza_city/bizi_city_stations_no_prefix_derived.json` | `bizi_city_stations.json` with the same station's `title` stripped of `"164- "` |
| `zaragoza_city/bizi_city_stations_missing_164_derived.json` | `bizi_city_stations.json` without station 164 (`totalCount` 275), as when the city lists only a subset of the stations |
| `zaragoza_city/road_works_incidencia_unknown_category_derived.json` | `road_works_incidencia.json` with the first item's `tipo.title` set to `"Obras Menores"` (a category the adapter does not know) |
| `zaragoza_city/road_works_incidencia_ended_derived.json` | `road_works_incidencia.json` without its first item (id 25688, `totalCount` 69), as when an incident ends |
| `zaragoza_city/pharmacies_on_duty_next_shift_derived.json` | `pharmacies_on_duty.json` without its first pharmacy (id 8860, `totalCount` 6), as when its shift ends at 09:15 |
| `zaragoza_city/pharmacies_on_duty_next_turn_derived.json` | `pharmacies_on_duty_next_shift_derived.json` with every `guardia.fecha` set to 2026-11-10: the next day's turn, as the city publishes it after 09:15 |
| `zaragoza_city/pharmacies_on_duty_previous_turn_derived.json` | `pharmacies_on_duty.json` with every `guardia.fecha` set to 2026-11-08: the turn before, which the city keeps listing until it publishes the new one |
| `zaragoza_city/air_quality_stations_missing_7_derived.json` | `air_quality_stations.json` without station 7 (Jaime Ferran, `totalCount` 7), as when the city stops listing a station |
| `zaragoza_city/air_quality_stations_empty_derived.json` | `air_quality_stations.json` with no station at all (`totalCount` 0) |
| `zaragoza_city/pharmacies_on_duty_repeated_derived.json` | `pharmacies_on_duty.json` with its first pharmacy (id 8860) listed a second time at the end (`totalCount` 8) |
| `zaragoza_city/air_quality_stations_actur_without_pm25_derived.json` | `air_quality_stations.json` with station 12 (Actur) lacking its `PM2.5` observations, as when an analyser is silent for the two hours the list covers |
| `zaragoza_city/road_works_conservacion_hoy_overlap_derived.json` | `road_works_conservacion_hoy.json` whose first item reuses the id of `incidencia`'s first item (title `"REPEATED INCIDENT, MAINTENANCE COPY"`), to pin "first occurrence wins" (the two real lists do not overlap) |

The city 400 variant of the bus error has no file: tests serve `bus_error_200_derived.json` with HTTP 400. Tests that need other Avanza edits (no accessibility icon, "En la parada.", ISO-8859-1 bytes) edit `stop_688.html` in memory.

## Measured quirks worth knowing

- On 2026-11-09 the city's `estacion-bicicleta` list returned all 276 stations (the design's "132" is stale). With `fl=id,title,estado,bicisDisponibles,anclajesDisponibles,geometry,lastUpdated` every one of those fields survives (checked with one real request), so the adapter uses `fl`; the recorded file was captured without it and has extra fields.
- On 2026-11-10 the city listed station 92 (`id` 80, `"92-S. Juan Cruz: Lasala"`) with `estado: "MAINTENANCE"` and neither `bicisDisponibles` nor `anclajesDisponibles`. Closed stations without counts keep their catalogue entries but have no availability; the adapter and Bizi acceptance tests reproduce this shape by editing station 164 in memory.
- One real GBFS name has a space before the hyphen: `"160 - Jardines Montemolín"`.
- The bus stop pages hold two networks: 983 urban rows (`"tuzsa-N"`) and 288 others (`"rural-N"`, line 501 among them, with no real time anywhere); 175 numbers are in both, the `rural-` row first for some (338). Five urban rows are tram platforms whose only line is `TRA` (1, 2, 11, 12, 22). No row mixes `TRA` with bus lines, and no number repeats among the urban rows; the tests pinning those two rules use stop 338's row, edited inline. A fresh fetch at 22:56 the same day returned exactly the recorded rows.
- On the tram list, `fl` silently drops `destinos` and `mensajes`, so the list is requested
  without `fl` (about 47 KB, still one call for all 50 platforms).
- The road works lists are requested without `fl` (only the fixtures were captured with it). Three of the 28 maintenance jobs in `conservacion-hoy` have no `geometry` at all (ids 31527, 31525, 31511 on 2026-11-09); the adapter skips them. Ids are integers in the JSON.
- The Avanza page is served as UTF-8 (with BOM), not ISO-8859-1 as first assumed.
- Air quality: `calidad-aire/listado.json` carries, per station, an `observation` array with the last two hours of every pollutant (real `publicationDate`; magnitudes `NO2`, `NO`, `O3`, `CO`, `SO2`, `PM10`, `PM2.5`, `SH2`, `Benceno`), so readings need one request. `calidad-aire.json` repeats pollutants all stamped `T00:00:00` and is not used; the per-station `calidad-aire/estacion/horaria.json` works only with the station's `idSparql` and `fechaFin` = tomorrow, and costs 8 requests.
