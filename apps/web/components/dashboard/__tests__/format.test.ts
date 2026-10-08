import { describe, expect, it } from "vitest";

import {
  formatAge,
  formatCount,
  formatDate,
  formatDateTime,
  formatHours,
  formatMinutes,
  formatPercent,
  utcDayOffset,
} from "@/components/dashboard/format";

describe("formatCount", () => {
  it("groups thousands and shows an em dash when missing", () => {
    expect(formatCount(0)).toBe("0");
    expect(formatCount(1234567)).toBe("1,234,567");
    expect(formatCount(null)).toBe("—");
    expect(formatCount(undefined)).toBe("—");
    expect(formatCount(Number.NaN)).toBe("—");
  });
});

describe("formatPercent", () => {
  it("turns a ratio into a whole percentage", () => {
    expect(formatPercent(0.05)).toBe("5%");
    expect(formatPercent(1)).toBe("100%");
    expect(formatPercent(null)).toBe("—");
  });
});

describe("formatHours and formatMinutes", () => {
  it("shows hours with one decimal at most", () => {
    expect(formatHours(3.5)).toBe("3.5 h");
    expect(formatHours(12)).toBe("12 h");
    expect(formatHours(null)).toBe("—");
  });

  it("shows minutes, and hours and minutes from 60 on", () => {
    expect(formatMinutes(0)).toBe("0 min");
    expect(formatMinutes(45)).toBe("45 min");
    expect(formatMinutes(120)).toBe("2 h");
    expect(formatMinutes(125.4)).toBe("2 h 5 min");
    expect(formatMinutes(-3)).toBe("0 min");
    expect(formatMinutes(undefined)).toBe("—");
  });
});

describe("formatAge", () => {
  const now = new Date("2026-10-08T12:00:00Z");

  it("shows the age in hours, then days", () => {
    expect(formatAge("2026-10-08T11:30:00Z", now)).toBe("under 1 h");
    expect(formatAge("2026-10-08T09:00:00Z", now)).toBe("3 h");
    expect(formatAge("2026-10-06T12:00:00Z", now)).toBe("2 d");
    expect(formatAge("2026-10-05T10:00:00Z", now)).toBe("3 d 2 h");
  });

  it("returns an em dash for a missing or future start", () => {
    expect(formatAge(null, now)).toBe("—");
    expect(formatAge("not a date", now)).toBe("—");
    expect(formatAge("2026-10-09T00:00:00Z", now)).toBe("—");
  });
});

describe("formatDate and formatDateTime", () => {
  it("formats a date-only value without a time zone shift", () => {
    expect(formatDate("2022-10-10")).toBe("10 Oct 2022");
    expect(formatDate(null)).toBe("—");
  });

  it("formats a timestamp in UTC with a label", () => {
    expect(formatDateTime("2026-10-08T10:30:00Z")).toBe("8 Oct 2026, 10:30 UTC");
    expect(formatDateTime(undefined)).toBe("—");
  });
});

describe("utcDayOffset", () => {
  it("returns the UTC calendar day n days back", () => {
    const now = new Date("2026-10-08T23:59:00Z");
    expect(utcDayOffset(now, 0)).toBe("2026-10-08");
    expect(utcDayOffset(now, 6)).toBe("2026-10-02");
    expect(utcDayOffset(new Date("2026-03-01T00:30:00Z"), 1)).toBe("2026-02-28");
  });
});
