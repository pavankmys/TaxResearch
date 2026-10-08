import { describe, expect, it } from "vitest";

import { buildStatusPatch } from "@/components/documents/status";

describe("buildStatusPatch", () => {
  it("builds the body with the valid-from date when one is given", () => {
    expect(
      buildStatusPatch({ status: "amended", validFrom: "2023-04-01", reason: "Amended by N/1" }, "in_force"),
    ).toEqual({
      ok: true,
      body: { status: "amended", status_valid_from: "2023-04-01", reason: "Amended by N/1" },
    });
  });

  it("omits the valid-from date when it is blank", () => {
    const result = buildStatusPatch({ status: "stayed", validFrom: " ", reason: "Stay order" }, "in_force");
    expect(result).toEqual({ ok: true, body: { status: "stayed", reason: "Stay order" } });
  });

  it("refuses the current status, a bad date and a short reason", () => {
    expect(buildStatusPatch({ status: "in_force", validFrom: "", reason: "Same" }, "in_force")).toEqual({
      ok: false,
      error: "The document already has that status.",
    });
    expect(buildStatusPatch({ status: "stayed", validFrom: "01-04-2023", reason: "Stay" }, "in_force")).toEqual({
      ok: false,
      error: "The valid-from date must be a date in the form YYYY-MM-DD.",
    });
    expect(buildStatusPatch({ status: "stayed", validFrom: "", reason: "x" }, "in_force")).toEqual({
      ok: false,
      error: "Give a reason for the change (at least 3 characters).",
    });
  });
});
