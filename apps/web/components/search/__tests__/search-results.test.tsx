import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { SearchResults } from "../search-results";
import type { components } from "@/lib/api-client/schema";

type SearchResponse = components["schemas"]["SearchResponse"];

const mockPush = vi.fn();
let mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
  }),
  useSearchParams: () => mockSearchParams,
}));

describe("SearchResults", () => {
  beforeEach(() => {
    mockPush.mockReset();
    mockSearchParams = new URLSearchParams("q=itc&as_on=2026-10-10");
  });

  const mockResponse: SearchResponse = {
    query: "itc",
    as_on: "2026-10-10",
    total_count: 25,
    groups: {
      act: 15,
      notification: 10,
    },
    expanded_terms: ["input tax credit", "electronic credit ledger"],
    items: [
      {
        chunk_id: "00000000-0000-0000-0000-000000000001",
        chunk_kind: "provision",
        document_id: "10000000-0000-0000-0000-000000000001",
        doc_canonical_id: "act:cgst-2017:s16",
        doc_title: "Central Goods and Services Tax Act, 2017",
        doc_type: "act",
        heading_path: "s16.2.c",
        authority_rank: 1,
        score: 0.892,
        passage_count: 3,
        snippet: "Subject to conditions of <mark>input tax credit</mark> entitlement.",
        provision_version_id: "20000000-0000-0000-0000-000000000001",
      },
      {
        chunk_id: "00000000-0000-0000-0000-000000000002",
        chunk_kind: "document",
        document_id: "10000000-0000-0000-0000-000000000002",
        doc_canonical_id: "notf:11-2017:ct-r",
        doc_title: "Notification No. 11/2017-Central Tax (Rate)",
        doc_type: "notification",
        authority_rank: 3,
        score: 0.741,
        passage_count: 1,
        snippet: "Prescribing rates and conditions for goods and services.",
      },
    ],
  };

  it("renders empty state when items list is empty", () => {
    const emptyResponse: SearchResponse = {
      query: "unknown query",
      as_on: "2026-10-10",
      total_count: 0,
      groups: {},
      expanded_terms: [],
      items: [],
    };

    render(<SearchResults response={emptyResponse} />);
    expect(
      screen.getByText("No documents found matching your search")
    ).toBeInTheDocument();
  });

  it("renders result items with authority badges, passages, and highlighted snippets", () => {
    render(<SearchResults response={mockResponse} limit={20} offset={0} />);

    expect(
      screen.getByText("Central Goods and Services Tax Act, 2017")
    ).toBeInTheDocument();
    expect(
      screen.getByText("Notification No. 11/2017-Central Tax (Rate)")
    ).toBeInTheDocument();
    expect(screen.getByText("s16.2.c")).toBeInTheDocument();

    // Authority badges
    expect(screen.getByText("Statute / Primary")).toBeInTheDocument();
    expect(screen.getByText("Notification")).toBeInTheDocument();

    // Query expansion banner
    expect(screen.getByText("Also expanded to:")).toBeInTheDocument();
    expect(screen.getAllByText("input tax credit").length).toBeGreaterThanOrEqual(1);

    // Multiple passage count indicator
    expect(screen.getByText("+2 other matching passages")).toBeInTheDocument();

    // Highlighting
    const mark = document.querySelector("mark");
    expect(mark).toBeInTheDocument();
    expect(mark?.textContent).toBe("input tax credit");
  });

  it("handles pagination clicks", () => {
    render(<SearchResults response={mockResponse} limit={20} offset={0} />);

    const nextBtn = screen.getByRole("button", { name: /Next/ });
    expect(nextBtn).toBeEnabled();

    fireEvent.click(nextBtn);
    expect(mockPush).toHaveBeenCalled();
    expect(mockPush.mock.calls[0][0]).toContain("offset=20");
  });
});
