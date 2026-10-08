import { describe, expect, it } from "vitest";

import { isTerminalJob } from "@/components/ingest/job-state";

describe("isTerminalJob", () => {
  it("is terminal when the pipeline finished or a job failed", () => {
    expect(isTerminalJob("publish", "done")).toBe(true);
    expect(isTerminalJob("acquire", "skipped")).toBe(true);
    expect(isTerminalJob("parse", "failed")).toBe(true);
    expect(isTerminalJob("publish", "failed")).toBe(true);
  });

  it("keeps running while a stage is queued, running or done before publish", () => {
    expect(isTerminalJob("acquire", "queued")).toBe(false);
    expect(isTerminalJob("acquire", "running")).toBe(false);
    expect(isTerminalJob("acquire", "done")).toBe(false);
    expect(isTerminalJob("segment", "done")).toBe(false);
    expect(isTerminalJob("publish", "running")).toBe(false);
  });
});
