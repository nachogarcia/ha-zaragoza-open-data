import type { HassEntity } from "home-assistant-js-websocket";

import { isNumber, isString } from "./guards";
import type { HomeAssistant } from "./types";

export interface Point {
  readonly latitude: number;
  readonly longitude: number;
}

export interface Zone {
  readonly entityId: string;
  readonly name: string;
  readonly point: Point;
}

/** Where an entity is, when Home Assistant knows: a person's phone, a zone's centre. */
export function pointOf(entity: HassEntity | undefined): Point | undefined {
  if (entity === undefined) return undefined;
  const latitude: unknown = entity.attributes["latitude"];
  const longitude: unknown = entity.attributes["longitude"];
  return isNumber(latitude) && isNumber(longitude) ? { latitude, longitude } : undefined;
}

/** The entity that is "my location": the one configured, else the logged-in user's person. */
export function myLocation(
  hass: Pick<HomeAssistant, "states" | "user">,
  configured: string | undefined,
): HassEntity | undefined {
  if (configured !== undefined) return hass.states[configured];
  const userId = hass.user?.id;
  if (userId === undefined) return undefined;
  return Object.values(hass.states).find(
    (entity) => entity.entity_id.startsWith("person.") && entity.attributes["user_id"] === userId,
  );
}

/** The zones to search near, by name: those with a point, but home, which has its own chip. */
export function zonesToChoose(
  hass: Pick<HomeAssistant, "states" | "locale">,
  homeZone: string,
): readonly Zone[] {
  const zones: Zone[] = [];
  for (const entity of Object.values(hass.states)) {
    if (!entity.entity_id.startsWith("zone.") || entity.entity_id === homeZone) continue;
    const point = pointOf(entity);
    const name: unknown = entity.attributes.friendly_name;
    if (point !== undefined) {
      zones.push({ entityId: entity.entity_id, name: isString(name) ? name : entity.entity_id, point });
    }
  }
  return zones.sort((a, b) => a.name.localeCompare(b.name, hass.locale.language));
}
