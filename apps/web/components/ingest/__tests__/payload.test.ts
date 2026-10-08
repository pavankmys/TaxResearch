import { describe, expect, it } from "vitest";

import {
  buildUploadFields,
  buildUrlSubmission,
  checkUploadSize,
  messageFromDetail,
  UPLOAD_LIMIT_BYTES,
} from "@/components/ingest/payload";

const base = {
  source: "cbic_gst_portal",
  doc_type: "circular",
  url: "https://www.cbic-gst.gov.in/circular.pdf",
};

describe("checkUploadSize", () => {
  it("accepts a file up to 50 MB and refuses an empty or larger one", () => {
    expect(checkUploadSize(1)).toBeNull();
    expect(checkUploadSize(UPLOAD_LIMIT_BYTES)).toBeNull();
    expect(checkUploadSize(UPLOAD_LIMIT_BYTES + 1)).toBe("The file is larger than 50 MB. Choose a smaller file.");
    expect(checkUploadSize(0)).toBe("The file is empty. Choose a PDF or HTML file.");
  });
});

describe("buildUrlSubmission", () => {
  it("omits blank optional fields", () => {
    const result = buildUrlSubmission({ ...base, title: "  ", series: "", number: "183", year: "" });
    expect(result).toEqual({ ok: true, body: { ...base, number: "183" } });
  });

  it("keeps the identifying details that are filled in", () => {
    const result = buildUrlSubmission({
      ...base,
      case_number: "CA 1234/2020",
      court_code: "SC",
      decision_date: "2022-10-10",
    });
    expect(result).toEqual({
      ok: true,
      body: { ...base, case_number: "CA 1234/2020", court_code: "SC", decision_date: "2022-10-10" },
    });
  });

  it("requires a source, a known document type and an http(s) URL", () => {
    expect(buildUrlSubmission({ ...base, source: "" })).toEqual({ ok: false, error: "Choose a source." });
    expect(buildUrlSubmission({ ...base, doc_type: "memo" })).toEqual({
      ok: false,
      error: "Choose a document type.",
    });
    expect(buildUrlSubmission({ ...base, url: "" })).toEqual({
      ok: false,
      error: "Enter the document's URL.",
    });
    expect(buildUrlSubmission({ ...base, url: "not a url" })).toEqual({
      ok: false,
      error: "The URL is not valid.",
    });
    expect(buildUrlSubmission({ ...base, url: "ftp://example.gov/x.pdf" })).toEqual({
      ok: false,
      error: "The URL must start with http:// or https://.",
    });
  });
});

describe("buildUploadFields", () => {
  it("returns the required and filled-in fields only", () => {
    const result = buildUploadFields({
      source: "manual",
      doc_type: "circular",
      title: "E2E",
      series: "",
      circular_a: "",
    });
    expect(result).toEqual({
      ok: true,
      body: { source: "manual", doc_type: "circular", title: "E2E" },
    });
  });
});

describe("messageFromDetail", () => {
  it("reads a string detail, a list of validation messages, or falls back", () => {
    expect(messageFromDetail("Source is disabled: x", "Failed")).toBe("Source is disabled: x");
    expect(messageFromDetail([{ msg: "field required" }, { msg: "bad value" }], "Failed")).toBe(
      "field required bad value",
    );
    expect(messageFromDetail(undefined, "Failed")).toBe("Failed");
  });
});
