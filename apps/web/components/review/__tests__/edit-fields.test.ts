import { describe, expect, it } from "vitest";

import {
  AMENDMENT_FIELDS,
  buildEditPatch,
  editableAmendmentFields,
  editableFields,
  formValueFor,
  label,
  METADATA_FIELDS,
  parseListText,
} from "../edit-fields";

const ORIGINAL = {
  title: "Old title",
  number: "7/2026",
  year: 2026,
  doc_date: null,
  judges: ["A. Rao", "B. Iyer"],
  case_numbers: [],
  canonical_id: "CGST-N-7-2026",
};

function edited(overrides: Record<string, string>): Record<string, string> {
  const base: Record<string, string> = {};
  for (const field of editableFields(ORIGINAL)) {
    base[field.name] = field.initial;
  }
  return { ...base, ...overrides };
}

describe("buildEditPatch", () => {
  it("sends only the fields that changed", () => {
    const result = buildEditPatch(ORIGINAL, edited({ title: "New title" }));
    expect(result).toEqual({ patch: { title: "New title" }, errors: [] });
  });

  it("sends nothing when no field changed", () => {
    expect(buildEditPatch(ORIGINAL, edited({})).patch).toEqual({});
  });

  it("ignores surrounding spaces when comparing", () => {
    expect(buildEditPatch(ORIGINAL, edited({ title: "  Old title  " })).patch).toEqual({});
  });

  it("turns a cleared field into null", () => {
    expect(buildEditPatch(ORIGINAL, edited({ number: "  " })).patch).toEqual({ number: null });
  });

  it("converts comma-separated text back into a list", () => {
    const result = buildEditPatch(ORIGINAL, edited({ judges: "A. Rao, C. Menon ,, " }));
    expect(result.patch).toEqual({ judges: ["A. Rao", "C. Menon"] });
  });

  it("leaves a list alone when only its text is reformatted to the same values", () => {
    expect(buildEditPatch(ORIGINAL, edited({ judges: "A. Rao,B. Iyer" })).patch).toEqual({});
  });

  it("clears a list when its text is emptied", () => {
    expect(buildEditPatch(ORIGINAL, edited({ judges: "" })).patch).toEqual({ judges: null });
  });

  it("sends a year as a number and rejects a non-number", () => {
    expect(buildEditPatch(ORIGINAL, edited({ year: "2025" })).patch).toEqual({ year: 2025 });
    expect(buildEditPatch(ORIGINAL, edited({ year: "twenty" }))).toEqual({
      patch: {},
      errors: ["Year must be a whole number"],
    });
  });

  it("checks date fields are YYYY-MM-DD", () => {
    expect(buildEditPatch(ORIGINAL, edited({ doc_date: "2026-10-08" })).patch).toEqual({
      doc_date: "2026-10-08",
    });
    expect(buildEditPatch(ORIGINAL, edited({ doc_date: "08/10/2026" })).errors).toEqual([
      "Doc date must be a date as YYYY-MM-DD",
    ]);
  });

  it("ignores names that are not metadata fields and object fields", () => {
    const result = buildEditPatch(ORIGINAL, { status: "in_force", parties: '{"x":[]}' });
    expect(result).toEqual({ patch: {}, errors: [] });
  });
});

describe("editableFields", () => {
  it("offers every metadata field except object fields, starting from the proposal", () => {
    const fields = editableFields(ORIGINAL);
    const names = fields.map((field) => field.name);
    expect(names).toEqual(METADATA_FIELDS.filter((name) => name !== "parties"));
    expect(fields.find((field) => field.name === "judges")?.initial).toBe("A. Rao, B. Iyer");
    expect(fields.find((field) => field.name === "title")?.initial).toBe("Old title");
    expect(fields.find((field) => field.name === "doc_date")?.initial).toBe("");
  });
});

describe("helpers", () => {
  it("parses list text", () => {
    expect(parseListText(" a, ,b ,, c ")).toEqual(["a", "b", "c"]);
    expect(parseListText("")).toEqual([]);
  });

  it("formats stored values for an input", () => {
    expect(formValueFor(["x", "y"])).toBe("x, y");
    expect(formValueFor(null)).toBe("");
    expect(formValueFor(12)).toBe("12");
  });

  it("labels a field name for a reviewer", () => {
    expect(label("doc_date")).toBe("Doc date");
  });
});

describe("editableAmendmentFields and amendment buildEditPatch", () => {
  const AMENDMENT_ORIGINAL = {
    op: "substitute",
    old_text: "twenty",
    new_text: "ten",
    effective_from: "2026-01-01",
    effective_condition: "on_date",
    target_provision_id: "00000000-0000-0000-0000-000000000001",
  };

  it("offers all amendment fields with initial values", () => {
    const fields = editableAmendmentFields(AMENDMENT_ORIGINAL);
    expect(fields.map((f) => f.name)).toEqual([
      "op",
      "old_text",
      "new_text",
      "effective_from",
      "effective_condition",
      "target_provision_id",
    ]);
    expect(fields.find((f) => f.name === "old_text")?.initial).toBe("twenty");
    expect(fields.find((f) => f.name === "new_text")?.initial).toBe("ten");
  });

  it("builds edit patch for amendment fields", () => {
    const patch = buildEditPatch(
      AMENDMENT_ORIGINAL,
      { new_text: "fifteen", effective_from: "2026-06-01" },
      AMENDMENT_FIELDS,
    );
    expect(patch.errors).toEqual([]);
    expect(patch.patch).toEqual({
      new_text: "fifteen",
      effective_from: "2026-06-01",
    });
  });

  it("validates date format for effective_from", () => {
    const patch = buildEditPatch(
      AMENDMENT_ORIGINAL,
      { effective_from: "invalid-date" },
      AMENDMENT_FIELDS,
    );
    expect(patch.errors.length).toBeGreaterThan(0);
    expect(patch.errors[0]).toContain("must be a date");
  });
});
