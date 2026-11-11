import { isNumber, isString } from "./guards";
import type { Kind, RawCardConfig } from "./types";

export const KINDS = ["tram", "bus", "bizi"] as const satisfies readonly Kind[];

export const NEAREST = { min: 1, max: 10, default: 5 } as const;

const DEFAULT_HOME_ZONE = "zone.home";

/** The card's settings, with every default filled in. */
export interface Settings {
  /** The modes shown, in the order configured, each once; never empty. */
  readonly modes: readonly [Kind, ...Kind[]];
  /** Always one of `modes`. */
  readonly defaultMode: Kind;
  /** A whole number from `NEAREST.min` to `NEAREST.max`. */
  readonly nearest: number;
  readonly homeZone: string;
  readonly showZones: boolean;
  /** Undefined: the logged-in user's person. */
  readonly myLocationEntity: string | undefined;
}

export function isKind(value: unknown): value is Kind {
  return KINDS.some((kind) => kind === value);
}

/**
 * Check the dashboard's settings for the card and fill in the defaults.
 *
 * A setting of the wrong type, an unknown mode or no modes at all throws an `Error`
 * naming the setting, which Home Assistant shows on the card (and the editor, by falling
 * back to YAML). Within the right types, the card makes do: a default mode that isn't
 * shown becomes the first shown, `nearest` is rounded into 1–10, a repeated mode counts
 * once, and an empty person means the logged-in user's.
 */
export function settingsOf(config: RawCardConfig): Settings {
  const modes = modesOf(config["modes"]);
  const defaultMode = optional(config, "default_mode", isKind, "one of tram, bus, bizi");
  const nearest = optional(config, "nearest", isNumber, "a number");
  const homeZone = optional(config, "home_zone", isString, "an entity id, such as zone.home");
  const showZones = optional(config, "show_zones", isBoolean, "true or false");
  const person = optional(config, "my_location_entity", isString, "an entity id, such as person.ana");
  return {
    modes,
    defaultMode: defaultMode !== undefined && modes.includes(defaultMode) ? defaultMode : modes[0],
    nearest: Math.min(Math.max(Math.round(nearest ?? NEAREST.default), NEAREST.min), NEAREST.max),
    homeZone: homeZone ?? DEFAULT_HOME_ZONE,
    showZones: showZones ?? true,
    myLocationEntity: person === "" ? undefined : person,
  };
}

function modesOf(value: unknown): Settings["modes"] {
  if (value === undefined) return KINDS;
  const kinds = Array.isArray(value) ? value.filter(isKind) : [];
  if (!Array.isArray(value) || kinds.length !== value.length) {
    throw new Error("modes must be a list of tram, bus and bizi");
  }
  const [first, ...rest] = [...new Set(kinds)];
  if (first === undefined) throw new Error("modes must list at least one of tram, bus and bizi");
  return [first, ...rest];
}

function optional<T>(
  config: RawCardConfig,
  name: string,
  guard: (value: unknown) => value is T,
  expected: string,
): T | undefined {
  const value = config[name];
  if (value === undefined || guard(value)) return value;
  throw new Error(`${name} must be ${expected}`);
}

function isBoolean(value: unknown): value is boolean {
  return typeof value === "boolean";
}
