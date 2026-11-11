import { LitElement, html, nothing } from "lit";
import type { TemplateResult } from "lit";
import { property, state } from "lit/decorators.js";

import { findStops, getArrivals, getBiziStation } from "./api";
import type { FindStopsQuery } from "./api";
import { KINDS, settingsOf } from "./config";
import type { Settings } from "./config";
import { EDITOR_TAG, ZaragozaOpenDataCardEditor } from "./editor";
import { clockTime, errorText } from "./format";
import { isTranslationKey, localize } from "./localize";
import type { TranslationKey } from "./localize";
import { saveStop, savedStop } from "./memory";
import { myLocation, pointOf, zonesToChoose } from "./places";
import type { Point, Zone } from "./places";
import { VisibleRefresh, askAgainIn } from "./refresh";
import { cardStyles } from "./styles";
import en from "./translations/en.json";
import type {
  ArrivalsResponse,
  BiziResponse,
  CardConfig,
  FoundStop,
  HomeAssistant,
  Kind,
  RawCardConfig,
} from "./types";

export const CARD_TAG = "zaragoza-open-data-card";

const TYPING_PAUSE_MS = 500;
const MIN_QUERY_LENGTH = 2;
const SUGGESTIONS = 8;

interface Chip {
  readonly label: TranslationKey;
  readonly icon: string;
}

const MODES: Readonly<Record<Kind, Chip>> = {
  tram: { label: "mode.tram", icon: "mdi:tram" },
  bus: { label: "mode.bus", icon: "mdi:bus" },
  bizi: { label: "mode.bizi", icon: "mdi:bicycle" },
};

/** Where to search from: a place, for the nearest stops, or the text typed. */
type Origin = "me" | "home" | "zone" | "text";

const ORIGINS: Readonly<Record<Origin, Chip>> = {
  me: { label: "origin.me", icon: "mdi:crosshairs-gps" },
  home: { label: "origin.home", icon: "mdi:home" },
  zone: { label: "origin.zone", icon: "mdi:map-marker-radius" },
  text: { label: "origin.text", icon: "mdi:magnify" },
};

type StopList =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly stops: readonly FoundStop[] }
  | { readonly status: "failed"; readonly error: unknown; readonly query: FindStopsQuery }
  // The place to search near has no coordinates in Home Assistant.
  | { readonly status: "nowhere" };

interface OpenedStop {
  readonly kind: Kind;
  readonly code: string;
  readonly name: string;
  readonly direction: string | null;
}

type Board =
  | { readonly status: "loading" }
  | { readonly status: "arrivals"; readonly response: ArrivalsResponse }
  | { readonly status: "bizi"; readonly response: BiziResponse }
  | { readonly status: "failed"; readonly error: unknown };

/**
 * The search card: pick any tram or bus stop or Bizi station on the fly, near a place or
 * by typing, and see what comes next. Each phone remembers its own stops.
 */
export class ZaragozaOpenDataCard extends LitElement {
  static override styles = cardStyles;

  static getConfigElement(): ZaragozaOpenDataCardEditor {
    return document.createElement(EDITOR_TAG);
  }

  static getStubConfig(): Omit<CardConfig, "type"> {
    return { modes: [...KINDS] };
  }

  @property({ attribute: false }) hass?: HomeAssistant;

  @state() private settings: Settings | undefined;
  @state() private mode: Kind | undefined;
  @state() private origin: Origin | undefined;
  @state() private zone: string | undefined;
  @state() private query = "";
  @state() private list: StopList | undefined;
  @state() private opened: OpenedStop | undefined;
  @state() private board: Board | undefined;

  // An answer is shown only if no newer call of its kind started meanwhile.
  private searchCall = 0;
  private stopCall = 0;
  private typing: ReturnType<typeof setTimeout> | undefined;
  private focusQuery = false;

  private readonly refresh = new VisibleRefresh(this, () => {
    void this.fetchOpened();
  });

  /** Take the dashboard's settings; wrong ones throw, for Home Assistant to show. */
  setConfig(config: RawCardConfig): void {
    this.settings = settingsOf(config);
  }

  getCardSize(): number {
    return 4;
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    clearTimeout(this.typing);
  }

  protected override willUpdate(): void {
    if (this.hass === undefined || this.settings === undefined) return;
    // On load, and when the settings no longer show the mode: the default mode, with the
    // stop this phone last opened for it.
    if (this.mode === undefined || !this.settings.modes.includes(this.mode)) {
      this.mode = this.settings.defaultMode;
      this.clearList();
      this.reopen(this.mode);
    }
  }

  protected override updated(): void {
    if (!this.focusQuery) return;
    this.focusQuery = false;
    this.renderRoot.querySelector("input")?.focus();
  }

  override render(): TemplateResult | typeof nothing {
    const { hass, settings, mode } = this;
    if (hass === undefined || settings === undefined || mode === undefined) return nothing;
    const zones = settings.showZones ? zonesToChoose(hass, settings.homeZone) : [];
    const origins: Origin[] = [
      ...(myLocation(hass, settings.myLocationEntity) === undefined ? [] : ["me" as const]),
      ...(hass.states[settings.homeZone] === undefined ? [] : ["home" as const]),
      ...(zones.length === 0 ? [] : ["zone" as const]),
      "text",
    ];
    return html`<ha-card>
      <div class="content">
        <div class="chips">
          ${settings.modes.map((kind) =>
            renderChip(hass, MODES[kind], kind === mode, () => {
              this.chooseMode(kind);
            }),
          )}
        </div>
        <div class="chips">
          ${origins.map((origin) =>
            renderChip(hass, ORIGINS[origin], origin === this.origin, () => {
              this.chooseOrigin(origin);
            }),
          )}
        </div>
        ${this.origin === "zone" ? this.renderZones(hass, zones) : nothing}
        ${this.origin === "text" ? this.renderQuery(hass) : nothing} ${this.renderList(hass, mode)}
        ${this.renderBoard(hass)}
      </div>
      <div class="footer">${localize(hass, footerOf(this.board))}</div>
    </ha-card>`;
  }

  private renderZones(hass: HomeAssistant, zones: readonly Zone[]): TemplateResult {
    return html`<select class="field" aria-label=${localize(hass, "origin.zone")} @change=${this.onZoneChange}>
      ${zones.map(
        (zone) =>
          html`<option value=${zone.entityId} ?selected=${zone.entityId === this.zone}>${zone.name}</option>`,
      )}
    </select>`;
  }

  private renderQuery(hass: HomeAssistant): TemplateResult {
    const label = localize(hass, "search.placeholder");
    return html`<input
      class="field"
      type="search"
      autocomplete="off"
      enterkeyhint="search"
      .value=${this.query}
      placeholder=${label}
      aria-label=${label}
      @input=${this.onQueryInput}
    />`;
  }

  private renderList(hass: HomeAssistant, kind: Kind): TemplateResult | typeof nothing {
    const list = this.list;
    switch (list?.status) {
      case undefined:
        return nothing;
      case "loading":
        return html`<p class="note">${localize(hass, "list.loading")}</p>`;
      case "nowhere":
        return html`<p class="note">${localize(hass, "location.unknown")}</p>`;
      case "failed":
        return renderError(hass, list.error, () => {
          void this.search(list.query);
        });
      case "ready":
        if (list.stops.length === 0) return html`<p class="note">${localize(hass, "list.empty")}</p>`;
        return html`<ul>
          ${list.stops.map(
            (stop) =>
              html`<li>
                ${renderStop(hass, stop, () => {
                  this.open({ kind, code: stop.code, name: stop.name, direction: stop.direction });
                })}
              </li>`,
          )}
        </ul>`;
    }
  }

  private renderBoard(hass: HomeAssistant): TemplateResult | typeof nothing {
    const { opened, board } = this;
    if (opened === undefined || board === undefined) return nothing;
    // The answer's name, once there is one; until then, the name it was opened with.
    const title =
      board.status === "arrivals"
        ? board.response.stop
        : board.status === "bizi"
          ? { name: board.response.station.name, direction: null }
          : opened;
    return html`<section class="board">
      <div class="board-title">
        <ha-icon .icon=${MODES[opened.kind].icon}></ha-icon>
        <div>
          <div class="board-name">${title.name}</div>
          ${title.direction === null
            ? nothing
            : html`<div class="board-direction">
                ${localize(hass, "stop.direction", { direction: title.direction })}
              </div>`}
        </div>
      </div>
      ${this.renderBoardBody(hass, board)}
    </section>`;
  }

  private renderBoardBody(hass: HomeAssistant, board: Board): TemplateResult {
    switch (board.status) {
      case "loading":
        return html`<p class="note">${localize(hass, "board.loading")}</p>`;
      case "failed":
        return renderError(hass, board.error, () => {
          void this.fetchOpened();
        });
      case "arrivals":
        return renderArrivals(hass, board.response);
      case "bizi":
        return renderBizi(hass, board.response);
    }
  }

  private chooseMode(kind: Kind): void {
    if (kind === this.mode) return;
    this.mode = kind;
    // The same place or text, now for this kind; and this kind's last stop.
    this.searchAgain();
    this.reopen(kind);
  }

  private chooseOrigin(origin: Origin): void {
    this.origin = origin;
    this.focusQuery = origin === "text";
    if (origin === "zone") {
      // The zone last chosen, while it still has a point; else the first by name.
      const zones = this.zones();
      if (!zones.some((zone) => zone.entityId === this.zone)) this.zone = zones[0]?.entityId;
    }
    this.searchAgain();
  }

  private readonly onZoneChange = (event: Event): void => {
    const select = event.currentTarget;
    if (!(select instanceof HTMLSelectElement)) return;
    this.zone = select.value;
    this.searchAgain();
  };

  private readonly onQueryInput = (event: Event): void => {
    const input = event.currentTarget;
    if (!(input instanceof HTMLInputElement)) return;
    this.query = input.value;
    clearTimeout(this.typing);
    if (this.query.trim().length < MIN_QUERY_LENGTH) {
      this.clearList();
      return;
    }
    // Wait for a pause in the typing, so not every keystroke is a call.
    this.typing = setTimeout(() => {
      this.searchAgain();
    }, TYPING_PAUSE_MS);
  };

  /** Search for what the chips and the text box ask for now. */
  private searchAgain(): void {
    const { settings, mode, origin } = this;
    clearTimeout(this.typing);
    if (settings === undefined || mode === undefined || origin === undefined) return;
    if (origin === "text") {
      const query = this.query.trim();
      if (query.length < MIN_QUERY_LENGTH) this.clearList();
      else void this.search({ kind: mode, query, limit: SUGGESTIONS });
      return;
    }
    const point = this.originPoint(origin);
    if (point === undefined) {
      // No call: without a point the action searches near home, which isn't what was asked.
      this.clearList();
      this.list = { status: "nowhere" };
      return;
    }
    void this.search({ kind: mode, ...point, limit: settings.nearest });
  }

  /** Where a place chip searches from, if Home Assistant knows where that is. */
  private originPoint(origin: Exclude<Origin, "text">): Point | undefined {
    const { hass, settings } = this;
    if (hass === undefined || settings === undefined) return undefined;
    switch (origin) {
      case "me":
        return pointOf(myLocation(hass, settings.myLocationEntity));
      case "home":
        return pointOf(hass.states[settings.homeZone]);
      case "zone":
        return this.zones().find((zone) => zone.entityId === this.zone)?.point;
    }
  }

  private zones(): readonly Zone[] {
    const { hass, settings } = this;
    return hass === undefined || settings === undefined ? [] : zonesToChoose(hass, settings.homeZone);
  }

  private async search(query: FindStopsQuery): Promise<void> {
    const hass = this.hass;
    if (hass === undefined) return;
    const call = ++this.searchCall;
    this.list = { status: "loading" };
    try {
      const stops = await findStops(hass, query);
      if (call !== this.searchCall) return;
      this.list = { status: "ready", stops };
    } catch (error: unknown) {
      // Shown with a Retry in the list only: a search is never repeated on its own, and the
      // board keeps its own refresh.
      if (call !== this.searchCall) return;
      this.list = { status: "failed", error, query };
    }
  }

  private clearList(): void {
    this.searchCall++;
    this.list = undefined;
  }

  private open(stop: OpenedStop): void {
    this.clearList();
    saveStop(stop.kind, stop);
    this.opened = stop;
    this.board = { status: "loading" };
    void this.fetchOpened();
  }

  /** Open the stop this phone last opened for `kind`, if any; else none. */
  private reopen(kind: Kind): void {
    const saved = savedStop(kind);
    this.stopCall++;
    if (saved === undefined) {
      this.opened = undefined;
      this.board = undefined;
      return;
    }
    this.opened = { kind, code: saved.code, name: saved.name, direction: null };
    this.board = { status: "loading" };
    // While the page is hidden, it is fetched when the page shows.
    if (document.visibilityState === "visible") void this.fetchOpened();
  }

  private async fetchOpened(): Promise<void> {
    const { hass, opened } = this;
    if (hass === undefined || opened === undefined) return;
    const call = ++this.stopCall;
    if (this.board?.status === "failed") this.board = { status: "loading" };
    try {
      const board: Board =
        opened.kind === "bizi"
          ? { status: "bizi", response: await getBiziStation(hass, opened.code) }
          : { status: "arrivals", response: await getArrivals(hass, opened.kind, opened.code) };
      if (call !== this.stopCall) return;
      this.board = board;
      // Just after the answer's minutes next drop, as the stop's minutes sensor does.
      this.refresh.succeeded(askAgainIn(board.response.updated, Date.now()));
    } catch (error: unknown) {
      if (call !== this.stopCall) return;
      this.board = { status: "failed", error };
      this.refresh.failed();
    }
  }
}

/**
 * Who published what the card shows, worded as the entities' attribution: the source of
 * the open stop's answer, or the city, whose lists the stops come from.
 */
function footerOf(board: Board | undefined): TranslationKey {
  const source = board?.status === "arrivals" || board?.status === "bizi" ? board.response.source : undefined;
  const key = `footer.${source ?? "zaragoza_city"}`;
  return isTranslationKey(key) ? key : "footer.zaragoza_city";
}

function renderChip(hass: HomeAssistant, chip: Chip, pressed: boolean, choose: () => void): TemplateResult {
  return html`<button class="chip" aria-pressed=${pressed ? "true" : "false"} @click=${choose}>
    <ha-icon .icon=${chip.icon}></ha-icon>
    ${localize(hass, chip.label)}
  </button>`;
}

function renderStop(hass: HomeAssistant, stop: FoundStop, open: () => void): TemplateResult {
  // A tram platform by its direction; a bus stop by its lines; a Bizi station by neither.
  const detail =
    stop.direction !== null
      ? html`<span class="detail">${localize(hass, "stop.direction", { direction: stop.direction })}</span>`
      : stop.lines.length > 0
        ? html`<span class="detail lines">${stop.lines.map((line) => html`<span class="pill">${line}</span>`)}</span>`
        : nothing;
  return html`<button class="stop" @click=${open}>
    <span class="name">${stop.name}</span>
    ${detail}
    <span class="distance">${localize(hass, "stop.distance", { distance: stop.distance_m })}</span>
  </button>`;
}

function renderError(hass: HomeAssistant, error: unknown, retry: () => void): TemplateResult {
  return html`<div class="error" role="alert">
    <span>${errorText(hass, error)}</span>
    <button class="retry" @click=${retry}>${localize(hass, "action.retry")}</button>
  </div>`;
}

function renderArrivals(hass: HomeAssistant, response: ArrivalsResponse): TemplateResult {
  if (response.arrivals.length === 0) {
    return html`<p class="note">${localize(hass, "arrivals.none")}</p>`;
  }
  return html`<ul class="arrivals">
    ${response.arrivals.map(
      (arrival) =>
        html`<li>
          <span class="pill">${arrival.line}</span>
          <span class="destination">${arrival.destination}</span>
          <span class="minutes">${localize(hass, "arrivals.minutes", { minutes: arrival.minutes })}</span>
          <span class="time">${clockTime(hass, arrival.time)}</span>
        </li>`,
    )}
  </ul>`;
}

function renderBizi(hass: HomeAssistant, response: BiziResponse): TemplateResult {
  const { electric, mechanical } = response;
  const counts: readonly (readonly [string, number, TranslationKey])[] = [
    // The city's list, standing in for the operator's, doesn't split the bikes.
    ...(electric === null || mechanical === null
      ? [["mdi:bicycle", response.bikes, "bizi.bikes"] as const]
      : [
          ["mdi:bicycle-electric", electric, "bizi.electric"] as const,
          ["mdi:bicycle", mechanical, "bizi.mechanical"] as const,
        ]),
    ["mdi:parking", response.docks, "bizi.docks"],
  ];
  return html`<ul class="bikes">
      ${counts.map(
        ([icon, count, label]) =>
          html`<li>
            <ha-icon .icon=${icon}></ha-icon>
            <span class="count">${count}</span>
            <span class="what">${localize(hass, label)}</span>
          </li>`,
      )}
    </ul>
    ${response.renting ? nothing : html`<p class="note">${localize(hass, "bizi.not_renting")}</p>`}
    ${response.returning ? nothing : html`<p class="note">${localize(hass, "bizi.not_returning")}</p>`}`;
}

// The file may also be added as a dashboard resource, besides by the integration: a
// second definition would throw, and the card would be listed twice.
if (customElements.get(CARD_TAG) === undefined) {
  customElements.define(CARD_TAG, ZaragozaOpenDataCard);
}

interface CustomCard {
  readonly type: string;
  readonly name: string;
  readonly description: string;
  readonly preview: boolean;
}

window.customCards ??= [];
if (!window.customCards.some((card) => card.type === CARD_TAG)) {
  window.customCards.push({
    type: CARD_TAG,
    name: en["card.name"],
    description: en["card.description"],
    preview: true,
  });
}

declare global {
  interface Window {
    // Home Assistant's list of custom cards, for its card picker.
    customCards?: CustomCard[];
  }

  interface HTMLElementTagNameMap {
    "zaragoza-open-data-card": ZaragozaOpenDataCard;
  }
}
