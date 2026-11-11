import { afterEach, describe, expect, it } from "vitest";

import { ZaragozaOpenDataCard } from "../../src/zaragoza-open-data-card";
import type { CardConfig } from "../../src/types";
import { CARD_TYPE } from "../support/card-dom";
import { FakeHome } from "../support/fake-hass";

// Home Assistant's `ha-form` isn't loaded in these tests: they check what the editor hands
// it, and answer as it does, with a `value-changed` event carrying the whole form's data.

async function openEditor(config: CardConfig, language = "es") {
  const editor = ZaragozaOpenDataCard.getConfigElement();
  editor.hass = new FakeHome({ language }).hass;
  editor.setConfig(config);
  document.body.append(editor);
  await editor.updateComplete;
  const form = editor.shadowRoot?.querySelector("ha-form");
  if (form === null || form === undefined) throw new Error("The editor shows no form");
  const changes: unknown[] = [];
  editor.addEventListener("config-changed", (event) => {
    changes.push(event instanceof CustomEvent ? event.detail : event);
  });
  return { editor, form, changes };
}

afterEach(() => {
  document.body.replaceChildren();
});

describe("editor", () => {
  it("editor emits config-changed with chosen modes", async () => {
    const { form, changes } = await openEditor({ type: CARD_TYPE });

    form.dispatchEvent(
      new CustomEvent("value-changed", { detail: { value: { ...form.data, modes: ["tram", "bizi"] } } }),
    );

    expect(changes).toStrictEqual([
      {
        config: {
          type: CARD_TYPE,
          modes: ["tram", "bizi"],
          default_mode: "tram",
          nearest: 5,
          home_zone: "zone.home",
          show_zones: true,
        },
      },
    ]);
  });

  it("shows each setting with its default, labelled in the user's language", async () => {
    const { form } = await openEditor({ type: CARD_TYPE, nearest: 3 }, "es");

    expect(form.data).toStrictEqual({
      modes: ["tram", "bus", "bizi"],
      default_mode: "tram",
      nearest: 3,
      home_zone: "zone.home",
      show_zones: true,
    });
    expect(form.schema.map((field) => [field.name, form.computeLabel(field)])).toStrictEqual([
      ["modes", "Modos"],
      ["default_mode", "Modo al abrir"],
      ["nearest", "Paradas cercanas que se listan"],
      ["home_zone", "Zona de casa"],
      ["show_zones", "Mostrar zonas"],
      ["my_location_entity", "Persona de «Mi ubicación» (por defecto, quien mira)"],
    ]);
  });

  it("offers the modes, a default among the chosen ones, and the limits of each setting", async () => {
    const { form } = await openEditor({ type: CARD_TYPE, modes: ["bus", "bizi"] }, "en");

    expect(form.schema).toStrictEqual([
      {
        name: "modes",
        required: true,
        selector: {
          select: {
            multiple: true,
            mode: "list",
            options: [
              { value: "tram", label: "Tram" },
              { value: "bus", label: "Bus" },
              { value: "bizi", label: "Bizi" },
            ],
          },
        },
      },
      {
        name: "default_mode",
        selector: {
          select: {
            mode: "dropdown",
            options: [
              { value: "bus", label: "Bus" },
              { value: "bizi", label: "Bizi" },
            ],
          },
        },
      },
      { name: "nearest", selector: { number: { min: 1, max: 10, mode: "slider" } } },
      { name: "home_zone", selector: { entity: { filter: { domain: "zone" } } } },
      { name: "show_zones", selector: { boolean: {} } },
      { name: "my_location_entity", selector: { entity: { filter: { domain: "person" } } } },
    ]);
  });

  it("keeps what else the dashboard stores in the card's config", async () => {
    const stored = { type: CARD_TYPE, grid_options: { columns: 6 }, visibility: [] };
    const { form, changes } = await openEditor(stored);

    form.dispatchEvent(new CustomEvent("value-changed", { detail: { value: { ...form.data, nearest: 7 } } }));

    expect(changes).toStrictEqual([
      {
        config: {
          ...stored,
          modes: ["tram", "bus", "bizi"],
          default_mode: "tram",
          nearest: 7,
          home_zone: "zone.home",
          show_zones: true,
        },
      },
    ]);
  });

  it("keeps the modes when every mode is unticked", async () => {
    const { form, changes } = await openEditor({ type: CARD_TYPE, modes: ["bus", "bizi"] });

    form.dispatchEvent(new CustomEvent("value-changed", { detail: { value: { ...form.data, modes: [] } } }));

    expect(changes).toStrictEqual([
      {
        config: {
          type: CARD_TYPE,
          modes: ["bus", "bizi"],
          default_mode: "bus",
          nearest: 5,
          home_zone: "zone.home",
          show_zones: true,
        },
      },
    ]);
  });

  it("drops a cleared person and a default mode that is no longer shown", async () => {
    const { form, changes } = await openEditor({
      type: CARD_TYPE,
      default_mode: "tram",
      my_location_entity: "person.luis",
    });

    form.dispatchEvent(
      new CustomEvent("value-changed", {
        detail: { value: { ...form.data, modes: ["bus"], my_location_entity: "" } },
      }),
    );

    expect(changes).toStrictEqual([
      {
        config: {
          type: CARD_TYPE,
          modes: ["bus"],
          nearest: 5,
          home_zone: "zone.home",
          show_zones: true,
        },
      },
    ]);
  });
});
