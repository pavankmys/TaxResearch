import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { SearchBar } from "../search-bar";

const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
  }),
}));

describe("SearchBar", () => {
  beforeEach(() => {
    mockPush.mockReset();
    vi.restoreAllMocks();
  });

  it("renders with initial values and inputs", () => {
    render(
      <SearchBar
        initialQuery="input tax credit"
        initialAsOn="2026-10-10"
        initialExpand={true}
      />
    );

    const input = screen.getByLabelText("Search query") as HTMLInputElement;
    expect(input.value).toBe("input tax credit");

    const asOnInput = screen.getByLabelText("As-on date") as HTMLInputElement;
    expect(asOnInput.value).toBe("2026-10-10");

    const expandCheckbox = screen.getByRole("checkbox") as HTMLInputElement;
    expect(expandCheckbox.checked).toBe(true);
  });

  it("displays citation banner when initialCitationMatch is provided", () => {
    render(
      <SearchBar
        initialQuery="s.16(2)(c)"
        initialCitationMatch={{
          matched: true,
          kind: "provision",
          canonical_id: "prov:CGST_ACT:s16.2.c",
          entity_id: "00000000-0000-0000-0000-000000000001",
          title: "Section 16(2)(c)",
          confidence: 0.98,
        }}
      />
    );

    expect(screen.getByTestId("citation-banner")).toBeInTheDocument();
    expect(screen.getByText("Citation Detected:")).toBeInTheDocument();
    expect(screen.getByText("Section 16(2)(c)")).toBeInTheDocument();
    expect(screen.getByText("prov:CGST_ACT:s16.2.c")).toBeInTheDocument();
    expect(screen.getByText(/98% match/)).toBeInTheDocument();

    const jumpButton = screen.getByRole("button", { name: /Jump to Provision/ });
    fireEvent.click(jumpButton);
    expect(mockPush).toHaveBeenCalledWith(
      "/baseline/CGST_ACT?p=00000000-0000-0000-0000-000000000001"
    );
  });
});
