import type { MessageBase } from "home-assistant-js-websocket";

import { isNumber, isRecord, isString } from "./guards";
import type {
  Arrival,
  ArrivalsResponse,
  BiziResponse,
  FindStopsResponse,
  FoundStop,
  Kind,
  Mode,
} from "./types";

/** The integration whose actions these are, and whose errors the card can translate. */
export const DOMAIN = "zaragoza_open_data";

/** What the client needs of `hass`: the socket to call the actions on. */
export interface HassSocket {
  readonly connection: { sendMessagePromise(message: MessageBase): Promise<unknown> };
}

/** A `find_stops` call: text, a point (both coordinates or neither, else home), or both. */
export type FindStopsQuery = {
  readonly kind: Kind;
  readonly query?: string;
  readonly limit?: number;
} & (
  | { readonly latitude: number; readonly longitude: number }
  | { readonly latitude?: never; readonly longitude?: never }
);

/**
 * Home Assistant answered the action with an error: an unknown stop, a kind switched
 * off, a source that doesn't answer. `message` is Home Assistant's text, which is in
 * English; the translation key and placeholders let the card say it in the user's
 * language.
 */
export class ActionError extends Error {
  override readonly name = "ActionError";
  readonly code: string;
  readonly translationKey: string | undefined;
  readonly translationDomain: string | undefined;
  readonly translationPlaceholders: Readonly<Record<string, string>>;

  constructor(error: HassError) {
    super(error.message);
    this.code = error.code;
    this.translationKey = error.translation_key ?? undefined;
    this.translationDomain = error.translation_domain ?? undefined;
    this.translationPlaceholders = error.translation_placeholders ?? {};
  }
}

/** The action answered, but not in the shape this card knows. */
export class UnexpectedResponseError extends Error {
  override readonly name = "UnexpectedResponseError";

  constructor(readonly service: string) {
    super(`Unexpected response from ${DOMAIN}.${service}`);
  }
}

/** Return the stops or stations `find_stops` ranks first: nearest, or best matching. */
export async function findStops(
  hass: HassSocket,
  query: FindStopsQuery,
): Promise<readonly FoundStop[]> {
  const serviceData: Record<string, string | number> = { kind: query.kind };
  if (query.query !== undefined) serviceData["query"] = query.query;
  if (query.latitude !== undefined) {
    serviceData["latitude"] = query.latitude;
    serviceData["longitude"] = query.longitude;
  }
  if (query.limit !== undefined) serviceData["limit"] = query.limit;
  const response = await callAction(hass, "find_stops", serviceData, isFindStopsResponse);
  return response.stops;
}

/** Return what comes next to a tram platform or bus stop. */
export function getArrivals(hass: HassSocket, mode: Mode, stop: string): Promise<ArrivalsResponse> {
  return callAction(hass, "get_arrivals", { mode, stop }, isArrivalsResponse);
}

/** Return a Bizi station's bikes and free docks. */
export function getBiziStation(hass: HassSocket, station: string): Promise<BiziResponse> {
  return callAction(hass, "get_bizi_station", { station }, isBiziResponse);
}

/**
 * Call one of the integration's actions for its response, and check its shape.
 *
 * A call that fails without an error from Home Assistant (the connection is lost)
 * rejects with whatever the socket rejected with.
 */
async function callAction<T>(
  hass: HassSocket,
  service: string,
  serviceData: Readonly<Record<string, string | number>>,
  isResponse: (value: unknown) => value is T,
): Promise<T> {
  let result: unknown;
  try {
    result = await hass.connection.sendMessagePromise({
      type: "call_service",
      domain: DOMAIN,
      service,
      service_data: serviceData,
      return_response: true,
    });
  } catch (err: unknown) {
    throw isHassError(err) ? new ActionError(err) : err;
  }
  const response = isRecord(result) ? result["response"] : undefined;
  if (!isResponse(response)) {
    throw new UnexpectedResponseError(service);
  }
  return response;
}

// The error Home Assistant sends when an action fails. With a translation key it
// always sends the domain and placeholders too, as null when there are none.
interface HassError {
  readonly code: string;
  readonly message: string;
  readonly translation_key?: string | null;
  readonly translation_domain?: string | null;
  readonly translation_placeholders?: Readonly<Record<string, string>> | null;
}

function isHassError(value: unknown): value is HassError {
  return (
    isRecord(value) &&
    isString(value["code"]) &&
    isString(value["message"]) &&
    isAbsentOr(value["translation_key"], isString) &&
    isAbsentOr(value["translation_domain"], isString) &&
    isAbsentOr(value["translation_placeholders"], isPlaceholders)
  );
}

function isPlaceholders(value: unknown): value is Readonly<Record<string, string>> {
  return isRecord(value) && Object.values(value).every(isString);
}

// Type guards for the answers: each checks every field `responses.py` sends.

function isFindStopsResponse(value: unknown): value is FindStopsResponse {
  return isRecord(value) && isArrayOf(value["stops"], isFoundStop);
}

function isFoundStop(value: unknown): value is FoundStop {
  return (
    isRecord(value) &&
    isString(value["code"]) &&
    isString(value["name"]) &&
    isNullable(value["direction"], isString) &&
    isArrayOf(value["lines"], isString) &&
    isInteger(value["distance_m"]) &&
    isNumber(value["latitude"]) &&
    isNumber(value["longitude"])
  );
}

function isArrivalsResponse(value: unknown): value is ArrivalsResponse {
  if (!isRecord(value)) return false;
  const stop = value["stop"];
  return (
    isRecord(stop) &&
    isString(stop["code"]) &&
    isString(stop["name"]) &&
    isNullable(stop["direction"], isString) &&
    isArrayOf(value["arrivals"], isArrival) &&
    isString(value["source"]) &&
    isTime(value["updated"])
  );
}

function isArrival(value: unknown): value is Arrival {
  return (
    isRecord(value) &&
    isString(value["line"]) &&
    isString(value["destination"]) &&
    isInteger(value["minutes"]) &&
    isTime(value["time"])
  );
}

function isBiziResponse(value: unknown): value is BiziResponse {
  if (!isRecord(value)) return false;
  const station = value["station"];
  return (
    isRecord(station) &&
    isString(station["code"]) &&
    isString(station["name"]) &&
    isInteger(value["bikes"]) &&
    isNullable(value["electric"], isInteger) &&
    isNullable(value["mechanical"], isInteger) &&
    isInteger(value["docks"]) &&
    isBoolean(value["renting"]) &&
    isBoolean(value["returning"]) &&
    isString(value["source"]) &&
    isTime(value["updated"])
  );
}

function isInteger(value: unknown): value is number {
  return Number.isInteger(value);
}

function isBoolean(value: unknown): value is boolean {
  return typeof value === "boolean";
}

/** An ISO 8601 time, which the card shows as a clock time. */
function isTime(value: unknown): value is string {
  return isString(value) && !Number.isNaN(Date.parse(value));
}

function isNullable<T>(value: unknown, guard: (value: unknown) => value is T): value is T | null {
  return value === null || guard(value);
}

/** Absent, null, or passing `guard`. */
function isAbsentOr<T>(
  value: unknown,
  guard: (value: unknown) => value is T,
): value is T | null | undefined {
  return value === undefined || value === null || guard(value);
}

function isArrayOf<T>(value: unknown, guard: (value: unknown) => value is T): value is T[] {
  return Array.isArray(value) && value.every(guard);
}
