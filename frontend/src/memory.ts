import { KINDS } from "./config";
import { isRecord, isString } from "./guards";
import type { Kind } from "./types";

// Each phone keeps its own stops: the last one opened for each mode, in this browser.
// One key for the card, with a version, so another shape later reads as nothing saved.
const KEY = "zaragoza-open-data-card.last-stops";
const VERSION = 1;

export interface SavedStop {
  readonly code: string;
  readonly name: string;
}

type Saved = { [K in Kind]?: SavedStop };

/** The stop last opened for `kind` in this browser, if any. */
export function savedStop(kind: Kind): SavedStop | undefined {
  return readSaved()[kind];
}

/** Remember `stop` as the last opened for `kind`. */
export function saveStop(kind: Kind, stop: SavedStop): void {
  const stops: Saved = { ...readSaved(), [kind]: { code: stop.code, name: stop.name } };
  try {
    localStorage.setItem(KEY, JSON.stringify({ version: VERSION, stops }));
  } catch {
    // Storage refused (private browsing, full, blocked): the phone just won't remember.
  }
}

function readSaved(): Saved {
  let value: unknown;
  try {
    const text = localStorage.getItem(KEY);
    value = text === null ? undefined : JSON.parse(text);
  } catch {
    return {};
  }
  if (!isRecord(value) || value["version"] !== VERSION) return {};
  const stops = value["stops"];
  const saved: Saved = {};
  if (!isRecord(stops)) return saved;
  for (const kind of KINDS) {
    const stop = stops[kind];
    if (isRecord(stop) && isString(stop["code"]) && isString(stop["name"])) {
      saved[kind] = { code: stop["code"], name: stop["name"] };
    }
  }
  return saved;
}
