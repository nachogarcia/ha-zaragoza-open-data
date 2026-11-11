import { describe, expect, it } from "vitest";

import { localize } from "../../src/localize";
import en from "../../src/translations/en.json";
import es from "../../src/translations/es.json";

const speaking = (language: string) => ({ locale: { language } });

describe("localize", () => {
  it.each(["es", "es-ES", "es-419"])("speaks Spanish to %s", (language) => {
    expect(localize(speaking(language), "mode.tram")).toBe("Tranvía");
  });

  it.each(["en", "en-GB", "fr", "ca", "eu"])("speaks English to %s", (language) => {
    expect(localize(speaking(language), "mode.tram")).toBe("Tram");
  });

  it("fills in the placeholders", () => {
    expect(localize(speaking("es-ES"), "stop.distance", { distance: 150 })).toBe("a 150 m");
    expect(localize(speaking("en"), "stop.distance", { distance: 150 })).toBe("150 m away");
  });
});

describe("translations", () => {
  const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

  it("have the same keys in English and Spanish", () => {
    expect(Object.keys(es).sort()).toStrictEqual(Object.keys(en).sort());
  });

  it("have the same placeholders in English and Spanish", () => {
    const english: Record<string, string> = en;
    const spanish: Record<string, string> = es;

    for (const [key, text] of Object.entries(english)) {
      expect(placeholders(spanish[key] ?? ""), key).toStrictEqual(placeholders(text));
    }
  });
});
