import { describe, expect, it } from "vitest";

import {
  failedPageTotal,
  flaggedPageTotal,
  maxQueueLag,
  openTasksByKind,
  overdueTotal,
} from "@/components/dashboard/dashboard-data";

describe("openTasksByKind", () => {
  it("sums open statuses per kind and keeps the oldest opening time", () => {
    const rows = [
      { kind: "parse_failure", status: "open", count: 2, oldest_opened_at: "2026-10-06T00:00:00Z", overdue_count: 0 },
      { kind: "parse_failure", status: "in_review", count: 1, oldest_opened_at: "2026-10-05T00:00:00Z", overdue_count: 0 },
      { kind: "parse_failure", status: "approved", count: 9, oldest_opened_at: "2026-01-01T00:00:00Z", overdue_count: 0 },
      { kind: "metadata", status: "open", count: 4, oldest_opened_at: null, overdue_count: 0 },
    ];
    expect(openTasksByKind(rows)).toEqual([
      { kind: "metadata", count: 4, oldestOpenedAt: null },
      { kind: "parse_failure", count: 3, oldestOpenedAt: "2026-10-05T00:00:00Z" },
    ]);
  });
});

describe("totals", () => {
  it("adds up overdue and flagged pages, and counts failed pages by status", () => {
    const review = [
      { kind: "a", status: "open", count: 1, oldest_opened_at: null, overdue_count: 2 },
      { kind: "b", status: "open", count: 1, oldest_opened_at: null, overdue_count: 1 },
    ];
    expect(overdueTotal(review)).toBe(3);

    const pages = [
      { method: "pdf_text", status: "ok", pages: 10, flagged_pages: 1, pages_last_30d: 10 },
      { method: "ocr", status: "failed", pages: 2, flagged_pages: 2, pages_last_30d: 2 },
    ];
    expect(flaggedPageTotal(pages)).toBe(3);
    expect(failedPageTotal(pages)).toBe(2);
  });

  it("returns the largest queue lag, or null with no queues", () => {
    expect(maxQueueLag([])).toBeNull();
    expect(
      maxQueueLag([
        { queue: "ingest.parse", queued: 1, lag_minutes: 4 },
        { queue: "ingest.publish", queued: 2, lag_minutes: 31.5 },
      ]),
    ).toBe(31.5);
  });
});
