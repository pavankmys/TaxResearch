import { describe, expect, it } from "vitest";

import { assigneeFilter, parseKind, parseTab, queueHref } from "../queue-links";

describe("queue links", () => {
  it("defaults to My tasks for an unknown tab", () => {
    expect(parseTab(undefined)).toBe("mine");
    expect(parseTab("everything")).toBe("mine");
    expect(parseTab("unassigned")).toBe("unassigned");
  });

  it("accepts only the known kinds", () => {
    expect(parseKind("metadata")).toBe("metadata");
    expect(parseKind("amendment")).toBeUndefined();
    expect(parseKind(undefined)).toBeUndefined();
  });

  it("maps each tab to the API assignee filter", () => {
    expect(assigneeFilter("mine")).toBe("me");
    expect(assigneeFilter("unassigned")).toBe("none");
    expect(assigneeFilter("open")).toBeUndefined();
  });

  it("keeps the tab and kind in the next-page link", () => {
    expect(queueHref({ tab: "open", kind: "parse_failure", cursor: "abc_-=" })).toBe(
      "/queue?tab=open&kind=parse_failure&cursor=abc_-%3D",
    );
    expect(queueHref({ tab: "mine" })).toBe("/queue?tab=mine");
  });
});
