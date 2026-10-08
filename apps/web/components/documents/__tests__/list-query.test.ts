import { describe, expect, it } from "vitest";

import { documentsHref } from "@/components/documents/list-query";

describe("documentsHref", () => {
  it("drops blank values and the all sentinel", () => {
    expect(documentsHref({ q: "  ", docType: "all", reviewState: "" })).toBe("/documents");
  });

  it("keeps the search, the filters and the cursor", () => {
    expect(
      documentsHref({ q: "GST", docType: "circular", reviewState: "pending_review", cursor: "abc" }),
    ).toBe("/documents?q=GST&doc_type=circular&review_state=pending_review&cursor=abc");
  });
});
