import { ActionError, DOMAIN, UnexpectedResponseError } from "./api";
import { isTranslationKey, localize } from "./localize";
import type { HomeAssistant } from "./types";

/**
 * The clock time of an ISO 8601 moment as HH:MM, in the time zone the user's profile
 * asks for: the server's, or the browser's.
 */
export function clockTime(hass: Pick<HomeAssistant, "locale" | "config">, iso: string): string {
  const zone = hass.locale.time_zone === "server" ? { timeZone: hass.config.time_zone } : {};
  return new Intl.DateTimeFormat(hass.locale.language, {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    ...zone,
  }).format(new Date(iso));
}

/**
 * What to tell the user about a failed call, in their language. Home Assistant's own
 * message is English, so the card says it with its text for the error's key.
 */
export function errorText(hass: Pick<HomeAssistant, "locale">, error: unknown): string {
  if (error instanceof UnexpectedResponseError) return localize(hass, "error.unexpected_response");
  if (error instanceof ActionError && error.translationDomain === DOMAIN) {
    const key = `error.${error.translationKey ?? ""}`;
    if (isTranslationKey(key)) return localize(hass, key, error.translationPlaceholders);
  }
  // No key, one this card doesn't know, another domain's, or no answer at all.
  return localize(hass, "error.generic");
}
