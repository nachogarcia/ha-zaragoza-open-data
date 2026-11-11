import type { HassEntity } from "home-assistant-js-websocket";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ZaragozaOpenDataCard } from "../../src/zaragoza-open-data-card";
import {
  CARD_TYPE,
  chooseZone,
  footer,
  labels,
  mount,
  pressed,
  rows,
  setVisibility,
  settle,
  shown,
  tap,
  tapStop,
  typeStop,
  wait,
  zoneDropdownName,
  zoneOptions,
} from "../support/card-dom";
import { FakeHome, callOf, person, recorded, zone } from "../support/fake-hass";
import type { FakeHomeOptions } from "../support/fake-hass";

const ANA = { latitude: 41.6488, longitude: -0.8891 };
const LUIS = { latitude: 41.6561, longitude: -0.8773 };
const HOME = { latitude: 41.627, longitude: -0.9073 };
const WORK = { latitude: 41.6833, longitude: -0.8888 };
const GYM = { latitude: 41.64, longitude: -0.9 };

const STATES: readonly HassEntity[] = [
  person("ana", "u-ana", ANA),
  person("luis", "u-luis", LUIS),
  zone("home", "Casa", HOME),
  zone("trabajo", "Trabajo", WORK),
  zone("gimnasio", "Gimnasio", GYM),
  // Not a real zone's shape, but any entity in the zone domain may lack a point.
  zone("sin_sitio", "Sin sitio"),
];

/** Ana's house: she is logged in, her phone reports where she is. */
function house(options: FakeHomeOptions = {}) {
  return new FakeHome({ userId: "u-ana", states: STATES, ...options });
}

const MINUTE = 60_000;

const TRAM_SUGGESTIONS = [
  "Plaza del Pilar - Murallas hacia Mago de Oz a 1104 m",
  "Plaza del Pilar - Murallas hacia Avenida de la Academia a 1104 m",
];
const TRAM_BOARD = ["L1 Avenida Academia 4 min 13:44", "L1 Avenida Academia 8 min 13:48"];
const OPEN_1102 = callOf("get_arrivals", { mode: "tram", stop: "1102" });
const SOURCE_DOWN_ES = "La fuente de estos datos no responde ahora mismo";
const GENERIC_ES = "Algo ha fallado al hablar con Home Assistant: vuelve a intentarlo";

/** Open the tram platform towards Avenida de la Academia, near home. */
async function openTramStop(card: ZaragozaOpenDataCard): Promise<void> {
  await tap(card, "Casa");
  await tapStop(card, "Avenida de la Academia");
}

beforeEach(async () => {
  vi.useFakeTimers();
  // 2 s after the recorded tram list was read: the opened tram stop is then asked again
  // each whole minute, as the card does 2 s after each minute of a reading.
  vi.setSystemTime(Date.parse(recorded.tramArrivals.updated) + 2_000);
  localStorage.clear();
  await setVisibility("visible");
});

afterEach(() => {
  document.body.replaceChildren();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("modes", () => {
  it("renders only configured modes", async () => {
    const card = await mount(house(), { modes: ["bus", "bizi"] });

    expect(labels(card)).toStrictEqual([
      "Bus",
      "Bizi",
      "Mi ubicación",
      "Casa",
      "Zona",
      "Escribir parada…",
    ]);
    expect(pressed(card)).toStrictEqual(["Bus"]);
  });

  it.each([
    ["the default mode", { default_mode: "bizi" }, "Bizi", "bizi"],
    ["the first mode when the default isn't shown", { modes: ["bus", "bizi"], default_mode: "tram" }, "Bus", "bus"],
  ] as const)("opens on %s", async (_case, config, chip, kind) => {
    const home = house();
    const card = await mount(home, config);

    await tap(card, "Casa");

    expect(pressed(card)).toStrictEqual([chip, "Casa"]);
    expect(home.sent).toStrictEqual([callOf("find_stops", { kind, ...HOME, limit: 5 })]);
  });

  it("switching mode searches the same place for that kind", async () => {
    const home = house();
    const card = await mount(home);

    await tap(card, "Casa");
    await tap(card, "Bus");

    expect(home.sent).toStrictEqual([
      callOf("find_stops", { kind: "tram", ...HOME, limit: 5 }),
      callOf("find_stops", { kind: "bus", ...HOME, limit: 5 }),
    ]);
    expect(pressed(card)).toStrictEqual(["Bus", "Casa"]);
    expect(rows(card)).toStrictEqual([
      "P. Reyes de Aragón N.º 24 58 a 0 m",
      "P. Infantes de España N.º 1 / Vía Ibérica 58 a 53 m",
      "Vía Ibérica N.º 33 / P. Infantes de España N4 a 118 m",
    ]);
  });
});

describe("typing a stop", () => {
  it("typing two characters calls findStops once after 500 ms", async () => {
    const home = house();
    const card = await mount(home);
    await tap(card, "Escribir parada…");

    await typeStop(card, "p");
    await typeStop(card, "pi");
    await wait(499);

    expect(home.sent).toStrictEqual([]);

    await wait(1);

    expect(home.sent).toStrictEqual([callOf("find_stops", { kind: "tram", query: "pi", limit: 8 })]);
    expect(rows(card)).toStrictEqual(TRAM_SUGGESTIONS);

    await wait(5 * MINUTE);

    expect(home.sent).toHaveLength(1);
  });

  it("one character does not search", async () => {
    const home = house();
    const card = await mount(home);
    await tap(card, "Escribir parada…");

    await typeStop(card, "p");
    await wait(MINUTE);
    // Nor does going back to one character before the pause is over.
    await typeStop(card, "pi");
    await wait(300);
    await typeStop(card, "p");
    await wait(MINUTE);

    expect(home.sent).toStrictEqual([]);
  });

  it("selecting a suggestion opens arrivals", async () => {
    const home = house();
    const card = await mount(home);
    await tap(card, "Escribir parada…");
    await typeStop(card, "pilar");
    await wait(500);

    await tapStop(card, "Avenida de la Academia");

    expect(home.take()).toStrictEqual([
      callOf("find_stops", { kind: "tram", query: "pilar", limit: 8 }),
      OPEN_1102,
    ]);
    expect(shown(card)).toContain("Mago de Oz hacia Avenida de la Academia");
    expect(rows(card)).toStrictEqual(TRAM_BOARD);
  });

  it("says when no stop matches", async () => {
    const home = house();
    const card = await mount(home);
    await tap(card, "Escribir parada…");
    home.respondNext({ stops: [] });

    await typeStop(card, "zzz");
    await wait(500);

    expect(shown(card)).toContain("No se ha encontrado ninguna parada");
    expect(rows(card)).toStrictEqual([]);
  });
});

describe("nearest stops", () => {
  it("my location uses the current user's person coordinates", async () => {
    const home = house();
    const card = await mount(home);

    await tap(card, "Mi ubicación");

    expect(home.sent).toStrictEqual([callOf("find_stops", { kind: "tram", ...ANA, limit: 5 })]);
    expect(pressed(card)).toStrictEqual(["Tranvía", "Mi ubicación"]);
    expect(rows(card)).toStrictEqual(TRAM_SUGGESTIONS);
  });

  it("my location can be another entity, as configured", async () => {
    const home = house();
    const card = await mount(home, { my_location_entity: "person.luis" });

    await tap(card, "Mi ubicación");

    expect(home.sent).toStrictEqual([callOf("find_stops", { kind: "tram", ...LUIS, limit: 5 })]);
  });

  it.each([
    ["no one is logged in", {}, { userId: undefined }],
    ["the user is no person", {}, { userId: "u-guest" }],
    ["the configured entity doesn't exist", { my_location_entity: "person.nadie" }, {}],
  ])("my location isn't offered when %s", async (_case, config, options) => {
    const card = await mount(house(options), config);

    expect(labels(card)).not.toContain("Mi ubicación");
    expect(labels(card)).toContain("Casa");
  });

  it.each([
    ["my location", "Mi ubicación", [person("ana", "u-ana"), zone("home", "Casa", HOME)]],
    ["home", "Casa", [person("ana", "u-ana", ANA), zone("home", "Casa")]],
  ])("%s without coordinates explains and sends nothing", async (_place, chip, states) => {
    const home = house({ states });
    const card = await mount(home);

    await tap(card, chip);

    expect(shown(card)).toContain("Home Assistant no sabe ahora dónde está");
    expect(home.sent).toStrictEqual([]);
  });

  it("home searches near the configured home zone, as many stops as configured", async () => {
    const home = house();
    const card = await mount(home, { home_zone: "zone.trabajo", nearest: 3 });

    await tap(card, "Casa");

    expect(home.sent).toStrictEqual([callOf("find_stops", { kind: "tram", ...WORK, limit: 3 })]);
  });

  it("home isn't offered when the home zone doesn't exist", async () => {
    const card = await mount(house(), { home_zone: "zone.pueblo" });

    expect(labels(card)).not.toContain("Casa");
    expect(labels(card)).toContain("Mi ubicación");
  });

  it("zone chip searches near the chosen zone", async () => {
    const home = house();
    const card = await mount(home);

    await tap(card, "Zona");
    // Zones with a point, other than home, by name.
    expect(zoneOptions(card)).toStrictEqual(["Gimnasio", "Trabajo"]);
    expect(zoneDropdownName(card)).toBe("Zona");
    await chooseZone(card, "zone.trabajo");

    expect(home.sent).toStrictEqual([
      callOf("find_stops", { kind: "tram", ...GYM, limit: 5 }),
      callOf("find_stops", { kind: "tram", ...WORK, limit: 5 }),
    ]);
    expect(pressed(card)).toStrictEqual(["Tranvía", "Zona"]);
    expect(rows(card)).toStrictEqual(TRAM_SUGGESTIONS);
  });

  it.each([
    ["zones are switched off", { show_zones: false }, STATES],
    ["no other zone has a point", {}, [zone("home", "Casa", HOME), zone("sin_sitio", "Sin sitio")]],
  ])("zones aren't offered when %s", async (_case, config, states) => {
    const card = await mount(house({ states }), config);

    expect(labels(card)).not.toContain("Zona");
    expect(labels(card)).toContain("Casa");
  });

  it("tapping a listed stop opens it", async () => {
    const home = house();
    const card = await mount(home);

    await openTramStop(card);

    expect(home.sent).toStrictEqual([
      callOf("find_stops", { kind: "tram", ...HOME, limit: 5 }),
      OPEN_1102,
    ]);
    expect(rows(card)).toStrictEqual(TRAM_BOARD);
  });
});

describe("the opened stop", () => {
  it("says when nothing is coming, as at night", async () => {
    const home = house();
    const card = await mount(home);
    await tap(card, "Casa");
    home.respondNext({ ...recorded.tramArrivals, arrivals: [] });

    await tapStop(card, "Avenida de la Academia");

    expect(shown(card)).toContain("Ahora no hay llegadas");
    expect(rows(card)).toStrictEqual([]);
  });

  it("renders a bus stop's arrivals", async () => {
    const home = house();
    const card = await mount(home, { modes: ["bus"] });
    await tap(card, "Casa");

    await tapStop(card, "P. Reyes de Aragón N.º 24");

    expect(home.sent.at(-1)).toStrictEqual(callOf("get_arrivals", { mode: "bus", stop: "688" }));
    expect(shown(card)).toContain("La Lista de Schindler");
    expect(rows(card)).toStrictEqual([
      "59 TRANVIA-ARCOSUR 7 min 13:47",
      "56 VALDESPARTERA 22 min 14:02",
      "59 TRANVIA-ARCOSUR 27 min 14:07",
      "56 VALDESPARTERA 48 min 14:28",
    ]);
  });

  it("renders Bizi electric, mechanical and docks", async () => {
    const home = house();
    const card = await mount(home, { modes: ["bizi"] });
    await tap(card, "Casa");

    await tapStop(card, "H. Cortés: Pza. Arregui");

    expect(home.sent).toStrictEqual([
      callOf("find_stops", { kind: "bizi", ...HOME, limit: 5 }),
      callOf("get_bizi_station", { station: "48" }),
    ]);
    expect(shown(card)).toContain("Rosales: Illueca");
    expect(rows(card)).toStrictEqual(["4 Eléctricas", "0 Mecánicas", "15 Anclajes libres"]);
  });

  it("renders the bike total while the city's list stands in", async () => {
    const home = house();
    const card = await mount(home, { modes: ["bizi"] });
    await tap(card, "Casa");
    home.respondNext({ ...recorded.biziStation, electric: null, mechanical: null, source: "zaragoza_city" });

    await tapStop(card, "Pta. del Carmen");

    expect(rows(card)).toStrictEqual(["4 Bicis", "15 Anclajes libres"]);
  });

  it("says when a station isn't lending or taking bikes", async () => {
    const home = house();
    const card = await mount(home, { modes: ["bizi"] });
    await tap(card, "Casa");
    home.respondNext({ ...recorded.biziStation, renting: false, returning: false });

    await tapStop(card, "Pta. del Carmen");

    expect(shown(card)).toContain("Ahora no presta bicis");
    expect(shown(card)).toContain("Ahora no admite devoluciones");
  });
});

describe("the footer", () => {
  const CITY_ES = "Origen de los datos: Ayuntamiento de Zaragoza";

  it("names the city while no stop is open", async () => {
    const card = await mount(house());

    expect(footer(card)).toBe(CITY_ES);
  });

  it("names the city for a tram stop", async () => {
    const card = await mount(house());

    await openTramStop(card);

    expect(footer(card)).toBe(CITY_ES);
  });

  it("names the operator for a bus board it answered", async () => {
    const home = house();
    const card = await mount(home, { modes: ["bus"] });
    await tap(card, "Casa");

    await tapStop(card, "P. Reyes de Aragón N.º 24");

    expect(recorded.busArrivals.source).toBe("avanza");
    expect(footer(card)).toBe("Origen de los datos: Avanza Zaragoza");
  });

  it("names the city for a bus board the city answered", async () => {
    const home = house();
    const card = await mount(home, { modes: ["bus"] });
    await tap(card, "Casa");
    home.respondNext({ ...recorded.busArrivals, source: "zaragoza_city" });

    await tapStop(card, "P. Reyes de Aragón N.º 24");

    expect(footer(card)).toBe(CITY_ES);
  });

  it("names Bizi Zaragoza for a station from the operator's feed", async () => {
    const card = await mount(house(), { modes: ["bizi"] });
    await tap(card, "Casa");

    await tapStop(card, "H. Cortés: Pza. Arregui");

    expect(recorded.biziStation.source).toBe("gbfs");
    expect(footer(card)).toBe("Origen de los datos: Bizi Zaragoza");
  });

  it("names the city again when the stop is closed by switching mode", async () => {
    const card = await mount(house(), { modes: ["bizi", "tram"] });
    await tap(card, "Casa");
    await tapStop(card, "H. Cortés: Pza. Arregui");

    await tap(card, "Tranvía");

    expect(footer(card)).toBe(CITY_ES);
  });

  it("falls back to the city for a source it doesn't know", async () => {
    const home = house();
    const card = await mount(home, { modes: ["bus"] });
    await tap(card, "Casa");
    home.respondNext({ ...recorded.busArrivals, source: "someone_new" });

    await tapStop(card, "P. Reyes de Aragón N.º 24");

    expect(footer(card)).toBe(CITY_ES);
  });

  it("says it in English to an English speaker", async () => {
    const card = await mount(house({ language: "en" }), { modes: ["bus"] });
    await tap(card, "Home");

    await tapStop(card, "P. Reyes de Aragón N.º 24");

    expect(footer(card)).toBe("Data source: Avanza Zaragoza");
  });
});

describe("refresh timed from the reading", () => {
  const SECOND = 1_000;
  // When the recorded answers were read: the tram list at 13:40:02, the Bizi station at
  // 13:40:04 in Zaragoza. The stop's minutes sensor counts down a whole minute after.
  const TRAM_READ = Date.parse(recorded.tramArrivals.updated);
  const BIZI_READ = Date.parse(recorded.biziStation.updated);

  it("asks again 2 s after the reading's next whole minute, not 60 s after the answer", async () => {
    vi.setSystemTime(TRAM_READ + 30 * SECOND);
    const home = house();
    const card = await mount(home);
    await openTramStop(card);
    home.take();

    await wait(31 * SECOND);
    expect(home.take()).toStrictEqual([]);
    await wait(SECOND);
    // Reading + 62 s: 32 s after the answer.
    expect(home.take()).toStrictEqual([OPEN_1102]);

    // The same reading again, now 62 s old: the next whole minute after it, plus 2 s.
    await wait(MINUTE - 1);
    expect(home.take()).toStrictEqual([]);
    await wait(1);
    expect(home.take()).toStrictEqual([OPEN_1102]);
  });

  it("times a Bizi station from its last report", async () => {
    vi.setSystemTime(BIZI_READ + 30 * SECOND);
    const home = house();
    const card = await mount(home, { modes: ["bizi"] });
    await tap(card, "Casa");
    await tapStop(card, "H. Cortés: Pza. Arregui");
    home.take();

    await wait(32 * SECOND - 1);
    expect(home.take()).toStrictEqual([]);
    await wait(1);
    expect(home.take()).toStrictEqual([callOf("get_bizi_station", { station: "48" })]);
  });

  it("asks nothing while hidden, and times the next call from the answer it gets when shown", async () => {
    vi.setSystemTime(TRAM_READ + 30 * SECOND);
    const home = house();
    const card = await mount(home);
    await openTramStop(card);
    home.take();

    await setVisibility("hidden");
    await wait(5 * MINUTE);
    expect(home.take()).toStrictEqual([]);

    // Shown at reading + 5 min 30 s: asked at once, then at reading + 6 min 2 s.
    await setVisibility("visible");
    expect(home.take()).toStrictEqual([OPEN_1102]);
    await wait(32 * SECOND - 1);
    expect(home.take()).toStrictEqual([]);
    await wait(1);
    expect(home.take()).toStrictEqual([OPEN_1102]);
  });
});

describe("refresh", () => {
  it("refreshes every 60 s only while visible", async () => {
    const home = house();
    const card = await mount(home);
    await openTramStop(card);
    home.take();

    await wait(MINUTE - 1);
    expect(home.take()).toStrictEqual([]);
    await wait(1);
    // Only the opened stop: the nearest list isn't refreshed.
    expect(home.take()).toStrictEqual([OPEN_1102]);

    await setVisibility("hidden");
    await wait(10 * MINUTE);
    expect(home.take()).toStrictEqual([]);

    await setVisibility("visible");
    expect(home.take()).toStrictEqual([OPEN_1102]);
    await wait(MINUTE);
    expect(home.take()).toStrictEqual([OPEN_1102]);
    expect(rows(card)).toStrictEqual(TRAM_BOARD);
  });

  it("stops refreshing when hidden and on disconnect", async () => {
    const home = house();
    const card = await mount(home);
    await openTramStop(card);
    home.take();

    await setVisibility("hidden");
    await wait(5 * MINUTE);
    expect(home.take()).toStrictEqual([]);

    await setVisibility("visible");
    expect(home.take()).toStrictEqual([OPEN_1102]);

    card.remove();
    await wait(5 * MINUTE);
    await setVisibility("hidden");
    await setVisibility("visible");
    await wait(5 * MINUTE);
    expect(home.take()).toStrictEqual([]);
  });

  it("refreshes at once when the card is put back on the page", async () => {
    const home = house();
    const card = await mount(home);
    await openTramStop(card);
    card.remove();
    home.take();

    document.body.append(card);
    await settle();
    expect(home.take()).toStrictEqual([OPEN_1102]);
    await wait(MINUTE);
    expect(home.take()).toStrictEqual([OPEN_1102]);
  });

  it.each([
    ["the page is hidden", async () => setVisibility("hidden")],
    [
      "the card is removed",
      async (card: ZaragozaOpenDataCard) => {
        card.remove();
        await settle();
      },
    ],
  ])("an answer arriving after %s starts no refresh", async (_case, leave) => {
    const home = house();
    const card = await mount(home);
    await tap(card, "Casa");
    const slow = home.holdNext();
    await tapStop(card, "Avenida de la Academia");
    home.take();

    await leave(card);
    slow.respond(recorded.tramArrivals);
    await wait(10 * MINUTE);

    expect(home.take()).toStrictEqual([]);
  });

  it("setting hass again sends nothing", async () => {
    const home = house();
    const card = await mount(home);
    await openTramStop(card);
    home.take();

    // Home Assistant hands every card a new `hass` on each state change.
    for (let change = 0; change < 20; change++) {
      card.hass = { ...home.hass, states: { ...home.hass.states } };
      await settle();
    }
    expect(home.take()).toStrictEqual([]);

    await wait(MINUTE - 1);
    expect(home.take()).toStrictEqual([]);
    await wait(1);
    expect(home.take()).toStrictEqual([OPEN_1102]);
  });

  it("lists of stops are not refreshed", async () => {
    const home = house();
    const card = await mount(home);
    await tap(card, "Casa");
    home.take();

    await wait(10 * MINUTE);

    expect(home.take()).toStrictEqual([]);
  });
});

describe("errors", () => {
  it("shows translated error on unknown stop", async () => {
    const home = house();
    const card = await mount(home);
    await tap(card, "Casa");
    home.failNext(recorded.errorUnknownStop);

    await tapStop(card, "Avenida de la Academia");

    expect(shown(card)).toContain("Ninguna parada ni estación tiene el código 9999");
    expect(shown(card)).not.toContain("Validation error");
    expect(labels(card)).toContain("Reintentar");
  });

  it("says the error in English to an English speaker", async () => {
    const home = house({ language: "en" });
    const card = await mount(home);
    await tap(card, "Home");
    home.failNext(recorded.errorUnknownStop);

    await tapStop(card, "Avenida de la Academia");

    expect(shown(card)).toContain("No stop or station has the code 9999");
    expect(labels(card)).toContain("Retry");
  });

  it.each([
    ["the source being down", recorded.errorSourceUnavailable, SOURCE_DOWN_ES],
    [
      "a key the card doesn't know",
      { ...recorded.errorSourceUnavailable, translation_key: "brand_new" },
      GENERIC_ES,
    ],
    ["an error without a key", { code: "unknown_error", message: "Something broke" }, GENERIC_ES],
    [
      "Home Assistant's own error",
      {
        code: "service_not_found",
        message: "Action zaragoza_open_data.find_stops not found",
        translation_domain: "homeassistant",
        translation_key: "service_not_found",
        translation_placeholders: { domain: "zaragoza_open_data", service: "find_stops" },
      },
      GENERIC_ES,
    ],
    [
      "another integration's key, even one the card has",
      { ...recorded.errorUnknownStop, translation_domain: "other_integration" },
      GENERIC_ES,
    ],
    ["a lost connection", 3, GENERIC_ES],
  ])("translates %s", async (_case, error, text) => {
    const home = house();
    const card = await mount(home);
    home.failNext(error);

    await tap(card, "Casa");

    expect(shown(card)).toContain(text);
    expect(labels(card)).toContain("Reintentar");
  });

  it("says when the answer can't be read", async () => {
    const home = house();
    const card = await mount(home);
    home.respondNext({ stops: "688" });

    await tap(card, "Casa");

    expect(shown(card)).toContain(
      "Home Assistant ha enviado una respuesta que esta tarjeta no entiende: actualiza la integración y recarga la página",
    );
  });
});

describe("after an error", () => {
  /** Open a stop, then have the source go down for the next refresh. */
  async function failingRefresh(home: FakeHome): Promise<ZaragozaOpenDataCard> {
    const card = await mount(home);
    await openTramStop(card);
    home.failAlways(recorded.errorSourceUnavailable);
    await wait(MINUTE);
    expect(home.take()).toStrictEqual([
      callOf("find_stops", { kind: "tram", ...HOME, limit: 5 }),
      OPEN_1102,
      OPEN_1102,
    ]);
    expect(shown(card)).toContain(SOURCE_DOWN_ES);
    return card;
  }

  it("no further calls while visible, even after several minutes", async () => {
    const home = house();
    await failingRefresh(home);

    await wait(10 * MINUTE);

    expect(home.take()).toStrictEqual([]);
  });

  it("retry calls again", async () => {
    const home = house();
    const card = await failingRefresh(home);

    await tap(card, "Reintentar");

    expect(home.take()).toStrictEqual([OPEN_1102]);
    await wait(10 * MINUTE);
    expect(home.take()).toStrictEqual([]);
  });

  it("hidden then visible makes exactly one call", async () => {
    const home = house();
    await failingRefresh(home);

    await setVisibility("hidden");
    await setVisibility("visible");

    expect(home.take()).toStrictEqual([OPEN_1102]);
    await wait(10 * MINUTE);
    expect(home.take()).toStrictEqual([]);
  });

  it("reconnecting after an error retries once and stays backed off if it fails", async () => {
    const home = house();
    const card = await failingRefresh(home);

    card.remove();
    await wait(5 * MINUTE);
    expect(home.take()).toStrictEqual([]);
    document.body.append(card);
    await settle();

    expect(home.take()).toStrictEqual([OPEN_1102]);
    expect(shown(card)).toContain(SOURCE_DOWN_ES);
    await wait(10 * MINUTE);
    expect(home.take()).toStrictEqual([]);
  });

  it("a successful retry on reconnect resumes the 60 s refresh", async () => {
    const home = house();
    const card = await failingRefresh(home);
    card.remove();
    home.recover();

    document.body.append(card);
    await settle();

    expect(home.take()).toStrictEqual([OPEN_1102]);
    expect(rows(card)).toStrictEqual(TRAM_BOARD);
    expect(shown(card)).not.toContain(SOURCE_DOWN_ES);
    await wait(MINUTE);
    expect(home.take()).toStrictEqual([OPEN_1102]);
    await wait(MINUTE);
    expect(home.take()).toStrictEqual([OPEN_1102]);
  });

  it("success after a retry resumes the 60 s refresh", async () => {
    const home = house();
    const card = await failingRefresh(home);
    home.recover();

    await tap(card, "Reintentar");

    expect(home.take()).toStrictEqual([OPEN_1102]);
    expect(rows(card)).toStrictEqual(TRAM_BOARD);
    expect(shown(card)).not.toContain(SOURCE_DOWN_ES);
    await wait(MINUTE);
    expect(home.take()).toStrictEqual([OPEN_1102]);
    await wait(MINUTE);
    expect(home.take()).toStrictEqual([OPEN_1102]);
  });

});

describe("a failed search: each area backs off on its own", () => {
  it("the board keeps refreshing after a failed search is cleared", async () => {
    // Open a tram stop, the Casa search fails, tap "Escribir parada…".
    const home = house();
    const card = await mount(home);
    await openTramStop(card);
    home.failNext(recorded.errorSourceUnavailable);
    await tap(card, "Casa");
    await tap(card, "Escribir parada…");
    home.take();

    await wait(MINUTE);
    expect(home.take()).toStrictEqual([OPEN_1102]);
    await wait(MINUTE);
    expect(home.take()).toStrictEqual([OPEN_1102]);
    await wait(MINUTE);
    expect(home.take()).toStrictEqual([OPEN_1102]);
    expect(rows(card)).toStrictEqual(TRAM_BOARD);
  });

  it("a failed search leaves the open board refreshing", async () => {
    const home = house();
    const card = await mount(home);
    await openTramStop(card);
    home.failNext(recorded.errorSourceUnavailable);
    await tap(card, "Casa");
    home.take();

    expect(shown(card)).toContain(SOURCE_DOWN_ES);
    await wait(MINUTE);
    expect(home.take()).toStrictEqual([OPEN_1102]);
    await wait(MINUTE);
    expect(home.take()).toStrictEqual([OPEN_1102]);
    // The search itself is never repeated on its own; Retry repeats it once.
    expect(shown(card)).toContain(SOURCE_DOWN_ES);
    await tap(card, "Reintentar");
    expect(home.take()).toStrictEqual([callOf("find_stops", { kind: "tram", ...HOME, limit: 5 })]);
    expect(rows(card)).toStrictEqual([...TRAM_SUGGESTIONS, ...TRAM_BOARD]);
  });

  it("a failed board isn't restarted by a successful search", async () => {
    const home = house();
    const card = await mount(home);
    await openTramStop(card);
    home.failNext(recorded.errorSourceUnavailable);
    await wait(MINUTE);
    expect(shown(card)).toContain(SOURCE_DOWN_ES);
    home.take();

    await tap(card, "Casa");
    await wait(10 * MINUTE);
    expect(home.take()).toStrictEqual([callOf("find_stops", { kind: "tram", ...HOME, limit: 5 })]);

    // Only the board's own Retry resumes it.
    await tap(card, "Reintentar");
    expect(home.take()).toStrictEqual([OPEN_1102]);
    await wait(MINUTE);
    expect(home.take()).toStrictEqual([OPEN_1102]);
  });

  it("becoming visible doesn't repeat a failed search", async () => {
    const home = house();
    const card = await mount(home);
    home.failNext(recorded.errorSourceUnavailable);
    await tap(card, "Casa");
    home.take();

    await setVisibility("hidden");
    await setVisibility("visible");
    await wait(10 * MINUTE);

    expect(home.take()).toStrictEqual([]);
    expect(labels(card)).toContain("Reintentar");
  });
});

describe("late answers", () => {
  it("a slow earlier search does not replace a newer one", async () => {
    const home = house();
    const card = await mount(home);
    await tap(card, "Escribir parada…");
    const slow = home.holdNext();
    await typeStop(card, "pl");
    await wait(500);

    await typeStop(card, "pilar");
    await wait(500);
    slow.respond(recorded.findBusStops);
    await settle();

    expect(home.sent).toStrictEqual([
      callOf("find_stops", { kind: "tram", query: "pl", limit: 8 }),
      callOf("find_stops", { kind: "tram", query: "pilar", limit: 8 }),
    ]);
    expect(rows(card)).toStrictEqual(TRAM_SUGGESTIONS);
  });

  it("switching stops ignores the old stop's late answer", async () => {
    const home = house();
    const card = await mount(home);
    await tap(card, "Casa");
    const slow = home.holdNext();
    await tapStop(card, "Mago de Oz");

    await openTramStop(card);
    slow.respond(recorded.busArrivals);
    await settle();

    expect(shown(card)).toContain("Mago de Oz hacia Avenida de la Academia");
    expect(rows(card)).toStrictEqual(TRAM_BOARD);
  });

  it("an old stop's late failure neither shows nor stops the refresh", async () => {
    const home = house();
    const card = await mount(home);
    await tap(card, "Casa");
    const slow = home.holdNext();
    await tapStop(card, "Mago de Oz");
    await openTramStop(card);
    home.take();

    slow.fail(recorded.errorSourceUnavailable);
    await settle();

    expect(shown(card)).not.toContain(SOURCE_DOWN_ES);
    await wait(MINUTE);
    expect(home.take()).toStrictEqual([OPEN_1102]);
  });
});

describe("remembered stops", () => {
  it("reopens the last stop after a reload", async () => {
    const first = await mount(house());
    await openTramStop(first);
    first.remove();

    const home = house();
    const card = await mount(home);

    expect(home.sent).toStrictEqual([OPEN_1102]);
    expect(rows(card)).toStrictEqual(TRAM_BOARD);
  });

  it("each mode reopens its own last stop, all under one key", async () => {
    const first = await mount(house());
    await openTramStop(first);
    await tap(first, "Bizi");
    await tap(first, "Casa");
    await tapStop(first, "Pta. del Carmen");
    first.remove();

    expect(localStorage).toHaveLength(1);
    expect(localStorage.key(0)).toMatch(/^zaragoza-open-data-card/);

    const home = house();
    const card = await mount(home);
    await tap(card, "Bizi");

    expect(home.sent).toStrictEqual([OPEN_1102, callOf("get_bizi_station", { station: "26" })]);

    const biziFirst = house();
    await mount(biziFirst, { default_mode: "bizi" });

    expect(biziFirst.sent).toStrictEqual([callOf("get_bizi_station", { station: "26" })]);
  });

  it.each([
    ["not JSON", "{nope"],
    ["null", "null"],
    ["a list", "[]"],
    ["another shape", JSON.stringify({ tram: "1102" })],
    ["a code that isn't text", JSON.stringify({ version: 1, stops: { tram: { code: 1102 } } })],
    ["another version", JSON.stringify({ version: 0, stops: { tram: { code: "1102", name: "Mago de Oz" } } })],
  ])("a saved value that is %s is ignored", async (_case, value) => {
    const first = await mount(house());
    await openTramStop(first);
    first.remove();
    const key = localStorage.key(0);
    if (key === null) throw new Error("Nothing was saved");
    localStorage.setItem(key, value);

    const home = house();
    const card = await mount(home);

    expect(home.sent).toStrictEqual([]);
    expect(labels(card)).toContain("Casa");
  });

  it("works when the browser refuses storage", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("The operation is insecure.", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("The quota has been exceeded.", "QuotaExceededError");
    });
    const home = house();
    const card = await mount(home);

    await openTramStop(card);

    expect(rows(card)).toStrictEqual(TRAM_BOARD);
  });
});

describe("times", () => {
  const browserZone = process.env["TZ"];

  afterEach(() => {
    if (browserZone === undefined) delete process.env["TZ"];
    else process.env["TZ"] = browserZone;
  });

  it("shows minutes as given and the clock time in Home Assistant's time zone", async () => {
    // A browser elsewhere doesn't change the time shown.
    process.env["TZ"] = "America/New_York";
    const card = await mount(house());

    await openTramStop(card);

    expect(rows(card)).toStrictEqual(TRAM_BOARD);
  });

  it("follows the server's time zone", async () => {
    const card = await mount(house({ timeZone: "Atlantic/Canary" }));

    await openTramStop(card);

    expect(rows(card)).toStrictEqual(["L1 Avenida Academia 4 min 12:44", "L1 Avenida Academia 8 min 12:48"]);
  });

  it("uses the browser's time zone when the profile asks for it", async () => {
    process.env["TZ"] = "Asia/Tokyo";
    const card = await mount(house({ localeTimeZone: "local" }));

    await openTramStop(card);

    expect(rows(card)).toStrictEqual(["L1 Avenida Academia 4 min 21:44", "L1 Avenida Academia 8 min 21:48"]);
  });

  it("shows a 24-hour clock in English too", async () => {
    const card = await mount(house({ language: "en" }));
    await tap(card, "Home");

    await tapStop(card, "Avenida de la Academia");

    expect(rows(card)).toStrictEqual(TRAM_BOARD);
  });
});

describe("languages", () => {
  it.each([
    [
      "es",
      ["Tranvía", "Bus", "Bizi", "Mi ubicación", "Casa", "Zona", "Escribir parada…"],
      "Origen de los datos: Ayuntamiento de Zaragoza",
      ["4 Eléctricas", "0 Mecánicas", "15 Anclajes libres"],
    ],
    [
      "en",
      ["Tram", "Bus", "Bizi", "My location", "Home", "Zone", "Type a stop…"],
      "Data source: Ayuntamiento de Zaragoza",
      ["4 Electric", "0 Mechanical", "15 Free docks"],
    ],
  ])("spanish and english labels (%s)", async (language, chips, footer, bizi) => {
    const card = await mount(house({ language }));

    expect(labels(card)).toStrictEqual(chips);
    expect(shown(card)).toContain(footer);

    const [, , biziChip = "", , homeChip = ""] = chips;
    await tap(card, biziChip);
    await tap(card, homeChip);
    await tapStop(card, "Pta. del Carmen");

    expect(rows(card)).toStrictEqual(bizi);
  });
});

describe("settings written by hand", () => {
  it.each([
    ["modes that aren't a list", { modes: "tram" }, "modes"],
    ["an unknown mode", { modes: ["tram", "metro"] }, "modes"],
    ["no modes", { modes: [] }, "modes"],
    ["an unknown default mode", { default_mode: "metro" }, "default_mode"],
    ["nearest as text", { nearest: "5" }, "nearest"],
    ["show_zones as text", { show_zones: "yes" }, "show_zones"],
    ["a home zone that isn't an entity id", { home_zone: 7 }, "home_zone"],
    ["a person that isn't an entity id", { my_location_entity: ["person.ana"] }, "my_location_entity"],
  ])("refuses %s, naming the setting", (_case, settings, name) => {
    const card = document.createElement("zaragoza-open-data-card");
    const editor = ZaragozaOpenDataCard.getConfigElement();
    const config = { type: CARD_TYPE, ...settings };

    // Home Assistant shows the card's error on the card, and the editor's by falling back to YAML.
    expect(() => {
      card.setConfig(config);
    }).toThrow(name);
    expect(() => {
      editor.setConfig(config);
    }).toThrow(name);
  });

  it("lists at most 10 nearest stops, and at least 1", async () => {
    const home = house();
    const many = await mount(home, { nearest: 20 });
    await tap(many, "Casa");
    const few = await mount(home, { nearest: 0 });
    await tap(few, "Casa");

    expect(home.sent).toStrictEqual([
      callOf("find_stops", { kind: "tram", ...HOME, limit: 10 }),
      callOf("find_stops", { kind: "tram", ...HOME, limit: 1 }),
    ]);
  });
});

describe("registration", () => {
  it("is registered once even when the file is loaded twice", async () => {
    vi.resetModules();
    await import("../../src/zaragoza-open-data-card");
    vi.resetModules();
    await import("../../src/zaragoza-open-data-card");

    expect(window.customCards?.filter((card) => card.type === "zaragoza-open-data-card")).toStrictEqual([
      {
        type: "zaragoza-open-data-card",
        name: "Zaragoza Open Data",
        description: "Find any tram or bus stop or Bizi station and see what comes next.",
        preview: true,
      },
    ]);
    expect(customElements.get("zaragoza-open-data-card")).toBe(ZaragozaOpenDataCard);
    expect(customElements.get("zaragoza-open-data-card-editor")).toBeDefined();
  });

  it("offers a starting config and its editor", () => {
    expect(ZaragozaOpenDataCard.getStubConfig()).toStrictEqual({ modes: ["tram", "bus", "bizi"] });
    expect(ZaragozaOpenDataCard.getConfigElement().localName).toBe("zaragoza-open-data-card-editor");
  });
});
