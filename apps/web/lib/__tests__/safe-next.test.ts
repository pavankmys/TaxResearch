import { describe, expect, it } from "vitest";

import { safeNext } from "@/lib/safe-next";

describe("safeNext", () => {
  it("keeps relative paths inside the app, with query strings", () => {
    expect(safeNext("/documents/abc?page=2")).toBe("/documents/abc?page=2");
  });

  it("falls back for missing values", () => {
    expect(safeNext(undefined)).toBe("/queue");
    expect(safeNext(null)).toBe("/queue");
    expect(safeNext("")).toBe("/queue");
    expect(safeNext(undefined, "/dashboard")).toBe("/dashboard");
  });

  it.each([
    "https://evil.example/path",
    "//evil.example/path",
    "/\\evil.example",
    "queue",
    "javascript:alert(1)",
    "/queue\r\nSet-Cookie: x=1",
  ])("rejects %j", (value) => {
    expect(safeNext(value)).toBe("/queue");
  });
});
