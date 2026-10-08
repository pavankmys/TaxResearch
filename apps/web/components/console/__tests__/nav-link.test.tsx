import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NavLink } from "@/components/console/nav-link";

const mockUsePathname = vi.fn<() => string>();

vi.mock("next/navigation", () => ({
  usePathname: () => mockUsePathname(),
}));

describe("NavLink", () => {
  beforeEach(() => {
    mockUsePathname.mockReset();
  });

  it("marks the link for the current page with aria-current", () => {
    mockUsePathname.mockReturnValue("/queue");
    render(
      <nav>
        <NavLink href="/queue">Queue</NavLink>
        <NavLink href="/dashboard">Dashboard</NavLink>
      </nav>,
    );

    expect(screen.getByRole("link", { name: "Queue" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute("aria-current");
  });

  it("treats nested paths as the same section", () => {
    mockUsePathname.mockReturnValue("/queue/task-123");
    render(<NavLink href="/queue">Queue</NavLink>);

    expect(screen.getByRole("link", { name: "Queue" })).toHaveAttribute("aria-current", "page");
  });

  it("does not match a path that only shares a prefix", () => {
    mockUsePathname.mockReturnValue("/queuex");
    render(<NavLink href="/queue">Queue</NavLink>);

    expect(screen.getByRole("link", { name: "Queue" })).not.toHaveAttribute("aria-current");
  });
});
