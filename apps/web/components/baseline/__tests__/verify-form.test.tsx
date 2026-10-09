import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VerifyForm } from "@/components/baseline/verify-form";

vi.mock("@/app/(console)/baseline/[code]/actions", () => ({
  verifyBaseline: vi.fn(async () => ({ outcome: "verified", message: "Success" })),
}));

describe("VerifyForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("has a labeled confirmation checkbox and disabled button initially", () => {
    render(<VerifyForm code="TEST_CODE" />);

    const checkbox = screen.getByRole("checkbox");
    const label = screen.getByText(/i have checked the provision tree against the source document/i);
    const button = screen.getByRole("button", { name: /verify baseline/i });

    expect(checkbox).toBeInTheDocument();
    expect(label).toBeInTheDocument();
    expect(button).toBeDisabled();
  });

  it("has a hidden input with the code", () => {
    render(<VerifyForm code="TEST_123" />);

    const input = document.querySelector('input[name="code"]') as HTMLInputElement;
    expect(input).toHaveValue("TEST_123");
  });

  it("renders alert placeholder container", () => {
    render(<VerifyForm code="TEST_CODE" />);

    const form = screen.getByRole("form", { hidden: true });
    expect(form).toBeInTheDocument();
  });
});
