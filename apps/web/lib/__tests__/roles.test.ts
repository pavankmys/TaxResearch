import { describe, expect, it } from "vitest";

import { isReviewer } from "@/lib/roles";

describe("isReviewer", () => {
  it("accepts platform admins and content editors", () => {
    expect(isReviewer(["platform_admin"])).toBe(true);
    expect(isReviewer(["professional", "platform_content_editor"])).toBe(true);
  });

  it("rejects other roles and empty role lists", () => {
    expect(isReviewer(["professional"])).toBe(false);
    expect(isReviewer([])).toBe(false);
  });
});
