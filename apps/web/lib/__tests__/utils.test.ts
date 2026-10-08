import { describe, expect, it } from "vitest";

import { cn } from "@/lib/utils";

describe("cn", () => {
  it("joins class names and skips falsy values", () => {
    expect(cn("text-sm", false, undefined, null, "font-medium")).toBe("text-sm font-medium");
  });

  it("lets later Tailwind classes win over conflicting ones", () => {
    expect(cn("px-2 text-sm", "px-4")).toBe("text-sm px-4");
  });
});
