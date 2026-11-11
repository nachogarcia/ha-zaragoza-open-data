import en from "./translations/en.json";
import es from "./translations/es.json";
import type { HomeAssistant } from "./types";

export type TranslationKey = keyof typeof en;

// Typed against the English keys, so a key missing in Spanish fails the type check.
const spanish: Record<TranslationKey, string> = es;

/** Whether the card has a text for `key`, as for a key built from an error's. */
export function isTranslationKey(key: string): key is TranslationKey {
  return Object.hasOwn(en, key);
}

/**
 * Return the card's text for `key` in the user's Home Assistant language: Spanish for
 * any Spanish variant, else English. `{name}` placeholders are filled from `vars`.
 */
export function localize(
  hass: Pick<HomeAssistant, "locale">,
  key: TranslationKey,
  vars: Readonly<Record<string, string | number>> = {},
): string {
  const text = hass.locale.language.startsWith("es") ? spanish[key] : en[key];
  return text.replace(/\{(\w+)\}/g, (placeholder, name: string) =>
    Object.hasOwn(vars, name) ? String(vars[name]) : placeholder,
  );
}
