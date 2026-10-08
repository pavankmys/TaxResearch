import { describe, expect, it } from "vitest";

import { alertSeverity, alertSeverityLabel } from "@/components/dashboard/alerts";

describe("alertSeverity", () => {
  it("maps the known kinds to a severity", () => {
    expect(alertSeverity("failure_rate")).toBe("critical");
    expect(alertSeverity("overdue_review")).toBe("critical");
    expect(alertSeverity("freshness_p95")).toBe("warning");
    expect(alertSeverity("stale_source")).toBe("warning");
    expect(alertSeverity("queue_lag")).toBe("warning");
  });

  it("treats an unknown kind as a warning", () => {
    expect(alertSeverity("something_new")).toBe("warning");
  });
});

describe("alertSeverityLabel", () => {
  it("gives a text label for each severity", () => {
    expect(alertSeverityLabel("critical")).toBe("Critical");
    expect(alertSeverityLabel("warning")).toBe("Warning");
  });
});
