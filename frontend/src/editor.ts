import { LitElement, html, nothing } from "lit";
import type { TemplateResult } from "lit";
import { property, state } from "lit/decorators.js";

import { KINDS, NEAREST, isKind, settingsOf } from "./config";
import type { Settings } from "./config";
import { isNumber, isRecord, isString } from "./guards";
import { localize } from "./localize";
import type { TranslationKey } from "./localize";
import type { HomeAssistant, Kind, RawCardConfig } from "./types";

export const EDITOR_TAG = "zaragoza-open-data-card-editor";

type Field = "modes" | "default_mode" | "nearest" | "home_zone" | "show_zones" | "my_location_entity";

const LABELS: Readonly<Record<Field, TranslationKey>> = {
  modes: "editor.modes",
  default_mode: "editor.default_mode",
  nearest: "editor.nearest",
  home_zone: "editor.home_zone",
  show_zones: "editor.show_zones",
  my_location_entity: "editor.my_location_entity",
};

const MODE_LABELS: Readonly<Record<Kind, TranslationKey>> = {
  tram: "mode.tram",
  bus: "mode.bus",
  bizi: "mode.bizi",
};

// The selectors this editor uses, as Home Assistant's `ha-form` reads them.
type Selector =
  | {
      readonly select: {
        readonly multiple?: boolean;
        readonly mode: "list" | "dropdown";
        readonly options: readonly { readonly value: Kind; readonly label: string }[];
      };
    }
  | { readonly number: { readonly min: number; readonly max: number; readonly mode: "slider" } }
  | { readonly entity: { readonly filter: { readonly domain: string } } }
  | { readonly boolean: Readonly<Record<string, never>> };

export interface FormField {
  readonly name: Field;
  readonly required?: boolean;
  readonly selector: Selector;
}

/** The settings as the form shows them: every default filled in. */
export interface FormData {
  readonly modes: readonly Kind[];
  readonly default_mode: Kind;
  readonly nearest: number;
  readonly home_zone: string;
  readonly show_zones: boolean;
  readonly my_location_entity?: string;
}

/** What this editor sets on Home Assistant's form element. */
interface HaForm extends HTMLElement {
  hass?: HomeAssistant;
  data: FormData;
  schema: readonly FormField[];
  computeLabel: (field: FormField) => string;
}

/**
 * The card's visual editor: Home Assistant's own form, with its selectors, for the
 * modes, the default mode, how many nearest stops, the home zone, zones and the person.
 */
export class ZaragozaOpenDataCardEditor extends LitElement {
  @property({ attribute: false }) hass?: HomeAssistant;

  @state() private config: RawCardConfig | undefined;

  /** Take the card's settings; wrong ones throw, so Home Assistant offers YAML instead. */
  setConfig(config: RawCardConfig): void {
    settingsOf(config);
    this.config = config;
  }

  override render(): TemplateResult | typeof nothing {
    if (this.hass === undefined || this.config === undefined) return nothing;
    const settings = settingsOf(this.config);
    return html`<ha-form
      .hass=${this.hass}
      .data=${formData(settings)}
      .schema=${schema(this.hass, settings)}
      .computeLabel=${this.computeLabel}
      @value-changed=${this.onValueChanged}
    ></ha-form>`;
  }

  private readonly computeLabel = (field: FormField): string =>
    this.hass === undefined ? field.name : localize(this.hass, LABELS[field.name]);

  // The form sends all its data on each change; Home Assistant's editor contract is a
  // `config-changed` event with the whole new config.
  private readonly onValueChanged = (event: Event): void => {
    const detail: unknown = event instanceof CustomEvent ? event.detail : undefined;
    const value = isRecord(detail) ? detail["value"] : undefined;
    if (this.config === undefined || !isRecord(value)) return;
    const config = withForm(this.config, value);
    this.config = config;
    this.dispatchEvent(
      new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }),
    );
  };
}

function formData(settings: Settings): FormData {
  return {
    modes: [...settings.modes],
    default_mode: settings.defaultMode,
    nearest: settings.nearest,
    home_zone: settings.homeZone,
    show_zones: settings.showZones,
    ...(settings.myLocationEntity === undefined ? {} : { my_location_entity: settings.myLocationEntity }),
  };
}

function schema(hass: HomeAssistant, settings: Settings): readonly FormField[] {
  const option = (kind: Kind) => ({ value: kind, label: localize(hass, MODE_LABELS[kind]) });
  return [
    {
      name: "modes",
      required: true,
      selector: { select: { multiple: true, mode: "list", options: KINDS.map(option) } },
    },
    // The mode shown first can only be one of those shown.
    { name: "default_mode", selector: { select: { mode: "dropdown", options: settings.modes.map(option) } } },
    { name: "nearest", selector: { number: { min: NEAREST.min, max: NEAREST.max, mode: "slider" } } },
    { name: "home_zone", selector: { entity: { filter: { domain: "zone" } } } },
    { name: "show_zones", selector: { boolean: {} } },
    { name: "my_location_entity", selector: { entity: { filter: { domain: "person" } } } },
  ];
}

/**
 * The config with the form's values. Whatever else the dashboard keeps in it (layout,
 * visibility) stays; a cleared person, or a default mode no longer shown, is removed.
 */
function withForm(config: RawCardConfig, value: RawCardConfig): RawCardConfig {
  const shown = settingsOf(config);
  const ticked = Array.isArray(value["modes"]) ? value["modes"].filter(isKind) : [];
  // The card shows at least one mode: unticking the last one keeps those shown.
  const modes = ticked.length > 0 ? ticked : [...shown.modes];
  const nearest = value["nearest"];
  const homeZone = value["home_zone"];
  const showZones = value["show_zones"];
  const next: Record<string, unknown> = {
    ...config,
    modes,
    nearest: isNumber(nearest) ? nearest : shown.nearest,
    home_zone: isString(homeZone) && homeZone !== "" ? homeZone : shown.homeZone,
    show_zones: typeof showZones === "boolean" ? showZones : shown.showZones,
  };
  const defaultMode = value["default_mode"];
  if (isKind(defaultMode) && modes.includes(defaultMode)) next["default_mode"] = defaultMode;
  else delete next["default_mode"];
  const person = value["my_location_entity"];
  if (isString(person) && person !== "") next["my_location_entity"] = person;
  else delete next["my_location_entity"];
  return next;
}

if (customElements.get(EDITOR_TAG) === undefined) {
  customElements.define(EDITOR_TAG, ZaragozaOpenDataCardEditor);
}

declare global {
  interface HTMLElementTagNameMap {
    "zaragoza-open-data-card-editor": ZaragozaOpenDataCardEditor;
    "ha-form": HaForm;
  }
}
