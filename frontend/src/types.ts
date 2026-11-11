import type { HassConfig, HassEntities, HassUser } from "home-assistant-js-websocket";

import type { HassSocket } from "./api";

/**
 * What the card reads from the `hass` object the dashboard hands it. Of the socket, a
 * `Connection`, it needs only what the action client sends with, so tests can hand it a
 * fake one; `test/types/home-assistant.ts` checks that the library's `Connection` fits.
 */
export interface HomeAssistant {
  readonly states: HassEntities;
  // Missing until the frontend has fetched the logged-in user.
  readonly user?: HassUser;
  readonly locale: {
    readonly language: string;
    /** The user's profile choice: times in the server's time zone, or the browser's. */
    readonly time_zone?: "local" | "server";
  };
  readonly config: Pick<HassConfig, "time_zone">;
  readonly connection: HassSocket["connection"];
}

/** The kinds with stops or stations, as the actions name them. */
export type Kind = "tram" | "bus" | "bizi";

/** The kinds with arrivals. */
export type Mode = Exclude<Kind, "bizi">;

// The answers below mirror `responses.py` field for field; the Python acceptance
// snapshots of those answers are the card's test fixtures.

/** One `find_stops` result: a stop, or a Bizi station (no direction, no lines). */
export interface FoundStop {
  readonly code: string;
  readonly name: string;
  readonly direction: string | null;
  readonly lines: readonly string[];
  readonly distance_m: number;
  readonly latitude: number;
  readonly longitude: number;
}

export interface FindStopsResponse {
  readonly stops: readonly FoundStop[];
}

export interface Arrival {
  readonly line: string;
  readonly destination: string;
  readonly minutes: number;
  /** ISO 8601, in Home Assistant's time zone. */
  readonly time: string;
}

export interface ArrivalsResponse {
  readonly stop: {
    readonly code: string;
    readonly name: string;
    readonly direction: string | null;
  };
  readonly arrivals: readonly Arrival[];
  readonly source: string;
  /** ISO 8601, in Home Assistant's time zone. */
  readonly updated: string;
}

export interface BiziResponse {
  readonly station: { readonly code: string; readonly name: string };
  readonly bikes: number;
  // Null while the city's list stands in for the operator's: it doesn't split them.
  readonly electric: number | null;
  readonly mechanical: number | null;
  readonly docks: number;
  readonly renting: boolean;
  readonly returning: boolean;
  readonly source: string;
  /** ISO 8601, in Home Assistant's time zone. */
  readonly updated: string;
}

/**
 * What the dashboard hands `setConfig`: written by hand in YAML, it may hold anything, and
 * other keys the dashboard keeps (layout, visibility). `settingsOf` checks it.
 */
export type RawCardConfig = Readonly<Record<string, unknown>>;

/** The card's settings, as the editor writes them. */
export type CardConfig = {
  readonly type: string;
  readonly modes?: readonly Kind[];
  readonly default_mode?: Kind;
  /** How many nearest stops the location chips list. */
  readonly nearest?: number;
  readonly home_zone?: string;
  readonly show_zones?: boolean;
  /** The entity whose position is "my location"; by default the user's person. */
  readonly my_location_entity?: string;
};
