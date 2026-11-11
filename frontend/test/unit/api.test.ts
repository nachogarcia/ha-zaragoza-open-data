import type { MessageBase } from "home-assistant-js-websocket";
import { describe, expect, it } from "vitest";

import {
  ActionError,
  UnexpectedResponseError,
  findStops,
  getArrivals,
  getBiziStation,
} from "../../src/api";
import type { ArrivalsResponse, BiziResponse, FindStopsResponse } from "../../src/types";
// The Python acceptance snapshots of the actions' answers (`make card-fixtures`).
// Typed here, so a changed answer shape fails the type check as well.
import bizi_station from "../fixtures/bizi_station.json";
import bus_arrivals from "../fixtures/bus_arrivals.json";
// And of its errors, as Home Assistant's websocket sends them.
import error_source_unavailable from "../fixtures/error_source_unavailable.json";
import error_unknown_stop from "../fixtures/error_unknown_stop.json";
import find_bizi_stations from "../fixtures/find_bizi_stations.json";
import find_bus_stops from "../fixtures/find_bus_stops.json";
import find_tram_stops from "../fixtures/find_tram_stops.json";
import tram_arrivals from "../fixtures/tram_arrivals.json";

const findTramStops: FindStopsResponse = find_tram_stops;
const findBusStops: FindStopsResponse = find_bus_stops;
const findBiziStations: FindStopsResponse = find_bizi_stations;
const tramArrivals: ArrivalsResponse = tram_arrivals;
const busArrivals: ArrivalsResponse = bus_arrivals;
const biziStation: BiziResponse = bizi_station;

/** A `hass` whose socket records what is sent and answers with `answer`. */
function fakeHass(answer: () => Promise<unknown>) {
  const sent: MessageBase[] = [];
  const hass = {
    connection: {
      sendMessagePromise: (message: MessageBase): Promise<unknown> => {
        sent.push(message);
        return answer();
      },
    },
  };
  return { hass, sent };
}

/** A `hass` whose socket rejects with `reason`: like the real one, not with an `Error`. */
function failing(reason: unknown) {
  // eslint-disable-next-line @typescript-eslint/prefer-promise-reject-errors -- as the real one
  return fakeHass(() => Promise.reject(reason));
}

/** Home Assistant's result for an action called with `return_response`. */
function answering(response: unknown) {
  return fakeHass(() =>
    Promise.resolve({
      context: { id: "01KCONTEXT", parent_id: null, user_id: "abc" },
      response,
    }),
  );
}

function callOf(service: string, serviceData: Record<string, unknown>) {
  return {
    type: "call_service",
    domain: "zaragoza_open_data",
    service,
    service_data: serviceData,
    return_response: true,
  };
}

describe("findStops", () => {
  it("sends find_stops with the text and limit, asking for the response", async () => {
    const { hass, sent } = answering(findTramStops);

    await findStops(hass, { kind: "tram", query: "pilar", limit: 8 });

    expect(sent).toStrictEqual([callOf("find_stops", { kind: "tram", query: "pilar", limit: 8 })]);
  });

  it("sends a point as latitude and longitude", async () => {
    const { hass, sent } = answering(findBusStops);

    await findStops(hass, { kind: "bus", latitude: 41.6488, longitude: -0.8891, limit: 5 });

    expect(sent).toStrictEqual([
      callOf("find_stops", { kind: "bus", latitude: 41.6488, longitude: -0.8891, limit: 5 }),
    ]);
  });

  it("sends only the kind when nothing else is given", async () => {
    const { hass, sent } = answering(findBiziStations);

    await findStops(hass, { kind: "bizi" });

    expect(sent).toStrictEqual([callOf("find_stops", { kind: "bizi" })]);
  });

  it.each([
    ["tram", findTramStops],
    ["bus", findBusStops],
    ["bizi", findBiziStations],
  ] as const)("returns the %s stops of the response, in order", async (kind, response) => {
    const { hass } = answering(response);

    const stops = await findStops(hass, { kind });

    expect(stops).toStrictEqual(response.stops);
  });

  it.each([
    ["no response", undefined],
    ["a null response", null],
    ["no stops", {}],
    ["stops that aren't a list", { stops: "688" }],
    ["a stop without a code", { stops: [{ ...findBusStops.stops[0], code: undefined }] }],
    ["a distance as text", { stops: [{ ...findBusStops.stops[0], distance_m: "53" }] }],
    ["a line that isn't text", { stops: [{ ...findBusStops.stops[0], lines: [58] }] }],
    ["a direction that isn't text", { stops: [{ ...findTramStops.stops[0], direction: 1 }] }],
  ])("rejects an answer with %s", async (_case, response) => {
    const { hass } = answering(response);

    await expect(findStops(hass, { kind: "bus" })).rejects.toThrow(UnexpectedResponseError);
  });
});

describe("getArrivals", () => {
  it("sends get_arrivals with the mode and stop, asking for the response", async () => {
    const { hass, sent } = answering(tramArrivals);

    await getArrivals(hass, "tram", "2502");

    expect(sent).toStrictEqual([callOf("get_arrivals", { mode: "tram", stop: "2502" })]);
  });

  it.each([
    ["tram", "2502", tramArrivals],
    ["bus", "1231", busArrivals],
  ] as const)("returns the %s board as answered", async (mode, stop, response) => {
    const { hass } = answering(response);

    expect(await getArrivals(hass, mode, stop)).toStrictEqual(response);
  });

  it("returns an empty board, as at night", async () => {
    const night = { ...tramArrivals, arrivals: [] };
    const { hass } = answering(night);

    expect(await getArrivals(hass, "tram", "2502")).toStrictEqual(night);
  });

  const firstBus = busArrivals.arrivals[0];

  it.each([
    ["no arrivals", { ...tramArrivals, arrivals: undefined }],
    ["no stop", { ...tramArrivals, stop: undefined }],
    ["minutes as text", { ...busArrivals, arrivals: [{ ...firstBus, minutes: "7" }] }],
    ["a time that isn't one", { ...busArrivals, arrivals: [{ ...firstBus, time: "soon" }] }],
    ["no update time", { ...tramArrivals, updated: undefined }],
  ])("rejects a board with %s", async (_case, response) => {
    const { hass } = answering(response);

    await expect(getArrivals(hass, "bus", "1231")).rejects.toThrow(UnexpectedResponseError);
  });
});

describe("getBiziStation", () => {
  it("sends get_bizi_station with the station, asking for the response", async () => {
    const { hass, sent } = answering(biziStation);

    await getBiziStation(hass, "164");

    expect(sent).toStrictEqual([callOf("get_bizi_station", { station: "164" })]);
  });

  it("returns the station's bikes and docks as answered", async () => {
    const { hass } = answering(biziStation);

    expect(await getBiziStation(hass, "164")).toStrictEqual(biziStation);
  });

  it("returns no bike types while the city's list stands in", async () => {
    const fromCity = { ...biziStation, electric: null, mechanical: null, source: "zaragoza_city" };
    const { hass } = answering(fromCity);

    expect(await getBiziStation(hass, "164")).toStrictEqual(fromCity);
  });

  it.each([
    ["no bikes", { ...biziStation, bikes: null }],
    ["docks as text", { ...biziStation, docks: "15" }],
    ["renting as a number", { ...biziStation, renting: 1 }],
    ["no station name", { ...biziStation, station: { code: "164" } }],
  ])("rejects a station with %s", async (_case, response) => {
    const { hass } = answering(response);

    await expect(getBiziStation(hass, "164")).rejects.toThrow(UnexpectedResponseError);
  });
});

describe("errors from Home Assistant", () => {
  it("rejects an unknown stop with Home Assistant's message and translation", async () => {
    const { hass } = failing(error_unknown_stop);

    const error: unknown = await getBiziStation(hass, "9999").catch((err: unknown) => err);

    expect(error).toBeInstanceOf(ActionError);
    expect(error).toMatchObject({
      message: "Validation error: No stop or station has the code 9999",
      code: "service_validation_error",
      translationKey: "unknown_stop",
      translationDomain: "zaragoza_open_data",
      translationPlaceholders: { code: "9999" },
    });
  });

  it("rejects a source that doesn't answer with its translation, no placeholders", async () => {
    const { hass } = failing(error_source_unavailable);

    const error: unknown = await getArrivals(hass, "tram", "2502").catch((err: unknown) => err);

    expect(error).toBeInstanceOf(ActionError);
    expect(error).toMatchObject({
      message: "The source of this data can't be reached right now",
      code: "home_assistant_error",
      translationKey: "source_unavailable",
      translationDomain: "zaragoza_open_data",
      translationPlaceholders: {},
    });
  });

  it("rejects with the message alone when the error has no translation", async () => {
    const failure = { code: "unknown_error", message: "Something broke" };
    const { hass } = failing(failure);

    const error: unknown = await findStops(hass, { kind: "tram" }).catch((err: unknown) => err);

    expect(error).toBeInstanceOf(ActionError);
    expect(error).toMatchObject({ message: "Something broke", code: "unknown_error" });
    expect(error).toHaveProperty("translationKey", undefined);
    expect(error).toHaveProperty("translationPlaceholders", {});
  });

  it("passes a lost connection on as the socket reported it", async () => {
    const lost = { type: "result", success: false, error: { code: 3, message: "Connection lost" } };
    const { hass } = failing(lost);

    await expect(getBiziStation(hass, "164")).rejects.toBe(lost);
  });
});
