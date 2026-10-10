import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AmendmentSection, parseWordDiff } from "../amendment-section";
import type { components } from "@/lib/api-client/schema";

type AmendmentSummary = components["schemas"]["AmendmentSummary"];

describe("parseWordDiff", () => {
  it("parses equal text", () => {
    const tokens = parseWordDiff("The quick brown fox");
    expect(tokens).toEqual([{ type: "equal", text: "The quick brown fox" }]);
  });

  it("parses deletions and additions", () => {
    const diff = "shall not exceed [-120-]{+105+} per cent";
    const tokens = parseWordDiff(diff);
    expect(tokens).toEqual([
      { type: "equal", text: "shall not exceed " },
      { type: "delete", text: "120" },
      { type: "insert", text: "105" },
      { type: "equal", text: " per cent" },
    ]);
  });

  it("handles pure insertion", () => {
    const diff = "{+new rule added+}";
    const tokens = parseWordDiff(diff);
    expect(tokens).toEqual([{ type: "insert", text: "new rule added" }]);
  });

  it("handles pure deletion", () => {
    const diff = "[-omitted provision-]";
    const tokens = parseWordDiff(diff);
    expect(tokens).toEqual([{ type: "delete", text: "omitted provision" }]);
  });
});

describe("AmendmentSection", () => {
  const baseAmendment: AmendmentSummary = {
    id: "00000000-0000-0000-0000-000000000001",
    source_document_id: "00000000-0000-0000-0000-000000000002",
    source_block_id: null,
    op: "substitute",
    target_provision_id: "00000000-0000-0000-0000-000000000003",
    target_locator: {
      instrument: "CGST_RULES",
      target_path: "r36.4",
      problems: [],
    },
    old_text: "twenty",
    new_text: "ten",
    effective_from: "2026-01-01",
    effective_condition: "on_date",
    extraction_method: "rule",
    extraction_conf: 0.95,
    dry_run_ok: true,
    dry_run_diff: "shall not exceed [-twenty-]{+ten+} per cent",
    review_status: "proposed",
    target_provision_path: "r36.4",
    current_provision_text: "shall not exceed twenty per cent",
  };

  it("renders proposal details and dry run diff when dry_run_ok is true", () => {
    render(<AmendmentSection amendment={baseAmendment} resolution={{}} />);

    expect(screen.getByText("substitute")).toBeInTheDocument();
    expect(screen.getByText("Target Resolved")).toBeInTheDocument();
    expect(screen.getByText("CGST_RULES")).toBeInTheDocument();
    expect(screen.getByText("r36.4")).toBeInTheDocument();
    expect(screen.getByText("Dry-run clean")).toBeInTheDocument();

    // Verify word diff rendering
    expect(screen.getAllByText("twenty").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ten").length).toBeGreaterThan(0);
    expect(screen.getByText(/Current Provision Text/)).toBeInTheDocument();
  });

  it("renders failure alert when dry_run_ok is false", () => {
    const failedAmendment: AmendmentSummary = {
      ...baseAmendment,
      dry_run_ok: false,
      dry_run_diff: "old_text_not_found",
    };

    render(
      <AmendmentSection
        amendment={failedAmendment}
        resolution={{ problems: ["old_text_not_found"] }}
      />
    );

    expect(screen.getByText("Dry-run failed")).toBeInTheDocument();
    expect(screen.getAllByText("old_text_not_found").length).toBeGreaterThan(0);
    expect(screen.getByText("Locator Problems:")).toBeInTheDocument();
  });

  it("renders fallback message when amendment is null", () => {
    render(<AmendmentSection amendment={null} resolution={null} />);
    expect(screen.getByText(/No amendment proposal data is available/)).toBeInTheDocument();
  });
});
