import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProvisionTimeline, type ProvisionTimelineItem } from "../provision-timeline";

describe("ProvisionTimeline", () => {
  const items: ProvisionTimelineItem[] = [
    {
      version_id: "00000000-0000-0000-0000-000000000001",
      heading: "Rule 36(4)",
      valid_from: "2019-10-09",
      valid_to: "2020-01-01",
      origin: "baseline",
      text_chars: 100,
      text_preview: "Input tax credit shall not exceed 120 per cent.",
      created_by_amendment_id: null,
      amending_document: null,
    },
    {
      version_id: "00000000-0000-0000-0000-000000000002",
      heading: "Rule 36(4)",
      valid_from: "2020-01-01",
      valid_to: null,
      origin: "amendment",
      text_chars: 100,
      text_preview: "Input tax credit shall not exceed 110 per cent.",
      created_by_amendment_id: "00000000-0000-0000-0000-000000000003",
      amending_document: {
        id: "00000000-0000-0000-0000-000000000004",
        title: "Central Tax Notification 75/2019",
        number: "75/2019",
        doc_date: "2019-12-26",
      },
    },
  ];

  it("renders empty state when no items exist", () => {
    render(<ProvisionTimeline provisionId="test-id" items={[]} />);
    expect(screen.getByText(/No version history available/)).toBeInTheDocument();
  });

  it("renders timeline items with origin badges and dates", () => {
    render(<ProvisionTimeline provisionId="test-id" items={items} />);

    expect(screen.getByText("baseline")).toBeInTheDocument();
    expect(screen.getByText("amendment")).toBeInTheDocument();
    expect(screen.getByText("Current")).toBeInTheDocument();

    expect(screen.getByText(/Valid: 2019-10-09 to 2020-01-01/)).toBeInTheDocument();
    expect(screen.getByText(/Valid: 2020-01-01 onwards/)).toBeInTheDocument();

    expect(screen.getByText(/75\/2019/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Compare with previous version" })).toBeInTheDocument();
  });
});
