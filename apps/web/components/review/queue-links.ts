export type QueueTab = "mine" | "open" | "unassigned";

export const QUEUE_TABS: ReadonlyArray<{ id: QueueTab; label: string }> = [
  { id: "mine", label: "My tasks" },
  { id: "open", label: "All open" },
  { id: "unassigned", label: "Unassigned" },
];

export const QUEUE_KINDS = ["metadata", "parse_failure", "miss_report"] as const;
export type QueueKind = (typeof QUEUE_KINDS)[number];

export function parseTab(value: string | undefined): QueueTab {
  return QUEUE_TABS.some((tab) => tab.id === value) ? (value as QueueTab) : "mine";
}

export function parseKind(value: string | undefined): QueueKind | undefined {
  return QUEUE_KINDS.find((kind) => kind === value);
}

/** The API's assignee filter for a tab: "me", "none", or no filter for All open. */
export function assigneeFilter(tab: QueueTab): "me" | "none" | undefined {
  if (tab === "mine") {
    return "me";
  }
  if (tab === "unassigned") {
    return "none";
  }
  return undefined;
}

/** Queue URL that keeps the tab and kind, with an optional page cursor. */
export function queueHref(options: { tab: QueueTab; kind?: QueueKind; cursor?: string }): string {
  const params = new URLSearchParams({ tab: options.tab });
  if (options.kind) {
    params.set("kind", options.kind);
  }
  if (options.cursor) {
    params.set("cursor", options.cursor);
  }
  return `/queue?${params.toString()}`;
}
