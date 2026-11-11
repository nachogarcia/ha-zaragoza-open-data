// Compile-time checks, with no code to run: `npm run typecheck` fails when they drift.
import type { Connection } from "home-assistant-js-websocket";

import type { HassSocket } from "../../src/api";
import type { HomeAssistant } from "../../src/types";

type Fits<Value extends Target, Target> = Value;

/** The dashboard's `hass` is all the action client needs. */
export type HomeAssistantFitsHassSocket = Fits<HomeAssistant, HassSocket>;

/** The library's socket, which the real `hass` carries, is what the card asks of it. */
export type ConnectionFitsHomeAssistant = Fits<Connection, HomeAssistant["connection"]>;
