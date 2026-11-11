import type { ReactiveController, ReactiveControllerHost } from "lit";

const MINUTE_MS = 60_000;
// Past the minute, so the integration has counted its minutes down by then.
const AFTER_THE_MINUTE_MS = 2_000;

/**
 * How long to wait before asking again about an answer read at `updated` (ISO 8601), at
 * `now` (ms since the epoch): until 2 s after the next whole minute since that reading.
 *
 * The integration counts each stop's minutes down a whole minute after the source's
 * reading, the stop's minutes sensor too; asking just after keeps the card and the badge
 * showing the same number. Steady, that is once a minute. 60 s when `updated` is no time.
 */
export function askAgainIn(updated: string | undefined, now: number): number {
  const read = updated === undefined ? Number.NaN : Date.parse(updated);
  if (Number.isNaN(read)) return MINUTE_MS;
  const minutesSince = Math.floor((now - read) / MINUTE_MS);
  return read + (minutesSince + 1) * MINUTE_MS + AFTER_THE_MINUTE_MS - now;
}

/**
 * Keeps the opened stop fresh while someone can see it: after each answer, at the moment
 * the caller names, while the page is visible and the card is on it; and at once when the
 * page comes back into view or the card back onto the page.
 *
 * Only the board's own calls drive it. After a failed one it stops, because Home
 * Assistant logs each failed action call as an error and polling a source that is down
 * would flood the log. Then it fetches only once each time the page comes back into view,
 * or when the person taps Retry; the next board fetch that succeeds resumes it.
 */
export class VisibleRefresh implements ReactiveController {
  private timer: ReturnType<typeof setTimeout> | undefined;
  private connected = false;

  constructor(
    host: ReactiveControllerHost,
    /** Fetch the opened stop again; nothing when no stop is open. */
    private readonly refresh: () => void,
  ) {
    host.addController(this);
  }

  hostConnected(): void {
    this.connected = true;
    document.addEventListener("visibilitychange", this.onVisibilityChange);
    if (visible()) this.refresh();
  }

  hostDisconnected(): void {
    this.connected = false;
    document.removeEventListener("visibilitychange", this.onVisibilityChange);
    this.stop();
  }

  /** The opened stop answered: fetch it again in `delay` ms. */
  succeeded(delay: number): void {
    this.start(delay);
  }

  /** Fetching the opened stop failed: no more fetching on a timer. */
  failed(): void {
    this.stop();
  }

  // Once on coming back into view, failing or not: after a failure, that is the one retry.
  private readonly onVisibilityChange = (): void => {
    if (visible()) this.refresh();
    else this.stop();
  };

  private start(delay: number): void {
    this.stop();
    if (!this.connected || !visible()) return;
    this.timer = setTimeout(() => {
      this.timer = undefined;
      this.refresh();
    }, delay);
  }

  private stop(): void {
    clearTimeout(this.timer);
    this.timer = undefined;
  }
}

function visible(): boolean {
  return document.visibilityState === "visible";
}
