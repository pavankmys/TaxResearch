/** Human labels for the document enums shown across the documents pages. */

export const REVIEW_STATE_LABELS: Record<string, string> = {
  auto_published: "Auto-published",
  pending_review: "Pending review",
  reviewed: "Reviewed",
};

export const REVIEW_STATE_VALUES = Object.keys(REVIEW_STATE_LABELS);

export const DOC_TYPE_FILTER_LABELS: Record<string, string> = {
  notification: "Notification",
  circular: "Circular",
  instruction: "Instruction",
  order: "Order",
  judgement: "Judgement",
  act: "Act",
  rules: "Rules",
  other: "Other",
};

export function labelOr(map: Record<string, string>, value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  return map[value] ?? value;
}

/** A metadata field name as words, for the metadata list: "in_force_date" becomes "In force date". */
export function humanFieldName(name: string): string {
  const words = name.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}
