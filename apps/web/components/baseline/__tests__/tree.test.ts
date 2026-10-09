import { describe, expect, it } from "vitest";

import { provisionFlags, rowLabel } from "@/components/baseline/tree";
import type { ProvisionRow } from "@/components/baseline/types";

function mockRow(overrides?: Partial<ProvisionRow>): ProvisionRow {
  return {
    id: "test-id",
    depth: 0,
    level: "section",
    number_label: "1",
    heading: "Test heading",
    has_baseline: true,
    text_chars: 100,
    path: "/test",
    parent_id: null,
    ...overrides,
  };
}

describe("provisionFlags", () => {
  it("returns 'No baseline text' when has_baseline is false", () => {
    const row = mockRow({ has_baseline: false });
    expect(provisionFlags(row)).toEqual(["No baseline text"]);
  });

  it("returns 'Empty text' when has_baseline and text_chars is 0 and level is not chapter", () => {
    const row = mockRow({ has_baseline: true, text_chars: 0, level: "section" });
    expect(provisionFlags(row)).toEqual(["Empty text"]);
  });

  it("does not return 'Empty text' for chapter level with zero chars", () => {
    const row = mockRow({ has_baseline: true, text_chars: 0, level: "chapter" });
    expect(provisionFlags(row)).toEqual([]);
  });

  it("returns empty array when baseline is loaded and has text", () => {
    const row = mockRow({ has_baseline: true, text_chars: 100 });
    expect(provisionFlags(row)).toEqual([]);
  });
});

describe("rowLabel", () => {
  it("formats chapter", () => {
    expect(rowLabel(mockRow({ level: "chapter", number_label: "5" }))).toBe("Chapter 5");
  });

  it("formats section", () => {
    expect(rowLabel(mockRow({ level: "section", number_label: "16" }))).toBe("Section 16");
  });

  it("formats rule", () => {
    expect(rowLabel(mockRow({ level: "rule", number_label: "36" }))).toBe("Rule 36");
  });

  it("formats subsection", () => {
    expect(rowLabel(mockRow({ level: "subsection", number_label: "2" }))).toBe("(2)");
  });

  it("formats clause", () => {
    expect(rowLabel(mockRow({ level: "clause", number_label: "a" }))).toBe("(a)");
  });

  it("formats subclause", () => {
    expect(rowLabel(mockRow({ level: "subclause", number_label: "iv" }))).toBe("(iv)");
  });

  it("formats proviso", () => {
    expect(rowLabel(mockRow({ level: "proviso", number_label: "1" }))).toBe("Proviso 1");
  });

  it("formats explanation", () => {
    expect(rowLabel(mockRow({ level: "explanation", number_label: "1" }))).toBe("Explanation 1");
  });

  it("handles missing number_label", () => {
    const row = mockRow({ level: "section", number_label: null });
    expect(rowLabel(row)).toBe("Section");
  });
});
