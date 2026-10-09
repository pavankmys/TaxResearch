import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProvisionTree } from "@/components/baseline/provision-tree";
import type { ProvisionRow } from "@/components/baseline/types";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: any) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

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

describe("ProvisionTree", () => {
  it("renders rows in the given order", () => {
    const items = [
      mockRow({ id: "1", number_label: "1" }),
      mockRow({ id: "2", number_label: "2" }),
      mockRow({ id: "3", number_label: "3" }),
    ];

    render(<ProvisionTree items={items} instrumentCode="TEST" />);

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(3);
    expect(links[0]).toHaveAttribute("href", `/baseline/TEST?p=1`);
    expect(links[1]).toHaveAttribute("href", `/baseline/TEST?p=2`);
    expect(links[2]).toHaveAttribute("href", `/baseline/TEST?p=3`);
  });

  it("applies different indentation classes by depth", () => {
    const items = [
      mockRow({ id: "1", depth: 0 }),
      mockRow({ id: "2", depth: 1 }),
      mockRow({ id: "3", depth: 2 }),
    ];

    const { container } = render(<ProvisionTree items={items} instrumentCode="TEST" />);

    const divs = container.querySelectorAll("div[class*='pl-']");
    expect(divs.length).toBeGreaterThan(0);
    expect(divs[0]).toHaveClass("pl-0");
    expect(divs[1]).toHaveClass("pl-4");
    expect(divs[2]).toHaveClass("pl-8");
  });

  it("marks selected row with aria-current", () => {
    const items = [mockRow({ id: "1" }), mockRow({ id: "2" })];

    render(<ProvisionTree items={items} instrumentCode="TEST" selectedId="1" />);

    const links = screen.getAllByRole("link");
    expect(links[0]).toHaveAttribute("aria-current", "page");
    expect(links[1]).not.toHaveAttribute("aria-current");
  });

  it("renders flagged row with flag badge", () => {
    const items = [mockRow({ id: "1", has_baseline: false })];

    render(<ProvisionTree items={items} instrumentCode="TEST" />);

    expect(screen.getByText("No baseline text")).toBeInTheDocument();
  });

  it("does not render flag badge when no flags", () => {
    const items = [mockRow({ id: "1", has_baseline: true, text_chars: 100 })];

    render(<ProvisionTree items={items} instrumentCode="TEST" />);

    expect(screen.queryByText("No baseline text")).not.toBeInTheDocument();
  });
});
