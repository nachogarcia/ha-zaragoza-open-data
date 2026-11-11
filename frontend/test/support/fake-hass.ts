import type { HassEntity, MessageBase } from "home-assistant-js-websocket";

import type { ArrivalsResponse, BiziResponse, FindStopsResponse, HomeAssistant } from "../../src/types";
// The Python acceptance snapshots of the actions' answers and errors (`make card-fixtures`),
// typed here so a changed answer shape fails the type check too.
import bizi_station from "../fixtures/bizi_station.json";
import bus_arrivals from "../fixtures/bus_arrivals.json";
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

export const recorded = {
  findTramStops,
  findBusStops,
  findBiziStations,
  tramArrivals,
  busArrivals,
  biziStation,
  errorUnknownStop: error_unknown_stop,
  errorSourceUnavailable: error_source_unavailable,
};

// What each action answered, by service and then by kind or mode.
const ANSWERS: Readonly<Record<string, Readonly<Record<string, unknown>>>> = {
  find_stops: { tram: findTramStops, bus: findBusStops, bizi: findBiziStations },
  get_arrivals: { tram: tramArrivals, bus: busArrivals },
};

export interface Point {
  readonly latitude: number;
  readonly longitude: number;
}

const CONTEXT = { id: "01KCONTEXT", parent_id: null, user_id: null };

function entity(entity_id: string, state: string, attributes: HassEntity["attributes"]): HassEntity {
  const at = "2026-11-09T12:40:00+00:00";
  return { entity_id, state, attributes, last_changed: at, last_updated: at, context: CONTEXT };
}

/** A person; `point` is where their phone last said they are, if it said. */
export function person(objectId: string, userId: string, point?: Point): HassEntity {
  return entity(`person.${objectId}`, point === undefined ? "unknown" : "not_home", {
    friendly_name: objectId,
    user_id: userId,
    ...point,
  });
}

/** A zone, with or without a point. */
export function zone(objectId: string, name: string, point?: Point): HassEntity {
  return entity(`zone.${objectId}`, "0", { friendly_name: name, radius: 100, ...point });
}

/** The message the card sends to call one of the integration's actions. */
export function callOf(service: string, serviceData: Readonly<Record<string, unknown>>) {
  return {
    type: "call_service",
    domain: "zaragoza_open_data",
    service,
    service_data: serviceData,
    return_response: true,
  };
}

export interface FakeHomeOptions {
  readonly language?: string;
  readonly states?: readonly HassEntity[];
  /** The logged-in user; none while the frontend hasn't fetched it. */
  readonly userId?: string | undefined;
  /** The server's time zone. */
  readonly timeZone?: string;
  /** The user's profile choice: the server's time zone, or the browser's. */
  readonly localeTimeZone?: "local" | "server";
}

type Answer = (message: MessageBase) => Promise<unknown>;

/** A call the test answers when it chooses, to make an answer arrive late. */
export interface Held {
  respond(response: unknown): void;
  fail(error: unknown): void;
}

/**
 * Home Assistant as the card sees it: states, the user, the language and time zone, and
 * a socket that records every message and answers as the integration did when the
 * fixtures were recorded, unless the test says otherwise.
 */
export class FakeHome {
  readonly sent: MessageBase[] = [];
  readonly hass: HomeAssistant;
  private readonly next: Answer[] = [];
  private always: Answer | undefined;

  constructor(options: FakeHomeOptions = {}) {
    const states = options.states ?? [];
    this.hass = {
      states: Object.fromEntries(states.map((state) => [state.entity_id, state])),
      ...(options.userId === undefined
        ? {}
        : { user: { id: options.userId, name: "Ana", is_admin: false, is_owner: false } }),
      locale: { language: options.language ?? "es", time_zone: options.localeTimeZone ?? "server" },
      config: { time_zone: options.timeZone ?? "Europe/Madrid" },
      connection: {
        sendMessagePromise: (message: MessageBase): Promise<unknown> => {
          this.sent.push(message);
          const answer = this.next.shift() ?? this.always ?? answerAsRecorded;
          return answer(message);
        },
      },
    };
  }

  /** The messages sent since the last `take`, forgetting them. */
  take(): MessageBase[] {
    return this.sent.splice(0);
  }

  /** The next call is answered with `response` as the action's response. */
  respondNext(response: unknown): void {
    this.next.push(() => Promise.resolve(result(response)));
  }

  /** The next call fails with `error`, as Home Assistant's socket rejects. */
  failNext(error: unknown): void {
    this.next.push(() => rejection(error));
  }

  /** From now on every call fails with `error`, until `recover`. */
  failAlways(error: unknown): void {
    this.always = () => rejection(error);
  }

  /** From now on every call is answered as recorded again. */
  recover(): void {
    this.always = undefined;
  }

  /** The next call waits for the test to answer it. */
  holdNext(): Held {
    let respond: (response: unknown) => void = () => undefined;
    let fail: (error: unknown) => void = () => undefined;
    const answer = new Promise<unknown>((resolve, reject) => {
      respond = (response) => {
        resolve(result(response));
      };
      fail = reject;
    });
    this.next.push(() => answer);
    return { respond, fail };
  }
}

function result(response: unknown) {
  return { context: CONTEXT, response };
}

function rejection(error: unknown): Promise<never> {
  // eslint-disable-next-line @typescript-eslint/prefer-promise-reject-errors -- as the real socket
  return Promise.reject(error);
}

/** Answer as the integration did when the fixtures were recorded. */
function answerAsRecorded(message: MessageBase): Promise<unknown> {
  const service: unknown = message["service"];
  const data: unknown = message["service_data"];
  const which: unknown =
    typeof data === "object" && data !== null
      ? (Reflect.get(data, "kind") ?? Reflect.get(data, "mode"))
      : undefined;
  const response =
    service === "get_bizi_station"
      ? biziStation
      : ANSWERS[String(service)]?.[String(which)];
  if (response === undefined) {
    return Promise.reject(new Error(`No recorded answer for ${JSON.stringify(message)}`));
  }
  return Promise.resolve(result(response));
}
