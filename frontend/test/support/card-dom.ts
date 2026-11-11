import { vi } from "vitest";

import "../../src/zaragoza-open-data-card";
import type { CardConfig } from "../../src/types";
import type { FakeHome } from "./fake-hass";

export const CARD_TYPE = "custom:zaragoza-open-data-card";

/** Put a card on the page, as a dashboard does: settings, then `hass`, then attached. */
export async function mount(home: FakeHome, config: Omit<CardConfig, "type"> = {}) {
  const card = document.createElement("zaragoza-open-data-card");
  card.setConfig({ type: CARD_TYPE, ...config });
  card.hass = home.hass;
  document.body.append(card);
  await settle();
  return card;
}

/** Let pending answers arrive and the page render, without moving the clock. */
export async function settle(): Promise<void> {
  await vi.advanceTimersByTimeAsync(0);
}

/** Move the clock, letting answers arrive on the way. */
export async function wait(ms: number): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms);
}

function shadow(element: Element): ShadowRoot {
  const root = element.shadowRoot;
  if (root === null) throw new Error(`${element.localName} has not rendered`);
  return root;
}

/** The text a person reads in `node`: each piece once, separated by single spaces. */
export function textOf(node: Node): string {
  const parts: string[] = [];
  const walk = (current: Node): void => {
    if (current instanceof HTMLStyleElement) return;
    if (current.nodeType === Node.TEXT_NODE) {
      const text = (current.textContent ?? "").trim();
      if (text !== "") parts.push(text);
    }
    current.childNodes.forEach(walk);
  };
  walk(node);
  return parts.join(" ").replace(/\s+/g, " ");
}

/** Everything the card shows. */
export function shown(card: Element): string {
  return textOf(shadow(card));
}

/** The card's footer: where the data comes from. */
export function footer(card: Element): string {
  const found = shadow(card).querySelector(".footer");
  if (found === null) throw new Error("The card has no footer");
  return textOf(found);
}

function buttons(card: Element): HTMLButtonElement[] {
  return [...shadow(card).querySelectorAll("button")];
}

/** The text of each button, in order. */
export function labels(card: Element): string[] {
  return buttons(card).map(textOf);
}

/** The buttons shown as chosen. */
export function pressed(card: Element): string[] {
  return buttons(card)
    .filter((button) => button.getAttribute("aria-pressed") === "true")
    .map(textOf);
}

/** The button reading exactly `label`. */
export function button(card: Element, label: string): HTMLButtonElement {
  const found = buttons(card).find((candidate) => textOf(candidate) === label);
  if (found === undefined) {
    throw new Error(`No button "${label}"; there are: ${JSON.stringify(labels(card))}`);
  }
  return found;
}

/** Tap the button reading exactly `label`. */
export async function tap(card: Element, label: string): Promise<void> {
  button(card, label).click();
  await settle();
}

/** Tap the listed stop whose button mentions `text`. */
export async function tapStop(card: Element, text: string): Promise<void> {
  const found = buttons(card).find((candidate) => textOf(candidate).includes(text));
  if (found === undefined) {
    throw new Error(`No stop "${text}"; there are: ${JSON.stringify(labels(card))}`);
  }
  found.click();
  await settle();
}

/** The listed items, stops or arrivals, as read. */
export function rows(card: Element): string[] {
  return [...shadow(card).querySelectorAll("li")].map(textOf);
}

/** Type `text` into the stop box, replacing what was there, as one keystroke. */
export async function typeStop(card: Element, text: string): Promise<void> {
  const input = shadow(card).querySelector("input");
  if (input === null) throw new Error("No text box");
  input.value = text;
  input.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
  await settle();
}

/** The options of the zone dropdown, as read. */
export function zoneOptions(card: Element): string[] {
  return [...shadow(card).querySelectorAll("select option")].map(textOf);
}

/** The zone dropdown's accessible name. */
export function zoneDropdownName(card: Element): string | null {
  return shadow(card).querySelector("select")?.getAttribute("aria-label") ?? null;
}

/** Choose a zone in the dropdown. */
export async function chooseZone(card: Element, entityId: string): Promise<void> {
  const select = shadow(card).querySelector("select");
  if (select === null) throw new Error("No zone dropdown");
  select.value = entityId;
  select.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
  await settle();
}

let visibility: DocumentVisibilityState = "visible";
Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });

/** Show or hide the page, as a phone's screen going off or the tab changing does. */
export async function setVisibility(state: DocumentVisibilityState): Promise<void> {
  visibility = state;
  document.dispatchEvent(new Event("visibilitychange"));
  await settle();
}
