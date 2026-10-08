import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LoginForm } from "@/app/login/login-form";

// The real action imports server-only modules, so tests replace it with a stub.
vi.mock("@/app/login/actions", () => ({
  login: vi.fn(async () => ({ error: "Invalid email or password" })),
}));

describe("LoginForm", () => {
  it("renders labelled email and password fields and an empty error region", () => {
    render(<LoginForm next="/queue" />);

    expect(screen.getByLabelText("Email")).toHaveAttribute("type", "email");
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("");
  });

  it("shows the error message in the alert region after a failed sign-in", async () => {
    render(<LoginForm next="/queue" />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "pro@e2e.test" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Invalid email or password");
    });
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
  });
});
