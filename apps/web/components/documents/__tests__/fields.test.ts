import { describe, expect, it } from "vitest";

import {
  buildMetadataPatch,
  currentFieldValue,
  currentFieldValues,
  isIsoDate,
  type MetadataSource,
} from "@/components/documents/fields";

const doc: MetadataSource = {
  title: "Circular No. 183/15/2022-GST",
  number: "183/15/2022-GST",
  series: null,
  doc_date: "2022-10-10",
  in_force_date: null,
  issuing_authority: "CBIC",
  bench: null,
  metadata: { fields: { year: 2022, subject: "Test circular" } },
  typed_row: { din: "DIN-1", subject: "From typed row" },
};

const current = currentFieldValues(doc);

describe("currentFieldValue", () => {
  it("prefers the metadata JSON, then the columns, then the typed row", () => {
    expect(currentFieldValue(doc, "year")).toBe("2022");
    expect(currentFieldValue(doc, "subject")).toBe("Test circular");
    expect(currentFieldValue(doc, "title")).toBe("Circular No. 183/15/2022-GST");
    expect(currentFieldValue(doc, "doc_date")).toBe("2022-10-10");
    expect(currentFieldValue(doc, "din")).toBe("DIN-1");
    expect(currentFieldValue(doc, "court_name")).toBe("");
  });
});

describe("buildMetadataPatch", () => {
  it("sends only the fields that changed, and omits blank and unchanged ones", () => {
    const submitted = { ...current, title: "New title", number: "", subject: "Test circular" };
    const result = buildMetadataPatch(current, submitted, "  Fix the title  ");
    expect(result).toEqual({
      ok: true,
      body: { fields: { title: "New title" }, reason: "Fix the title" },
    });
  });

  it("omits empty optional fields from the payload", () => {
    const submitted = { ...current, title: "A", decision_date: "", court_name: "" };
    const result = buildMetadataPatch(current, submitted, "Typo fix");
    expect(result.ok && Object.keys(result.body.fields)).toEqual(["title"]);
  });

  it("requires a reason of at least three characters", () => {
    const result = buildMetadataPatch(current, { ...current, title: "A" }, " ab ");
    expect(result).toEqual({
      ok: false,
      error: "Give a reason for the change (at least 3 characters).",
    });
  });

  it("refuses an edit with nothing changed", () => {
    expect(buildMetadataPatch(current, current, "No change")).toEqual({
      ok: false,
      error: "No changes to save.",
    });
  });

  it("checks the year and date formats", () => {
    const badYear = buildMetadataPatch(current, { ...current, year: "22" }, "Wrong year");
    expect(badYear).toEqual({ ok: false, error: "Year must be a four-digit year." });

    const badDate = buildMetadataPatch(current, { ...current, doc_date: "2022-02-30" }, "Bad date");
    expect(badDate).toEqual({
      ok: false,
      error: "Document date must be a date in the form YYYY-MM-DD.",
    });
  });
});

describe("isIsoDate", () => {
  it("accepts real calendar dates only", () => {
    expect(isIsoDate("2024-02-29")).toBe(true);
    expect(isIsoDate("2023-02-29")).toBe(false);
    expect(isIsoDate("10/10/2022")).toBe(false);
  });
});
