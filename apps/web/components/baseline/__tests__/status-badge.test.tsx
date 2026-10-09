import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "@/components/baseline/status-badge";

describe("StatusBadge", () => {
  it('shows "Not loaded" for missing or unknown status', () => {
    render(<StatusBadge status="unknown" />);
    expect(screen.getByText("Not loaded")).toBeInTheDocument();
  });

  it('shows "Loaded, awaiting verification" for loaded status', () => {
    render(<StatusBadge status="loaded" />);
    expect(screen.getByText("Loaded, awaiting verification")).toBeInTheDocument();
  });

  it('shows "Verified" for verified status', () => {
    render(<StatusBadge status="verified" />);
    expect(screen.getByText("Verified")).toBeInTheDocument();
  });
});
