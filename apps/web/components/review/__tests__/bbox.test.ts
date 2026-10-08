import { describe, expect, it } from "vitest";

import { bboxToPercent, pageSizeFromPixels, parseBbox, RENDER_DPI } from "../bbox";

describe("parseBbox", () => {
  it("accepts a box with finite edges and positive size", () => {
    expect(parseBbox({ x0: 10, top: 20, x1: 110, bottom: 60 })).toEqual({
      x0: 10,
      top: 20,
      x1: 110,
      bottom: 60,
    });
  });

  it.each([
    ["null", null],
    ["an array", [10, 20, 110, 60]],
    ["a missing edge", { x0: 10, top: 20, x1: 110 }],
    ["a string edge", { x0: "10", top: 20, x1: 110, bottom: 60 }],
    ["an empty box", { x0: 10, top: 20, x1: 10, bottom: 60 }],
    ["an infinite edge", { x0: 0, top: 0, x1: Number.POSITIVE_INFINITY, bottom: 10 }],
  ])("rejects %s", (_name, value) => {
    expect(parseBbox(value)).toBeNull();
  });
});

describe("pageSizeFromPixels", () => {
  it("converts a 110 dpi image to points", () => {
    // A US Letter page (612 x 792 pt) rendered at 110 dpi.
    const pixels = { width: 935, height: 1210 };
    const size = pageSizeFromPixels(pixels);
    expect(RENDER_DPI).toBe(110);
    expect(size.widthPt).toBeCloseTo(612, 0);
    expect(size.heightPt).toBeCloseTo(792, 0);
  });
});

describe("bboxToPercent", () => {
  const page = { widthPt: 612, heightPt: 792 };

  it("expresses the box as percentages of the page", () => {
    const percent = bboxToPercent({ x0: 61.2, top: 79.2, x1: 306, bottom: 198 }, page);
    expect(percent.left).toBeCloseTo(10, 5);
    expect(percent.top).toBeCloseTo(10, 5);
    expect(percent.width).toBeCloseTo(40, 5);
    expect(percent.height).toBeCloseTo(15, 5);
  });

  it("clips a box that runs past the page edge", () => {
    const percent = bboxToPercent({ x0: 600, top: 780, x1: 700, bottom: 900 }, page);
    expect(percent.left).toBeCloseTo((600 / 612) * 100, 5);
    expect(percent.width).toBeCloseTo(100 - (600 / 612) * 100, 5);
    expect(percent.top + percent.height).toBeLessThanOrEqual(100);
    expect(percent.width).toBeGreaterThanOrEqual(0);
  });

  it("keeps a box that starts off the page at the edge", () => {
    const percent = bboxToPercent({ x0: -10, top: -5, x1: 50, bottom: 20 }, page);
    expect(percent.left).toBe(0);
    expect(percent.top).toBe(0);
    expect(percent.width).toBeCloseTo((60 / 612) * 100, 5);
  });
});
