import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { SearchFilters } from "../search-filters";

const mockPush = vi.fn();
let mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
  }),
  useSearchParams: () => mockSearchParams,
}));

describe("SearchFilters", () => {
  beforeEach(() => {
    mockPush.mockReset();
    mockSearchParams = new URLSearchParams("q=itc&as_on=2026-10-10");
  });

  it("renders document type checkboxes with facet counts", () => {
    const groups = {
      act: 5,
      notification: 12,
      circular: 3,
    };

    render(
      <SearchFilters
        selectedTypes={["act"]}
        groups={groups}
      />
    );

    expect(screen.getByText("Primary Acts / Statutes")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();

    const actCheckbox = screen.getAllByRole("checkbox")[0] as HTMLInputElement;
    expect(actCheckbox.checked).toBe(true);
  });

  it("triggers router push when toggling document type", () => {
    render(
      <SearchFilters
        selectedTypes={[]}
        groups={{ notification: 4 }}
      />
    );

    const notfCheckbox = screen.getAllByRole("checkbox")[2]; // notification is 3rd
    fireEvent.click(notfCheckbox);

    expect(mockPush).toHaveBeenCalled();
    const calledUrl = mockPush.mock.calls[0][0];
    expect(calledUrl).toContain("types=notification");
  });

  it("updates court and state filters", () => {
    render(
      <SearchFilters
        selectedTypes={[]}
        selectedCourt="SC"
        selectedState="MH"
        groups={{}}
      />
    );

    const select = screen.getByLabelText("Court level filter") as HTMLSelectElement;
    expect(select.value).toBe("SC");

    fireEvent.change(select, { target: { value: "HC" } });
    expect(mockPush).toHaveBeenCalled();
    expect(mockPush.mock.calls[0][0]).toContain("court=HC");
  });

  it("clears all filters when Clear all button is clicked", () => {
    mockSearchParams = new URLSearchParams("q=itc&types=act&court=SC&offset=20");
    render(
      <SearchFilters
        selectedTypes={["act"]}
        selectedCourt="SC"
        groups={{}}
      />
    );

    const clearBtn = screen.getByRole("button", { name: "Clear all" });
    fireEvent.click(clearBtn);

    expect(mockPush).toHaveBeenCalled();
    const targetUrl = mockPush.mock.calls[0][0];
    expect(targetUrl).not.toContain("types=");
    expect(targetUrl).not.toContain("court=");
    expect(targetUrl).not.toContain("offset=");
  });
});
