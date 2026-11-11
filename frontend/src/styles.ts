import { css } from "lit";

// Home Assistant's look: its theme variables throughout, so the card follows any theme.
export const cardStyles = css`
  :host {
    display: block;
  }

  .content {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px;
  }

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  button {
    font: inherit;
    color: inherit;
    cursor: pointer;
  }

  button:focus-visible,
  input:focus-visible,
  select:focus-visible {
    outline: 2px solid var(--primary-color);
    outline-offset: 2px;
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 32px;
    padding: 0 12px;
    border: 1px solid var(--divider-color);
    border-radius: 16px;
    background: none;
    color: var(--primary-text-color);
    font-size: var(--ha-font-size-s, 14px);
  }

  .chip ha-icon {
    --mdc-icon-size: 18px;
  }

  .chip[aria-pressed="true"] {
    border-color: var(--primary-color);
    background: rgba(var(--rgb-primary-color), 0.12);
    color: var(--primary-color);
  }

  .field {
    box-sizing: border-box;
    width: 100%;
    height: 40px;
    padding: 0 12px;
    border: 1px solid var(--divider-color);
    border-radius: 8px;
    background: var(--secondary-background-color);
    color: var(--primary-text-color);
    font: inherit;
  }

  ul {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .stop {
    display: grid;
    grid-template-columns: 1fr auto;
    align-items: center;
    gap: 2px 12px;
    width: 100%;
    padding: 8px 0;
    border: none;
    border-bottom: 1px solid var(--divider-color);
    background: none;
    text-align: start;
  }

  .stop .name {
    color: var(--primary-text-color);
  }

  .stop .detail {
    grid-row: 2;
    color: var(--secondary-text-color);
    font-size: var(--ha-font-size-s, 14px);
  }

  .stop .distance {
    grid-row: 1 / span 2;
    grid-column: 2;
    color: var(--secondary-text-color);
    font-size: var(--ha-font-size-s, 14px);
  }

  .lines {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }

  .pill {
    display: inline-block;
    min-width: 2.2em;
    padding: 2px 6px;
    border-radius: 4px;
    background: var(--primary-color);
    color: var(--text-primary-color);
    font-weight: 500;
    text-align: center;
  }

  .stop .pill {
    font-size: var(--ha-font-size-xs, 12px);
  }

  .board {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .board-title {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .board-title ha-icon {
    color: var(--state-icon-color, var(--primary-color));
  }

  .board-name {
    color: var(--primary-text-color);
    font-size: var(--ha-font-size-l, 18px);
    font-weight: 500;
  }

  .board-direction {
    color: var(--secondary-text-color);
  }

  .arrivals li {
    display: grid;
    grid-template-columns: auto 1fr auto auto;
    align-items: center;
    gap: 12px;
    padding: 6px 0;
    border-bottom: 1px solid var(--divider-color);
  }

  .destination {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .minutes {
    font-weight: 500;
  }

  .time {
    color: var(--secondary-text-color);
    font-variant-numeric: tabular-nums;
  }

  .bikes {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(88px, 1fr));
    gap: 8px;
  }

  .bikes li {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 8px;
    border-radius: 8px;
    background: var(--secondary-background-color);
    text-align: center;
  }

  .count {
    color: var(--primary-text-color);
    font-size: var(--ha-font-size-2xl, 24px);
    font-weight: 500;
  }

  .what,
  .note {
    color: var(--secondary-text-color);
  }

  .note {
    margin: 0;
  }

  .error {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    color: var(--error-color);
  }

  .retry {
    flex: none;
    padding: 6px 12px;
    border: 1px solid var(--primary-color);
    border-radius: 16px;
    background: none;
    color: var(--primary-color);
  }

  .footer {
    padding: 8px 16px;
    border-top: 1px solid var(--divider-color);
    color: var(--secondary-text-color);
    font-size: var(--ha-font-size-xs, 12px);
  }
`;
