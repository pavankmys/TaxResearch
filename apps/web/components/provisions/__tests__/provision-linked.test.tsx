import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProvisionLinked } from "../provision-linked";
import type { components } from "@/lib/api-client/schema";

type ProvisionLinkedResponse = components["schemas"]["ProvisionLinkedResponse"];

describe("ProvisionLinked", () => {
  const mockLinked: ProvisionLinkedResponse = {
    provision_id: "00000000-0000-0000-0000-000000000001",
    total_count: 2,
    counts: {
      amending_instruments: 1,
      circulars: 1,
    },
    groups: {
      amending_instruments: [
        {
          link_id: "10000000-0000-0000-0000-000000000001",
          link_type: "substitutes",
          document_id: "20000000-0000-0000-0000-000000000001",
          title: "Finance Act 2020",
          doc_type: "act",
          canonical_id: "act:finance-2020",
          authority_rank: 1,
          doc_date: "2020-03-27",
          in_force_date: "2020-04-01",
          confidence: 1.0,
        },
      ],
      circulars: [
        {
          link_id: "10000000-0000-0000-0000-000000000002",
          link_type: "clarifies",
          document_id: "20000000-0000-0000-0000-000000000002",
          title: "Circular No. 183/15/2022-GST",
          doc_type: "circular",
          canonical_id: "cir:183-15-2022",
          authority_rank: 4,
          doc_date: "2022-12-27",
          confidence: 0.95,
        },
      ],
    },
  };

  it("renders empty state when total_count is 0", () => {
    const empty: ProvisionLinkedResponse = {
      provision_id: "00000000-0000-0000-0000-000000000001",
      total_count: 0,
      counts: {},
      groups: {},
    };
    render(<ProvisionLinked linked={empty} />);
    expect(
      screen.getByText("No linked instruments or citations recorded for this provision.")
    ).toBeInTheDocument();
  });

  it("renders linked resources with titles, badges, and canonical IDs", () => {
    render(<ProvisionLinked linked={mockLinked} />);

    expect(screen.getByText("Finance Act 2020")).toBeInTheDocument();
    expect(screen.getByText("Circular No. 183/15/2022-GST")).toBeInTheDocument();
    expect(screen.getByText("act:finance-2020")).toBeInTheDocument();
    expect(screen.getByText("cir:183-15-2022")).toBeInTheDocument();
    expect(screen.getByText("substitutes")).toBeInTheDocument();
    expect(screen.getByText("clarifies")).toBeInTheDocument();
    expect(screen.getByText(/Confidence: 95%/)).toBeInTheDocument();
  });

  it("filters items by group tab click", () => {
    render(<ProvisionLinked linked={mockLinked} />);

    const circularsTab = screen.getByRole("button", { name: /Clarifying Circulars/ });
    fireEvent.click(circularsTab);

    expect(screen.getByText("Circular No. 183/15/2022-GST")).toBeInTheDocument();
    expect(screen.queryByText("Finance Act 2020")).not.toBeInTheDocument();

    const allTab = screen.getByRole("button", { name: /All \(2\)/ });
    fireEvent.click(allTab);

    expect(screen.getByText("Finance Act 2020")).toBeInTheDocument();
  });
});
