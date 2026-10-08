import { describe, expect, it } from "vitest";

import { structureDepth } from "@/components/documents/structure";

describe("structureDepth", () => {
  it("counts one level per dot", () => {
    expect(structureDepth("p3")).toBe(0);
    expect(structureDepth("hdr")).toBe(0);
    expect(structureDepth("p3.i2")).toBe(1);
    expect(structureDepth("sched1.row12.c")).toBe(2);
    expect(structureDepth("ch5.s16.2.c")).toBe(3);
  });

  it("puts a block without a path at level 0", () => {
    expect(structureDepth(null)).toBe(0);
    expect(structureDepth(undefined)).toBe(0);
    expect(structureDepth("")).toBe(0);
  });
});
