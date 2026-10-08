import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ConfidenceBadge } from "../confidence-badge";
import { confidenceTone, formatConfidence } from "../confidence";

describe("confidenceTone", () => {
  it("is high at 0.85 and above", () => {
    expect(confidenceTone(0.85)).toBe("high");
    expect(confidenceTone(0.95)).toBe("high");
    expect(confidenceTone(1)).toBe("high");
  });

  it("is medium from 0.6 up to just under 0.85", () => {
    expect(confidenceTone(0.6)).toBe("medium");
    expect(confidenceTone(0.7)).toBe("medium");
    expect(confidenceTone(0.8499)).toBe("medium");
  });

  it("is low below 0.6", () => {
    expect(confidenceTone(0.5999)).toBe("low");
    expect(confidenceTone(0.5)).toBe("low");
    expect(confidenceTone(0)).toBe("low");
  });
});

describe("formatConfidence", () => {
  it("rounds to a whole percent", () => {
    expect(formatConfidence(0.95)).toBe("95%");
    expect(formatConfidence(0.7)).toBe("70%");
    expect(formatConfidence(0.849)).toBe("85%");
  });
});

describe("ConfidenceBadge", () => {
  it.each([
    [0.9, "90%", "emerald"],
    [0.7, "70%", "amber"],
    [0.4, "40%", "red"],
  ])("shows %s as %s with the %s colour", (value, text, colour) => {
    render(<ConfidenceBadge value={value} />);
    const label = screen.getByText(text);
    expect(label.parentElement?.className).toContain(colour);
  });
});
