import { describe, expect, it } from "vitest";

import { askAgainIn } from "../../src/refresh";

const SECOND = 1_000;
const MINUTE = 60 * SECOND;
// When the recorded tram list was read: 13:40:02 in Zaragoza.
const READ = "2026-11-09T13:40:02+01:00";
const READ_AT = Date.parse(READ);

describe("askAgainIn", () => {
  it.each([
    ["30 s", 30 * SECOND, 32 * SECOND],
    ["at once", 0, 62 * SECOND],
    ["59.5 s", 59.5 * SECOND, 2.5 * SECOND],
    ["exactly a minute", MINUTE, 62 * SECOND],
    ["10 min 30 s (a kept board)", 10.5 * MINUTE, 32 * SECOND],
  ])("waits until 2 s after the reading's next whole minute, answered %s after it", (_case, after, wait) => {
    expect(askAgainIn(READ, READ_AT + after)).toBe(wait);
  });

  it("waits 2 s past the minute for a reading the clock places in the future", () => {
    expect(askAgainIn(READ, READ_AT - 5 * SECOND)).toBe(7 * SECOND);
  });

  it("waits 60 s when there is no reading time to go by", () => {
    expect(askAgainIn(undefined, READ_AT)).toBe(MINUTE);
    expect(askAgainIn("soon", READ_AT)).toBe(MINUTE);
  });
});
