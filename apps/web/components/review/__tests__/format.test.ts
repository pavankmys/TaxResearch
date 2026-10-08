import { describe, expect, it } from "vitest";

import { formatAge, formatDateTimeUtc, isOverdue, kindLabel } from "../format";

const NOW = Date.parse("2026-10-08T12:00:00Z");

describe("formatAge", () => {
  it("shows minutes under an hour", () => {
    expect(formatAge("2026-10-08T11:48:00Z", NOW)).toBe("12 min");
    expect(formatAge("2026-10-08T11:59:30Z", NOW)).toBe("0 min");
  });

  it("shows whole hours under a day", () => {
    expect(formatAge("2026-10-08T09:00:00Z", NOW)).toBe("3 h");
    expect(formatAge("2026-10-07T13:00:00Z", NOW)).toBe("23 h");
  });

  it("shows whole days from one day on", () => {
    expect(formatAge("2026-10-06T12:00:00Z", NOW)).toBe("2 d");
    expect(formatAge("2026-10-07T12:00:00Z", NOW)).toBe("1 d");
  });

  it("treats a time in the future as just opened, and an invalid time as unknown", () => {
    expect(formatAge("2026-10-08T13:00:00Z", NOW)).toBe("0 min");
    expect(formatAge("not a date", NOW)).toBe("unknown");
  });
});

describe("isOverdue", () => {
  it("is true only when the SLA time has passed", () => {
    expect(isOverdue("2026-10-08T11:00:00Z", NOW)).toBe(true);
    expect(isOverdue("2026-10-08T13:00:00Z", NOW)).toBe(false);
    expect(isOverdue(null, NOW)).toBe(false);
  });
});

describe("formatDateTimeUtc", () => {
  it("labels the time as UTC", () => {
    expect(formatDateTimeUtc("2026-10-08T18:00:00Z")).toMatch(/8 Oct 2026.*18:00 UTC$/);
  });
});

describe("labels", () => {
  it("maps known kinds and passes unknown ones through", () => {
    expect(kindLabel("parse_failure")).toBe("Parse failure");
    expect(kindLabel("treatment")).toBe("treatment");
  });
});
